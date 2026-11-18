"""
Modular input "coolashaker" – CoolaShaker multi-technology demo data (HEC edition).

Unlike the bar datagen this input is long-running: the 13 generators keep
internal state (device up/down, active calls, perf cache), so one process runs
the simulated clock continuously and streams events. Disabling the input stops
the process; `interval` only tells splunkd to restart it if it ever dies.

Progress (last generated second) is checkpointed every minute, so after a
restart short gaps are filled and the optional backfill runs only once.
"""

import fcntl
import os
import signal
import time

import import_declare_test  # noqa: F401
from solnlib import conf_manager, log
from splunklib import modularinput as smi

import coolashaker_hec as cs
import switch_telemetry as st
from bar_datagen_helper import ADDON_NAME, SETTINGS_CONF, SITE_STATE_KEY, CheckpointStore, get_setup, _int
from bar_datagen_hec import HecClient, HecError

CHECKPOINT_EVERY_SEC = 60
FLUSH_EVERY_SEC = 2
DOS_SAMPLE_THRESHOLD = 50     # tomcat cycles with more lines than this are DoS bursts
DOS_SAMPLE_KEEP = 10          # "reduced" volume keeps 1 of 10 burst lines

WATCHDOG_EVERY_SEC = 10
SITE_STATE_EVERY_SEC = 30
SITE_STATE_STALE_SEC = 900
NI_SCHEME = "ni_datagen"

_stop = {"flag": False}


def _on_term(signum, frame):
    _stop["flag"] = True


class Watchdog:
    """
    splunkd starts the input through `/bin/sh -c python …` and, on disable, kills
    the shell – the python child would survive as an orphan and keep sending.
    So every few seconds we check (a) that our parent is still alive and (b) that
    the input is still enabled, and stop otherwise.
    """

    def __init__(self, name, session_key, logger):
        self.name, self.session_key, self.logger = name, session_key, logger
        self.ppid = os.getppid()
        self.last = time.time()
        self.stanza = None    # latest input settings, used to apply scenario switches live

    def should_stop(self):
        now = time.time()
        if now - self.last < WATCHDOG_EVERY_SEC:
            return False
        self.last = now
        if os.getppid() != self.ppid:
            self.logger.info("Parent process gone (input disabled or splunkd restarting) – stopping")
            return True
        try:
            cfm = conf_manager.ConfManager(self.session_key, ADDON_NAME)
            stanza = cfm.get_conf("inputs").get("coolashaker://" + self.name)
            self.stanza = stanza
            if str(stanza.get("disabled", "0")).lower() in ("1", "true"):
                self.logger.info("Input disabled – stopping")
                return True
        except Exception as e:
            if "not exist" in str(e).lower() or "404" in str(e):
                self.logger.info("Input deleted – stopping")
                return True
            self.logger.debug("watchdog check skipped: %s", e)
        return False




def acquire_lock(checkpoint_dir, name, logger, wait_sec=30):
    """One generator process per input – a second instance waits, then gives up."""
    path = os.path.join(checkpoint_dir, "coolashaker_%s.lock" % name)
    os.makedirs(checkpoint_dir, exist_ok=True)
    fh = open(path, "w")
    deadline = time.time() + wait_sec
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.time() > deadline or _stop["flag"]:
                logger.warning("Another CoolaShaker process for '%s' is still running – exiting", name)
                fh.close()
                return None
            time.sleep(1)


def scenario_flags(item):
    """Input fields scenario_<name> -> {name: bool}. Missing fields = off."""
    return {name: str(item.get("scenario_" + name, "0")).strip().lower() in ("1", "true", "yes", "on")
            for name in cs.SCENARIOS}


def describe_scenarios(flags):
    return ", ".join("%s=%s" % (n, "on" if on else "off") for n, on in sorted(flags.items()))


def logger_for_input(name):
    return log.Logs().get_logger("%s_coolashaker_%s" % (ADDON_NAME.lower(), name))


def validate_input(definition: smi.ValidationDefinition):
    p = definition.parameters
    if not 0 <= _int(p.get("backfill_minutes"), 0) <= 10080:
        raise ValueError("Backfill must be between 0 and 10080 minutes (7 days).")


class ReducedRouter(cs.Router):
    """Optionally thins out the Berlin DoS bursts (85 % of the original volume)."""

    def __init__(self, out, host, reduced):
        cs.Router.__init__(self, out, default_host=host)
        self.reduced = reduced
        self._n = 0

    def emit_lines(self, server, lines, ts):
        if self.reduced and len(lines) > DOS_SAMPLE_THRESHOLD:
            lines = lines[::DOS_SAMPLE_KEEP]
        cs.Router.emit_lines(self, server, lines, ts)


