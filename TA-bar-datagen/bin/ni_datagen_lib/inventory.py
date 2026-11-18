"""Deterministic network inventory: sites, devices, ports, links, synthetic tests.

Everything is derived from a single seed so restarts reuse the same serials,
MACs and IDs, which keeps the app's KV store graph stable.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .util import rng_uuid

MERAKI_ORG_ID = "713288"
MERAKI_ORG_NAME = "ACME Europe"
TE_ACCOUNT_ID = "1203456"

MERAKI_OUIS = ("e0:55:3d", "88:15:44", "0c:8d:db", "ac:17:c8", "98:18:88", "f8:9e:28")
CISCO_OUIS = ("00:1e:7a", "70:1f:53", "a4:b2:39", "f4:bd:9e", "00:3a:9a", "bc:e7:12")


@dataclass
class Site:
    key: str
    source: str
    internal_id: str
    name: str
    code: str
    city: str
    country: str
    time_zone: str
    utc_offset: int
    lat: float
    lon: float
    hierarchy: str = ""
    url: str = ""
    tags: list = field(default_factory=list)


@dataclass
class Port:
    port_id: str
    name: str
    ifindex: int = 0
    kind: str = "access"  # access | uplink | wan | loopback | svi | ap
    connected: bool = False
    poe: bool = False
    speed_mbps: int = 1000
    peer: str = ""  # device key of the attached infra device, if any
    peer_port: str = ""  # SNMP: LLDP port ID reported by the neighbour
    interface_id: str = ""  # Catalyst Center interface UUID
    if_type: str = "ethernetCsmacd"  # SNMP: IF-MIB.ifType
    is_wan: bool = False
    admin_up: bool = True
    vlan: int = 100
    load: float = 0.0  # relative traffic weight


@dataclass
class Device:
    key: str
    source: str
    site: Site
    name: str
    serial: str
    mac: str
    model: str
    product_type: str  # meraki productType or catalyst DeviceFamily
    role: str
    firmware: str
    ip: str
    lat: float
    lon: float
    device_id: str = ""  # Catalyst Center DeviceID
    ports: list = field(default_factory=list)
    uplinks: list = field(default_factory=list)  # meraki WAN uplink names
    url: str = ""
    vendor: str = ""  # SNMP: manufacturer name (ENTITY-MIB)
    sys_object_id: str = ""  # SNMP: SNMPv2-MIB.sysObjectID
    sys_descr: str = ""  # SNMP: SNMPv2-MIB.sysDescr

    def port(self, port_id: str) -> Optional[Port]:
        for port in self.ports:
            if port.port_id == port_id:
                return port
        return None


@dataclass
class Link:
    link_id: str
    a: Device
    a_port: str
    b: Device
    b_port: str


@dataclass
class Neighbor:
    derived_id: str
    reporter: Device
    reporter_port: str
    mac: str
    system_name: str
    description: str
    platform: str
    capabilities: list
    port_id: str
    address: str
    protocol: str = "LLDP"


@dataclass
class TEAgent:
    agent_id: str
    name: str
    location: str
    country: str
    region: str
    geoname_id: str
    kind: str  # Cloud | Enterprise


@dataclass
class TETest:
    test_id: str
    name: str
    test_type: str  # agent-to-server | http-server | dns-server
    target: str
    agents: list = field(default_factory=list)


@dataclass
class Inventory:
    sites: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    links: list = field(default_factory=list)
    neighbors: list = field(default_factory=list)
    te_agents: list = field(default_factory=list)
    te_tests: list = field(default_factory=list)

    def by_source(self, source: str) -> list:
        return [d for d in self.devices if d.source == source]

    def sites_by_source(self, source: str) -> list:
        return [s for s in self.sites if s.source == source]


# ── Meraki ────────────────────────────────────────────────────────────────
# (appliance, switch, wireless, camera, sensor, cellularGateway)
MERAKI_COUNTS = {"factory": (1, 3, 10, 4, 4, 1), "branch": (1, 1, 2, 0, 0, 0)}
_DE = ("DE", "Europe/Berlin", 2, "europe")
_AT = ("AT", "Europe/Vienna", 2, "europe")
_EST = ("US", "America/New_York", -4, "americas")
_CST = ("US", "America/Chicago", -5, "americas")
_MST = ("US", "America/Denver", -6, "americas")
_PST = ("US", "America/Los_Angeles", -7, "americas")
# name, code, city, state, (country, tz, utc offset, region), lat, lon, kind
MERAKI_SITES = [
    ("Atlanta Factory", "ATLF", "Atlanta", "GA", _EST, 33.7962, -84.4336, "factory"),
    ("Berlin Factory", "BERF", "Berlin", "BE", _DE, 52.4313, 13.5297, "factory"),
    ("Vienna Factory", "VIEF", "Vienna", "9", _AT, 48.1712, 16.4196, "factory"),
    # one branch per German state (Berlin has the office and the factory)
    ("Stuttgart Branch", "STR", "Stuttgart", "BW", _DE, 48.7758, 9.1829, "branch"),
    ("Munich Branch", "MUC", "Munich", "BY", _DE, 48.1351, 11.5820, "branch"),
    ("Potsdam Branch", "POT", "Potsdam", "BB", _DE, 52.3906, 13.0645, "branch"),
    ("Bremen Branch", "BRE", "Bremen", "HB", _DE, 53.0793, 8.8017, "branch"),
    ("Hamburg Branch", "HAM", "Hamburg", "HH", _DE, 53.5511, 9.9937, "branch"),
    ("Frankfurt Branch", "FRA", "Frankfurt", "HE", _DE, 50.1109, 8.6821, "branch"),
    ("Schwerin Branch", "SWR", "Schwerin", "MV", _DE, 53.6355, 11.4012, "branch"),
    ("Hanover Branch", "HAJ", "Hanover", "NI", _DE, 52.3759, 9.7320, "branch"),
    ("Duesseldorf Branch", "DUS", "Duesseldorf", "NW", _DE, 51.2277, 6.7735, "branch"),
    ("Mainz Branch", "MAI", "Mainz", "RP", _DE, 49.9929, 8.2473, "branch"),
    ("Saarbruecken Branch", "SCN", "Saarbruecken", "SL", _DE, 49.2402, 6.9969, "branch"),
    ("Dresden Branch", "DRS", "Dresden", "SN", _DE, 51.0504, 13.7373, "branch"),
    ("Magdeburg Branch", "MAG", "Magdeburg", "ST", _DE, 52.1205, 11.6276, "branch"),
    ("Kiel Branch", "KEL", "Kiel", "SH", _DE, 54.3233, 10.1228, "branch"),
    ("Erfurt Branch", "ERF", "Erfurt", "TH", _DE, 50.9848, 11.0299, "branch"),
    # one branch per Austrian state (Vienna has the office and the factory)
    ("Eisenstadt Branch", "EIS", "Eisenstadt", "1", _AT, 47.8456, 16.5233, "branch"),
    ("Klagenfurt Branch", "KLU", "Klagenfurt", "2", _AT, 46.6247, 14.3053, "branch"),
    ("St. Poelten Branch", "STP", "St. Poelten", "3", _AT, 48.2047, 15.6256, "branch"),
    ("Linz Branch", "LNZ", "Linz", "4", _AT, 48.3069, 14.2858, "branch"),
    ("Salzburg Branch", "SZG", "Salzburg", "5", _AT, 47.8095, 13.0550, "branch"),
    ("Graz Branch", "GRZ", "Graz", "6", _AT, 47.0707, 15.4395, "branch"),
    ("Innsbruck Branch", "INN", "Innsbruck", "7", _AT, 47.2692, 11.4041, "branch"),
    ("Bregenz Branch", "BRG", "Bregenz", "8", _AT, 47.5031, 9.7471, "branch"),
    # one branch per large US state
    ("Los Angeles Branch", "LAX", "Los Angeles", "CA", _PST, 34.0522, -118.2437, "branch"),
    ("Dallas Branch", "DFW", "Dallas", "TX", _CST, 32.7767, -96.7970, "branch"),
    ("New York Branch", "NYC", "New York", "NY", _EST, 40.7128, -74.0060, "branch"),
    ("Miami Branch", "MIA", "Miami", "FL", _EST, 25.7617, -80.1918, "branch"),
    ("Chicago Branch", "CHI", "Chicago", "IL", _CST, 41.8781, -87.6298, "branch"),
    ("Seattle Branch", "SEA", "Seattle", "WA", _PST, 47.6062, -122.3321, "branch"),
    ("Boston Branch", "BOS", "Boston", "MA", _EST, 42.3601, -71.0589, "branch"),
    ("Charlotte Branch", "CLT", "Charlotte", "NC", _EST, 35.2271, -80.8431, "branch"),
    ("Columbus Branch", "CMH", "Columbus", "OH", _EST, 39.9612, -82.9988, "branch"),
    ("Denver Branch", "DEN", "Denver", "CO", _MST, 39.7392, -104.9903, "branch"),
]

MERAKI_MODELS = {
    "appliance": (["MX85", "MX95"], "MX 18.211.2"),
    "switch": (["MS250-24P", "MS225-24P", "MS130-24P", "MS120-24P"], "MS 16.9"),
    "wireless": (["MR46", "MR36", "CW9166I", "MR57"], "MR 30.7"),
    "camera": (["MV63", "MV22", "MV33"], "MV 5.2"),
    "sensor": (["MT10", "MT14", "MT12"], "MT 1.7"),
    "cellularGateway": (["MG41"], "MG 2.2"),
}
MERAKI_NAME_PREFIX = {
    "appliance": "MX",
    "switch": "MS",
    "wireless": "AP",
    "camera": "CAM",
    "sensor": "MT",
    "cellularGateway": "MG",
}

# ── Catalyst Center ───────────────────────────────────────────────────────
# building name, code, city, country, tz, offset, lat, lon, hierarchy,
# (routers, core, access, wlc, aps)
CATALYST_SITES = [
    ("Atlanta-Office", "ATL", "Atlanta", "US", "America/New_York", -4, 33.7537, -84.3863,
     "Global/North America/USA/Atlanta/Atlanta-Office", (1, 2, 5, 1, 14)),
    ("Berlin-Office", "BER", "Berlin", "DE", "Europe/Berlin", 2, 52.5208, 13.4094,
     "Global/Europe/Germany/Berlin/Berlin-Office", (1, 2, 5, 1, 14)),
]
# Vienna office: built on its own RNG stream after everything else with a fixed
# site index (IPs 10.104.x), so its IDs stay identical to earlier inventories.
VIENNA_CATALYST_SITE = ("Vienna-Office", "VIE", "Vienna", "AT", "Europe/Vienna", 2, 48.2100, 16.3700,
                        "Global/Europe/Austria/Vienna/Vienna-Office", (1, 2, 4, 1, 10))
VIENNA_SITE_IDX = 4
VIENNA_SITE_KEY = "catalyst:site:VIE"
# devicehealth "Location" of the Vienna office: must equal the CoolaShaker Vienna site,
# the ITSI site entities match on it; the NI app reads "Site" first.
VIENNA_SHARED_LOCATION = "Global/Europe/Austria/Vienna"

# ── ThousandEyes ──────────────────────────────────────────────────────────
TE_AGENTS = [
    ("3", "Frankfurt, Germany", "Frankfurt, Hesse, Germany", "DE", "DE-HE", "2925533", "Cloud"),
    ("4", "London, England", "London, England, United Kingdom", "GB", "GB-ENG", "2643743", "Cloud"),
    ("7", "Amsterdam, Netherlands", "Amsterdam, North Holland, Netherlands", "NL", "NL-NH", "2759794", "Cloud"),
    ("11", "Paris, France", "Paris, Ile-de-France, France", "FR", "FR-IDF", "2988507", "Cloud"),
    ("19", "Ashburn, VA", "Ashburn, Virginia, US", "US", "US-VA", "4744870", "Cloud"),
    ("31", "Singapore", "Singapore", "SG", "SG-01", "1880252", "Cloud"),
    ("1024", "ber-office-te-ea01", "Berlin, Berlin, Germany", "DE", "DE-BE", "2950159", "Enterprise"),
    ("1025", "ber-factory-te-ea01", "Berlin, Berlin, Germany", "DE", "DE-BE", "2950159", "Enterprise"),
    ("1026", "atl-factory-te-ea01", "Atlanta, Georgia, US", "US", "US-GA", "4180439", "Enterprise"),
    ("1027", "atl-office-te-ea01", "Atlanta, Georgia, US", "US", "US-GA", "4180439", "Enterprise"),
    ("1028", "vie-office-te-ea01", "Vienna, Vienna, Austria", "AT", "AT-9", "2761369", "Enterprise"),
]
VIENNA_TE_AGENT = "1028"

# test id (ITSI services match on these), name, type, target, agent ids
TE_TESTS = [
    ("7746776", "Microsoft 365 - Outlook", "http-server", "outlook.office365.com", ["3", "4", "1024", "1025", "1026", "1028"]),
    ("7958177", "Salesforce Login", "http-server", "login.salesforce.com", ["3", "19", "31", "1024", "1027"]),
    ("7109127", "SAP Portal", "http-server", "sap.corp.acme.example", ["1024", "1025", "1026", "1027", "1028"]),
    ("7511054", "Webex Meetings", "http-server", "acme.webex.com", ["3", "4", "7", "1025", "1028"]),
    ("7984820", "ServiceNow ITSM", "http-server", "acme.service-now.com", ["4", "11", "1024", "1026"]),
    ("7878078", "Corporate Website", "http-server", "www.acme.example", ["3", "7", "11", "19", "31"]),
    ("7554970", "GitHub Enterprise", "http-server", "github.com", ["3", "19", "1025", "1027"]),
    ("7382312", "Corporate DNS - acme.example", "dns-server", "acme.example", ["4", "1024", "1025", "1026", "1028"]),
    ("7315183", "Public DNS - Google", "dns-server", "8.8.8.8", ["3", "7", "1027"]),
    ("7592435", "Datacenter Frankfurt", "agent-to-server", "10.10.0.1", ["1024", "1025", "1026", "1027", "1028"]),
    ("7026375", "AWS eu-central-1", "agent-to-server", "ec2.eu-central-1.amazonaws.com", ["3", "4", "1024", "1025"]),
    ("7097035", "Azure West Europe", "agent-to-server", "westeurope.cloudapp.azure.com", ["7", "11", "1026"]),
    ("7856720", "Zscaler Gateway", "agent-to-server", "gateway.zscaler.net", ["1024", "1025", "1026", "1027", "1028"]),
    ("7662500", "Branch VPN Hub", "agent-to-server", "vpn-hub.acme.example", ["3", "1024", "1026"]),
]


def _mac(rng: random.Random, ouis: tuple) -> str:
    oui = rng.choice(ouis)
    return oui + ":" + ":".join(f"{rng.randrange(256):02x}" for _ in range(3))


def _meraki_serial(rng: random.Random) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    block = lambda: "".join(rng.choice(alphabet) for _ in range(4))  # noqa: E731
    return f"Q2{rng.choice('KDHPQE')}{rng.choice('ABCDEFGH')}-{block()}-{block()}"


def _cisco_serial(rng: random.Random) -> str:
    prefix = rng.choice(["FOC", "FDO", "FCW", "FXS", "FJC"])
    return prefix + "".join(rng.choice("0123456789ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(8))


def _near(rng: random.Random, lat: float, lon: float) -> tuple:
    return round(lat + rng.uniform(-0.002, 0.002), 6), round(lon + rng.uniform(-0.002, 0.002), 6)


def build_inventory(seed: int) -> Inventory:
    rng = random.Random(seed)
    inv = Inventory()
    used_macs: set = set()

    def unique_mac(ouis):
        while True:
            mac = _mac(rng, ouis)
            if mac not in used_macs:
                used_macs.add(mac)
                return mac

    _build_meraki(inv, rng, unique_mac)
    _build_catalyst(inv, rng, unique_mac)
    _build_thousandeyes(inv, rng)

    # Own RNG stream so the Meraki/Catalyst/ThousandEyes IDs stay identical to
    # inventories generated before SNMP existed.
    snmp_rng = random.Random(f"{seed}:snmp")

    def unique_snmp_mac(ouis):
        while True:
            mac = _mac(snmp_rng, ouis)
            if mac not in used_macs:
                used_macs.add(mac)
                return mac

    _build_snmp(inv, snmp_rng, unique_snmp_mac)

    vie_rng = random.Random(f"{seed}:vienna")

    def unique_vie_mac(ouis):
        while True:
            mac = _mac(vie_rng, ouis)
            if mac not in used_macs:
                used_macs.add(mac)
                return mac

    _build_catalyst(inv, vie_rng, unique_vie_mac, [VIENNA_CATALYST_SITE], VIENNA_SITE_IDX)
    return inv


def _build_meraki(inv: Inventory, rng: random.Random, unique_mac) -> None:
    for site_idx, (name, code, city, state, (country, tz, offset, region), lat, lon, kind) in enumerate(MERAKI_SITES):
        counts = MERAKI_COUNTS[kind]
        network_id = "L_" + "".join(str(rng.randrange(10)) for _ in range(18))
        site = Site(
            key=f"meraki:site:{code}",
            source="meraki",
            internal_id=network_id,
            name=name,
            code=code,
            city=city,
            country=country,
            time_zone=tz,
            utc_offset=offset,
            lat=lat,
            lon=lon,
            url=f"https://n{rng.randrange(100, 400)}.meraki.com/{code}-{name.split()[-1]}/n/{network_id[-6:]}/manage/usage/list",
            tags=[region, kind, f"{country}-{state}".lower()],
        )
        inv.sites.append(site)

        per_type: dict = {}
        for product_type, count in zip(
            ("appliance", "switch", "wireless", "camera", "sensor", "cellularGateway"), counts
        ):
            models, firmware = MERAKI_MODELS[product_type]
            for i in range(count):
                serial = _meraki_serial(rng)
                dlat, dlon = _near(rng, lat, lon)
                if product_type == "switch" and i == 0:
                    model = "MS250-24P" if kind == "factory" else models[-1]
                else:
                    model = rng.choice(models)
                host_octet = {"appliance": 1, "switch": 10, "wireless": 50, "camera": 120,
                              "sensor": 150, "cellularGateway": 2}[product_type] + i
                device = Device(
                    key=f"meraki:{serial}",
                    source="meraki",
                    site=site,
                    name=f"{code}-{MERAKI_NAME_PREFIX[product_type]}{i + 1:02d}",
                    serial=serial,
                    mac=unique_mac(MERAKI_OUIS),
                    model=model,
                    product_type=product_type,
                    role=product_type,
                    firmware=firmware,
                    ip=f"10.{20 + site_idx}.0.{host_octet}",
                    lat=dlat,
                    lon=dlon,
                    url=f"https://n{rng.randrange(100, 400)}.meraki.com/{code}/n/{network_id[-6:]}/manage/nodes/new_list/{rng.randrange(10**11, 10**12)}",
                )
                if product_type == "switch":
                    device.ports = [
                        Port(port_id=str(p), name=f"Port {p}", kind="access", poe=model.endswith("P"),
                             speed_mbps=1000, vlan=100)
                        for p in range(1, 25)
                    ]
                elif product_type == "appliance":
                    device.uplinks = ["wan1", "wan2"]
                elif product_type == "cellularGateway":
                    device.uplinks = ["cellular"]
                per_type.setdefault(product_type, []).append(device)
                inv.devices.append(device)

        switches = per_type.get("switch", [])
        core = switches[0]
        access = switches[1:] or [core]
        mx = per_type["appliance"][0]

        # MX LAN port 3 -> core uplink port 24
        _meraki_link(inv, rng, mx, "3", core, "24", uplink_on_b=True)
        # core ports 23, 22, ... -> access switch uplink port 24
        for i, sw in enumerate(switches[1:], start=1):
            core_port = str(24 - i)
            _meraki_link(inv, rng, sw, "24", core, core_port, uplink_on_a=True)

        # APs and cameras hang off access switch ports 1..n
        next_port = {sw.key: 1 for sw in access}
        endpoints = per_type.get("wireless", []) + per_type.get("camera", [])
        for j, dev in enumerate(endpoints):
            sw = access[j % len(access)]
            port_id = str(next_port[sw.key])
            next_port[sw.key] += 1
            _meraki_link(inv, rng, sw, port_id, dev, "wired0")

        # random end-user ports, plus a couple of LLDP neighbours (phones/printers)
        for sw in switches:
            for port in sw.ports:
                if not port.connected and port.kind == "access" and rng.random() < 0.45:
                    port.connected = True
                    port.load = rng.uniform(0.05, 0.6)
        for n in range(rng.randint(1, 2)):
            sw = rng.choice(access)
            free = [p for p in sw.ports if p.kind == "access" and not p.peer and int(p.port_id) < 19]
            port = rng.choice(free)
            taken = {nb.reporter_port for nb in inv.neighbors if nb.reporter is sw}
            if port.port_id in taken:
                # The topology view drops traffic labels on ports with several neighbours.
                port = next(p for p in free if p.port_id not in taken)
            port.connected = True
            port.load = 0.05
            is_phone = n == 0
            nmac = unique_mac(("00:1b:54", "3c:52:82", "64:16:7f"))
            inv.neighbors.append(Neighbor(
                derived_id=str(rng.randrange(10**15, 10**16)),
                reporter=sw,
                reporter_port=port.port_id,
                mac=nmac,
                system_name=f"SEP{nmac.replace(':', '').upper()}" if is_phone else f"{site.code.lower()}-printer-{n:02d}",
                description="Cisco IP Phone 8851, V3, sip88xx.14-2-1" if is_phone else "HP LaserJet Enterprise M507",
                platform="CP-8851" if is_phone else "HP M507",
                capabilities=["Telephone", "Bridge"] if is_phone else ["Station"],
                port_id="Port 1" if is_phone else "eth0",
                address=f"10.{20 + site_idx}.{40 + n}.{rng.randrange(10, 250)}",
            ))
        # ISP CPE seen on the MX WAN port
        cpe_mac = unique_mac(("00:0c:42", "d4:ca:6d", "48:8f:5a"))
        inv.neighbors.append(Neighbor(
            derived_id=str(rng.randrange(10**15, 10**16)),
            reporter=mx,
            reporter_port="wan1",
            mac=cpe_mac,
            system_name=f"{site.code.lower()}-isp-cpe01",
            description="ISP managed CPE, RouterOS 7.12",
            platform="CCR2004",
            capabilities=["Router"],
            port_id="ether1",
            address=f"100.64.{site_idx}.1",
        ))


def _meraki_link(inv, rng, a: Device, a_port: str, b: Device, b_port: str,
                 uplink_on_a: bool = False, uplink_on_b: bool = False) -> None:
    for dev, port_id, is_uplink, peer in ((a, a_port, uplink_on_a, b), (b, b_port, uplink_on_b, a)):
        port = dev.port(port_id)
        if port is None:
            continue
        port.connected = True
        port.peer = peer.key
        if is_uplink:
            port.kind = "uplink"
            port.load = 0.8
        elif peer.product_type in ("switch", "appliance"):
            port.kind = "trunk"
            port.load = 0.7
        else:
            port.load = 0.35 if peer.product_type == "wireless" else 0.25
    inv.links.append(Link(link_id=str(rng.randrange(10**17, 10**18)), a=a, a_port=a_port, b=b, b_port=b_port))


def _build_catalyst(inv: Inventory, rng: random.Random, unique_mac, sites=CATALYST_SITES, first_idx=0) -> None:
    for site_idx, (name, code, city, country, tz, offset, lat, lon, hierarchy, counts) in enumerate(sites, first_idx):
        site = Site(
            key=f"catalyst:site:{code}",
            source="catalyst_center",
            internal_id=rng_uuid(rng),
            name=name,
            code=code,
            city=city,
            country=country,
            time_zone=tz,
            utc_offset=offset,
            lat=lat,
            lon=lon,
            hierarchy=hierarchy,
        )
        inv.sites.append(site)
        n_routers, n_core, n_access, n_wlc, n_aps = counts
        net = 100 + site_idx

        def make(role, family, model, firmware, index, octet):
            dlat, dlon = _near(rng, lat, lon)
            suffix = {"BORDER ROUTER": "RTR", "CORE": "CORE", "ACCESS": "ACC",
                      "WLC": "WLC", "AP": "AP"}[role]
            serial = _cisco_serial(rng)
            device = Device(
                key=f"catalyst:{serial}",
                source="catalyst_center",
                site=site,
                name=f"{code.lower()}-{suffix.lower()}-{index:02d}.acme.example",
                serial=serial,
                mac=unique_mac(CISCO_OUIS),
                model=model,
                product_type=family,
                role=role,
                firmware=firmware,
                ip=f"10.{net}.{1 if role != 'AP' else 20}.{octet}",
                lat=dlat,
                lon=dlon,
                device_id=rng_uuid(rng),
            )
            inv.devices.append(device)
            return device

        def iface(dev, name, ifindex, kind, **kw):
            port = Port(port_id=name, name=name, ifindex=ifindex, kind=kind,
                        interface_id=rng_uuid(rng), **kw)
            dev.ports.append(port)
            return port

        routers = [make("BORDER ROUTER", "Routers", "C8300-1N1S-6T", "17.12.3", i + 1, 1 + i) for i in range(n_routers)]
        cores = [make("CORE", "Switches and Hubs", "C9500-24Y4C", "17.9.4a", i + 1, 5 + i) for i in range(n_core)]
        accesses = [make("ACCESS", "Switches and Hubs", rng.choice(["C9300-24P", "C9300-24UX"]), "17.9.4a", i + 1, 20 + i)
                    for i in range(n_access)]
        wlcs = [make("WLC", "Wireless Controller", "C9800-40-K9", "17.9.5", i + 1, 10 + i) for i in range(n_wlc)]
        aps = [make("AP", "Unified AP", rng.choice(["C9130AXI-E", "C9120AXI-E", "C9136I-ROW"]), "17.9.5.47", i + 1, 30 + i)
               for i in range(n_aps)]

        for r in routers:
            iface(r, "GigabitEthernet0/0/0", 1, "wan", is_wan=True, connected=True, load=0.7)
            iface(r, "GigabitEthernet0/0/1", 2, "uplink", connected=True, load=0.6)
            iface(r, "GigabitEthernet0/0/2", 3, "uplink", connected=True, load=0.6)
            iface(r, "GigabitEthernet0/0/3", 4, "access", admin_up=False)
            iface(r, "Loopback0", 20, "loopback", connected=True, speed_mbps=8000)
        for c in cores:
            for p in range(1, 11):
                iface(c, f"TenGigabitEthernet1/0/{p}", p, "trunk", speed_mbps=10000)
            iface(c, "Vlan100", 50, "svi", connected=True)
            iface(c, "Loopback0", 60, "loopback", connected=True, speed_mbps=8000)
        for a in accesses:
            for p in range(1, 25):
                iface(a, f"GigabitEthernet1/0/{p}", p, "access", poe=True)
            iface(a, "TenGigabitEthernet1/1/1", 30, "uplink", speed_mbps=10000)
            iface(a, "Vlan100", 50, "svi", connected=True)
        for w in wlcs:
            for p in range(0, 4):
                iface(w, f"TenGigabitEthernet0/0/{p}", 1 + p, "trunk", speed_mbps=10000)
        for ap in aps:
            iface(ap, "GigabitEthernet0", 1, "ap", connected=True, speed_mbps=2500)

        def link(a, a_port, b, b_port, load=0.5):
            for dev, port_id, peer in ((a, a_port, b), (b, b_port, a)):
                port = dev.port(port_id)
                port.connected = True
                port.peer = peer.key
                port.load = max(port.load, load)
            inv.links.append(Link(link_id=rng_uuid(rng), a=a, a_port=a_port, b=b, b_port=b_port))

        r = routers[0]
        link(r, "GigabitEthernet0/0/1", cores[0], "TenGigabitEthernet1/0/1", 0.6)
        link(r, "GigabitEthernet0/0/2", cores[1 % len(cores)], "TenGigabitEthernet1/0/1", 0.6)
        if len(cores) > 1:
            link(cores[0], "TenGigabitEthernet1/0/2", cores[1], "TenGigabitEthernet1/0/2", 0.4)
        for i, a in enumerate(accesses):
            core = cores[i % len(cores)]
            link(a, "TenGigabitEthernet1/1/1", core, f"TenGigabitEthernet1/0/{3 + i // len(cores)}", 0.7)
        for i, w in enumerate(wlcs):
            link(w, "TenGigabitEthernet0/0/0", cores[0], f"TenGigabitEthernet1/0/{9 + i}", 0.5)
        for j, ap in enumerate(aps):
            a = accesses[j % len(accesses)]
            link(ap, "GigabitEthernet0", a, f"GigabitEthernet1/0/{1 + j // len(accesses)}", 0.35)
        for a in accesses:
            for port in a.ports:
                if port.kind == "access" and not port.connected and rng.random() < 0.5:
                    port.connected = True
                    port.load = rng.uniform(0.05, 0.5)


# ── SC4SNMP ───────────────────────────────────────────────────────────────
SNMP_SITE = ("Frankfurt DC1", "FRA1", "Frankfurt", "DE", "Europe/Berlin", 2, 50.1196, 8.7359)

# role: (count, model key)
SNMP_LAYOUT = (("edge", 2, "mx204"), ("spine", 2, "arista"), ("leaf", 6, "nexus"),
               ("storage", 2, "huawei"), ("oob", 2, "hp"))

# model key: manufacturer, model, product type, firmware, sysObjectID, sysDescr, OUIs
SNMP_MODELS = {
    "mx204": ("Juniper Networks", "MX204", "router", "23.4R2-S3.9", "1.3.6.1.4.1.2636.1.1.1.2.155",
              "Juniper Networks, Inc. mx204 internet router, kernel JUNOS 23.4R2-S3.9, Build date: "
              "2025-03-14 10:12:44 UTC Copyright (c) 1996-2025 Juniper Networks, Inc.",
              ("3c:61:04", "f4:a7:39")),
    "arista": ("Arista Networks", "DCS-7280CR3-32P4", "switch", "4.32.2F", "1.3.6.1.4.1.30065.1.3011.7280.3227.32.4",
               "Arista Networks EOS version 4.32.2F running on an Arista Networks DCS-7280CR3-32P4",
               ("44:4c:a8", "28:99:3a")),
    "nexus": ("Cisco Systems, Inc.", "N9K-C93180YC-FX3", "switch", "10.4(3)", "1.3.6.1.4.1.9.12.3.1.3.2183",
              "Cisco NX-OS(tm) Nexus9000 C93180YC-FX3, Software (NXOS 64-bit), Version 10.4(3), "
              "RELEASE SOFTWARE Copyright (c) 2002-2024 by Cisco Systems, Inc.",
              CISCO_OUIS),
    "huawei": ("Huawei Technologies Co., Ltd.", "CE6881-48S6CQ", "switch", "V300R022C00SPC100",
               "1.3.6.1.4.1.2011.2.239.53",
               "Huawei Versatile Routing Platform Software\r\nVRP (R) software, Version 8.220 "
               "(CE6881 V300R022C00SPC100)\r\nCopyright (C) 2012-2024 Huawei Technologies Co., Ltd.\r\n"
               "HUAWEI CE6881-48S6CQ\r\n",
               ("70:7b:e8", "f4:de:af")),
    "hp": ("Hewlett Packard", "J9729A", "switch", "WB.16.10.0025", "1.3.6.1.4.1.11.2.3.7.11.153",
           "HP J9729A 2920-48G-POE+ Switch, revision WB.16.10.0025, ROM WB.16.03",
           ("94:57:a5", "9c:8e:99")),
}


def _snmp_ports(model_key: str) -> list:
    """Interface tables with each vendor's ifName and ifIndex conventions."""
    def p(name, ifindex, kind="trunk", speed=10000):
        return Port(port_id=name, name=name, ifindex=ifindex, kind=kind, speed_mbps=speed,
                    if_type="softwareLoopback" if kind == "loopback" else "ethernetCsmacd")

    if model_key == "mx204":
        ports = [p("fxp0", 1, "mgmt", 1000), p("lo0", 6, "loopback")]
        ports += [p(f"et-0/0/{i}", 650 + i, speed=100000) for i in range(4)]
        ports += [p(f"xe-0/1/{i}", 660 + i) for i in range(8)]
    elif model_key == "arista":
        ports = [p(f"Ethernet{i}", i, speed=100000) for i in range(1, 33)]
        ports += [p("Management1", 999001, "mgmt", 1000), p("Loopback0", 5000, "loopback")]
    elif model_key == "nexus":
        numbers = list(range(1, 25)) + list(range(49, 55))
        ports = [p(f"Ethernet1/{n}", 436207616 + (n - 1) * 4096, "access" if n < 49 else "trunk",
                   25000 if n < 49 else 100000) for n in numbers]
        ports += [p("mgmt0", 83886080, "mgmt", 1000), p("loopback0", 151060480, "loopback")]
    elif model_key == "huawei":
        ports = [p("MEth0/0/0", 5, "mgmt", 1000), p("LoopBack0", 6, "loopback")]
        ports += [p(f"10GE1/0/{i}", 8 + i, "access") for i in range(1, 25)]
        ports += [p(f"100GE1/0/{i}", 40 + i, speed=100000) for i in range(1, 7)]
    else:
        ports = [p(str(i), i, "access", 1000) for i in range(1, 25)]
    return ports


