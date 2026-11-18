"""Deterministic health model.

Every problem in the simulated network is an ``Issue``: a periodic window
(period/offset/duration) attached to a device, port, uplink or synthetic test.
Raw telemetry, backfilled health observations and alerts all consult the same
issues, so the dashboards tell one consistent story.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import switch_telemetry as st

from .inventory import VIENNA_SITE_KEY, VIENNA_TE_AGENT, Device, Inventory, TEAgent, TETest
from .util import diurnal, stable_hex, stable_rng

HOUR = 3600
DAY = 86400
OPEN = float("inf")   # end of an alert window that is still open


@dataclass
class Issue:
    key: str
    kind: str
    source: str
    target: str  # lookup key: device key, "device|port", or "test|agent"
    period: int
    offset: int
    duration: int
    device: Optional[Device] = None
    port_id: str = ""
    test: Optional[TETest] = None
    agent: Optional[TEAgent] = None

    def active(self, t: float) -> bool:
        return (t + self.offset) % self.period < self.duration

    def windows(self, a: float, b: float):
        """(start, end) for every bad window overlapping [a, b]."""
        k = int((a + self.offset) // self.period) - 1
        while True:
            start = k * self.period - self.offset
            if start > b:
                return
            end = start + self.duration
            if end >= a:
                yield start, end
            k += 1


@dataclass
class AlertWindow:
    alert_id: str
    kind: str
    source: str
    start: float
    end: float
    device: Optional[Device] = None
    port_id: str = ""
    test: Optional[TETest] = None
    agent: Optional[TEAgent] = None


# Random "noise" alerts that are not tied to a health issue.
MERAKI_NOISE = [
    ("wireless", "high_channel_utilization", "warning", "High channel utilization on 5 GHz"),
    ("wireless", "rogue_ap_detected", "warning", "Rogue access point detected"),
    ("switch", "port_speed_downshift", "warning", "Port negotiated at a lower speed"),
    ("appliance", "vpn_connectivity_change", "warning", "Site-to-site VPN connectivity changed"),
    ("wireless", "dhcp_failures", "warning", "Clients failing to obtain DHCP leases"),
    ("camera", "camera_recording_gap", "warning", "Camera recording gap detected"),
]
CATALYST_NOISE = [
    ("Unified AP", "ap_radio_interference", "P3", "AP radio experiencing high interference on 5 GHz"),
    ("Unified AP", "ap_high_client_count", "P4", "AP serving an unusually high number of clients"),
    ("Switches and Hubs", "interface_flapping", "P3", "Interface flapping on access switch"),
    ("Switches and Hubs", "poe_power_budget", "P3", "PoE power budget nearly exhausted"),
    ("Wireless Controller", "wlc_ap_join_failures", "P2", "Access points failing to join the controller"),
]


def _is_vienna(dev: Device) -> bool:
    return dev.site.key == VIENNA_SITE_KEY


class HealthModel:
    def __init__(self, inv: Inventory, seed: int):
        self.inv = inv
        self.seed = seed
        self.issues: list = []
        self._by_target: dict = defaultdict(list)
        self._devices = {d.key: d for d in inv.devices}
        self.outage = st.Outage()
        self.vienna_cores = sorted((d for d in inv.devices if _is_vienna(d) and d.role == "CORE"),
                                   key=lambda d: d.name)
        self._build_issues()
        for issue in self.issues:
            self._by_target[(issue.kind, issue.target)].append(issue)

    # ── issue catalogue ──────────────────────────────────────────────────
    def _add(self, kind, source, target, period, duration, **kw):
        rng = stable_rng(self.seed, "issue", kind, target)
        issue = Issue(
            key=f"{kind}:{target}",
            kind=kind,
            source=source,
            target=target,
            period=int(period),
            offset=rng.randrange(int(period)),
            duration=int(duration),
            **kw,
        )
        self.issues.append(issue)
        return issue

    def _build_issues(self) -> None:
        rng = stable_rng(self.seed, "issue-picks")
        mk = self.inv.by_source("meraki")
        aps = [d for d in mk if d.product_type == "wireless"]
        cams = [d for d in mk if d.product_type == "camera"]
        switches = [d for d in mk if d.product_type == "switch"]
        access_sw = [s for s in switches if not s.name.endswith("MS01")]
        mxs = {d.site.code: d for d in mk if d.product_type == "appliance"}

        persistent_ap, *flap_aps = rng.sample(aps, 3)
        self._add("meraki_offline", "meraki", persistent_ap.key, 3 * DAY, 3 * DAY - 2 * HOUR, device=persistent_ap)
        cam = rng.choice(cams)
        self._add("meraki_offline", "meraki", cam.key, 6 * HOUR, 40 * 60, device=cam)
        for ap in flap_aps:
            self._add("meraki_alerting", "meraki", ap.key, 6 * HOUR, 25 * 60, device=ap)

        sw = rng.choice(access_sw)
        self._add("meraki_uplink_port_down", "meraki", f"{sw.key}|24", 8 * HOUR, 20 * 60, device=sw, port_id="24")
        candidates = [(s, p) for s in switches for p in s.ports if p.connected and p.kind == "access" and not p.peer]
        picks = rng.sample(candidates, 4)
        s, p = picks[0]
        self._add("meraki_port_errors", "meraki", f"{s.key}|{p.port_id}", 5 * HOUR, 30 * 60, device=s, port_id=p.port_id)
        for s, p in picks[1:]:
            self._add("meraki_port_warnings", "meraki", f"{s.key}|{p.port_id}", 2 * DAY, 2 * DAY - 4 * HOUR,
                      device=s, port_id=p.port_id)

        self._add("meraki_uplink_loss", "meraki", f"{mxs['HAM'].key}|wan2", 4 * HOUR, 75 * 60,
                  device=mxs["HAM"], port_id="wan2")
        self._add("meraki_uplink_latency", "meraki", f"{mxs['GRZ'].key}|wan1", 3 * HOUR, 30 * 60,
                  device=mxs["GRZ"], port_id="wan1")

        # the Vienna office stays out of the random picks
        cc = [d for d in self.inv.by_source("catalyst_center") if not _is_vienna(d)]
        c_aps = [d for d in cc if d.role == "AP"]
        c_access = [d for d in cc if d.role == "ACCESS"]
        c_core = [d for d in cc if d.role == "CORE"]
        c_routers = {d.site.code: d for d in cc if d.role == "BORDER ROUTER"}
        ap = rng.choice(c_aps)
        self._add("catalyst_unreachable", "catalyst_center", ap.key, 3 * DAY, 3 * DAY - 3 * HOUR, device=ap)
        acc = rng.choice(c_access)
        self._add("catalyst_high_cpu", "catalyst_center", acc.key, 5 * HOUR, 45 * 60, device=acc)
        rtr = c_routers["BER"]
        self._add("catalyst_high_memory", "catalyst_center", rtr.key, 2 * DAY, 2 * DAY - 3 * HOUR, device=rtr)
        core = rng.choice(c_core)
        self._add("catalyst_ping_reachable", "catalyst_center", core.key, 9 * HOUR, 15 * 60, device=core)
        atl = c_routers["ATL"]
        self._add("catalyst_wan_down", "catalyst_center", f"{atl.key}|GigabitEthernet0/0/0", 12 * HOUR, 30 * 60,
                  device=atl, port_id="GigabitEthernet0/0/0")
        ifaces = [(d, p) for d in c_access for p in d.ports if p.connected and p.kind == "access" and not p.peer]
        for d, p in rng.sample(ifaces, 3):
            self._add("catalyst_iface_errors", "catalyst_center", f"{d.key}|{p.port_id}", 6 * HOUR, 60 * 60,
                      device=d, port_id=p.port_id)

        tests = {t.name: t for t in self.inv.te_tests}
        agents = {a.agent_id: a for a in self.inv.te_agents}

        def te(kind, test_name, agent_id, period, duration):
            test = tests[test_name]
            agent = agents.get(agent_id) if agent_id else None
            target = f"{test.test_id}|{agent_id or '*'}"
            self._add(kind, "thousandeyes", target, period, duration, test=test, agent=agent)

        te("te_high_latency", "Salesforce Login", "31", DAY, 22 * HOUR)
        te("te_http_down", "SAP Portal", None, 6 * HOUR, 20 * 60)
        te("te_dns_failure", "Corporate DNS - acme.example", "4", 3 * HOUR, 15 * 60)
        te("te_packet_loss", "AWS eu-central-1", "1025", 4 * HOUR, 45 * 60)
        te("te_high_latency", "Webex Meetings", "7", 5 * HOUR, 30 * 60)

    def active(self, kind: str, target: str, t: float) -> bool:
        return any(i.active(t) for i in self._by_target.get((kind, target), ()))

    def te_active(self, kind: str, test: TETest, agent: TEAgent, t: float) -> bool:
        return self.active(kind, f"{test.test_id}|{agent.agent_id}", t) or self.active(kind, f"{test.test_id}|*", t)

    # ── Meraki ───────────────────────────────────────────────────────────
    def meraki_status(self, dev: Device, t: float) -> str:
        if self.active("meraki_offline", dev.key, t):
            return "offline"
        if self.active("meraki_alerting", dev.key, t):
            return "alerting"
        if dev.product_type == "switch" and self.active("meraki_uplink_port_down", f"{dev.key}|24", t):
            return "alerting"
        return "online"

    def meraki_port(self, dev: Device, port, t: float) -> dict:
        target = f"{dev.key}|{port.port_id}"
        rng = stable_rng(self.seed, "mport", target, int(t // 300))
        is_uplink = port.kind == "uplink"
        peer = self._devices.get(port.peer)
        down = (
            not port.connected
            or (peer is not None and peer.source == "meraki" and self.meraki_status(peer, t) == "offline")
            or self.active("meraki_uplink_port_down", target, t)
        )
        result = {
            "enabled": True,
            "status": "Disconnected" if down else "Connected",
            "is_uplink": is_uplink,
            "errors": [],
            "warnings": [],
            "speed": "",
            "duplex": "",
            "in_kbps": 0.0,
            "out_kbps": 0.0,
            "energy_wh": 0.0,
            "poe_allocated": False,
        }
        if down:
            result["errors"] = ["Port disconnected"]
            return result
        speed = port.speed_mbps
        if self.active("meraki_port_warnings", target, t):
            speed = 100
            result["warnings"] = ["Port is negotiating at a lower speed than its capability"]
        if self.active("meraki_port_errors", target, t):
            result["errors"] = ["CRC align errors detected"]
        result["speed"] = f"{speed // 1000} Gbps" if speed >= 1000 else f"{speed} Mbps"
        result["duplex"] = "full"
        load = port.load * diurnal(t, dev.site.utc_offset) * rng.uniform(0.7, 1.3)
        total = max(1.0, load * speed * 1000 * 0.12)
        result["in_kbps"] = round(total * 0.65, 1)
        result["out_kbps"] = round(total * 0.35, 1)
        if port.poe:
            watts = {"wireless": 14.5, "camera": 7.8}.get(peer.product_type, 0.0) if peer else 0.0
            if not peer and rng.random() < 0.3:
                watts = 4.8
            if watts:
                result["poe_allocated"] = True
                result["energy_wh"] = round(watts * rng.uniform(0.9, 1.1) * 300 / 3600, 3)
        return result

    def meraki_uplink(self, dev: Device, uplink: str, t: float) -> tuple:
        target = f"{dev.key}|{uplink}"
        rng = stable_rng(self.seed, "uplink", target, int(t // 60))
        loss = 0.0 if rng.random() < 0.9 else round(rng.uniform(0.1, 1.0), 1)
        latency = round(rng.uniform(8, 22) if uplink != "cellular" else rng.uniform(45, 80), 1)
        if self.active("meraki_uplink_loss", target, t):
            loss = round(rng.uniform(6, 14), 1)
        if self.active("meraki_uplink_latency", target, t):
            latency = round(rng.uniform(170, 380), 1)
        return loss, latency

    # ── Catalyst Center ──────────────────────────────────────────────────
    def vienna_isolated(self, dev: Device, t: float) -> bool:
        return False

    def catalyst_device(self, dev: Device, t: float) -> dict:
        rng = stable_rng(self.seed, "cdev", dev.key, int(t // 300))
        cpu = round(rng.uniform(4, 28), 1)
        mem = round(rng.uniform(32, 58), 1)
        result = {"reachability": "Reachable", "manageability": "Managed", "cpu": cpu, "mem": mem,
                  "cpu_health": 10, "mem_health": 10, "overall": 10}
        if self.active("catalyst_unreachable", dev.key, t):
            return {"reachability": "Unreachable", "manageability": "Managed", "cpu": None, "mem": None,
                    "cpu_health": None, "mem_health": None, "overall": 1}
        if self.active("catalyst_ping_reachable", dev.key, t):
            result.update(reachability="Ping Reachable", overall=6)
        if self.active("catalyst_high_cpu", dev.key, t):
            cpu = round(rng.uniform(84, 98), 1)
            result.update(cpu=cpu, cpu_health=2 if cpu > 93 else 5, overall=3 if cpu > 93 else 5)
        if self.active("catalyst_high_memory", dev.key, t):
            result.update(mem=round(rng.uniform(81, 88), 1), mem_health=6, overall=min(result["overall"], 6))
        return result

    def catalyst_iface(self, dev: Device, port, t: float) -> dict:
        target = f"{dev.key}|{port.port_id}"
        rng = stable_rng(self.seed, "ciface", target, int(t // 300))
        device_down = self.active("catalyst_unreachable", dev.key, t)
        peer = self._devices.get(port.peer)
        peer_down = peer is not None and self.active("catalyst_unreachable", peer.key, t)
        up = port.connected and port.admin_up and not device_down and not peer_down
        admin_up = port.admin_up
        if self.active("catalyst_wan_down", target, t):
            up = False
        result = {"admin": "UP" if admin_up else "DOWN", "oper": "up" if up else "down",
                  "rx_bps": 0, "tx_bps": 0, "rx_err": 0.0, "tx_err": 0.0, "rx_disc": 0.0, "tx_disc": 0.0}
        if not up or port.kind == "loopback":
            return result
        load = max(port.load, 0.02) * diurnal(t, dev.site.utc_offset) * rng.uniform(0.7, 1.3)
        total = load * port.speed_mbps * 1_000_000 * 0.1
        result["rx_bps"] = int(total * 0.6)
        result["tx_bps"] = int(total * 0.4)
        if self.active("catalyst_iface_errors", target, t):
            result["rx_err"] = round(rng.uniform(0.5, 3.0), 2)
            result["rx_disc"] = round(rng.uniform(0.1, 0.8), 2)
        return result

    # ── ThousandEyes ─────────────────────────────────────────────────────
    def te_metrics(self, test: TETest, agent: TEAgent, t: float) -> dict:
        base = stable_rng(self.seed, "te-base", test.test_id, agent.agent_id)
        rng = stable_rng(self.seed, "te", test.test_id, agent.agent_id, int(t // 300))
        far = agent.country in ("US", "SG") and not test.target.startswith("10.")
        base_latency = base.uniform(90, 170) if far else base.uniform(6, 38)
        metrics: dict = {}
        if test.test_type in ("agent-to-server", "http-server"):
            loss = 0.0
            latency = base_latency * rng.uniform(0.9, 1.15)
            jitter = rng.uniform(0.2, 2.5)
            if self.te_active("te_packet_loss", test, agent, t):
                loss = rng.uniform(2, 12)
            if self.te_active("te_high_latency", test, agent, t):
                latency = rng.uniform(270, 420)
                jitter = rng.uniform(8, 25)
            metrics["network.loss"] = round(loss, 1)
            metrics["network.latency"] = round(latency, 1)
            metrics["network.jitter"] = round(jitter, 2)
        if test.test_type == "http-server":
            availability = 1.0
            duration = base.uniform(0.18, 0.7) * rng.uniform(0.85, 1.25)
            if self.te_active("te_http_down", test, agent, t):
                availability = 0.0 if rng.random() < 0.7 else 0.5
                duration = rng.uniform(3.2, 8.0)
            metrics["http.server.request.availability"] = availability
            metrics["http.client.request.duration"] = round(duration, 3)
        if test.test_type == "dns-server":
            availability = 1.0
            duration = base.uniform(0.008, 0.06) * rng.uniform(0.85, 1.3)
            if self.te_active("te_dns_failure", test, agent, t):
                availability = 0.0
                duration = 5.0
            metrics["dns.lookup.availability"] = availability
            metrics["dns.lookup.duration"] = round(duration, 4)
        return metrics

    # ── alerts ───────────────────────────────────────────────────────────
    def alert_windows(self, a: float, b: float) -> list:
        windows = []
        for issue in self.issues:
            for start, end in issue.windows(a, b):
                windows.append(AlertWindow(
                    alert_id=stable_hex(issue.key, int(start)),
                    kind=issue.kind,
                    source=issue.source,
                    start=start,
                    end=end,
                    device=issue.device,
                    port_id=issue.port_id,
                    test=issue.test,
                    agent=issue.agent,
                ))
        windows.extend(self._noise_windows(a, b))
        return windows

    def _noise_windows(self, a: float, b: float) -> list:
        windows = []
        by_type: dict = defaultdict(list)
        for dev in self.inv.devices:
            if not _is_vienna(dev):
                by_type[(dev.source, dev.product_type)].append(dev)
        first_hour = int(a // HOUR) - 2
        last_hour = int(b // HOUR)
        for hour in range(first_hour, last_hour + 1):
            for source, templates, rate in (("meraki", MERAKI_NOISE, 0.7),
                                            ("catalyst_center", CATALYST_NOISE, 0.6)):
                rng = stable_rng(self.seed, "noise", source, hour)
                if rng.random() > rate:
                    continue
                product, kind, _sev, _title = rng.choice(templates)
                candidates = by_type.get((source, product))
                if not candidates:
                    continue
                dev = rng.choice(candidates)
                start = hour * HOUR + rng.randrange(HOUR)
                end = start + rng.randrange(10 * 60, 90 * 60)
                if end < a or start > b:
                    continue
                windows.append(AlertWindow(
                    alert_id=stable_hex("noise", source, hour, kind),
                    kind=f"noise:{kind}",
                    source=source,
                    start=start,
                    end=end,
                    device=dev,
                ))
        return windows
