# TA-bar-datagen – Demo Datagen (Buttercup Bar, CoolaShaker, Network Intelligence)

One Splunk add-on, three demo data generators, one HEC token, start/stop from the UI.
Installs on Splunk Cloud (Victoria/Classic) or Splunk Enterprise.

| Input type | What | Indexes |
|---|---|---|
| **Bar datagen** | Buttercup Rocks bar (conf26 ITSI demo), from `bar_datagen/datagen.py` | `bar_demo` |
| **Network Intelligence** | 279 network devices / 40 sites (Meraki, Catalyst Center, ThousandEyes, SC4SNMP) + health history for the Splunk **Network Intelligence** app 26.10.x – from `network_intelligence_datagen` | `demo_cisco_meraki`, `demo_cisco_catalyst`, `demo_thousendeyes` (shared with CoolaShaker), `netops`, `ni_capability_summary` |
| **CoolaShaker** | Coffee-cup manufacturer: Teams, ThousandEyes, Catalyst Center, Meraki, VMware, Windows, MSSQL, MES, Infra, Tomcat, AI Defense, SAP ERP/MII – from `cisco_netzwerkmonitoring/collashaker_fixed.py` | 13 × `demo_*` (below) |

* Install file: `TA-bar-datagen-1.9.0.tar.gz` (upgrade over 1.x keeps setup + inputs)
* AppInspect 4.4 (`cloud`, `private_victoria`, `private_classic`): **0 failures, 0 errors**
* Tested end-to-end on Splunk Enterprise 9.3.2 (Python 3.9): setup, token check, HEC + direct
  mode for both generators incl. metric indexes, backfill, start/stop, gap fill.

## Before you install

| # | What | Why |
|---|------|-----|
| 1 | A **HEC token** whose *allowed indexes* contain all 16 indexes below | Each event carries its index; a missing one → `Incorrect index` (code 7). |
| 2 | The **HEC URL** | Splunk Cloud: `https://http-inputs-<stack>.splunkcloud.com:443` · Enterprise: `https://<host>:8088` |
| 3 | Role **sc_admin** (Cloud) / admin | Upload private app, edit inputs. |

The **indexes are created by the app** (`default/indexes.conf`):

| Index | Type | Sourcetypes |
|---|---|---|
| `bar_demo` | event | `bar:*` |
| `demo_msteams` | event | `msteams:json` |
| `demo_thousendeyes` | event | CoolaShaker: `thousendeyes:json` · Network Intelligence: `cisco:thousandeyes:metric`, `cisco:thousandeyes:alerts` |
| `demo_cisco_catalyst` | event | CoolaShaker: `cisco:dnac:devicehealth`, `cisco:dnac:site:topology`, `cisco:dnac:securityadvisory` · Network Intelligence: `cisco:dnac:devicehealth`, `cisco:dnac:devicehealth:interface`, `cisco:dnac:custom`, `cisco:dnac:issue`, `cisco:dnac:site:topology`, `cisco:ios` (switch syslog), `cisco:gnmi` (gNMI telemetry) |
| `demo_cisco_meraki` | event | `meraki:organizations`, `meraki:organizationsnetworks`, `meraki:assurancealerts`, `meraki:devicesavailabilitieschangehistory`, `meraki:wirelessdevicespacketlossbydevice` · Network Intelligence: `meraki:devices`, `meraki:devicesavailabilities`, `meraki:switchportsbyswitch`, `meraki:custom`, … |
| `demo_windows_events` | event | `windows:events:json` |
| `demo_mssql` | event | `mssql:json` |
| `demo_mes` | event | `mes:json` |
| `demo_infra` | event | `infra:json` |
| `demo_ai_defense` | event | `cisco:ai:defense` (Cisco AI Defense, AI Support Bot) |
| `demo_sap` | event | `sap:erp:performance`, `sap:idoc`, `sap:idoc:status`, `sap:mii:performance` (SAP ERP PRD, SAP MII) |
| `demo_tomcat_logs` | event | `tomcat:access` |
| `demo_vmware_metrics` | **metric** | `vmware:metrics:json` |
| `demo_windows_metrics` | **metric** | `webex:windows:metrics:json` |
| `netops` | event | `sc4snmp:event` |
| `ni_capability_summary` | event | `ni:capability:observation` – **not created by this app**, ships with the Network Intelligence app |

