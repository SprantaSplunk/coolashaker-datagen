"""Raw vendor events in the shapes the Network Intelligence app parses.

Field names follow network_intelligence/default/props.conf, graph_adapters.conf
and capability_bindings.conf. Payloads are kept below ~9.5 KB so Splunk's
default TRUNCATE (10000 bytes) and auto-KV limits never cut a JSON event.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .health import CATALYST_NOISE, MERAKI_NOISE, AlertWindow, HealthModel
from .inventory import (MERAKI_ORG_ID, TE_ACCOUNT_ID, VIENNA_SHARED_LOCATION, VIENNA_SITE_KEY,
                        Device, Inventory)
from .util import iso_z, stable_hex, stable_rng

MAX_EVENT_BYTES = 9500
SNMP_POLL_SECONDS = 900
CATALYST_HOST = "catalyst-center.acme.example"
MERAKI_HOST = "api.meraki.com"
TE_HOST = "api.thousandeyes.com"


@dataclass
class Event:
    index: str
    sourcetype: str
    source: str
    host: str
    time: float
    data: dict

    def hec(self) -> dict:
        return {
            "time": round(self.time, 3),
            "index": self.index,
            "sourcetype": self.sourcetype,
            "source": self.source,
            "host": self.host,
            "event": self.data,
        }


def _size(data: dict) -> int:
    return len(json.dumps(data, separators=(",", ":")))


def _chunked(base: dict, list_key: str, items: list) -> list:
    """Split ``items`` across copies of ``base`` so each payload stays under MAX_EVENT_BYTES."""
    chunks, current = [], []
    for item in items:
        candidate = dict(base, **{list_key: current + [item]})
        if current and _size(candidate) > MAX_EVENT_BYTES:
            chunks.append(dict(base, **{list_key: current}))
            current = [item]
        else:
            current.append(item)
    if current or not chunks:
        chunks.append(dict(base, **{list_key: current}))
    return chunks


class EventFactory:
    def __init__(self, inv: Inventory, health: HealthModel, indexes: dict):
        self.inv = inv
        self.health = health
        self.idx = indexes
        self._snmp_slot = None

    # ── snapshots ────────────────────────────────────────────────────────
    def snapshot(self, t: float) -> list:
        events = []
        events += self.meraki_snapshot(t)
        events += self.catalyst_snapshot(t)
        events += self.thousandeyes_snapshot(t)
        slot = int(t // SNMP_POLL_SECONDS)
        if slot != self._snmp_slot:
            self._snmp_slot = slot
            events += self.snmp_snapshot(t)
        return events

    def _mk(self, sourcetype: str, t: float, data: dict) -> Event:
        return Event(self.idx["meraki"], sourcetype, f"meraki://{MERAKI_ORG_ID}/{sourcetype.split(':', 1)[1]}",
                     MERAKI_HOST, t, data)

    def _cc(self, sourcetype: str, t: float, data: dict) -> Event:
        return Event(self.idx["catalyst"], sourcetype, f"cisco_catalyst://{sourcetype.split(':', 2)[-1]}",
                     CATALYST_HOST, t, data)

    def meraki_snapshot(self, t: float) -> list:
        h = self.health
        out = []
        ctime = iso_z(t, micro=True)
        for site in self.inv.sites_by_source("meraki"):
            out.append(self._mk("meraki:organizationsnetworks", t, {
                "id": site.internal_id,
                "organizationId": MERAKI_ORG_ID,
                "name": site.name,
                "productTypes": ["appliance", "camera", "sensor", "switch", "wireless"],
                "timeZone": site.time_zone,
                "tags": site.tags,
                "enrollmentString": None,
                "url": site.url,
                "notes": f"{site.city}, {site.country}",
                "isBoundToConfigTemplate": False,
            }))
        for dev in self.inv.by_source("meraki"):
            out.append(self._mk("meraki:devices", t, {
                "name": dev.name,
                "serial": dev.serial,
                "mac": dev.mac,
                "model": dev.model,
                "networkId": dev.site.internal_id,
                "organizationId": MERAKI_ORG_ID,
                "productType": dev.product_type,
                "firmware": dev.firmware,
                "lanIp": dev.ip,
                "lat": dev.lat,
                "lng": dev.lon,
                "address": f"{dev.site.city}, {dev.site.country}",
                "tags": [dev.site.code.lower()],
                "url": dev.url,
                "notes": "",
            }))
            out.append(self._mk("meraki:devicesavailabilities", t, {
                "serial": dev.serial,
                "name": dev.name,
                "mac": dev.mac,
                "productType": dev.product_type,
                "status": h.meraki_status(dev, t),
                "network": {"id": dev.site.internal_id, "name": dev.site.name},
                "tags": [dev.site.code.lower()],
            }))
            if dev.product_type == "switch":
                out += self._meraki_switch_events(dev, t, ctime)
            if dev.uplinks:
                out += self._meraki_uplink_events(dev, t)
        for link in self.inv.links:
            if link.a.source != "meraki":
                continue
            out.append(self._mk("meraki:custom", t, {
                "endpoint_name": "devices_topology_l2_links",
                "organizationId": MERAKI_ORG_ID,
                "collection_time": ctime,
                "linkId": link.link_id,
                "source": {"device": {"id": link.a.serial, "name": link.a.name, "port": {"id": link.a_port}}},
                "target": {"device": {"id": link.b.serial, "name": link.b.name, "port": {"id": link.b_port}}},
            }))
        for nb in self.inv.neighbors:
            out.append(self._mk("meraki:custom", t, {
                "endpoint_name": "devices_topology_nodes_discovered",
                "organizationId": MERAKI_ORG_ID,
                "collection_time": ctime,
                "protocol": nb.protocol,
                "reporter": {"id": nb.reporter.serial, "interface": {"id": nb.reporter_port, "status": "active"}},
                "discovered": {
                    "derivedId": nb.derived_id,
                    "mac": nb.mac,
                    "system": {"name": nb.system_name, "description": nb.description,
                               "platform": nb.platform, "capabilities": nb.capabilities},
                    "chassis": {"id": nb.mac},
                    "port": {"id": nb.port_id},
                    "addresses": [nb.address],
                },
            }))
        return out

    def _meraki_switch_events(self, dev: Device, t: float, ctime: str) -> list:
        h = self.health
        out = []
        config_ports, status_ports, usage_ports = [], [], []
        start_ts, end_ts = iso_z(t - 300, micro=True), ctime
        for port in dev.ports:
            config_ports.append({
                "portId": port.port_id,
                "name": "Uplink" if port.kind == "uplink" else port.name,
                "enabled": True,
                "type": "trunk" if port.kind in ("uplink", "trunk") else "access",
                "vlan": 1 if port.kind in ("uplink", "trunk") else port.vlan,
                "voiceVlan": None if port.kind in ("uplink", "trunk") else 200,
                "allowedVlans": "all" if port.kind in ("uplink", "trunk") else "1-1000",
                "poeEnabled": port.poe,
                "linkNegotiation": "Auto negotiate",
                "rstpEnabled": True,
                "stpGuard": "disabled" if port.kind in ("uplink", "trunk") else "bpdu guard",
                "accessPolicyType": "Open",
            })
            st = h.meraki_port(dev, port, t)
            status_ports.append({
                "portId": port.port_id,
                "enabled": st["enabled"],
                "status": st["status"],
                "isUplink": st["is_uplink"],
                "errors": st["errors"],
                "warnings": st["warnings"],
                "speed": st["speed"],
                "duplex": st["duplex"],
                "spanningTree": {"statuses": ["Forwarding"] if st["status"] == "Connected" else []},
                "poe": {"isAllocated": st["poe_allocated"]},
            })
            interval = {
                "startTs": start_ts,
                "endTs": end_ts,
                "data": {"usage": {"total": round((st["in_kbps"] + st["out_kbps"]) * 300 / 8, 1),
                                   "upstream": round(st["out_kbps"] * 300 / 8, 1),
                                   "downstream": round(st["in_kbps"] * 300 / 8, 1)}},
                "bandwidth": {"usage": {"total": round(st["in_kbps"] + st["out_kbps"], 1),
                                        "upstream": st["out_kbps"],
                                        "downstream": st["in_kbps"]}},
            }
            if port.poe:
                interval["energy"] = {"usage": {"total": st["energy_wh"]}}
            usage_ports.append({"portId": port.port_id, "intervals": [interval]})

        common = {"serial": dev.serial, "mac": dev.mac, "name": dev.name, "networkId": dev.site.internal_id,
                  "network": {"id": dev.site.internal_id, "name": dev.site.name}}
        for payload in _chunked(dict(common), "ports", config_ports):
            out.append(self._mk("meraki:switchportsbyswitch", t, payload))
        base = {"endpoint_name": "switch_ports_statuses_by_switch", "organizationId": MERAKI_ORG_ID,
                "collection_time": ctime, "serial": dev.serial, "name": dev.name, "model": dev.model,
                "network": {"id": dev.site.internal_id, "name": dev.site.name}}
        for payload in _chunked(base, "ports", status_ports):
            out.append(self._mk("meraki:custom", t, payload))
        base = {"endpoint_name": "switch_ports_usage_history_by_device_by_interval",
                "organizationId": MERAKI_ORG_ID, "collection_time": ctime, "serial": dev.serial,
                "name": dev.name, "network": {"id": dev.site.internal_id, "name": dev.site.name}}
        # The usage binding keeps only the latest event per serial (dedup serial),
        # so this payload must never be split.
        out.append(self._mk("meraki:custom", t, dict(base, ports=usage_ports)))
        return out

    def _meraki_uplink_events(self, dev: Device, t: float) -> list:
        site_idx = int(dev.ip.split(".")[1]) - 20
        uplinks = []
        for i, name in enumerate(dev.uplinks):
            public = f"198.51.{100 + site_idx}.{10 + i}" if name != "cellular" else f"100.72.{site_idx}.{20 + i}"
            uplinks.append({
                "interface": name,
                "addresses": [{
                    "protocol": "ipv4",
                    "assignmentMode": "dynamic" if name != "wan1" else "static",
                    "address": public,
                    "gateway": public.rsplit(".", 1)[0] + ".1",
                    "public": {"address": public},
                }],
            })
        out = [self._mk("meraki:devicesuplinksaddressesbydevice", t, {
            "serial": dev.serial,
            "mac": dev.mac,
            "name": dev.name,
            "model": dev.model,
            "networkId": dev.site.internal_id,
            "network": {"id": dev.site.internal_id, "name": dev.site.name},
            "uplinks": uplinks,
        })]
        for name in dev.uplinks:
            series = []
            for minute in range(4, -1, -1):
                ts = int(t // 60) * 60 - minute * 60
                loss, latency = self.health.meraki_uplink(dev, name, ts)
                series.append({"ts": iso_z(ts), "lossPercent": loss, "latencyMs": latency})
            out.append(self._mk("meraki:devicesuplinkslossandlatency", t, {
                "networkId": dev.site.internal_id,
                "serial": dev.serial,
                "uplink": name,
                "ip": "8.8.8.8",
                "timeSeries": series,
            }))
        return out

    def catalyst_snapshot(self, t: float) -> list:
        h = self.health
        out = []
        ms = int(t * 1000)
        for site in self.inv.sites_by_source("catalyst_center"):
            out.append(self._cc("cisco:dnac:site:topology", t, {
                "id": site.internal_id,
                "name": site.name,
                "nameHierarchy": site.hierarchy,
                "type": "building",
                "latitude": str(site.lat),
                "longitude": str(site.lon),
                "address": f"{site.city}, {site.country}",
                "parentId": stable_hex("cc-parent", site.hierarchy.rsplit("/", 1)[0], length=32),
            }))
        for dev in self.inv.by_source("catalyst_center"):
            st = h.catalyst_device(dev, t)
            out.append(self._cc("cisco:dnac:devicehealth", t, {
                "DeviceID": dev.device_id,
                "DeviceName": dev.name,
                "DeviceFamily": dev.product_type,
                "DeviceType": dev.model,
                "DeviceRole": dev.role,
                "Platform": dev.model,
                "SerialNumber": dev.serial,
                "MACAddress": dev.mac,
                "IpAddress": dev.ip,
                "ImageVersion": dev.firmware,
                "Site": dev.site.hierarchy,
                "Location": VIENNA_SHARED_LOCATION if dev.site.key == VIENNA_SITE_KEY else dev.site.hierarchy,
                "Reachability": st["reachability"],
                "Manageability": st["manageability"],
                "OverallHealth": st["overall"],
                "HealthScore": st["overall"],
                "CPUHealth": st["cpu_health"] if st["cpu_health"] is not None else -1,
                "CPUUtilization": st["cpu"] if st["cpu"] is not None else -1,
                "MemoryUtilizationHealth": st["mem_health"] if st["mem_health"] is not None else -1,
                "MemoryUtilization": st["mem"] if st["mem"] is not None else -1,
                "ClientCount": 0 if dev.role != "AP" else stable_rng(dev.key, int(t // 300)).randint(3, 45),
                "LastUpdateTime": ms,
            }))
            for port in dev.ports:
                ist = h.catalyst_iface(dev, port, t)
                logical = port.kind in ("loopback", "svi")
                out.append(self._cc("cisco:dnac:devicehealth:interface", t, {
                    "InterfaceID": port.interface_id,
                    "InterfaceIfIndex": str(port.ifindex),
                    "InterfaceName": port.name,
                    "InterfaceType": "Virtual" if logical else "Physical",
                    "DeviceID": dev.device_id,
                    "DeviceName": dev.name,
                    "AdminStatus": ist["admin"],
                    "InterfaceStatus": ist["oper"],
                    "PortMode": "routed" if port.kind in ("wan", "loopback", "svi") or dev.role == "BORDER ROUTER"
                    else ("trunk" if port.kind in ("uplink", "trunk") else "access"),
                    "PortType": "Service Module Interface" if logical else "Ethernet Port",
                    "Speed": str(port.speed_mbps * 1000),
                    "IsWan": "true" if port.is_wan else "false",
                    "IsL3Interface": "true" if logical or dev.role == "BORDER ROUTER" else "false",
                    "HasInterfaceStats": "true",
                    "RxRate": ist["rx_bps"],
                    "TxRate": ist["tx_bps"],
                    "RxUtilization": round(ist["rx_bps"] / (port.speed_mbps * 1e6) * 100, 2),
                    "TxUtilization": round(ist["tx_bps"] / (port.speed_mbps * 1e6) * 100, 2),
                    "RxError": ist["rx_err"],
                    "TxError": ist["tx_err"],
                    "RxDiscards": ist["rx_disc"],
                    "TxDiscards": ist["tx_disc"],
                    "Timestamp": ms,
                }))
        for site in self.inv.sites_by_source("catalyst_center"):
            links = [lk for lk in self.inv.links if lk.a.source == "catalyst_center" and lk.a.site is site]
            items = [{
                "id": lk.link_id,
                "source": lk.a.device_id,
                "target": lk.b.device_id,
                "startPortID": lk.a.port(lk.a_port).interface_id,
                "startPortName": lk.a_port,
                "endPortID": lk.b.port(lk.b_port).interface_id,
                "endPortName": lk.b_port,
                "linkStatus": "up" if h.catalyst_iface(lk.a, lk.a.port(lk.a_port), t)["oper"] == "up" else "down",
            } for lk in links]
            base = {"endpoint_name": "topology_physical_topology", "collection_time": int(t),
                    "siteName": site.hierarchy}
            for payload in _chunked(base, "links", items):
                out.append(self._cc("cisco:dnac:custom", t, payload))
        return out

    def thousandeyes_snapshot(self, t: float) -> list:
        out = []
        units = {"network.loss": "%", "network.latency": "ms", "network.jitter": "ms",
                 "http.server.request.availability": "%", "http.client.request.duration": "s",
                 "dns.lookup.availability": "%", "dns.lookup.duration": "s"}
        for test in self.inv.te_tests:
            permalink = f"https://app.thousandeyes.com/view/tests/?__a={TE_ACCOUNT_ID}&testId={test.test_id}"
            for agent in test.agents:
                common = {
                    "thousandeyes.account.id": TE_ACCOUNT_ID,
                    "thousandeyes.test.id": test.test_id,
                    "thousandeyes.test.name": test.name,
                    "thousandeyes.test.type": test.test_type,
                    "thousandeyes.test.target": test.target,
                    "server.address": test.target,
                    "thousandeyes.source.agent.id": agent.agent_id,
                    "thousandeyes.source.agent.name": agent.name,
                    "thousandeyes.source.agent.location": agent.location,
                    "thousandeyes.source.agent.type": agent.kind,
                    "thousandeyes.source.agent.geo.country.iso_code": agent.country,
                    "thousandeyes.source.agent.geo.region.iso_code": agent.region,
                    "thousandeyes.source.agent.geoname.id": agent.geoname_id,
                    "thousandeyes.permalink": permalink,
                }
                for metric, value in self.health.te_metrics(test, agent, t).items():
                    out.append(Event(self.idx["thousandeyes"], "cisco:thousandeyes:metric",
                                     "thousandeyes:otel:metrics", TE_HOST, t,
                                     dict(common, metric_name=metric, metric_value=value, unit=units[metric],
                                          **{"metric_name:" + metric: value})))
        return out

    # ── alerts ───────────────────────────────────────────────────────────
    def snmp_snapshot(self, t: float) -> list:
        """One SC4SNMP walk per device: system scalars, chassis entity, IF-MIB rows and LLDP tables."""
        out = []
        devices = {d.key: d for d in self.inv.devices}
        for dev in self.inv.by_source("snmp"):
            def ev(varbinds):
                data = {"frequency": str(SNMP_POLL_SECONDS), "profiles": f"ni_{dev.role}"}
                for key, (value, oid, kind) in varbinds.items():
                    data[key] = {"time": round(t, 3), "type": kind, "value": value, "oid": oid}
                return Event(self.idx["snmp"], "sc4snmp:event", "sc4snmp", dev.ip, t, data)

            out.append(ev({
                "SNMPv2-MIB.sysDescr": (dev.sys_descr, "1.3.6.1.2.1.1.1.0", "r"),
                "SNMPv2-MIB.sysObjectID": (dev.sys_object_id, "1.3.6.1.2.1.1.2.0", "r"),
                "SNMPv2-MIB.sysUpTime": (str(int((t % 7_776_000) * 100)), "1.3.6.1.2.1.1.3.0", "g"),
                "SNMPv2-MIB.sysContact": ("noc@acme.example", "1.3.6.1.2.1.1.4.0", "r"),
                "SNMPv2-MIB.sysName": (dev.name, "1.3.6.1.2.1.1.5.0", "r"),
                "SNMPv2-MIB.sysLocation": (f"{dev.site.name}, Hall 2, Row C, Rack {dev.ip.rsplit('.', 1)[1]:0>2}",
                                           "1.3.6.1.2.1.1.6.0", "r"),
                "BRIDGE-MIB.dot1dBaseBridgeAddress": (dev.mac, "1.3.6.1.2.1.17.1.1.0", "r"),
                "LLDP-MIB.lldpLocChassisIdSubtype": ("macAddress", "1.0.8802.1.1.2.1.3.1.0", "r"),
                "LLDP-MIB.lldpLocChassisId": (dev.mac, "1.0.8802.1.1.2.1.3.2.0", "r"),
                "LLDP-MIB.lldpLocSysName": (dev.name, "1.0.8802.1.1.2.1.3.3.0", "r"),
            }))
            entity = "1.3.6.1.2.1.47.1.1.1.1"
            for ent_index, ent_class, descr, serial in ((1, "chassis", f"{dev.model} Chassis", dev.serial),
                                                       (10, "powerSupply", "Power Supply 1",
                                                        stable_hex(dev.serial, "psu", length=10).upper())):
                out.append(ev({
                    "ENTITY-MIB.entPhysicalDescr": (descr, f"{entity}.2.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalClass": (ent_class, f"{entity}.5.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalName": (descr, f"{entity}.7.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalSoftwareRev": (dev.firmware, f"{entity}.10.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalSerialNum": (serial, f"{entity}.11.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalMfgName": (dev.vendor, f"{entity}.12.{ent_index}", "r"),
                    "ENTITY-MIB.entPhysicalModelName": (dev.model, f"{entity}.13.{ent_index}", "r"),
                }))
            for port in dev.ports:
                i = port.ifindex
                up = port.connected or port.kind == "loopback"
                peer = devices.get(port.peer)
                alias = f"to {peer.name} {port.peer_port}" if peer else ("" if port.kind == "loopback" else
                                                                         "server" if port.connected else "")
                out.append(ev({
                    "IF-MIB.ifDescr": (port.name, f"1.3.6.1.2.1.2.2.1.2.{i}", "r"),
                    "IF-MIB.ifType": (port.if_type, f"1.3.6.1.2.1.2.2.1.3.{i}", "r"),
                    "IF-MIB.ifMtu": ("9216" if port.kind == "trunk" else "1500", f"1.3.6.1.2.1.2.2.1.4.{i}", "g"),
                    "IF-MIB.ifPhysAddress": ("" if port.kind == "loopback" else dev.mac,
                                             f"1.3.6.1.2.1.2.2.1.6.{i}", "r"),
                    "IF-MIB.ifAdminStatus": ("up" if up or port.kind != "access" else "down",
                                             f"1.3.6.1.2.1.2.2.1.7.{i}", "r"),
                    "IF-MIB.ifOperStatus": ("up" if up else "down", f"1.3.6.1.2.1.2.2.1.8.{i}", "r"),
                    "IF-MIB.ifName": (port.name, f"1.3.6.1.2.1.31.1.1.1.1.{i}", "r"),
                    "IF-MIB.ifHighSpeed": (str(port.speed_mbps if up else 0), f"1.3.6.1.2.1.31.1.1.1.15.{i}", "g"),
                    "IF-MIB.ifAlias": (alias, f"1.3.6.1.2.1.31.1.1.1.18.{i}", "r"),
                }))
                if not port.peer:
                    continue
                loc = "1.0.8802.1.1.2.1.3.7.1"
                out.append(ev({
                    "LLDP-MIB.lldpLocPortIdSubtype": ("interfaceName", f"{loc}.2.{i}", "r"),
                    "LLDP-MIB.lldpLocPortId": (port.name, f"{loc}.3.{i}", "r"),
                    "LLDP-MIB.lldpLocPortDesc": (alias, f"{loc}.4.{i}", "r"),
                }))
                rem = "1.0.8802.1.1.2.1.4.1.1"
                suffix = f"0.{i}.1"
                # IOS-XE advertises its port ID as an abbreviated, locally assigned name.
                port_subtype = "interfaceName" if peer.source == "snmp" else "local"
                out.append(ev({
                    "LLDP-MIB.lldpRemChassisIdSubtype": ("macAddress", f"{rem}.4.{suffix}", "r"),
                    "LLDP-MIB.lldpRemChassisId": (peer.mac, f"{rem}.5.{suffix}", "r"),
                    "LLDP-MIB.lldpRemPortIdSubtype": (port_subtype, f"{rem}.6.{suffix}", "r"),
                    "LLDP-MIB.lldpRemPortId": (port.peer_port, f"{rem}.7.{suffix}", "r"),
                    "LLDP-MIB.lldpRemPortDesc": (f"to {dev.name} {port.name}", f"{rem}.8.{suffix}", "r"),
                    "LLDP-MIB.lldpRemSysName": (peer.name, f"{rem}.9.{suffix}", "r"),
                    "LLDP-MIB.lldpRemSysDesc": (peer.sys_descr or f"Cisco IOS XE Software, {peer.model}, "
                                                f"Version {peer.firmware}", f"{rem}.10.{suffix}", "r"),
                }))
        return out

    def alert_events(self, a: float, b: float, live: bool) -> list:
        """Alert events for windows that start/end in (a, b].

        Both modes emit a separate event per lifecycle change (open, then
        closed), because the NI Alerts page lists open notifications by default.
        Backfill additionally opens windows already active at ``a``.
        """
        out = []
        for w in self.health.alert_windows(a, b):
            if live:
                if a < w.start <= b:
                    out.append(self._render_alert(w, w.start, closed=False))
            else:
                if w.end <= a:
                    continue
                out.append(self._render_alert(w, max(w.start, a), closed=False))
            if a < w.end <= b:
                out.append(self._render_alert(w, w.end, closed=True))
        return out

    def _render_alert(self, w: AlertWindow, t: float, closed: bool) -> Event:
        if w.source == "meraki":
            return self._meraki_alert(w, t, closed)
        if w.source == "catalyst_center":
            return self._catalyst_issue(w, t, closed)
        return self._te_alert(w, t, closed)

    def _meraki_alert(self, w: AlertWindow, t: float, closed: bool) -> Event:
        dev = w.device
        site = dev.site
        templates = {
            "meraki_offline": ("device_offline", "critical", "connectivity",
                               f"{dev.name} went offline", f"{dev.model} {dev.name} stopped checking in to the Meraki cloud."),
            "meraki_alerting": ("device_alerting", "warning", "device_health",
                                f"{dev.name} is reporting connectivity issues",
                                f"{dev.name} has intermittent connectivity to its gateway."),
            "meraki_uplink_port_down": ("switch_uplink_down", "critical", "connectivity",
                                        f"Uplink port {w.port_id} on {dev.name} is down",
                                        f"The uplink port {w.port_id} on {dev.name} lost link; the switch is running without redundancy."),
            "meraki_port_errors": ("switch_port_errors", "warning", "device_health",
                                   f"CRC errors on port {w.port_id} of {dev.name}",
                                   "The port is reporting CRC/alignment errors. Check cabling and the connected client."),
            "meraki_port_warnings": ("switch_port_speed_downshift", "warning", "device_health",
                                     f"Port {w.port_id} on {dev.name} negotiated at 100 Mbps",
                                     "The port negotiated at a lower speed than its capability."),
            "meraki_uplink_loss": ("wan_packet_loss", "warning", "connectivity",
                                   f"High packet loss on {w.port_id} at {site.name}",
                                   f"{w.port_id} on {dev.name} is seeing more than 5% packet loss to 8.8.8.8."),
            "meraki_uplink_latency": ("wan_high_latency", "warning", "connectivity",
                                      f"High latency on {w.port_id} at {site.name}",
                                      f"{w.port_id} on {dev.name} latency to 8.8.8.8 exceeded 150 ms."),
        }
        if w.kind.startswith("noise:"):
            kind = w.kind.split(":", 1)[1]
            _p, _k, severity, title = next(n for n in MERAKI_NOISE if n[1] == kind)
            template = (kind, severity, "insight", f"{title} - {dev.name}", f"{title} on {dev.name} at {site.name}.")
        else:
            template = templates[w.kind]
        alert_type, severity, category, title, description = template
        data = {
            "id": str(int(w.alert_id[:15], 16)),
            "categoryType": category,
            "network": {"id": site.internal_id, "name": site.name, "url": site.url},
            "startedAt": iso_z(w.start),
            "resolvedAt": iso_z(w.end) if closed else None,
            "dismissedAt": None,
            "deviceType": dev.product_type,
            "type": alert_type,
            "title": title,
            "description": description,
            "severity": severity,
            "scope": {
                "devices": [{"serial": dev.serial, "name": dev.name, "mac": dev.mac,
                             "productType": dev.product_type, "url": dev.url}],
                "applications": [],
            },
        }
        return Event(self.idx["meraki"], "meraki:assurancealerts", f"meraki://{MERAKI_ORG_ID}/assurancealerts",
                     MERAKI_HOST, t, data)

    def _catalyst_issue(self, w: AlertWindow, t: float, closed: bool) -> Event:
        dev = w.device
        templates = {
            "catalyst_unreachable": ("Network Device Unreachable From Catalyst Center", "P1", "Availability",
                                     f"Network device {dev.name} is unreachable from Catalyst Center",
                                     "The device is not reachable via ICMP or SNMP. Check power and uplink connectivity."),
            "catalyst_high_cpu": ("Switch High CPU Utilization", "P2", "Device",
                                  f"Switch {dev.name} is experiencing high CPU utilization",
                                  "CPU utilization has exceeded 85% for several polling intervals."),
            "catalyst_high_memory": ("Router High Memory Utilization", "P3", "Device",
                                     f"Router {dev.name} is experiencing high memory utilization",
                                     "Memory utilization has exceeded 80%."),
            "catalyst_ping_reachable": ("Device Only Ping Reachable", "P2", "Availability",
                                        f"{dev.name} is ping reachable but SNMP is failing",
                                        "Catalyst Center can ping the device but cannot collect inventory over SNMP/NETCONF."),
            "catalyst_wan_down": ("WAN Interface Down", "P1", "Connectivity",
                                  f"Interface {w.port_id} is down on router {dev.name}",
                                  "The WAN interface is administratively up but operationally down."),
            "catalyst_iface_errors": ("Interface Input Errors", "P3", "Connectivity",
                                      f"Interface {w.port_id} on {dev.name} is reporting input errors",
                                      "The interface is reporting CRC and input errors above threshold."),
            "catalyst_core_ports_down": ("Core Switch Interfaces Administratively Down", "P1", "Connectivity",
                                         f"All interfaces on core switch {dev.name} are administratively down",
                                         "Every physical interface was shut down by a configuration change "
                                         "(see the device syslog / config archive). Downstream devices lost "
                                         "their uplinks."),
        }
        if w.kind.startswith("noise:"):
            kind = w.kind.split(":", 1)[1]
            _p, _k, priority, title = next(n for n in CATALYST_NOISE if n[1] == kind)
            template = (title, priority, "Device", f"{title}: {dev.name}", f"{title} detected on {dev.name}.")
        else:
            template = templates[w.kind]
        name, priority, category, summary, description = template
        h = w.alert_id
        data = {
            "IssueID": f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}",
            "IssueName": name,
            "IssueSpecificSummary": summary,
            "IssueSpecificDescription": description,
            "IssuePriority": priority,
            "IssueSpecificCategory": category,
            "IssueStatus": "resolved" if closed else "active",
            "DeviceMACAddress": dev.mac,
            "DeviceName": dev.name,
            "DeviceIpAddress": dev.ip,
            "DeviceRole": dev.role,
            "SiteHierarchy": dev.site.hierarchy,
            "IssueTimestamp": int(w.start * 1000),
            "IssueLastOccurenceTime": int(min(w.end, t) * 1000),
            "cisco_catalyst_host": CATALYST_HOST,
        }
        return self._cc("cisco:dnac:issue", t, data)

    def _te_alert(self, w: AlertWindow, t: float, closed: bool) -> Event:
        test = w.test
        rules = {
            "te_high_latency": ("Network latency > 250 ms", "((latency >= 250 ms))", "MAJOR"),
            "te_http_down": ("HTTP availability < 100%", "((errorType != \"None\"))", "CRITICAL"),
            "te_dns_failure": ("DNS resolution failure", "((errorType != \"None\"))", "MAJOR"),
            "te_packet_loss": ("Packet loss > 1%", "((loss >= 1%))", "MINOR"),
        }
        rule_name, expression, severity = rules[w.kind]
        agents = [w.agent] if w.agent else test.agents
        permalink = f"https://app.thousandeyes.com/alerts/list/?__a={TE_ACCOUNT_ID}&alertId={w.alert_id[:10]}"
        alert = {
            "id": str(int(w.alert_id[:10], 16)),
            "type": test.test_type,
            "severity": severity,
            "rule": {"id": stable_hex("rule", rule_name, length=8), "name": rule_name, "expression": expression},
            "test": {"id": test.test_id, "name": test.name, "type": test.test_type},
            "startDate": iso_z(w.start),
            "targets": [{"name": test.target}],
            "details": [{"source": {"id": a.agent_id, "name": a.name}, "metricsAtStart": rule_name}
                        for a in agents],
            "permalink": permalink,
        }
        if closed:
            alert["cleared"] = iso_z(w.end)
        data = {
            "id": stable_hex(w.alert_id, "clear" if closed else "trigger"),
            "eventType": "ALERT_NOTIFICATION_CLEAR" if closed else "ALERT_NOTIFICATION_TRIGGER",
            "testId": test.test_id,
            "alert": alert,
            "itsiDrilldownURI": permalink,
        }
        return Event(self.idx["thousandeyes"], "cisco:thousandeyes:alerts", "thousandeyes:webhook",
                     TE_HOST, t, data)
