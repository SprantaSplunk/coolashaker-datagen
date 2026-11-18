"""
Modular input "bar_datagen" – Buttercup Rocks bar simulator.

Start/stop = enable/disable the input on the Inputs page.
Each run (every `interval` seconds) generates all events between the last
checkpoint and now at 10-second resolution, sends them (HEC or direct), saves
the bar state to the KV store and exits. On the very first run it optionally
backfills N days at 5-minute resolution.
"""

import json
import logging
import time

import import_declare_test  # noqa: F401  (sets sys.path to ../lib)
from solnlib import conf_manager, log
from solnlib.modular_input import checkpointer
from splunklib import modularinput as smi

import bar_datagen_engine as engine
from bar_datagen_hec import HecClient, HecError

ADDON_NAME = "TA-bar-datagen"
SETTINGS_CONF = "ta_bar_datagen_settings"
SETUP_STANZA = "hec_setup"
CHECKPOINT_COLLECTION = "ta_bar_datagen_checkpointer"
SITE_STATE_KEY = "ni_site_state"   # written by the Network Intelligence input, read by CoolaShaker
CHECKPOINT_EVERY_TICKS = 288      # backfill: persist progress roughly once per simulated day


def logger_for_input(input_name):
    return log.Logs().get_logger("%s_%s" % (ADDON_NAME.lower(), input_name))


def get_setup(session_key):
    cfm = conf_manager.ConfManager(
        session_key,
        ADDON_NAME,
        realm="__REST_CREDENTIAL__#%s#configs/conf-%s" % (ADDON_NAME, SETTINGS_CONF),
    )
    try:
        return cfm.get_conf(SETTINGS_CONF).get(SETUP_STANZA) or {}
    except Exception:
        return {}


def _int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def validate_input(definition: smi.ValidationDefinition):
    params = definition.parameters
    engine.get_tz(params.get("timezone") or "America/Denver")
    if not 0 <= _int(params.get("backfill_days"), 0) <= 30:
        raise ValueError("Backfill days must be between 0 and 30.")


class Sink:
    """Routes simulator events to HEC or to the modular input event writer."""

    def __init__(self, mode, index, host, event_writer, hec):
        self.mode, self.index, self.host = mode, index, host
        self.ew, self.hec = event_writer, hec
        self.count = 0

    def __call__(self, event, sourcetype, epoch):
        self.count += 1
        if self.mode == "hec":
            self.hec.add({
                "time": round(epoch, 3),
                "host": self.host,
                "index": self.index,
                "source": "bar_datagen",
                "sourcetype": sourcetype,
                "event": event,
            })
        else:
            self.ew.write_event(smi.Event(
                data=json.dumps(event, separators=(",", ":")),
                time="%.3f" % epoch,
                index=self.index,
                host=self.host,
                source="bar_datagen",
                sourcetype=sourcetype,
            ))

    def flush(self):
        if self.mode == "hec":
            self.hec.flush()


class CheckpointStore:
    """
    Bar state + last generated tick. Written to the KV store (survives SHC member
    changes) AND to a local file (works when the KV store is down). On load the
    newer of the two wins, so a KV hiccup never triggers a second backfill.
    """

    def __init__(self, key, session_key, checkpoint_dir, logger):
        self.key, self.logger = key, logger
        self.file = checkpointer.FileCheckpointer(checkpoint_dir)
        try:
            self.kv = checkpointer.KVStoreCheckpointer(CHECKPOINT_COLLECTION, session_key, ADDON_NAME)
        except Exception as e:
            logger.warning("KV store unavailable, using file checkpoint only: %s", e)
            self.kv = None

    def load(self):
        candidates = [self.file.get(self.key) or {}]
        if self.kv is not None:
            try:
                candidates.append(self.kv.get(self.key) or {})
            except Exception as e:
                self.logger.warning("KV store read failed, using file checkpoint: %s", e)
                self.kv = None
        return max(candidates, key=lambda c: c.get("last_tick") or 0)

    def save(self, data):
        self.file.update(self.key, data)
        if self.kv is not None:
            try:
                self.kv.update(self.key, data)
            except Exception as e:
                self.logger.warning("KV store write failed (file checkpoint kept): %s", e)
                self.kv = None


