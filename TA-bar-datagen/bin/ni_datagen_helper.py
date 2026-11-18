"""
Modular input "ni_datagen" – Network Intelligence demo data
(Meraki, Catalyst Center, ThousandEyes, SC4SNMP + health history) for the
Splunk Network Intelligence app 26.10.x.

The generator library (ni_datagen_lib/) is the original network_intelligence_datagen
package, unchanged. It is stateless apart from the SNMP poll slot: inventory and
health are derived from the seed and the timestamp. So this input works like the
original systemd service, just driven by splunkd:

  * first start  : current snapshot + backfill (alerts, raw telemetry, health history)
  * every run    : one snapshot per collection cycle since the last run + all alert
                   open/close transitions since the last run, then exit
  * stop / start : alert transitions are always caught up; snapshots for gaps longer
                   than "Fill gaps up to" are skipped (only "now" is sent)
"""

import time

import import_declare_test  # noqa: F401
from solnlib import conf_manager, log
from splunklib import modularinput as smi

from bar_datagen_helper import ADDON_NAME, SETTINGS_CONF, SITE_STATE_KEY, CheckpointStore, get_setup, _int
from bar_datagen_hec import HecClient, HecError
from ni_datagen_lib.events import EventFactory
from ni_datagen_lib.health import HealthModel
from ni_datagen_lib.inventory import build_inventory
from ni_datagen_lib.summary import SummaryFactory
from ni_datagen_lib.switches import SwitchTelemetry
import switch_telemetry as st

ALERT_SOURCETYPES = ("meraki:assurancealerts", "cisco:dnac:issue", "cisco:thousandeyes:alerts")
SUMMARY_STEP = 900          # seconds between backfilled health observations (original default)
SUMMARY_SKIP_RECENT = 1800  # the app's own materializers cover the last 30 minutes


def logger_for_input(name):
    return log.Logs().get_logger("%s_ni_%s" % (ADDON_NAME.lower(), name))


def _float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_input(definition: smi.ValidationDefinition):
    p = definition.parameters
    if not 60 <= _int(p.get("interval"), 300) <= 3600:
        raise ValueError("Collection cycle must be between 60 and 3600 seconds.")


class Output:
    """Sends ni_datagen_lib Event objects via HEC or the modular input writer."""

    def __init__(self, mode, setup, event_writer, logger):
        self.mode, self.ew, self.count = mode, event_writer, 0
        self.hec = None
        if mode == "hec":
            self.hec = HecClient(setup["hec_url"], setup["hec_token"],
                                 batch_size=_int(setup.get("hec_batch_size"), 500), logger=logger,
                                 verify=str(setup.get("hec_verify_ssl", "1")).lower() not in ("0", "false", "no"))

    def send(self, events):
        for e in events:
            self.count += 1
            if self.hec:
                self.hec.add(e.hec())
            else:
                self.ew.write_event(smi.Event(
                    data=e.data if isinstance(e.data, str) else log_json(e.data), time="%.3f" % e.time, index=e.index,
                    host=e.host, source=e.source, sourcetype=e.sourcetype))

    def flush(self):
        if self.hec:
            self.hec.flush()


def log_json(data):
    import json
    return json.dumps(data, separators=(",", ":"))




def preflight(out, events, logger):
    """Send events index by index; False (and nothing more sent) if HEC rejects an index."""
    by_index = {}
    for e in events:
        by_index.setdefault(e.index, []).append(e)
    for index in sorted(by_index):
        try:
            out.send(by_index[index])
            out.flush()
        except HecError as e:
            if e.code != 7:
                raise
            logger.error("HEC token does not allow index '%s' (Incorrect index). Backfill not sent; add the index "
                         "to the token's allowed indexes, the next run starts over.", index)
            return False
    return True


