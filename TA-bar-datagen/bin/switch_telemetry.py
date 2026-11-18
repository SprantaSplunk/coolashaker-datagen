"""
IOS-XE syslog (sourcetype cisco:ios) and gNMI telemetry (sourcetype cisco:gnmi) for the
Catalyst campus switches of the Network Intelligence datagen.

The switches are configured like a typical managed campus:
  service timestamps log datetime msec localtime show-timezone
  logging origin-id hostname
  archive / log config / logging enable / notify syslog contenttype plaintext / hidekeys
      -> every configuration command: %PARSER-5-CFGLOG_LOGGEDCMD
  event manager applet CLI_AUDIT (cli pattern ".*" sync no skip no)
      -> every exec command: %HA_EM-6-LOG: CLI_AUDIT: ...
  telemetry: Telegraf gnmi input, openconfig-interfaces, sample 60 s
so the Cisco Catalyst add-on (TA_cisco_catalyst) extracts user, command, src_ip,
src_interface and vendor_action from the raw lines.

Everything is derived from (switch, minute) seeded RNGs, so the same window always
produces the same lines, so the stateless NI datagen can run in arbitrary windows.

"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

LINK_DELAY = 2.0             # seconds between the command and the resulting port events
SAMPLE_SEC = 60              # gNMI sample interval
COUNTER_EPOCH = 1_767_225_600  # 2026-01-01: interface counters count from here

ADMINS = ("a.huber", "k.novak", "m.schmidt", "l.wagner", "j.miller", "s.oconnor", "p.rossi")
AUTOMATION_USER = "svc-ansible"
SHOW_COMMANDS = (
    "show interfaces status", "show running-config", "show ip interface brief", "show logging",
    "show spanning-tree summary", "show cdp neighbors", "show lldp neighbors", "show version",
    "show interfaces counters errors", "show mac address-table dynamic", "show power inline",
    "show etherchannel summary", "show ip ospf neighbor", "show standby brief", "show vlan brief",
    "show authentication sessions", "show archive log config all",
)
VLANS = ((110, "USERS-OFFICE"), (120, "VOICE"), (130, "PRINTERS"), (140, "CAMERAS"),
         (150, "IOT-SENSORS"), (160, "GUEST"), (170, "LAB"), (180, "BUILDING-MGMT"))
DESCRIPTIONS = ("Office 2.14", "Meeting room Danube", "Printer floor 3", "Badge reader lobby",
                "Desk 4.07", "Lab bench 2", "Video bar room 1.02", "Kiosk reception", "Desk 3.21")
CHANNEL = "Port-channel1"
NOT_PHYSICAL = ("svi", "loopback", "mgmt")


# ── topology ───────────────────────────────────────────────────────────────────
@dataclass
class SwPort:
    name: str
    kind: str = "access"        # access | uplink | trunk | svi | loopback
    peer: str = ""              # name of the switch on the other end ("" = not a modelled switch)
    peer_port: str = ""
    desc: str = ""
    connected: bool = False
    speed_mbps: int = 1000
    load: float = 0.1
    channel: str = ""           # port-channel membership
    ospf_nbr: str = ""          # OSPF neighbour IP reached through this port


@dataclass
class Switch:
    name: str                   # Splunk host = Catalyst Center DeviceName
    hostname: str               # IOS hostname used in the messages
    site: str
    ip: str
    role: str                   # CORE | DISTRIBUTION | ACCESS
    model: str
    tz: object                  # tzinfo (None = UTC)
    admin_net: str              # "10.30.99": jump hosts of the site's network team
    vienna: bool = False
    ports: list = field(default_factory=list)

    def port(self, name):
        for p in self.ports:
            if p.name == name:
                return p
        return None

    @property
    def physical(self):
        return [p for p in self.ports if p.kind not in NOT_PHYSICAL]


class Topology:
    def __init__(self, switches, core_names):
        """core_names: the two Vienna campus cores the scenario shuts down."""
        self.switches = {s.name: s for s in switches}
        self.cores = [self.switches[n] for n in core_names if n in self.switches]
        self.sites = {}
        for s in switches:
            self.sites.setdefault(s.site, []).append(s)

    def core_index(self, sw):
        return self.cores.index(sw) if sw in self.cores else None


def connect(a: Switch, a_port: str, b: Switch, b_port: str, speed=10000, load=0.4, channel="", ospf=False):
    pa, pb = a.port(a_port), b.port(b_port)
    for p, peer, peer_port, peer_sw in ((pa, b.name, b_port, b), (pb, a.name, a_port, a)):
        p.peer, p.peer_port, p.connected = peer, peer_port, True
        p.desc = f"to {peer_sw.hostname} {peer_port}"
        p.speed_mbps, p.load, p.channel = speed, load, channel
        if ospf:
            p.ospf_nbr = peer_sw.ip


def attach(sw: Switch, port: str, desc: str, speed=None, load=0.2, ospf_nbr=""):
    p = sw.port(port)
    p.connected, p.desc, p.load, p.ospf_nbr = True, desc, load, ospf_nbr
    if speed:
        p.speed_mbps = speed


def range_expr(names):
    """IOS 'interface range' argument, e.g. 'TwentyFiveGigE1/0/1 - 24 , HundredGigE1/0/25 - 28'."""
    groups = []
    for name in names:
        prefix, _, num = name.rpartition("/")
        if not num.isdigit():
            groups.append([name, None, None])
            continue
        n = int(num)
        if groups and groups[-1][1] == prefix and groups[-1][2][1] == n - 1:
            groups[-1][2][1] = n
        else:
            groups.append([name, prefix, [n, n]])
    parts = []
    for first, prefix, span in groups:
        if span is None or span[0] == span[1]:
            parts.append(first)
        else:
            parts.append(f"{prefix}/{span[0]} - {span[1]}")
    return " , ".join(parts)


# ── site state ─────────────────────────────────────────────────────────────────
class Outage:
    """Always normal operation: no core is ever down and no switch is cut off."""

    active = False

    def __init__(self, *args, **kwargs):
        pass

    def shut_time(self, i):
        return None

    def was_shut(self, i):
        return False

    def up_time(self, i):
        return None

    def core_down(self, i, ts):
        return False

    def isolated(self, ts):
        return False

    def finished(self, ts):
        return True


def reachable(topo: Topology, outage: Outage, sw: Switch, ts):
    """Vienna switches behind the cores lose their path to the collector while both cores are down."""
    return not (sw.vienna and sw not in topo.cores and outage.isolated(ts))


def port_state(topo: Topology, outage: Outage, sw: Switch, port: SwPort, ts):
    """(admin_up, oper_up) at ts."""
    i = topo.core_index(sw)
    if i is not None and outage.core_down(i, ts):
        return (port.kind == "svi"), False
    peer = topo.switches.get(port.peer)
    j = topo.core_index(peer) if peer else None
    if j is not None and outage.core_down(j, ts):
        return True, False
    return True, port.connected or port.kind in NOT_PHYSICAL


# ── message formatting ────────────────────────────────────────────────────────
def stable_rng(*parts):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _local(sw, ts):
    return datetime.fromtimestamp(ts, sw.tz or timezone.utc)


def device_time(sw, ts):
    dt = _local(sw, ts)
    return f"{dt:%b} {dt.day:2d} {dt:%H:%M:%S}.{dt.microsecond // 1000:03d} {dt.tzname() or 'UTC'}"


def render(sw: Switch, ts, msg, seq):
    return f"{seq}: {sw.hostname}: {device_time(sw, ts)}: {msg}"


def _login_clock(sw, ts):
    dt = _local(sw, ts)
    return f"{dt:%H:%M:%S} {dt.tzname() or 'UTC'} {dt:%a %b} {dt.day} {dt:%Y}"


def ssh_login(sw, ts, user, src, tty):
    cipher = "using crypto cipher 'aes256-gcm', hmac 'hmac-sha2-256'"
    return [
        (ts, f"%SSH-5-SSH2_SESSION: SSH2 Session request from {src} (tty = {tty}) {cipher} Succeeded"),
        (ts + 0.4, f"%SSH-5-SSH2_USERAUTH: User '{user}' authentication for SSH2 Session from {src} "
                   f"(tty = {tty}) {cipher} Succeeded"),
        (ts + 0.5, f"%SEC_LOGIN-5-LOGIN_SUCCESS: Login Success [user: {user}] [Source: {src}] [localport: 22] "
                   f"at {_login_clock(sw, ts + 0.5)}"),
    ]


def login_failed(sw, ts, user, src):
    return [(ts, f"%SEC_LOGIN-4-LOGIN_FAILED: Login failed [user: {user}] [Source: {src}] [localport: 22] "
                 f"[Reason: Login Authentication Failed] at {_login_clock(sw, ts)}")]


def audit(ts, user, tty, src, cmd):
    return (ts, f'%HA_EM-6-LOG: CLI_AUDIT: user={user} line=vty{tty} src={src} cmd="{cmd}"')


def logged_cmd(ts, user, cmd):
    return (ts, f"%PARSER-5-CFGLOG_LOGGEDCMD: User:{user}  logged command:{cmd}")


def config_done(ts, user, tty, src):
    return (ts, f"%SYS-5-CONFIG_I: Configured from console by {user} on vty{tty} ({src})")


def logout(ts, user, tty, src):
    return (ts, f"%SYS-6-LOGOUT: User {user} has exited tty session {tty}({src})")


def link(ts, port, state):
    return [(ts, f"%LINK-3-UPDOWN: Interface {port}, changed state to {state}"),
            (ts + 0.9, f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {port}, changed state to {state}")]


def admin_down(ts, port):
    return (ts, f"%LINK-5-CHANGED: Interface {port}, changed state to administratively down")


def lineproto(ts, port, state):
    return (ts, f"%LINEPROTO-5-UPDOWN: Line protocol on Interface {port}, changed state to {state}")


def ospf(ts, nbr, port, up):
    if up:
        return (ts, f"%OSPF-5-ADJCHG: Process 1, Nbr {nbr} on {port} from LOADING to FULL, Loading Done")
    return (ts, f"%OSPF-5-ADJCHG: Process 1, Nbr {nbr} on {port} from FULL to DOWN, "
                f"Neighbor Down: Interface down or detached")


def hsrp(ts, vlan, old, new):
    return (ts, f"%HSRP-5-STATECHANGE: {vlan} Grp 1 state {old} -> {new}")


# ── baseline: admins, automation, end-user ports ───────────────────────────────
def _business(sw, ts):
    dt = _local(sw, ts)
    return dt.weekday() < 5 and 7 <= dt.hour < 19


def _config_template(sw, r):
    access = [p for p in sw.ports if p.kind == "access"]
    trunks = [p for p in sw.ports if p.kind in ("uplink", "trunk") and p.connected]
    vlan, vname = r.choice(VLANS)
    net = sw.ip.rsplit(".", 2)[0]
    options = [
        ["vlan %d" % vlan, "name %s" % vname],
        ["ntp server 10.0.0.%d prefer" % r.choice((5, 6))],
        ["snmp-server location %s, %s" % (sw.site, r.choice(("Floor 1", "Floor 2", "IDF 3", "MDF")))],
        ["ip access-list extended ACL-MGMT-IN", "%d permit tcp %s.0 0.0.0.255 any eq 22" % (r.randrange(10, 90, 10),
                                                                                            sw.admin_net)],
        ["logging buffered 64000 informational"],
        ["username %s privilege 15 secret *****" % r.choice(ADMINS)],
        ["banner motd ^C Authorized access only - all activity is logged ^C"],
    ]
    if access:
        p = r.choice(access).name
        options += [
            ["interface %s" % p, "description %s" % r.choice(DESCRIPTIONS), "switchport access vlan %d" % vlan],
            ["interface %s" % p, "switchport voice vlan 120", "spanning-tree portfast"],
            ["interface %s" % p, "authentication port-control auto", "mab", "dot1x pae authenticator"],
            ["interface %s" % p, "power inline auto", "description %s" % r.choice(DESCRIPTIONS)],
        ]
    if trunks:
        p = r.choice(trunks).name
        options.append(["interface %s" % p, "switchport trunk allowed vlan add %d" % vlan])
    if sw.role in ("CORE", "DISTRIBUTION"):
        options += [
            ["interface Vlan%d" % vlan, "description %s" % vname, "ip helper-address %s.0.20" % net, "no shutdown"],
            ["router ospf 1", "passive-interface Vlan%d" % vlan],
            ["ip route 10.200.%d.0 255.255.255.0 %s.0.1 name %s" % (vlan, net, vname)],
        ]
    cmds = r.choice(options)
    if r.random() < 0.35:
        cmds = cmds + r.choice(options)
    return cmds


def admin_session(sw, t0, r, user=None, configure=True):
    user = user or r.choice(ADMINS)
    src = "%s.%d" % (sw.admin_net, 11 + ADMINS.index(user) if user in ADMINS else 15)
    tty = r.randint(1, 4)
    ev = ssh_login(sw, t0, user, src, tty)
    t = t0 + r.uniform(3, 8)
    for cmd in r.sample(SHOW_COMMANDS, r.randint(1, 3)):
        ev.append(audit(t, user, tty, src, cmd))
        t += r.uniform(3, 15)
    if configure:
        ev.append(audit(t, user, tty, src, "configure terminal"))
        t += r.uniform(2, 5)
        for cmd in _config_template(sw, r):
            ev.append(logged_cmd(t, user, cmd))
            t += r.uniform(2, 8)
        ev.append(config_done(t + 0.5, user, tty, src))
        if r.random() < 0.7:
            t += r.uniform(3, 8)
            ev.append(audit(t, user, tty, src, "write memory"))
    ev.append(logout(t + r.uniform(5, 30), user, tty, src))
    return ev


def _flap(sw, r, t):
    users = [p for p in sw.ports if p.kind == "access" and p.connected and not p.peer]
    if not users:
        return []
    p = r.choice(users).name
    back = t + r.uniform(4, 120)
    ev = link(t, p, "down")
    ev += link(back, p, "up")
    if r.random() < 0.6:
        mac = "%04x.%04x.%04x" % (r.randrange(65536), r.randrange(65536), r.randrange(65536))
        sid = "%08X%016X" % (r.randrange(16 ** 8), r.randrange(16 ** 16))
        ev.append((back + 3.2, f"%SESSION_MGR-5-SUCCESS: Authorization succeeded for client ({mac}) on Interface "
                               f"{p} AuditSessionID {sid}"))
    return ev


def baseline_events(topo: Topology, a, b, seed):
    """[(ts, switch, msg)] for (a, b]: link flaps, 802.1X, admin sessions, automation, failed logins."""
    out = []
    for m in range(int(a // 60) - 3, int(b // 60) + 1):
        t0 = m * 60
        for site, switches in topo.sites.items():
            ref = switches[0]
            busy = _business(ref, t0)
            r = stable_rng(seed, "session", site, m)
            if r.random() < (0.09 if busy else 0.015):
                sw = r.choice(switches)
                out += [(t, sw, msg) for t, msg in admin_session(sw, t0 + r.uniform(0, 60), r)]
            r = stable_rng(seed, "misc", site, m)
            x = r.random()
            if x < 0.012:
                sw = r.choice(switches)
                out += [(t, sw, msg) for t, msg in login_failed(sw, t0 + r.uniform(0, 60), r.choice(
                    ("admin", "cisco", "root", "backup")), "%s.%d" % (sw.admin_net, r.randint(60, 99)))]
            elif x < 0.022:
                sw = r.choice(switches)
                out.append((t0 + r.uniform(0, 60), sw, "%DMI-5-CONFIG_I: R0/0: dmiauthd: Configured from "
                            f"NETCONF/RESTCONF by dnac-svc, transaction-id {r.randint(1000, 99999)}"))
            elif x < 0.03 and busy:
                sw = r.choice(switches)
                out += [(t, sw, msg) for t, msg in admin_session(sw, t0 + r.uniform(0, 60), r, user=AUTOMATION_USER)]
            elif x < 0.04:
                sw = r.choice(switches)
                out += [(t, sw, msg) for t, msg in admin_session(sw, t0 + r.uniform(0, 60), r, configure=False)]
            for sw in switches:
                if sw.role != "ACCESS":
                    continue
                r = stable_rng(seed, "flap", sw.name, m)
                if r.random() < (0.08 if busy else 0.02):
                    out += [(t, sw, msg) for t, msg in _flap(sw, r, t0 + r.uniform(0, 60))]
    return out


# ── scenario: the shutdown and the recovery ────────────────────────────────────
def _on(sw, items):
    return [(t, sw, msg) for t, msg in items]


def _peer_effects(topo, sw, port, ts, state):
    """Messages on the switch at the other end of ``port`` when the link goes down/up."""
    peer = topo.switches.get(port.peer)
    if peer is None:
        return []
    pp = peer.port(port.peer_port)
    out = _on(peer, link(ts, pp.name, state))
    if pp.channel:
        members = [p for p in peer.ports if p.channel == pp.channel]
        verb = "left the" if state == "down" else "joined"
        out.append((ts + 1.1, peer, f"%EC-5-{'UNBUNDLE' if state == 'down' else 'BUNDLE'}: Interface {pp.name} "
                                    f"{verb} port-channel {pp.channel}"))
        if pp is (members[-1] if state == "down" else members[0]):
            out += _on(peer, link(ts + 1.4, pp.channel, state))
            out += _on(peer, [ospf(ts + (2.2 if state == "down" else 9.5), sw.ip, pp.channel, state == "up")])
    elif pp.ospf_nbr:
        out.append((ts + (1.8 if state == "down" else 9.0), peer, ospf(0, sw.ip, pp.name, state == "up")[1]))
    return out


def _session_cmds(sw, user, tty, src, start, steps):
    """steps: [(offset, 'exec'|'conf', command)] relative to ``start``."""
    out = []
    for dt, kind, cmd in steps:
        item = audit(start + dt, user, tty, src, cmd) if kind == "exec" else logged_cmd(start + dt, user, cmd)
        out.append((item[0], sw, item[1]))
    return out


def scenario_events(topo: Topology, outage: Outage):
    return []


def syslog_lines(topo: Topology, outage: Outage, a, b, seed):
    """[(ts, switch, raw line)] in (a, b], in time order, without lines from unreachable switches."""
    events = baseline_events(topo, a, b, seed) + scenario_events(topo, outage)
    events = [(t, sw, m) for t, sw, m in events if a < t <= b and reachable(topo, outage, sw, t)]
    events = [e for e in events if not _quiet(topo, outage, e)]
    events.sort(key=lambda e: e[0])
    # sequence number from the 10 ms clock: increasing across windows without any state
    return [(t, sw, render(sw, t, msg, "%06d" % (int(t * 100) % 1000000))) for t, sw, msg in events]


def _quiet(topo, outage, event):
    return False


# ── gNMI telemetry ─────────────────────────────────────────────────────────────
def _diurnal(sw, ts):
    dt = _local(sw, ts)
    hour = dt.hour + dt.minute / 60
    f = 0.35 + 0.65 * max(0.0, 1 - abs(hour - 13) / 6) if 7 <= hour <= 19 else 0.15
    return f * (0.45 if dt.weekday() >= 5 else 1.0)


def _counter_ts(topo, outage, sw, port, ts):
    """Counters stop increasing while the port is down."""
    for i, core in enumerate(topo.cores):
        if (sw is core or port.peer == core.name) and outage.core_down(i, ts):
            return outage.shut_time(i) + LINK_DELAY
    return ts


def gnmi_events(topo: Topology, outage: Outage, ts, seed):
    """[(switch, event dict)] for one sample at ts (cores: every physical port, others: connected ports)."""
    out = []
    slot = int(ts // SAMPLE_SEC)
    for sw in topo.switches.values():
        if not reachable(topo, outage, sw, ts):
            continue
        is_core = sw in topo.cores
        oper_up = admin_down = 0
        load_f = _diurnal(sw, ts)
        for port in sw.ports:
            if port.kind in ("loopback", "mgmt"):
                continue
            # cores: every port (the scenario shuts them all); elsewhere: uplinks/trunks and SVIs
            if not ((is_core and port.kind not in NOT_PHYSICAL) or port.kind == "svi"
                    or (port.connected and port.kind != "access")):
                continue
            admin, oper = port_state(topo, outage, sw, port, ts)
            oper_up += oper
            admin_down += not admin
            if port.kind == "svi":
                continue
            r = stable_rng(seed, "gnmi", sw.name, port.name, slot)
            bps = port.speed_mbps * 1e6 * port.load * load_f * r.uniform(0.75, 1.25) * 0.5 if oper else 0.0
            in_bps, out_bps = int(bps * 0.6), int(bps * 0.4)
            avg = port.speed_mbps * 1e6 * port.load * 0.25 / 8 if port.connected else 0.0
            cts = max(0.0, _counter_ts(topo, outage, sw, port, ts) - COUNTER_EPOCH)
            base = stable_rng(seed, "gnmi-base", sw.name, port.name).randrange(10 ** 9, 10 ** 11)
            in_octets = int(base + avg * 0.6 * cts)
            out_octets = int(base * 0.7 + avg * 0.4 * cts)
            out.append((sw, {
                "device": sw.name, "device_ip": sw.ip, "site": sw.site, "role": sw.role, "platform": sw.model,
                "subscription": "interfaces", "origin": "openconfig-interfaces",
                "path": "/interfaces/interface/state", "mode": "sample", "sample_interval_s": SAMPLE_SEC,
                "collector": "telegraf-gnmi",
                "interface": port.name, "description": port.desc,
                "admin_status": "UP" if admin else "DOWN", "oper_status": "UP" if oper else "DOWN",
                "speed_mbps": port.speed_mbps,
                "in_octets": in_octets, "out_octets": out_octets,
                "in_unicast_pkts": in_octets // 780, "out_unicast_pkts": out_octets // 820,
                "in_errors": int(cts // 86400), "out_errors": 0,
                "in_discards": int(cts // 43200), "out_discards": int(cts // 21600),
                "in_bps": in_bps, "out_bps": out_bps,
                "in_util_pct": round(in_bps / (port.speed_mbps * 1e6) * 100, 2),
                "out_util_pct": round(out_bps / (port.speed_mbps * 1e6) * 100, 2),
            }))
        r = stable_rng(seed, "gnmi-sys", sw.name, slot)
        cpu = r.uniform(4, 18) + 10 * load_f
        physical = [p for p in sw.ports if p.kind not in NOT_PHYSICAL]
        out.append((sw, {
            "device": sw.name, "device_ip": sw.ip, "site": sw.site, "role": sw.role, "platform": sw.model,
            "subscription": "system", "origin": "Cisco-IOS-XE-process-cpu-oper",
            "path": "/cpu-usage/cpu-utilization", "mode": "sample", "sample_interval_s": SAMPLE_SEC,
            "collector": "telegraf-gnmi",
            "cpu_five_seconds": round(cpu, 1), "cpu_one_minute": round(cpu * 0.9, 1),
            "cpu_five_minutes": round(cpu * 0.85, 1),
            "memory_used_pct": round(r.uniform(38, 52), 1),
            "interfaces_physical": len(physical),
            "interfaces_oper_up": oper_up, "interfaces_admin_down": admin_down,
        }))
    return out
