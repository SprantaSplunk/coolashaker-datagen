"""Historical health observations for index=ni_capability_summary.

The app's "NI - Health Materialize" searches only look back 30 minutes, so
health history charts would otherwise start empty. This module writes the same
observation documents those searches `collect`, for times before the live
pipeline takes over. Subject IDs are the deterministic UUIDv5 vertex IDs the
app derives from canonical keys, so they line up with the KV store graph.
"""
from __future__ import annotations

import json

from .events import Event
from .health import HealthModel
from .inventory import Inventory
from .util import stable_hex, vertex_id_for

SOURCETYPE = "ni:capability:observation"

_SCORES = {"ok": 100, "degraded": 60, "critical": 0}


def _speed_bps(speed: str):
    if not speed:
        return None
    value, unit = speed.split(" ")
    return float(value) * {"Gbps": 1e9, "Mbps": 1e6, "Kbps": 1e3}.get(unit, 1)


class SummaryFactory:
    def __init__(self, inv: Inventory, health: HealthModel, indexes: dict):
        self.inv = inv
        self.health = health
        self.idx = indexes
        self.index = indexes["summary"]

    def _obs(self, t, binding_id, capability_id, source_system, source_id_type, source_id,
             subject_type, canonical_key, state, metrics, evidence, extra_id="") -> Event:
        observed_ts = int(t)
        data = {
            "observation_id": stable_hex(binding_id, source_id, extra_id, observed_ts),
            "capability_id": capability_id,
            "binding_id": binding_id,
            "source_system": source_system,
            "source_id_type": source_id_type,
            "source_id": source_id,
            "subject": f"vertex:{subject_type}",
            "subject_class": "vertex",
            "subject_type": subject_type,
            "subject_id": vertex_id_for(canonical_key),
            "subject_canonical_key": canonical_key,
            "state": state,
            "score": _SCORES.get(state),
            "metrics_json": json.dumps(metrics, separators=(",", ":")),
            "evidence_ref": json.dumps(evidence, separators=(",", ":")),
            "observed_ts": observed_ts,
            "materialized_ts": observed_ts + 60,
            "valid": 1,
            "error_message": "",
        }
        return Event(self.index, SOURCETYPE, "ni_datagen:backfill", "ni-datagen", observed_ts, data)

    def observations(self, t: float) -> list:
        out = []
        out += self._meraki(t)
        out += self._catalyst(t)
        out += self._thousandeyes(t)
        return out

    def _meraki(self, t: float) -> list:
        h = self.health
        out = []
        for dev in self.inv.by_source("meraki"):
            dev_key = f"device:{dev.mac}"
            status = h.meraki_status(dev, t)
            state = {"online": "ok", "offline": "critical", "alerting": "degraded", "dormant": "degraded"}[status]
            out.append(self._obs(t, "meraki.device_availability", "device.availability", "meraki",
                                 "serial_number", dev.serial, "device", dev_key, state,
                                 {"availability_status": status},
                                 {"index": self.idx["meraki"], "sourcetype": "meraki:devicesavailabilities",
                                  "keys": {"serial": dev.serial}}))
            for port in dev.ports:
                if not port.connected:
                    continue
                st = h.meraki_port(dev, port, t)
                iface_key = f"interface:{dev.mac}:internal_identifier:{port.port_id}"
                source_id = f"{dev.serial}:{port.port_id}"
                actionable = [e for e in st["errors"] if e.lower() not in ("port disconnected", "port disabled")]
                if st["enabled"] and st["status"] == "Disconnected" and st["is_uplink"]:
                    state = "critical"
                elif actionable:
                    state = "critical"
                elif st["warnings"]:
                    state = "degraded"
                else:
                    state = "ok"
                evidence = {"index": self.idx["meraki"], "sourcetype": "meraki:custom",
                            "keys": {"serial": dev.serial, "port_id": port.port_id}}
                out.append(self._obs(t, "meraki.interface_status", "interface.status", "meraki",
                                     "internal_identifier", source_id, "interface", iface_key, state, {
                                         "oper_status": st["status"].lower(),
                                         "admin_status": "enabled",
                                         "is_uplink": st["is_uplink"],
                                         "speed": st["speed"],
                                         "speed_bps": _speed_bps(st["speed"]),
                                         "duplex": st["duplex"],
                                         "errors": st["errors"],
                                         "warnings": st["warnings"],
                                         "error_count": len(actionable),
                                         "warning_count": len(st["warnings"]),
                                         "spanning_tree_statuses": ["Forwarding"] if st["status"] == "Connected" else [],
                                         "poe_is_allocated": st["poe_allocated"],
                                     }, evidence))
                in_bps, out_bps = st["in_kbps"] * 1000, st["out_kbps"] * 1000
                out.append(self._obs(t, "meraki.interface_throughput", "interface.throughput", "meraki",
                                     "internal_identifier", source_id, "interface", iface_key, "ok", {
                                         "throughput_in_bps": in_bps,
                                         "throughput_out_bps": out_bps,
                                         "throughput_total_bps": in_bps + out_bps,
                                         "traffic_in_kb": round(st["in_kbps"] * 300 / 8, 1),
                                         "traffic_out_kb": round(st["out_kbps"] * 300 / 8, 1),
                                         "traffic_total_kb": round((st["in_kbps"] + st["out_kbps"]) * 300 / 8, 1),
                                     }, evidence))
                if port.poe:
                    out.append(self._obs(t, "meraki.interface_power", "interface.power", "meraki",
                                         "internal_identifier", source_id, "interface", iface_key, "ok",
                                         {"energy_delivered_wh": st["energy_wh"]}, evidence))
            for uplink in dev.uplinks:
                loss, latency = h.meraki_uplink(dev, uplink, t)
                if loss >= 20 or latency >= 300:
                    state = "critical"
                elif loss >= 5 or latency >= 150:
                    state = "degraded"
                else:
                    state = "ok"
                out.append(self._obs(t, "meraki.interface_uplink_quality", "interface.uplink_quality", "meraki",
                                     "internal_identifier", f"{dev.serial}:{uplink}", "interface",
                                     f"interface:{dev.mac}:internal_identifier:{uplink}", state,
                                     {"loss_pct": loss, "latency_ms": latency, "target_ip": "8.8.8.8", "uplink": uplink},
                                     {"index": self.idx["meraki"], "sourcetype": "meraki:devicesuplinkslossandlatency",
                                      "keys": {"serial": dev.serial, "uplink": uplink, "ip": "8.8.8.8"}},
                                     extra_id="8.8.8.8"))
        return out

    def _catalyst(self, t: float) -> list:
        h = self.health
        out = []
        for dev in self.inv.by_source("catalyst_center"):
            dev_key = f"device:{dev.mac}"
            st = h.catalyst_device(dev, t)
            reach = st["reachability"].lower()
            if reach == "unreachable":
                availability = "offline"
            elif reach == "ping reachable":
                availability = "alerting"
            else:
                availability = "online"
            state = {"online": "ok", "offline": "critical", "alerting": "degraded"}[availability]
            evidence = {"index": self.idx["catalyst"], "sourcetype": "cisco:dnac:devicehealth",
                        "keys": {"device_id": dev.device_id, "serial_number": dev.serial}}
            out.append(self._obs(t, "catalyst_center.device_availability", "device.availability",
                                 "catalyst_center", "internal_identifier", dev.device_id, "device", dev_key,
                                 state, {"availability_status": availability}, evidence))
            if st["cpu"] is not None and st["mem"] is not None:
                cpu_h, mem_h = st["cpu_health"], st["mem_health"]
                if cpu_h <= 2 or mem_h <= 2:
                    state = "critical"
                elif cpu_h <= 7 or mem_h <= 7:
                    state = "degraded"
                else:
                    state = "ok"
                out.append(self._obs(t, "catalyst_center.device_telemetry", "device.telemetry",
                                     "catalyst_center", "internal_identifier", dev.device_id, "device", dev_key,
                                     state, {"cpu_utilization_pct": st["cpu"], "memory_utilization_pct": st["mem"]},
                                     evidence))
            for port in dev.ports:
                if not port.connected:
                    continue
                ist = h.catalyst_iface(dev, port, t)
                iface_key = f"interface:{dev.mac}:ifindex:{port.ifindex}"
                error_pct = ist["rx_err"] + ist["tx_err"]
                discard_pct = ist["rx_disc"] + ist["tx_disc"]
                admin = "enabled" if ist["admin"] == "UP" else "disabled"
                if admin == "enabled" and ist["oper"] == "down" and port.is_wan:
                    state = "critical"
                elif error_pct > 0 or discard_pct > 0:
                    state = "degraded"
                else:
                    state = "ok"
                evidence = {"index": self.idx["catalyst"], "sourcetype": "cisco:dnac:devicehealth:interface",
                            "keys": {"interface_id": port.interface_id, "device_id": dev.device_id}}
                out.append(self._obs(t, "catalyst_center.interface_status", "interface.status", "catalyst_center",
                                     "internal_identifier", port.interface_id, "interface", iface_key, state, {
                                         "oper_status": ist["oper"], "admin_status": admin,
                                         "is_uplink": port.is_wan, "error_pct": error_pct,
                                         "discard_pct": discard_pct,
                                     }, evidence))
                out.append(self._obs(t, "catalyst_center.interface_throughput", "interface.throughput",
                                     "catalyst_center", "internal_identifier", port.interface_id, "interface",
                                     iface_key, "ok", {
                                         "throughput_in_bps": ist["rx_bps"], "throughput_out_bps": ist["tx_bps"],
                                         "throughput_total_bps": ist["rx_bps"] + ist["tx_bps"],
                                     }, evidence))
        return out

    def _thousandeyes(self, t: float) -> list:
        out = []
        for test in self.inv.te_tests:
            test_key = f"synthetic_test:thousandeyes:{test.test_id}"
            for agent in test.agents:
                m = self.health.te_metrics(test, agent, t)
                source_id = f"{test.test_id}:{agent.agent_id}"
                evidence = {"index": self.idx["thousandeyes"], "sourcetype": "cisco:thousandeyes:metric",
                            "keys": {"test_id": test.test_id, "agent_id": agent.agent_id}}
                if "network.loss" in m:
                    loss, latency = m["network.loss"], m["network.latency"]
                    if loss >= 10 or latency >= 1000:
                        state = "critical"
                    elif loss > 0 or latency >= 250:
                        state = "degraded"
                    else:
                        state = "ok"
                    out.append(self._obs(t, "thousandeyes.synthetic_network_quality", "synthetic.network_quality",
                                         "thousandeyes", "test_agent", source_id, "synthetic_test", test_key, state,
                                         {"loss_pct": loss, "latency_ms": latency, "jitter_ms": m["network.jitter"],
                                          "test_type": test.test_type}, evidence))
                if "http.server.request.availability" in m:
                    pct = m["http.server.request.availability"] * 100
                    duration_ms = m["http.client.request.duration"] * 1000
                    if pct == 0:
                        state = "critical"
                    elif pct < 100 or duration_ms >= 3000:
                        state = "degraded"
                    else:
                        state = "ok"
                    out.append(self._obs(t, "thousandeyes.synthetic_http_availability", "synthetic.http_availability",
                                         "thousandeyes", "test_agent", source_id, "synthetic_test", test_key, state,
                                         {"http_availability_pct": pct, "http_duration_ms": round(duration_ms, 1),
                                          "test_type": test.test_type}, evidence))
                if "dns.lookup.availability" in m:
                    pct = m["dns.lookup.availability"] * 100
                    duration_ms = m["dns.lookup.duration"] * 1000
                    if pct == 0:
                        state = "critical"
                    elif pct < 100 or duration_ms >= 3000:
                        state = "degraded"
                    else:
                        state = "ok"
                    out.append(self._obs(t, "thousandeyes.synthetic_dns_availability", "synthetic.dns_availability",
                                         "thousandeyes", "test_agent", source_id, "synthetic_test", test_key, state,
                                         {"dns_availability_pct": pct, "dns_duration_ms": round(duration_ms, 1),
                                          "test_type": test.test_type}, evidence))
        return out