def run(name, item, session_key, event_writer, logger, checkpoint_dir):
    setup = get_setup(session_key)
    mode = setup.get("send_mode") or "hec"
    if mode == "hec" and not (setup.get("hec_url") and setup.get("hec_token")):
        logger.error("HEC is not configured. Open the add-on > Setup > HEC Setup.")
        return

    seed = _int(item.get("seed"), 2690)
    cycle = _int(item.get("interval"), 300)   # one snapshot per run interval, like --interval
    indexes = {
        "meraki": item.get("index_meraki") or "demo_cisco_meraki",
        "catalyst": item.get("index_catalyst") or "demo_cisco_catalyst",
        "thousandeyes": item.get("index_thousandeyes") or "demo_thousendeyes",
        "snmp": item.get("index_snmp") or "netops",
        "summary": item.get("index_summary") or "ni_capability_summary",
    }
    backfill_h = _float(item.get("backfill_hours"), 2)
    alert_h = _float(item.get("alert_backfill_hours"), 48)
    summary_h = _float(item.get("summary_backfill_hours"), 24)
    max_gap = _int(item.get("max_gap_minutes"), 30) * 60

    inv = build_inventory(seed)
    health = HealthModel(inv, seed)
    factory = EventFactory(inv, health, indexes)
    summary = SummaryFactory(inv, health, indexes)
    switches = SwitchTelemetry(inv, health, indexes, seed)
    out = Output(mode, setup, event_writer, logger)

    ckpt = CheckpointStore("ni_" + name, session_key, checkpoint_dir, logger)
    site_state = CheckpointStore(SITE_STATE_KEY, session_key, checkpoint_dir, logger)
    cp = ckpt.load()
    if cp.get("seed") not in (None, seed):
        logger.warning("Seed changed (%s -> %s): new inventory, the app's graph will be rebuilt", cp.get("seed"), seed)
    factory._snmp_slot = cp.get("snmp_slot")
    now = time.time()
    prev_run = cp.get("last_alert", cp.get("last_cycle"))

    def save(last_cycle, last_alert):
        out.flush()
        ckpt.save({"last_tick": last_cycle, "last_cycle": last_cycle, "last_alert": last_alert,
                   "snmp_slot": factory._snmp_slot, "seed": seed})
        site_state.save({"last_tick": time.time(), "interval": cycle, "input": name})

    if cp.get("last_cycle") is None:
        # ---- first start: same order as ni_datagen.py --------------------------
        logger.info("First start (seed=%s, %s devices): snapshot + backfill alerts %sh, telemetry %sh, "
                    "health %sh", seed, len(inv.devices), alert_h, backfill_h, summary_h)
        summary_t, summary_end = now - summary_h * 3600, now - SUMMARY_SKIP_RECENT
        first = factory.snapshot(now)
        if summary_h > 0 and summary_t < summary_end:
            first += summary.observations(summary_t)
            summary_t += SUMMARY_STEP
        # HEC accepts every batch up to the first rejected index and the checkpoint is only
        # written at the end, so check all indexes before the large backfill.
        if not preflight(out, first, logger):
            return
        if alert_h > 0:
            out.send(factory.alert_events(now - alert_h * 3600, now, live=False))
        out.flush()
        t = now - backfill_h * 3600
        while t < now - 1 and backfill_h > 0:
            out.send(factory.snapshot(t))
            t += cycle
        out.flush()
        if backfill_h > 0:
            out.send(switches.syslog(now - backfill_h * 3600, now))
            out.send(switches.gnmi(now - backfill_h * 3600, now))
            out.flush()
        while summary_h > 0 and summary_t < summary_end:
            out.send(summary.observations(summary_t))
            summary_t += SUMMARY_STEP
        save(now, now)
        logger.info("Backfill done: %s events", out.count)
        return

    # ---- regular run -------------------------------------------------------------
    last_cycle, last_alert = cp["last_cycle"], cp.get("last_alert", cp["last_cycle"])
    next_cycle = (int(last_cycle // cycle) + 1) * cycle
    if now - last_cycle > max_gap + cycle:
        logger.info("Input was stopped for %s min – sending a fresh snapshot, skipping the gap",
                    int(now - last_cycle) // 60)
        next_cycle = (int(now // cycle)) * cycle
    while next_cycle <= now:
        out.send(factory.snapshot(next_cycle))
        last_cycle = next_cycle
        next_cycle += cycle
    alerts = factory.alert_events(last_alert, now, live=True)
    out.send(alerts)
    tele_from = max(last_alert, now - max_gap)
    out.send(switches.syslog(tele_from, now))
    out.send(switches.gnmi(tele_from, now))
    save(last_cycle, now)
    if out.count:
        log.events_ingested(logger, "ni_datagen://" + name, "ni:*", out.count, ",".join(sorted(set(indexes.values()))))


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    for input_name, item in inputs.inputs.items():
        name = input_name.split("/")[-1]
        logger = logger_for_input(name)
        session_key = inputs.metadata["session_key"]
        try:
            logger.setLevel(conf_manager.get_log_level(
                logger=logger, session_key=session_key, app_name=ADDON_NAME, conf_name=SETTINGS_CONF))
            log.modular_input_start(logger, name)
            run(name, item, session_key, event_writer, logger, inputs.metadata.get("checkpoint_dir", "."))
            log.modular_input_end(logger, name)
        except HecError as e:
            if e.code == 7:
                logger.error("HEC rejected an index (Incorrect index). meraki, catalyst, thousandeyes, netops and "
                             "ni_capability_summary must exist and be allowed for the token. Retrying next run.")
            else:
                logger.error("HEC delivery failed, will retry next run: %s", e)
        except Exception as e:
            log.log_exception(logger, e, "ni_datagen_error", msg_before="ni_datagen run failed: ")