def _snmp_serial(rng: random.Random, model_key: str) -> str:
    chars = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
    pick = lambda n: "".join(rng.choice(chars) for _ in range(n))  # noqa: E731
    return {
        "mx204": lambda: "BV" + "".join(rng.choice("0123456789") for _ in range(10)),
        "arista": lambda: "JPE" + pick(8),
        "nexus": lambda: _cisco_serial(rng),
        "huawei": lambda: "2102351" + pick(13),
        "hp": lambda: "SG" + pick(8),
    }[model_key]()


def _build_snmp(inv: Inventory, rng: random.Random, unique_mac) -> None:
    name, code, city, country, tz, offset, lat, lon = SNMP_SITE
    site = Site(key=f"snmp:site:{code}", source="snmp", internal_id=code, name=name, code=code,
                city=city, country=country, time_zone=tz, utc_offset=offset, lat=lat, lon=lon)
    inv.sites.append(site)

    by_role: dict = {}
    octet = 1
    for role, count, model_key in SNMP_LAYOUT:
        mfg, model, product_type, firmware, sys_oid, descr, ouis = SNMP_MODELS[model_key]
        for i in range(count):
            dlat, dlon = _near(rng, lat, lon)
            device = Device(
                key=f"snmp:{code}:{role}:{i + 1}",
                source="snmp",
                site=site,
                name=f"{code.lower()}-{role}-{i + 1:02d}",
                serial=_snmp_serial(rng, model_key),
                mac=unique_mac(ouis),
                model=model,
                product_type=product_type,
                role=role,
                firmware=firmware,
                ip=f"10.250.0.{octet}",
                lat=dlat,
                lon=dlon,
                ports=_snmp_ports(model_key),
                vendor=mfg,
                sys_object_id=sys_oid,
                sys_descr=descr,
            )
            octet += 1
            by_role.setdefault(role, []).append(device)
            inv.devices.append(device)

    edges, spines, leaves = by_role["edge"], by_role["spine"], by_role["leaf"]
    storage, oob = by_role["storage"], by_role["oob"]

    for e_idx, edge in enumerate(edges):
        for s_idx, spine in enumerate(spines):
            _snmp_link(inv, rng, edge, f"et-0/0/{s_idx}", spine, f"Ethernet{1 + e_idx}", 0.6)
    for l_idx, leaf in enumerate(leaves + storage):
        for s_idx, spine in enumerate(spines):
            leaf_port = f"Ethernet1/{49 + s_idx}" if leaf.role == "leaf" else f"100GE1/0/{1 + s_idx}"
            _snmp_link(inv, rng, leaf, leaf_port, spine, f"Ethernet{3 + l_idx}", 0.5)
    for k in range(0, len(leaves), 2):
        for port in ("Ethernet1/53", "Ethernet1/54"):
            _snmp_link(inv, rng, leaves[k], port, leaves[k + 1], port, 0.3)
    for port in ("100GE1/0/5", "100GE1/0/6"):
        _snmp_link(inv, rng, storage[0], port, storage[1], port, 0.3)

    for idx, dev in enumerate(edges + spines + leaves + storage):
        port = next(p.port_id for p in dev.ports if p.kind == "mgmt")
        switch = oob[idx % len(oob)]
        _snmp_link(inv, rng, switch, str(1 + idx // len(oob)), dev, port, 0.05)
    _snmp_link(inv, rng, oob[0], "24", oob[1], "24", 0.05)

    for dev in by_role["leaf"] + storage:
        for port in dev.ports:
            if port.kind == "access" and rng.random() < 0.6:
                port.connected = True

    # DCI uplinks towards the Catalyst-managed campus routers; only the DC side speaks SNMP.
    campus_routers = [d for d in inv.devices if d.source == "catalyst_center" and d.role == "BORDER ROUTER"]
    for edge, router in zip(edges, campus_routers[:2]):
        _snmp_link(inv, rng, edge, "xe-0/1/0", router, "Gi0/0/0", 0.4)


def _snmp_link(inv, rng, a: Device, a_port: str, b: Device, b_port: str, load: float) -> None:
    for dev, port_id, peer, peer_port in ((a, a_port, b, b_port), (b, b_port, a, a_port)):
        port = dev.port(port_id) if dev.source == "snmp" else None
        if port is None:
            continue
        port.connected = True
        port.peer = peer.key
        port.peer_port = peer_port
        port.load = load
    inv.links.append(Link(link_id=rng_uuid(rng), a=a, a_port=a_port, b=b, b_port=b_port))


def _build_thousandeyes(inv: Inventory, rng: random.Random) -> None:
    agents = {}
    for agent_id, name, location, country, region, geoname, kind in TE_AGENTS:
        agent = TEAgent(agent_id, name, location, country, region, geoname, kind)
        agents[agent_id] = agent
        inv.te_agents.append(agent)
    for test_id, name, test_type, target, agent_ids in TE_TESTS:
        inv.te_tests.append(TETest(
            test_id=test_id,
            name=name,
            test_type=test_type,
            target=target,
            agents=[agents[a] for a in agent_ids],
        ))