Retention: 30 days for `bar_demo`/`demo_*`, 14 days for the Network Intelligence indexes (as in its original indexes.conf). Splunk Cloud does not allow
`maxTotalDataSizeMB` in app-shipped indexes.conf, so the 500 GB caps of the original were dropped.
Index names are unchanged from the original `inputs.conf`, so existing dashboards keep working.

Copy-paste for the token's allowed indexes:
`bar_demo,demo_ai_defense,demo_cisco_catalyst,demo_cisco_meraki,demo_infra,demo_mes,demo_mssql,demo_msteams,demo_sap,demo_thousendeyes,demo_tomcat_logs,demo_vmware_metrics,demo_windows_events,demo_windows_metrics,netops,ni_capability_summary`

## Install & run

1. *Apps → Manage Apps → Install app from file* → upload the `.tar.gz` (or *Upgrade*).
2. First launch → **Setup → HEC Setup**: Send mode (`HEC` default / `Direct`), HEC URL, HEC token
   (tested on save, stored encrypted), Verify TLS (on for Splunk Cloud).
3. **Inputs → Create New Input →** *Bar datagen* and/or *CoolaShaker*.
4. **Status toggle** = start / stop.

### CoolaShaker input settings

| Field | Default | Notes |
|---|---|---|
| Volume | **Reduced** | *Original* ≈ 540 k events / 80 MB per hour (≈ 1.9 GB/day) – 85 % of that is the Berlin Tomcat DoS burst. *Reduced* keeps 1 of 10 burst lines (≈ 0.6 GB/day); the DoS pattern stays clearly visible. |
| Time zone | Europe/Vienna | Business hours + fault windows (the original used the box's local time). |
| Backfill on first start | 0 min | Up to 7 days. 60 min ≈ 25 MB (reduced). |
| Fill gaps up to | 15 min | After stop/start; longer gaps are skipped. |
| Default host | coolashaker | Events with their own host (ESXi, DB, Tomcat servers) keep it. |

Every fault scenario has its own checkbox on the input. **Since 1.4.0 all scenarios are off by
default** – a fresh input produces a healthy CoolaShaker. Switching one off makes **every** data
source it touches produce its normal baseline. Changes are picked up live within ~10 s (no restart,
logged as `Fault scenarios changed: …`).

**Lab scenarios** (network outages and their impact on AI workloads) run continuously
while switched on. They ramp up over 10 minutes: network/path telemetry (leading indicators) moves
right away, business impact (MES, transactions, users) starts ~6 minutes after switching on. The
switch-on time is kept in the checkpoint, so a restart does not replay the ramp. Only additional
fields, devices, tests and metric names are added – existing indexes and sourcetypes are unchanged;
1.7.0 adds the index `demo_ai_defense` (sourcetype `cisco:ai:defense`), 1.9.0 the index `demo_sap`
(SAP ERP PRD on `vieerp01/02` + HANA `viehdb01` in the Vienna DC, SAP MII `atlmii01`, `bermii01`,
`viemii01`; these six servers also send Windows and VMware metrics like the other servers).

| Switch (inputs.conf) | Early warning (0–6 min) | Impact (from ~6 min) |
|---|---|---|
| `scenario_dc_frankfurt` | TE agent-to-agent "DC Atlanta/Berlin/Vienna to Frankfurt" loss/latency/jitter. TE "AI Support Assistant API" slow (the LLM runs in the Frankfurt DC). Cisco AI Defense (`demo_ai_defense`, `cisco:ai:defense`, app "CoolaShaker Support Bot"): allowed prompts without response, users repeat prompts (`event_conversation_id`); guardrail hits unchanged. VMware `fragpu01-04` (`location=frankfurt`, `workload=llm-inference`): utilization and memory up, `vmware.vm.gpu.llm.requests.aborted.pct`, `…queue.depth`, `…ttft.ms` up, `…tokens.delivered.per_sec` down. | Teams `event_type=call_queue_stats` `queue_name="Support Hotline"`: `calls_waiting`, `longest_wait_seconds`, `bot_handoffs`, `calls_abandoned` up. |
| `scenario_sdwan_brownout` | TE agent-to-agent "DC … Berlin …" loss/latency/jitter, TE Teams Media Berlin, Meraki `meraki:assurancealerts` high_latency/packet_loss/uplink_jitter on Berlin MX (`uplink=wan1`). | Meraki `uplink_failover`, `vpn_tunnel_degraded`, `activeUplink` wan1→cellular. Teams Berlin poor calls + `call_failed`, Tomcat `berweb01/02` 504 on `/api/v1/mes/data`, `/inventory/sync`, `/production/status`. TE Prod-API across the WAN slow, AI API from Berlin slow. MES Berlin lines 1–2 manual sampling + `wan_degraded`. Catalyst Center Berlin stays green. |
| `scenario_sap_idoc` | `demo_sap`: production order IDocs `LOIPRO05` ERP → MII get `status=02` ("SSL handshake failed … client certificate CN=PRD-RFC-CLIENT (certificate expired)", `rfc_destination=MII_<SITE>_IDOC`), `sap:idoc:status` `idoc_error_count`, `idoc_outbound_backlog`, `trfc_queue_entries`, `idoc_e2e_latency_s` up, `sap:mii:performance` `orders_received` and `mii_order_buffer` down; ERP job RSEOUT00 fails (`failed_background_jobs`). ERP response times, HANA, MII servers and the network stay green. | MII order buffers empty → MES Atlanta, Berlin and Vienna: every line `production_rate_per_hour=0`, `status=stopped`, `machine_status=waiting_for_orders`, `order_status=no_order_released`, `system_alert` `alert_type=order_data_missing`. Off: the backlog is delivered within a minute. |
| `scenario_isp_route_leak` | TE BGP from Atlanta: `bgp.reachability` down, updates/path changes up, `bgp.as_path` via AS64512. TE DNS Atlanta slow. TE Teams Media Atlanta latency. | From Atlanta: Teams/M365 HTTP, public websites, page load, "B2B Order Transaction" (errors, completion < 80 %), "AI Support Assistant API" slow/failing. Teams Atlanta poor calls. Catalyst/Meraki Atlanta stay green ("it's not our network"). |

**Original demo scenarios** (minute-of-hour windows, driven by each event's timestamp so they
also appear correctly in backfill):

| Switch (inputs.conf) | Window | Off = normal in |
|---|---|---|
| `scenario_berlin_db` | :00–:15, :30–:45 | Password change on `winsched_service` → "Database Log Cleanup" task fails → log/disk full, CPU/memory/paging → MSSQL alerts + failed backups → MES Berlin degraded + ThousandEyes Prod-API Berlin. Off: Windows events/metrics `berdb001`, MSSQL, MES Berlin, TE Prod-API Berlin all normal. |
| `scenario_berlin_dos` | :00–:15, :30–:45 | Tomcat access logs `berweb01/02` (attacker IPs, 429/503, 1-second burst cadence). |
| `scenario_atlanta_teams` | :00–:10 | Teams call/meeting failures Atlanta, TE Teams HTTP + media tests Atlanta. |
| `scenario_vienna_teams` | :20–:28 | TE Teams/M365 HTTP + media tests Vienna. |
| `scenario_atlanta_network` | :40–:45 (+ MES :45–:50) | Catalyst Center Atlanta, Meraki alerts/availability/packet loss Atlanta, MES Atlanta. |

Normal background noise (occasional Teams `login_failed`, base-rate Meraki alerts, 2 % device flaps)
is not a scenario and stays. Standalone: `--enable-scenario dc_frankfurt` (repeatable).
`tests/test_scenarios.py` (repo root) simulates 2 h with all/none/each scenario, checks every source,
the early-warning ramp, and that the set of indexes/sourcetypes never changes.

### Network Intelligence input settings

| Field | Default | Notes |
|---|---|---|
| Collection cycle | 300 s | One snapshot of all devices per run (≈ 1,350 events), = the original `--interval`. ≈ 390 k events/day. |
| Inventory seed | 2690 | Same seed → same serials/MACs/IDs → stable graph in the app. |
| Indexes | demo_cisco_meraki, demo_cisco_catalyst, demo_thousendeyes, netops, ni_capability_summary | Same indexes as the CoolaShaker network data, so the CoolaShaker ITSI service tree sees both. Must match the data-source config in *Network Intelligence → Configuration* (macro `ni_indexes`). |
| Backfill (first start only) | alerts 48 h, raw telemetry 2 h, health history 24 h | ≈ 375 k events in total (mostly health history). |
| Fill gaps up to | 30 min | Alert open/close transitions are always caught up. |

The generator library (`bin/ni_datagen_lib/`) is the original `datagen/` package (only `sinks.py`
is not used – the add-on sends through its own HEC client). Since 1.5.0 it adds switch syslog
(`cisco:ios`, source `udp:514`) and gNMI telemetry (`cisco:gnmi`, source `gnmi:telegraf`) to the
Catalyst index. The input replaces
`ni_datagen.py` + systemd + state file; the checkpoint lives in the KV store/file like the bar input.

Since 1.8.0 the sites follow the CoolaShaker locations:

| Site | Source | Devices |
|---|---|---|
| Atlanta-Office, Berlin-Office, Vienna-Office | Catalyst Center (campus: border router, 2 core, access, WLC, APs) | 18–23 each |
| Atlanta Factory, Berlin Factory, Vienna Factory | Meraki (MX, 3 MS, 10 MR, 4 MV cameras, 4 MT sensors, MG) | 23 each |
| `<City> Branch` – one per German state (15) and Austrian state (8) without Berlin/Vienna, one per large US state (CA, TX, NY, FL, IL, WA, MA, NC, OH, CO) | Meraki (MX, 1 MS, 2 MR) | 4 each |
| Frankfurt DC1 | SC4SNMP | 14 |

Vienna-Office devices, interface IDs and links as well as all ThousandEyes test IDs are unchanged
from earlier versions (`tests/test_ni_datagen.py` checks this); every other Meraki/Catalyst site
is new. ThousandEyes enterprise agents 1024–1027 now sit in Berlin (office, factory) and Atlanta
(factory, office). After the upgrade, clear the NI KV store collections once so the old sites
disappear from the app.

Since 1.6.1 the events also carry the fields the CoolaShaker ITSI KPIs (Catalyst Center and
ThousandEyes content packs) search on: `HealthScore` (= `OverallHealth`) in
`cisco:dnac:devicehealth`, `Location=Global/Europe/Austria/Vienna` for the Vienna office (= the
CoolaShaker Vienna site entity; `Site` keeps the NI hierarchy) and `metric_name:<metric>` next to
`metric_name`/`metric_value` in `cisco:thousandeyes:metric`.

On the first start the input first sends the current snapshot index by index. If the HEC token
does not allow one of the five indexes, the log names it and no backfill is sent; the next run
starts over.

After the first start, follow the original README: enable the four data sources in
*Network Intelligence → Configuration* and run **Backfill** per source after ~30 min.
**Stop the old systemd service `ni-datagen`** (or the `nohup` process) when you switch to the
add-on, otherwise every event arrives twice.

Not included on purpose: the original `splunk/props.conf` workaround (`KV_MODE = none` for
`meraki:assurancealerts` / `meraki:organizationsnetworks`). It is only needed when another
add-on extracts those sourcetypes at index time, and it would break the CoolaShaker Meraki events.
Check with `index=meraki sourcetype=meraki:assurancealerts | eval n=mvcount(id) | stats count by n`
(on the demo stack: `n=1`, so not needed). `ni_settings.conf` / `web.conf` (timeouts for busy
servers) belong to the NI app / system and stay manual.

## How CoolaShaker was converted (file → HEC)

* `coolashaker_hec.py` was generated from `collashaker_fixed.py` by `tools/convert.py`. Since 1.3.0
  it is edited directly (scenario switches in the `is_*_time()` checks) – do not regenerate it.
  Apart from that the 13 generator bodies are unchanged; only three things differ:
  * `datetime.now()` / `time.time()` → a simulated clock,
  * the 13 threads + `time.sleep(n)` → Python generators that `yield n` (same cadence 1 s … 300 s),
  * `write_data()` / Tomcat file writes → a router that sends to HEC.
* Routing = the old `inputs.conf` monitor stanzas (file → index + sourcetype). The old index-time
  `TRANSFORMS` that took the sourcetype from the JSON (`cisco:dnac:*`, `meraki:*`) is done in the
  router; HEC skips index-time transforms and `INDEXED_EXTRACTIONS`.
* JSON sourcetypes therefore use **search-time** `KV_MODE = json` (in this app's props.conf).
  Note: `TA_cisco_catalyst` sets `KV_MODE = none` for `cisco:dnac:devicehealth` and
  `cisco:dnac:securityadvisory`; this app sorts before it (`-` < `_`), so `json` wins.
* VMware/Windows metrics go to HEC as native metric events (`metric_name`, `_value`, dimensions).
  In Direct mode they use sourcetype `coolashaker:metrics:direct` + index-time transforms.
* Long-running input: the generators keep state (device up/down, perf cache), so one process
  streams continuously. A watchdog stops it within 10 s of disabling the input, a lock file
  prevents a second instance.
* Standalone (no Splunk app): `python3 coolashaker_hec.py --hec-url … --hec-token … [--no-verify]
  [--backfill-minutes N] [--dry-run]`.

## Bar datagen – how it behaves

* Every run (interval) generates all 10-second ticks since the previous run, sends them, saves
  the bar state and exits. State in KV store **and** a file checkpoint; the newer wins.
* First start backfills *N* days at 5-minute resolution (14 days ≈ 190 k events).
* ≈ 250 k events / 38 MB per day. Open Tue–Sun 18:00–01:00, QuickBooks batch at 01:xx.
* Sourcetypes unchanged, so `itsi_build_tree.spl` / `itsi_create_kpis.py` keep working.

## Logs

`index=_internal source=*ta-bar-datagen_*.log` (bar: `…_<input>.log`, CoolaShaker: `…_coolashaker_<input>.log`, Network Intelligence: `…_ni_<input>.log`)

## Rebuild from source

```bash
pip install splunk-add-on-ucc-framework   # tested with 6.6.0
# only when collashaker_fixed.py changed:
python3 tools/convert.py collashaker_fixed.py coolashaker_engine.py
cat coolashaker_engine.py tools/runtime_footer.py > package/bin/coolashaker_hec.py
tools/build.sh 1.2.2        # ucc-gen build + is_configured fix + package
```

`tools/build.sh` pins pip 25.3 for the build (UCC 6.6 breaks with pip 26) and sets
`is_configured = true` after the build: UCC always writes `false`, and Splunk Cloud then shows
its generic "App configuration" page instead of the app.

`package/bin/TA_bar_datagen_rh_settings.py` deliberately overrides the UCC-generated REST
handler (Setup page → token test + "configured" flag). If you change Setup fields in
`globalConfig.json`, delete it, build once, copy the generated file back and swap
`AdminExternalHandler` → `SetupHandler` (2 lines). `solnlib<8` is pinned on purpose
(solnlib 8 pulls in compiled `grpcio`).