def run_one(input_name, item, session_key, event_writer, logger, checkpoint_dir):
    setup = get_setup(session_key)
    mode = setup.get("send_mode") or "hec"
    hec = None
    if mode == "hec":
        url, token = setup.get("hec_url"), setup.get("hec_token")
        if not url or not token:
            logger.error("HEC is not configured. Open the add-on > Setup > HEC Setup and enter URL and token.")
            return
        hec = HecClient(url, token, batch_size=_int(setup.get("hec_batch_size"), 500), logger=logger,
                        verify=str(setup.get("hec_verify_ssl", "1")).lower() not in ("0", "false", "no"))

    index = item.get("index") or "bar_demo"
    host = item.get("bar_host") or "bar-datagen"
    tz_name = item.get("timezone") or "America/Denver"
    backfill_days = _int(item.get("backfill_days"), 14)
    max_gap = _int(item.get("max_gap_minutes"), 15) * 60

    ckpt = CheckpointStore("bar_datagen_" + input_name, session_key, checkpoint_dir, logger)
    cp = ckpt.load()
    state = cp.get("state") or engine.new_state()

    sink = Sink(mode, index, host, event_writer, hec)
    sim = engine.Simulator(state, tz_name, sink)

    step = engine.REALTIME_STEP_SEC
    now = int(time.time()) // step * step
    last = cp.get("last_tick")

    def save(last_tick):
        sink.flush()  # only checkpoint what was actually delivered
        ckpt.save({"last_tick": last_tick, "state": state})

    # --- first start: optional backfill --------------------------------------
    if last is None:
        if backfill_days > 0:
            bstep = engine.BACKFILL_STEP_SEC
            t = (now - backfill_days * 86400) // bstep * bstep
            logger.info("First start: backfilling %s days into index=%s (mode=%s)", backfill_days, index, mode)
            n = 0
            while t < now - bstep:
                sim.tick(t, bstep)
                n += 1
                if n % CHECKPOINT_EVERY_TICKS == 0:
                    save(t)
                t += bstep
            save(t)
            last = t
            logger.info("Backfill done: %s events", sink.count)
        else:
            last = now - step

    # --- gap handling -----------------------------------------------------------
    if now - last > max_gap + 2 * step:
        logger.info("Input was stopped for %s min (> %s min) – resuming at now without filling the gap",
                    (now - last) // 60, max_gap // 60)
        last = now - step

    # --- realtime catch-up ------------------------------------------------------
    t = last + step
    while t <= now:
        sim.tick(t, step)
        t += step
    save(now)
    log.events_ingested(logger, "bar_datagen://" + input_name, "bar:*", sink.count, index)


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    for input_name, item in inputs.inputs.items():
        name = input_name.split("/")[-1]
        logger = logger_for_input(name)
        try:
            session_key = inputs.metadata["session_key"]
            logger.setLevel(conf_manager.get_log_level(
                logger=logger, session_key=session_key,
                app_name=ADDON_NAME, conf_name=SETTINGS_CONF))
            log.modular_input_start(logger, name)
            run_one(name, item, session_key, event_writer, logger,
                    inputs.metadata.get("checkpoint_dir", "."))
            log.modular_input_end(logger, name)
        except HecError as e:
            index = item.get("index") or "bar_demo"
            if e.code == 7:
                logger.error(
                    "HEC rejected index '%s' (Incorrect index). Either the index does not exist "
                    "(Settings > Indexes) or it is not in the HEC token's allowed indexes "
                    "(Settings > Data inputs > HTTP Event Collector > token > Edit). "
                    "Nothing was checkpointed; generation resumes automatically once fixed.", index)
            elif e.code in (2, 3, 4):
                logger.error("HEC rejected the token (%s). Re-enter it under Setup > HEC Setup.", e)
            else:
                logger.error("HEC delivery failed, will retry next run: %s", e)
        except Exception as e:
            log.log_exception(logger, e, "bar_datagen_error", msg_before="bar_datagen run failed: ")
