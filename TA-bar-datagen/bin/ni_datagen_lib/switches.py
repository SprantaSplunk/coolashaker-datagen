"""IOS-XE syslog (cisco:ios) and gNMI telemetry (cisco:gnmi) for the Catalyst Center switches.

The messages themselves come from bin/switch_telemetry.py; this module maps the NI inventory
onto its topology.
"""
from __future__ import annotations

import switch_telemetry as st

from .events import Event
from .health import HealthModel, _is_vienna
from .inventory import Inventory

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

SYSLOG_SOURCE = "udp:514"
GNMI_SOURCE = "gnmi:telegraf"
PORT_KINDS = {"trunk": "trunk", "uplink": "uplink", "access": "access", "svi": "svi", "loopback": "loopback"}


def _tz(name):
    try:
        return ZoneInfo(name) if ZoneInfo else None
    except Exception:
        return None


def build_topology(inv: Inventory, health: HealthModel) -> st.Topology:
    switches = {}
    for dev in inv.by_source("catalyst_center"):
        if dev.product_type != "Switches and Hubs":
            continue
        net = dev.ip.split(".")[1]
        ports = [st.SwPort(p.port_id, PORT_KINDS.get(p.kind, "access"), connected=p.connected,
                           speed_mbps=p.speed_mbps, load=max(p.load, 0.02),
                           desc="SERVER-NET" if p.kind == "svi" else "")
                 for p in dev.ports]
        ports.append(st.SwPort("GigabitEthernet0/0", "mgmt", desc="OOB management", connected=True))
        switches[dev.key] = st.Switch(dev.name, dev.name.split(".")[0], dev.site.name, dev.ip, dev.role, dev.model,
                                      _tz(dev.site.time_zone), f"10.{net}.99", vienna=_is_vienna(dev), ports=ports)
    for lk in inv.links:
        for a, a_port, b, b_port in ((lk.a, lk.a_port, lk.b, lk.b_port), (lk.b, lk.b_port, lk.a, lk.a_port)):
            sw = switches.get(a.key)
            if sw is None:
                continue
            port = sw.port(a_port)
            peer = switches.get(b.key)
            if peer is not None:
                port.peer, port.peer_port = peer.name, b_port
                port.desc = f"to {peer.hostname} {b_port}"
                if a.role == "CORE" and b.role == "CORE":
                    port.ospf_nbr = b.ip
            else:
                port.desc = f"{b.role} {b.name.split('.')[0]} {b_port}"
                if b.role == "BORDER ROUTER":
                    port.ospf_nbr = b.ip
    for sw in switches.values():
        r = st.stable_rng("ports", sw.name)
        for port in sw.ports:
            if port.kind == "access" and port.connected and not port.desc:
                port.desc = r.choice(st.DESCRIPTIONS)
    return st.Topology(list(switches.values()), [d.name for d in health.vienna_cores])


class SwitchTelemetry:
    def __init__(self, inv: Inventory, health: HealthModel, indexes: dict, seed: int):
        self.health = health
        self.index = indexes["catalyst"]
        self.seed = seed
        self.topo = build_topology(inv, health)

    def syslog(self, a: float, b: float) -> list:
        return [Event(self.index, "cisco:ios", SYSLOG_SOURCE, sw.name, ts, line)
                for ts, sw, line in st.syslog_lines(self.topo, self.health.outage, a, b, self.seed)]

    def gnmi(self, a: float, b: float) -> list:
        """One sample every SAMPLE_SEC in (a, b]."""
        out = []
        t = (int(a // st.SAMPLE_SEC) + 1) * st.SAMPLE_SEC
        while t <= b:
            out += [Event(self.index, "cisco:gnmi", GNMI_SOURCE, sw.name, t, data)
                    for sw, data in st.gnmi_events(self.topo, self.health.outage, t, self.seed)]
            t += st.SAMPLE_SEC
        return out