def make_output(mode, setup, event_writer, logger):
    """Returns (out(payload), flush())."""
    if mode == "hec":
        hec = HecClient(setup["hec_url"], setup["hec_token"],
                        batch_size=_int(setup.get("hec_batch_size"), 500), logger=logger,
                        verify=str(setup.get("hec_verify_ssl", "1")).lower() not in ("0", "false", "no"))
        return hec.add, hec.flush

    def out(p):
        if p["event"] == "metric":
            # Direct mode: JSON metric line, turned into a data point by the
            # INDEXED_EXTRACTIONS of coolashaker:metrics:direct (props.conf)
            raw = cs.json.dumps(p["fields"], separators=(",", ":"))
            p = dict(p, sourcetype="coolashaker:metrics:direct")
        else:
            raw = p["event"] if isinstance(p["event"], str) else cs.json.dumps(p["event"], separators=(",", ":"))
        event_writer.write_event(smi.Event(
            data=raw, time="%.3f" % p["time"], index=p["index"], host=p["host"],
            source=p["source"], sourcetype=p["sourcetype"]))
    return out, (lambda: None)


def run(name, item, session_key, event_writer, logger, checkpoint_dir):
    setup = get_setup(session_key)
    mode = setup.get("send_mode") or "hec"
    if mode == "hec" and not (setup.get("hec_url") and setup.get("hec_token")):
        logger.error("HEC is not configured. Open the add-on > Setup > HEC Setup.")
        return

    tz_name = item.get("timezone") or "Europe/Vienna"
    host = item.get("cs_host") or "coolashaker"
    reduced = (item.get("volume") or "reduced") == "reduced"
    backfill = _int(item.get("backfill_minutes"), 0) * 60
    max_gap = _int(item.get("max_gap_minutes"), 15) * 60

    ckpt = CheckpointStore("coolashaker_" + name, session_key, checkpoint_dir, logger)
    cp = ckpt.load()
    now = time.time()
    last = cp.get("last_ts")
    if last is None:
        start = now - backfill
        if backfill:
            logger.info("First start: backfilling %s minutes (volume=%s)", backfill // 60,
                        "reduced" if reduced else "original")
    elif now - last <= max_gap:
        start = last
    else:
        logger.info("Input was stopped for %s min (> %s) – resuming at now", int(now - last) // 60, max_gap // 60)
        start = now

    out, flush = make_output(mode, setup, event_writer, logger)
    router = ReducedRouter(out, host, reduced)
    flags = scenario_flags(item)
    sim = cs.Simulation(router, tz_name, start_ts=start, logger=logger, passthrough=(HecError,),
                        scenarios=flags, onset=cp.get("scenario_onset"))
    logger.info("CoolaShaker started (mode=%s, tz=%s, start=%s, scenarios: %s)",
                mode, tz_name, int(start), describe_scenarios(flags))

    watchdog = Watchdog(name, session_key, logger)
    last_flush = last_ckpt = time.time()
    reported = 0
    while not _stop["flag"]:
        if watchdog.should_stop():
            break
        if watchdog.stanza is not None:
            changed = sim.set_scenarios(scenario_flags(watchdog.stanza))
            watchdog.stanza = None
            if changed:
                logger.info("Fault scenarios changed: %s", describe_scenarios(changed))
        now = time.time()
        sim.run_until(now)
        if now - last_flush >= FLUSH_EVERY_SEC:
            flush()
            last_flush = now
        if now - last_ckpt >= CHECKPOINT_EVERY_SEC:
            flush()
            ckpt.save({"last_ts": now, "scenario_onset": dict(sim.gen.onset)})
            log.events_ingested(logger, "coolashaker://" + name, "coolashaker:*",
                                router.count - reported, "demo_*")
            reported = router.count
            last_ckpt = now
        time.sleep(max(0.1, min(1.0, sim.next_due() - time.time())))

    flush()
    ckpt.save({"last_ts": time.time(), "scenario_onset": dict(sim.gen.onset)})
    logger.info("CoolaShaker stopped – %s events this session", router.count)


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)
    for input_name, item in inputs.inputs.items():
        name = input_name.split("/")[-1]
        logger = logger_for_input(name)
        session_key = inputs.metadata["session_key"]
        try:
            logger.setLevel(conf_manager.get_log_level(
                logger=logger, session_key=session_key, app_name=ADDON_NAME, conf_name=SETTINGS_CONF))
        except Exception:
            pass
        ckpt_dir = inputs.metadata.get("checkpoint_dir", ".")
        lock = acquire_lock(ckpt_dir, name, logger)
        if lock is None:
            return
        # keep running; a HEC outage must not kill the stream – retry after a pause
        while not _stop["flag"]:
            try:
                log.modular_input_start(logger, name)
                run(name, item, session_key, event_writer, logger, ckpt_dir)
                return
            except HecError as e:
                if e.code == 7:
                    logger.error("HEC rejected an index (Incorrect index). All of these must exist and be "
                                 "allowed for the token: %s. Retrying in 60 s.", ", ".join(cs.ALL_INDEXES))
                else:
                    logger.error("HEC delivery failed: %s – retrying in 60 s", e)
            except Exception as e:
                log.log_exception(logger, e, "coolashaker_error", msg_before="CoolaShaker crashed: ")
            for _ in range(60):
                if _stop["flag"] or os.getppid() == 1:
                    return
                time.sleep(1)
