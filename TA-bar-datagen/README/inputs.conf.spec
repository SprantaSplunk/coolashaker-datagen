[bar_datagen://<name>]
backfill_days = Only runs the very first time this input starts (5-minute resolution). 0 = realtime only. Clone the input under a new name to backfill again. (Default: 14)
bar_host = (Default: bar-datagen)
index = Must exist and (HEC mode) be allowed for the HEC token. (Default: bar_demo)
interval = Each run generates all events since the previous run (10-second resolution) and sends them. (Default: 60)
max_gap_minutes = After a stop/start, gaps shorter than this are filled. Longer gaps are skipped and generation resumes at 'now'. (Default: 15)
timezone = IANA name. Opening hours (Tue–Sun 18:00–01:00) are evaluated in this zone. (Default: America/Denver)
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set

[coolashaker://<name>]
backfill_minutes = 0 = realtime only. 60 min ≈ 25 MB (reduced). Runs only the first time this input starts. (Default: 0)
cs_host = Used when an event carries no host of its own (ESXi, Tomcat and DB servers keep their names). (Default: coolashaker)
interval = Long-running input: splunkd only uses this to restart the generator if it ever stops unexpectedly. (Default: 60)
max_gap_minutes = (Default: 15)
scenario_dc_frankfurt = Lab scenario (continuous while on): WAN connection to the Frankfurt DC degraded. The LLM of the AI Support Bot runs on the Frankfurt GPU cluster (fragpu01-04). ThousandEyes "DC Atlanta/Berlin/Vienna to Frankfurt" loss/latency/jitter up, "AI Support Assistant API" slow, Cisco AI Defense (demo_ai_defense, cisco:ai:defense) shows prompts without response and repeated prompts, Frankfurt GPUs busy with aborted requests, long queue and slow first token; after ~6 min calls pile up in the Teams "Support Hotline" queue. 0 = normal. Applied live within ~10 s. (Default: 0)
scenario_ai_fabric = Not used since 1.7.0 (replaced by scenario_dc_frankfurt). (Default: 0)
scenario_sdwan_brownout = Lab scenario (continuous while on): SD-WAN brownout Berlin. Loss/latency/jitter on all ThousandEyes DC paths from/to Berlin and Teams media Berlin, Meraki MX uplink alerts; after ~6 min failover to cellular, Teams Berlin poor, Tomcat berweb 504 on backend APIs, MES Berlin manual sampling + ERP sync delayed. Catalyst Center Berlin stays green. 0 = normal. Applied live within ~10 s. (Default: 0)
scenario_isp_route_leak = Lab scenario (continuous while on): ISP route leak at Atlanta. ThousandEyes BGP from Atlanta (reachability down, path changes up, AS path via AS64512), DNS slow; after ~6 min SaaS/M365/Teams, public websites, B2B order transaction and "AI Support Assistant API" degraded from Atlanta, Teams Atlanta poor. Catalyst/Meraki Atlanta stay green. 0 = normal. Applied live within ~10 s. (Default: 0)
scenario_atlanta_network = Fault scenario: Atlanta network outage minute 40-45 (Catalyst Center, Meraki alerts/availability/packet loss) and MES Atlanta 45-50. 0 = all of these stay normal. Applied live within ~10 s. (Default: 0)
scenario_atlanta_teams = Fault scenario: Microsoft Teams outage in Atlanta minute 0-10 (call/meeting failures, ThousandEyes Teams HTTP + media tests). 0 = normal. Applied live within ~10 s. (Default: 0)
scenario_sap_idoc = Lab scenario (continuous while on): SAP IDoc interface ERP -> MII broken. The TLS client certificate of the tRFC connection from SAP ERP PRD (vieerp01/02) to the SAP MII IDoc listeners (atlmii01, bermii01, viemii01) expired: production order IDocs LOIPRO05 (demo_sap, sap:idoc) get status 02, tRFC queue, IDoc backlog and latency grow (sap:idoc:status), MII receives fewer orders and its order buffer drains (sap:mii:performance); after ~6 min no orders are left and MES stops every line in Atlanta, Berlin and Vienna (status=stopped, machine_status=waiting_for_orders, alert_type=order_data_missing). ERP response times, HANA and the network stay green. 0 = normal. Applied live within ~10 s. (Default: 0)
scenario_berlin_db = Fault scenario: chain on berdb001, minute 0-15 and 30-45. Password change of the scheduled-task account -> "Database Log Cleanup" task fails -> transaction log/disk full, CPU/memory/paging up -> MSSQL alerts, failed backups -> MES Berlin production degraded + ThousandEyes Prod-API Berlin down. 0 = every source stays normal (no Windows error events, normal CPU/memory/disk, MSSQL, MES, API). Applied live within ~10 s. (Default: 0)
scenario_berlin_dos = Fault scenario: DoS burst on the Berlin Tomcat servers berweb01/02, same window as the berdb001 chain. 0 = normal access log volume and status codes. Applied live within ~10 s. (Default: 0)
scenario_vienna_teams = Fault scenario: Vienna Teams connectivity issues minute 20-28 (ThousandEyes HTTP + media tests). 0 = normal. Applied live within ~10 s. (Default: 0)
timezone = Business hours and the minute-of-hour fault windows run in this zone (the original ran on local time). (Default: Europe/Vienna)
volume = Reduced keeps 1 of 10 lines of the Berlin Tomcat DoS bursts (the pattern stays visible). Everything else is identical. (Default: reduced)
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set

[ni_datagen://<name>]
alert_backfill_hours = First start only. (Default: 48)
backfill_hours = First start only. (Default: 2)
index_catalyst = Shared with the CoolaShaker demo data. (Default: demo_cisco_catalyst)
index_meraki = Shared with the CoolaShaker demo data. (Default: demo_cisco_meraki)
index_snmp = Read by the app's ni_sc4snmp_indexes macro. (Default: netops)
index_summary = Ships with the Network Intelligence app. (Default: ni_capability_summary)
index_thousandeyes = Shared with the CoolaShaker demo data. (Default: demo_thousendeyes)
interval = One full snapshot of all ~214 devices per cycle (≈1,350 events). 300 = original --interval. (Default: 300)
max_gap_minutes = After stop/start, missed snapshots are only resent for shorter gaps. Alert open/close transitions are always caught up. (Default: 30)
seed = Keep it stable: same seed = same serials, MACs and IDs, so the app's graph stays stable. (Default: 2690)
summary_backfill_hours = First start only, written to the health-history index (~2,000 observations per 15 min). 0 disables. (Default: 24)
python.required = {3.7|3.9|3.13}
* For Python scripts only, selects which Python version to use.
* Set to "3.9" to use the Python 3.9 version.
* Set to "3.13" to use the Python 3.13 version.
* Optional.
* Default: not set
