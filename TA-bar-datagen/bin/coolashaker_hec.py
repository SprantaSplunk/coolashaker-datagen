#!/usr/bin/env python3
"""
CoolaShaker Multi-Technology Data Generator – engine (HEC edition)
Auto-converted from collashaker_fixed.py by convert.py: generator bodies are
unchanged, threads became Python generators driven by a simulated clock.
Generates realistic operational data for a virtual coffee cup manufacturer

KORREKTUR: MES Generator - Jede Produktionslinie bekommt unterschiedliche Werte
"""

import json
import random
import time
from datetime import datetime, timedelta, timezone

# Configuration
COMPANY = "coolashaker"

LOCATIONS = {
    "atlanta": {"code": "atl", "country": "US", "timezone": "America/New_York"},
    "berlin": {"code": "ber", "country": "DE", "timezone": "Europe/Berlin"},
    "vienna": {"code": "vie", "country": "AT", "timezone": "Europe/Vienna"}
}

# Server naming: [3-letter location][3-letter function][2-digit number]
SERVERS = {
    "atlanta": {
        "vms": ["atlapp01", "atlapp02", "atlweb01", "atlweb02", "atldb001"],
        "esxi": ["atlesx01", "atlesx02"]
    },
    "berlin": {
        "vms": ["berapp01", "berapp02", "berweb01", "berweb02", "berdb001"],
        "esxi": ["beresx01", "beresx02"]
    },
    "vienna": {
        "vms": ["vieapp01", "vieapp02", "vieweb01", "vieweb02", "viedb001"],
        "esxi": ["vieesx01", "vieesx02"]
    }
}

# Problem server in Berlin
PROBLEM_SERVER = "berdb001"

# Fault scenarios that can be switched on/off individually (all off by default).
# Off = every data source that the scenario touches produces its normal baseline.
SCENARIOS = {
    # --- Lab scenarios: continuous while switched on (early warning first, then impact) ---
    "dc_frankfurt":     "DC Frankfurt WAN degraded – loss/latency on every path to Frankfurt -> AI Support Bot "
                        "(LLM on the Frankfurt GPUs) slow, prompts unanswered and retried (AI Defense), GPUs busy "
                        "with aborted requests -> calls pile up in the Support Hotline queue",
    "sdwan_brownout":   "Berlin SD-WAN brownout – MX uplink loss/jitter, failover to cellular -> DC paths Berlin, "
                        "Teams Berlin, Tomcat 504s, AI inspection Berlin delayed",
    "isp_route_leak":   "Atlanta ISP route leak – BGP path changes -> DNS/SaaS/B2B/AI assistant slow from Atlanta, "
                        "own Catalyst/Meraki network stays green",
    # --- original demo: minute-of-hour windows ---
    "berlin_db":        "Berlin berdb001 chain :00-:15/:30-:45 – password change on the scheduled task "
                        "-> log cleanup fails -> disk/log full, CPU/memory -> MSSQL -> MES Berlin + Prod-API Berlin",
    "berlin_dos":       "Berlin Tomcat DoS burst on berweb01/02 :00-:15/:30-:45",
    "atlanta_teams":    "Teams outage Atlanta :00-:10 (Teams call failures, ThousandEyes Teams tests)",
    "vienna_teams":     "Vienna Teams connectivity :20-:28 (ThousandEyes HTTP/network tests)",
    "atlanta_network":  "Atlanta network outage :40-:45 (Catalyst, Meraki) + MES Atlanta :45-:50",
    # --- SAP: continuous while switched on ---
    "sap_idoc":         "SAP IDoc interface ERP -> MII broken – TLS client certificate of the tRFC connection from "
                        "ERP PRD to the MII IDoc listeners expired -> production order IDocs (LOIPRO05) stay in "
                        "status 02, tRFC queue and backlog grow, MII receives no orders -> after ~6 min the MII "
                        "order buffers are empty and every line in Atlanta, Berlin and Vienna stops",
}
LAB_SCENARIOS = ("dc_frankfurt", "sdwan_brownout", "isp_route_leak", "sap_idoc")

# Lab scenarios ramp up after being switched on: leading indicators (network/path telemetry)
# right away, business impact (MES, transactions, users) once the level reaches IMPACT_LEVEL.
SCENARIO_RAMP_SEC = 600
IMPACT_LEVEL = 0.6          # -> impact ~6 minutes after switching on
SCENARIO_MIN_LEVEL = 0.15

# AI vision inspection: camera images from all lines are scored by the GPU cluster in Vienna
GPU_NODES = [
    {"vm_name": "viegpu01", "host": "vieesx-gpu01", "workload": "ai-inference"},
    {"vm_name": "viegpu02", "host": "vieesx-gpu01", "workload": "ai-inference"},
    {"vm_name": "viegpu03", "host": "vieesx-gpu02", "workload": "ai-training"},
    {"vm_name": "viegpu04", "host": "vieesx-gpu02", "workload": "ai-training"},
]

# AI Support Bot: the LLM runs on the GPU cluster in the Frankfurt DC; every plant reaches it over
# the WAN, Cisco AI Defense inspects each prompt/response in front of the model
LLM_GPU_NODES = [
    {"vm_name": "fragpu01", "host": "fraesx-gpu01"},
    {"vm_name": "fragpu02", "host": "fraesx-gpu01"},
    {"vm_name": "fragpu03", "host": "fraesx-gpu02"},
    {"vm_name": "fragpu04", "host": "fraesx-gpu02"},
]
SUPPORT_BOT = {
    "application_id": "app-7f3c2a91-coolashaker-support-bot",
    "application_name": "CoolaShaker Support Bot",
    "connection_id": "conn-4b8e15d2-fra-llm-gateway",
    "connection_name": "fra-llm-gateway",
    "policy_id": "pol-2d6a9c40-support-bot",
    "policy_name": "Support Bot - Customer Facing",
    "model_name": "llama-3.1-70b-instruct",
    "model_provider_name": "Self-hosted (DC Frankfurt)",
}
# SAP: S/4HANA ERP (SID PRD) runs centrally in the Vienna DC, one SAP MII server per plant.
# Production orders: ERP -> IDoc LOIPRO05 over tRFC -> MII -> MES; MES confirmations go back via MII.
SAP_ERP = {"sid": "PRD", "client": "100", "app_servers": ("vieerp01", "vieerp02"), "db_server": "viehdb01",
           "location": "vienna"}
SAP_MII = {"atlanta": "atlmii01", "berlin": "bermii01", "vienna": "viemii01"}
SAP_SERVERS = {"atlanta": ["atlmii01"], "berlin": ["bermii01"],
               "vienna": ["vieerp01", "vieerp02", "viehdb01", "viemii01"]}
SAP_MII_BUFFER = 24           # released production orders an MII server keeps ready for its MES lines
SAP_CERT_ERROR = ("SSL handshake failed: peer rejected client certificate CN=PRD-RFC-CLIENT "
                  "(certificate expired)")

# (ruleset type, guardrail, rule, action, direction, share of messages) - same with or without the scenario
AI_GUARDRAILS = [
    ("Security", "Prompt Injection", "Jailbreak",              "Block", "prompt",   0.006),
    ("Privacy",  "PII",              "Email Address",          "Allow", "prompt",   0.020),
    ("Privacy",  "PII",              "Phone Number",           "Allow", "response", 0.008),
    ("Safety",   "Toxicity",         "Harassment",             "Block", "prompt",   0.002),
]

# Realistic user data
USERS = [
    {"name": "Sarah Johnson", "email": "sarah.johnson@coolashaker.com", "dept": "Production"},
    {"name": "Michael Chen", "email": "michael.chen@coolashaker.com", "dept": "Engineering"},
    {"name": "Emma Rodriguez", "email": "emma.rodriguez@coolashaker.com", "dept": "Quality"},
    {"name": "James Wilson", "email": "james.wilson@coolashaker.com", "dept": "IT"},
    {"name": "Lisa Anderson", "email": "lisa.anderson@coolashaker.com", "dept": "Management"},
    {"name": "David Kumar", "email": "david.kumar@coolashaker.com", "dept": "Production"},
    {"name": "Maria Garcia", "email": "maria.garcia@coolashaker.com", "dept": "HR"},
    {"name": "Thomas Mueller", "email": "thomas.mueller@coolashaker.com", "dept": "Engineering"},
    {"name": "Anna Kowalski", "email": "anna.kowalski@coolashaker.com", "dept": "Sales"},
    {"name": "Robert Taylor", "email": "robert.taylor@coolashaker.com", "dept": "Logistics"},
]

# Vienna site without network: servers there stop reporting, every ThousandEyes test from or to the
# site fails. The Vienna DC (GPU cluster, AI fabric, racks) and the Frankfurt DC stay reachable.
VIENNA_SILENT_FILES = ("windows_metrics.json", "windows_events.json", "mssql.json")
VIENNA_DC_ADDRESSES = ("ai-inference.vie.coolashaker.int",)
TE_TIMEOUT_SEC = 10.0


def isolate_vienna(filename, data):
    """Applies the Vienna site outage to one event in place; False = the event is not sent."""
    if filename in VIENNA_SILENT_FILES:
        return data.get("location") != "vienna"
    if filename == "vmware_metrics.json":
        return data.get("location") != "vienna" or data.get("metric_type") == "gpu_vm"
    if filename != "thousandeyes.json":
        return True
    address = data.get("server.address", "")
    if "vienna" not in (data.get("thousandeyes.agent.location"), data.get("thousandeyes.target.agent.location")) \
            and not (".vie." in address and address not in VIENNA_DC_ADDRESSES):
        return True
    failed = {
        "network.loss": 100.0, "network.latency": 0.0, "network.jitter": 0.0, "http.server.request.availability": 0.0, "http.server.throughput": 0,
        "http.client.request.duration": TE_TIMEOUT_SEC, "dns.lookup.availability": 0.0,
        "dns.lookup.duration": TE_TIMEOUT_SEC, "bgp.reachability": 0.0, "web.page_load.completion": 0.0,
        "web.page_load.duration": TE_TIMEOUT_SEC, "web.transaction.completion": 0.0,
        "web.transaction.errors.count": 1, "web.transaction.duration": TE_TIMEOUT_SEC,
        "api.completion": 0.0, "api.duration": TE_TIMEOUT_SEC,
    }
    for key in [k for k in data if k.startswith("metric_name:")]:
        metric = key.split(":", 1)[1]
        if metric in failed:
            data[key] = failed[metric]
    return True


class DataGenerator:
    def __init__(self, sink, tz=None):
        self.sink = sink              # receives (filename, payload) / tomcat lines
        self.tz = tz                  # zoneinfo for the simulated wall clock (None = server local)
        self._ts = None               # simulated epoch, set by the scheduler before every step
        self.active_calls = {}  # Track active calls
        self.perf_cache = {}  # Sync performance data between MSSQL and Windows metrics
        self.scenarios = dict.fromkeys(SCENARIOS, False)
        self.onset = {}               # lab scenario -> simulated epoch when it was switched on
        self.isolation = None         # callable(ts) -> True while the Vienna site has no network

    def vienna_isolated(self):
        return self.isolation is not None and self.isolation(self._ts)

    def scenario_on(self, name):
        return self.scenarios.get(name, False)

    def scenario_level(self, name):
        """0 = off; otherwise SCENARIO_MIN_LEVEL..1 rising over SCENARIO_RAMP_SEC after switch-on."""
        if not self.scenario_on(name):
            return 0.0
        elapsed = self._ts - self.onset.get(name, self._ts)
        return min(1.0, max(SCENARIO_MIN_LEVEL, elapsed / SCENARIO_RAMP_SEC))

    def scenario_impact(self, name):
        return self.scenario_level(name) >= IMPACT_LEVEL

    @staticmethod
    def ramp(level, normal, worst):
        """Value between normal (level 0) and worst (level 1)."""
        return normal + (worst - normal) * level

    def now_ts(self):
        return self._ts

    def now(self):
        """Simulated wall clock (naive local time, like the original datetime.now())."""
        return datetime.fromtimestamp(self._ts, self.tz).replace(tzinfo=None)

    def get_current_minute(self):
        """Get current minute of the hour"""
        return self.now().minute
    
    def get_current_hour(self):
        """Get current hour"""
        return self.now().hour
    
    def is_teams_outage_time(self):
        """Check if we're in a Teams outage window (every full hour for 10 minutes in US)"""
        minute = self.get_current_minute()
        return self.scenario_on("atlanta_teams") and 0 <= minute < 10

    def _is_berlin_window(self):
        minute = self.get_current_minute()
        return (0 <= minute < 15) or (30 <= minute < 45)

    def is_berlin_issue_time(self):
        """Check if Berlin server is having issues (every 30 minutes for 15 minutes)"""
        return self.scenario_on("berlin_db") and self._is_berlin_window()

    def is_berlin_dos_time(self):
        """Berlin Tomcat DoS – same window as the berdb001 chain, but a separate scenario"""
        return self.scenario_on("berlin_dos") and self._is_berlin_window()

    def is_atlanta_network_outage(self):
        """Check if Atlanta is in network outage window (minute 40-45 of every hour)"""
        minute = self.get_current_minute()
        return self.scenario_on("atlanta_network") and 40 <= minute < 45

    def is_atlanta_mes_outage(self):
        """MES Atlanta follows the network outage with a 5-minute lag (minute 45-50)"""
        minute = self.get_current_minute()
        return self.scenario_on("atlanta_network") and 45 <= minute < 50

    def is_vienna_issue_time(self):
        """Check if Vienna is having Teams connectivity issues (minute 20-28 of every hour)"""
        minute = self.get_current_minute()
        return self.scenario_on("vienna_teams") and 20 <= minute < 28
    
    def write_data(self, filename, data):
        """Hand one JSON event to the sink (HEC or modular input)."""
        if self.vienna_isolated() and not isolate_vienna(filename, data):
            return
        self.sink.emit(filename, data, self._ts)

    # ==================== MICROSOFT TEAMS ====================
    def generate_teams_data(self):
        """Generate REALISTIC Microsoft Teams data with diverse event types"""
        last_queue_minute = None
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_outage = self.is_teams_outage_time()
            hour = self.get_current_hour()
            
            # Business hours check (more activity during business hours)
            is_business_hours = 8 <= hour <= 18
            activity_multiplier = 3 if is_business_hours else 1
            
            for location, details in LOCATIONS.items():
                # media path quality (lab scenarios): Berlin WAN brownout, Atlanta internet path
                media_level = {"berlin": self.scenario_level("sdwan_brownout"),
                               "atlanta": self.scenario_level("isp_route_leak")}.get(location, 0.0)
                media_impact = media_level >= IMPACT_LEVEL
                site_down = location == "vienna" and self.vienna_isolated()

                # User presence updates
                if random.random() < 0.3 * activity_multiplier:
                    user = random.choice(USERS)
                    presence_states = ["Available", "Busy", "Away", "BeRightBack", "DoNotDisturb", "Offline"]
                    event = {
                        "timestamp": timestamp,
                        "event_type": "presence_changed",
                        "user_email": user["email"],
                        "user_name": user["name"],
                        "location": location,
                        "previous_state": random.choice(presence_states),
                        "new_state": random.choice(presence_states),
                        "client": random.choice(["Desktop", "Mobile", "Web"]),
                        "service": "microsoft_teams"
                    }
                    self.write_data("msteams.json", event)
                
                # Chat messages
                if random.random() < 0.4 * activity_multiplier:
                    user = random.choice(USERS)
                    chat_types = ["one_on_one", "group_chat", "channel_message"]
                    event = {
                        "timestamp": timestamp,
                        "event_type": "message_sent",
                        "user_email": user["email"],
                        "user_name": user["name"],
                        "location": location,
                        "chat_type": random.choice(chat_types),
                        "message_length": random.randint(10, 500),
                        "has_attachment": random.choice([True, False, False, False]),
                        "has_mention": random.choice([True, False, False]),
                        "client": random.choice(["Desktop", "Mobile", "Web"]),
                        "service": "microsoft_teams"
                    }
                    self.write_data("msteams.json", event)
                
                # File sharing
                if random.random() < 0.2 * activity_multiplier:
                    user = random.choice(USERS)
                    file_types = ["pdf", "docx", "xlsx", "pptx", "jpg", "png"]
                    event = {
                        "timestamp": timestamp,
                        "event_type": "file_shared",
                        "user_email": user["email"],
                        "user_name": user["name"],
                        "location": location,
                        "file_type": random.choice(file_types),
                        "file_size_mb": round(random.uniform(0.1, 50), 2),
                        "shared_with": random.choice(["user", "channel", "team"]),
                        "service": "microsoft_teams"
                    }
                    self.write_data("msteams.json", event)
                
                # Meeting/Call events
                if random.random() < 0.15 * activity_multiplier:
                    user = random.choice(USERS)
                    
                    if (location == "atlanta" and is_outage) or site_down:
                        # Call failures during outage
                        event = {
                            "timestamp": timestamp,
                            "event_type": "call_failed",
                            "user_email": user["email"],
                            "user_name": user["name"],
                            "location": location,
                            "call_type": random.choice(["audio", "video"]),
                            "error_code": random.choice(["408", "480"] if site_down else ["503", "500", "408"]),
                            "error_message": random.choice([
                                "Network unreachable",
                                "Connection timeout",
                                "Media connection failed"
                            ] if site_down else [
                                "Service Unavailable - Teams Backend Issue",
                                "Connection timeout",
                                "Media connection failed"
                            ]),
                            "attempted_participants": random.randint(2, 10),
                            "client": random.choice(["Desktop", "Mobile", "Web"]),
                            "service": "microsoft_teams",
                            "severity": "high"
                        }
                        self.write_data("msteams.json", event)
                        
                        # Meeting join failures
                        event2 = {
                            "timestamp": timestamp,
                            "event_type": "meeting_join_failed",
                            "user_email": user["email"],
                            "user_name": user["name"],
                            "location": location,
                            "meeting_id": f"MTG-{random.randint(100000, 999999)}",
                            "error": "Unable to connect to meeting service",
                            "retry_count": random.randint(1, 5),
                            "service": "microsoft_teams",
                            "severity": "high"
                        }
                        self.write_data("msteams.json", event2)
                    elif media_impact and random.random() < 0.35:
                        event = {
                            "timestamp": timestamp,
                            "event_type": "call_failed",
                            "user_email": user["email"],
                            "user_name": user["name"],
                            "location": location,
                            "call_type": random.choice(["audio", "video"]),
                            "error_code": random.choice(["480", "408", "503"]),
                            "error_message": random.choice([
                                "Media path degraded - high packet loss",
                                "Call dropped - network quality too low",
                                "Connection timeout",
                            ]),
                            "attempted_participants": random.randint(2, 10),
                            "client": random.choice(["Desktop", "Mobile", "Web"]),
                            "service": "microsoft_teams",
                            "severity": "high"
                        }
                        self.write_data("msteams.json", event)
                    else:
                        # Normal call/meeting activity
                        call_event_type = random.choice([
                            "call_started", "call_ended", "meeting_started", 
                            "meeting_ended", "user_joined", "user_left",
                            "screen_share_started", "screen_share_ended",
                            "recording_started", "recording_stopped"
                        ])
                        
                        if call_event_type in ["call_started", "meeting_started"]:
                            call_id = f"CALL-{random.randint(100000, 999999)}"
                            event = {
                                "timestamp": timestamp,
                                "event_type": call_event_type,
                                "call_id": call_id,
                                "organizer_email": user["email"],
                                "organizer_name": user["name"],
                                "location": location,
                                "call_type": random.choice(["audio", "video", "meeting"]),
                                "participant_count": random.randint(2, 15),
                                "scheduled": random.choice([True, False]),
                                "service": "microsoft_teams"
                            }
                            self.write_data("msteams.json", event)
                        
                        elif call_event_type in ["call_ended", "meeting_ended"]:
                            event = {
                                "timestamp": timestamp,
                                "event_type": call_event_type,
                                "call_id": f"CALL-{random.randint(100000, 999999)}",
                                "organizer_email": user["email"],
                                "location": location,
                                "duration_minutes": random.randint(5, 120),
                                "participant_count": random.randint(2, 15),
                                "call_quality": random.choice(["excellent", "good", "good", "fair", "poor"]),
                                "avg_jitter_ms": random.randint(5, 50),
                                "avg_latency_ms": random.randint(20, 150),
                                "packet_loss_pct": round(random.uniform(0, 2), 2),
                                "service": "microsoft_teams"
                            }
                            if media_impact:
                                event.update({
                                    "call_quality": random.choice(["fair", "poor", "poor"]),
                                    "avg_jitter_ms": int(self.ramp(media_level, 30, 90) + random.randint(0, 20)),
                                    "avg_latency_ms": int(self.ramp(media_level, 150, 380) + random.randint(0, 60)),
                                    "packet_loss_pct": round(self.ramp(media_level, 2, 9) + random.uniform(0, 1.5), 2),
                                })
                            self.write_data("msteams.json", event)
                        
                        elif call_event_type == "user_joined":
                            event = {
                                "timestamp": timestamp,
                                "event_type": "user_joined",
                                "call_id": f"CALL-{random.randint(100000, 999999)}",
                                "user_email": user["email"],
                                "user_name": user["name"],
                                "location": location,
                                "join_time_seconds": random.randint(2, 30),
                                "audio_enabled": random.choice([True, False]),
                                "video_enabled": random.choice([True, False, False]),
                                "client": random.choice(["Desktop", "Mobile", "Web"]),
                                "service": "microsoft_teams"
                            }
                            self.write_data("msteams.json", event)
                        
                        elif call_event_type == "screen_share_started":
                            event = {
                                "timestamp": timestamp,
                                "event_type": "screen_share_started",
                                "call_id": f"CALL-{random.randint(100000, 999999)}",
                                "user_email": user["email"],
                                "user_name": user["name"],
                                "location": location,
                                "share_type": random.choice(["full_screen", "window", "application"]),
                                "service": "microsoft_teams"
                            }
                            self.write_data("msteams.json", event)
                
                # Team/Channel operations
                if random.random() < 0.1:
                    user = random.choice(USERS)
                    operations = ["channel_created", "member_added", "member_removed", "team_settings_changed"]
                    event = {
                        "timestamp": timestamp,
                        "event_type": random.choice(operations),
                        "user_email": user["email"],
                        "user_name": user["name"],
                        "location": location,
                        "team_name": f"Team_{user['dept']}",
                        "service": "microsoft_teams"
                    }
                    self.write_data("msteams.json", event)
                
                # Authentication events
                if random.random() < 0.05:
                    user = random.choice(USERS)
                    event = {
                        "timestamp": timestamp,
                        "event_type": random.choice(["login_success", "login_failed", "logout"]),
                        "user_email": user["email"],
                        "user_name": user["name"],
                        "location": location,
                        "client": random.choice(["Desktop", "Mobile", "Web"]),
                        "ip_address": f"{random.randint(10, 192)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
                        "service": "microsoft_teams"
                    }
                    self.write_data("msteams.json", event)

            # Teams call queue of the customer Support Hotline (Vienna), one snapshot per minute.
            # The AI Support Bot hands conversations over to the hotline when it cannot answer.
            minute = int(self.now_ts()) // 60
            if minute != last_queue_minute:
                last_queue_minute = minute
                dc = self.scenario_level("dc_frankfurt")
                busy = 1.0 if is_business_hours else 0.3
                if dc >= IMPACT_LEVEL:
                    handoffs = int(self.ramp(dc, 8, 40) * busy) + random.randint(0, 4)
                    waiting = int(self.ramp(dc, 6, 35) * busy) + random.randint(0, 3)
                    longest = int(self.ramp(dc, 180, 900) * random.uniform(0.85, 1.15))
                    abandoned = int(self.ramp(dc, 2, 12) * busy) + random.randint(0, 2)
                else:
                    handoffs = int(random.randint(0, 3) * busy)
                    waiting = int(random.randint(0, 3) * busy)
                    longest = random.randint(10, 90) if waiting else 0
                    abandoned = random.choice([0] * 9 + [1])
                agents = 8 if is_business_hours else 3
                if self.vienna_isolated():
                    # the hotline agents sit in Vienna: nobody is logged in, callers give up
                    agents = 0
                    waiting = int(30 * busy) + random.randint(0, 8)
                    longest = random.randint(900, 1800)
                    abandoned = int(15 * busy) + random.randint(0, 5)
                self.write_data("msteams.json", {
                    "timestamp": timestamp,
                    "event_type": "call_queue_stats",
                    "queue_name": "Support Hotline",
                    "location": "vienna",
                    "calls_waiting": waiting,
                    "longest_wait_seconds": longest,
                    "calls_abandoned": abandoned,
                    "bot_handoffs": handoffs,
                    "agents_available": max(0, agents - min(agents, waiting)),
                    "agents_logged_in": agents,
                    "service": "microsoft_teams",
                })

            yield 5  # Generate every 5 seconds

    # ==================== THOUSANDEYES ====================
    # Format entspricht ITSI Content Pack for Cisco ThousandEyes (DA-ITSI-CP-thousandeyes v1.0.0)
    # KPI Base Searches lesen per eval folgende Felder aus jedem Event:
    #   thousandeyes.test.type, thousandeyes.test.id, thousandeyes.test.name
    #   Metrikwerte als Literal-Feldnamen "metric_name:<metricname>"
    # Feste Test-IDs damit entity_split_field in ITSI stabil bleibt
    def generate_thousandeyes_data(self):
        """Generate ThousandEyes data in ITSI Content Pack format"""

        # thousandeyes.account.id: feste Account-ID (wird für itsi_entity_id und Drilldown-URL gebraucht)
        # server.address / server.port: Ziel-Endpunkt des Tests (für Entity Import Search)
        ACCOUNT_ID = "demo-account-12345"

        TEST_DEFS = {
            # HTTP + Network Tests: pro Standort eigene ID
            "http_teams": {
                "atlanta": {"id": "TE-HTTP-1001", "name": "Teams Backend HTTP",  "type": "http-server",     "server.address": "teams.microsoft.com",             "server.port": 443},
                "berlin":  {"id": "TE-HTTP-1002", "name": "Teams Backend HTTP",  "type": "http-server",     "server.address": "teams.microsoft.com",             "server.port": 443},
                "vienna":  {"id": "TE-HTTP-1003", "name": "Teams Backend HTTP",  "type": "http-server",     "server.address": "teams.microsoft.com",             "server.port": 443},
            },
            "http_m365": {
                "atlanta": {"id": "TE-HTTP-1004", "name": "M365 Portal HTTP",    "type": "http-server",     "server.address": "portal.office.com",               "server.port": 443},
                "berlin":  {"id": "TE-HTTP-1005", "name": "M365 Portal HTTP",    "type": "http-server",     "server.address": "portal.office.com",               "server.port": 443},
                "vienna":  {"id": "TE-HTTP-1006", "name": "M365 Portal HTTP",    "type": "http-server",     "server.address": "portal.office.com",               "server.port": 443},
            },
            "net_teams": {
                "atlanta": {"id": "TE-NET-2001",  "name": "Teams Media Quality", "type": "agent-to-server", "server.address": "teams-media-relay.microsoft.com", "server.port": 3478},
                "berlin":  {"id": "TE-NET-2002",  "name": "Teams Media Quality", "type": "agent-to-server", "server.address": "teams-media-relay.microsoft.com", "server.port": 3478},
                "vienna":  {"id": "TE-NET-2003",  "name": "Teams Media Quality", "type": "agent-to-server", "server.address": "teams-media-relay.microsoft.com", "server.port": 3478},
            },
            # A2A, DNS, BGP: weiterhin eine ID pro Test
            "a2a_atl_ber": {"id": "TE-A2A-3001",  "name": "DC Atlanta to Berlin", "type": "agent-to-agent", "server.address": "te-agent-berlin-01",              "server.port": 49153},
            "a2a_atl_vie": {"id": "TE-A2A-3002",  "name": "DC Atlanta to Vienna", "type": "agent-to-agent", "server.address": "te-agent-vienna-01",              "server.port": 49153},
            "a2a_ber_vie": {"id": "TE-A2A-3003",  "name": "DC Berlin to Vienna",  "type": "agent-to-agent", "server.address": "te-agent-vienna-02",              "server.port": 49153},
            "a2a_ber_atl": {"id": "TE-A2A-3004",  "name": "DC Berlin to Atlanta", "type": "agent-to-agent", "server.address": "te-agent-atlanta-01",             "server.port": 49153},
            "a2a_vie_atl": {"id": "TE-A2A-3005",  "name": "DC Vienna to Atlanta", "type": "agent-to-agent", "server.address": "te-agent-atlanta-02",             "server.port": 49153},
            "a2a_vie_ber": {"id": "TE-A2A-3006",  "name": "DC Vienna to Berlin",  "type": "agent-to-agent", "server.address": "te-agent-berlin-02",             "server.port": 49153},
            # Paths to the Frankfurt DC (LLM of the AI Support Bot)
            "a2a_atl_fra": {"id": "TE-A2A-3007",  "name": "DC Atlanta to Frankfurt", "type": "agent-to-agent", "server.address": "te-agent-frankfurt-01",       "server.port": 49153},
            "a2a_ber_fra": {"id": "TE-A2A-3008",  "name": "DC Berlin to Frankfurt",  "type": "agent-to-agent", "server.address": "te-agent-frankfurt-01",       "server.port": 49153},
            "a2a_vie_fra": {"id": "TE-A2A-3009",  "name": "DC Vienna to Frankfurt",  "type": "agent-to-agent", "server.address": "te-agent-frankfurt-01",       "server.port": 49153},
            "dns_teams":   {"id": "TE-DNS-4001",  "name": "DNS Resolution Teams", "type": "dns-server",     "server.address": "teams.microsoft.com",             "server.port": 53},
            "bgp_ms":      {"id": "TE-BGP-5001",  "name": "BGP Route Monitoring", "type": "bgp",            "server.address": "52.113.0.1",                      "server.port": 179},
            # ---- CoolaShaker Public Websites: HTTP-Server Tests ----
            "http_csa_www": {
                "atlanta": {"id": "TE-HTTP-2001", "name": "CoolaShaker www HTTP",     "type": "http-server", "server.address": "www.coolashaker.com",     "server.port": 443},
                "berlin":  {"id": "TE-HTTP-2002", "name": "CoolaShaker www HTTP",     "type": "http-server", "server.address": "www.coolashaker.com",     "server.port": 443},
                "vienna":  {"id": "TE-HTTP-2003", "name": "CoolaShaker www HTTP",     "type": "http-server", "server.address": "www.coolashaker.com",     "server.port": 443},
            },
            "http_csa_b2b": {
                "atlanta": {"id": "TE-HTTP-2004", "name": "CoolaShaker B2B HTTP",     "type": "http-server", "server.address": "b2b.coolashaker.com",     "server.port": 443},
                "berlin":  {"id": "TE-HTTP-2005", "name": "CoolaShaker B2B HTTP",     "type": "http-server", "server.address": "b2b.coolashaker.com",     "server.port": 443},
                "vienna":  {"id": "TE-HTTP-2006", "name": "CoolaShaker B2B HTTP",     "type": "http-server", "server.address": "b2b.coolashaker.com",     "server.port": 443},
            },
            "http_csa_support": {
                "atlanta": {"id": "TE-HTTP-2007", "name": "CoolaShaker Support HTTP", "type": "http-server", "server.address": "support.coolashaker.com", "server.port": 443},
                "berlin":  {"id": "TE-HTTP-2008", "name": "CoolaShaker Support HTTP", "type": "http-server", "server.address": "support.coolashaker.com", "server.port": 443},
                "vienna":  {"id": "TE-HTTP-2009", "name": "CoolaShaker Support HTTP", "type": "http-server", "server.address": "support.coolashaker.com", "server.port": 443},
            },
            # ---- CoolaShaker Public Websites: Page-Load Tests ----
            "pageload_csa_www": {
                "atlanta": {"id": "TE-PL-3001", "name": "CoolaShaker www Page Load",  "type": "page-load", "server.address": "www.coolashaker.com",     "server.port": 443},
                "berlin":  {"id": "TE-PL-3002", "name": "CoolaShaker www Page Load",  "type": "page-load", "server.address": "www.coolashaker.com",     "server.port": 443},
                "vienna":  {"id": "TE-PL-3003", "name": "CoolaShaker www Page Load",  "type": "page-load", "server.address": "www.coolashaker.com",     "server.port": 443},
            },
            "pageload_csa_b2b": {
                "atlanta": {"id": "TE-PL-3004", "name": "CoolaShaker B2B Page Load",  "type": "page-load", "server.address": "b2b.coolashaker.com",     "server.port": 443},
                "berlin":  {"id": "TE-PL-3005", "name": "CoolaShaker B2B Page Load",  "type": "page-load", "server.address": "b2b.coolashaker.com",     "server.port": 443},
                "vienna":  {"id": "TE-PL-3006", "name": "CoolaShaker B2B Page Load",  "type": "page-load", "server.address": "b2b.coolashaker.com",     "server.port": 443},
            },
            # ---- Web-Transaction Tests (B2B checkout flow) ----
            "webtx_b2b_order": {
                "atlanta": {"id": "TE-TX-4001", "name": "B2B Order Transaction",      "type": "web-transaction", "server.address": "b2b.coolashaker.com", "server.port": 443},
                "berlin":  {"id": "TE-TX-4002", "name": "B2B Order Transaction",      "type": "web-transaction", "server.address": "b2b.coolashaker.com", "server.port": 443},
                "vienna":  {"id": "TE-TX-4003", "name": "B2B Order Transaction",      "type": "web-transaction", "server.address": "b2b.coolashaker.com", "server.port": 443},
            },
            # ---- Internal Tomcat API Endpoints (Schnittstellen zu Produktionsstrassen) ----
            # 3 interne Tomcat-Server – je einer pro Produktionsstandort
            # Jeder exponiert REST-Endpunkte für seine 3 lokalen Produktionslinien
            # Berlin-Endpoint faellt zur vollen/halben Stunde aus (is_berlin_issue_time),
            # als Folge des berdb001-Problems (Szenario "berlin_db").
            "api_tomcat_atl": {
                "atlanta": {"id": "TE-API-5001", "name": "Prod-API Atlanta Lines",    "type": "api", "server.address": "prod-tomcat.atl.coolashaker.int", "server.port": 8080},
                "berlin":  {"id": "TE-API-5002", "name": "Prod-API Atlanta Lines",    "type": "api", "server.address": "prod-tomcat.atl.coolashaker.int", "server.port": 8080},
                "vienna":  {"id": "TE-API-5003", "name": "Prod-API Atlanta Lines",    "type": "api", "server.address": "prod-tomcat.atl.coolashaker.int", "server.port": 8080},
            },
            "api_tomcat_ber": {
                "atlanta": {"id": "TE-API-5004", "name": "Prod-API Berlin Lines",     "type": "api", "server.address": "prod-tomcat.ber.coolashaker.int", "server.port": 8080},
                "berlin":  {"id": "TE-API-5005", "name": "Prod-API Berlin Lines",     "type": "api", "server.address": "prod-tomcat.ber.coolashaker.int", "server.port": 8080},
                "vienna":  {"id": "TE-API-5006", "name": "Prod-API Berlin Lines",     "type": "api", "server.address": "prod-tomcat.ber.coolashaker.int", "server.port": 8080},
            },
            "api_tomcat_vie": {
                "atlanta": {"id": "TE-API-5007", "name": "Prod-API Vienna Lines",     "type": "api", "server.address": "prod-tomcat.vie.coolashaker.int", "server.port": 8080},
                "berlin":  {"id": "TE-API-5008", "name": "Prod-API Vienna Lines",     "type": "api", "server.address": "prod-tomcat.vie.coolashaker.int", "server.port": 8080},
                "vienna":  {"id": "TE-API-5009", "name": "Prod-API Vienna Lines",     "type": "api", "server.address": "prod-tomcat.vie.coolashaker.int", "server.port": 8080},
            },
            # ---- AI workloads ----
            # Vision inspection inference service on the GPU cluster in the Vienna DC (all plants call it)
            "api_ai_inference": {
                "atlanta": {"id": "TE-API-6001", "name": "AI Vision Inference API",  "type": "api", "server.address": "ai-inference.vie.coolashaker.int", "server.port": 8443},
                "berlin":  {"id": "TE-API-6002", "name": "AI Vision Inference API",  "type": "api", "server.address": "ai-inference.vie.coolashaker.int", "server.port": 8443},
                "vienna":  {"id": "TE-API-6003", "name": "AI Vision Inference API",  "type": "api", "server.address": "ai-inference.vie.coolashaker.int", "server.port": 8443},
            },
            # AI Support Bot (LLM on the Frankfurt GPU cluster) used by the support portal and hotline
            "api_ai_assistant": {
                "atlanta": {"id": "TE-API-6004", "name": "AI Support Assistant API", "type": "api", "server.address": "assistant.coolashaker.com",        "server.port": 443},
                "berlin":  {"id": "TE-API-6005", "name": "AI Support Assistant API", "type": "api", "server.address": "assistant.coolashaker.com",        "server.port": 443},
                "vienna":  {"id": "TE-API-6006", "name": "AI Support Assistant API", "type": "api", "server.address": "assistant.coolashaker.com",        "server.port": 443},
            },
        }
        BGP_PREFIX = "52.112.0.0/14"
        BGP_AS_PATH_OK = "3356 8075"
        BGP_AS_PATH_LEAK = "7018 64512 3356 8075"   # AS64512 = customer of the upstream ISP leaking the prefix

        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_outage = self.is_teams_outage_time()
            is_vienna_issue = self.is_vienna_issue_time()
            wan = self.scenario_level("sdwan_brownout")          # Berlin SD-WAN brownout
            wan_impact = wan >= IMPACT_LEVEL
            leak = self.scenario_level("isp_route_leak")         # Atlanta internet path
            leak_impact = leak >= IMPACT_LEVEL
            dc = self.scenario_level("dc_frankfurt")             # WAN to the Frankfurt DC

            # --- HTTP Server Tests ---
            # KPI "ThousandEyes:KPI:Web":
            #   metric_name:http.server.request.availability  (%)
            #   metric_name:http.client.request.duration      (Sekunden)
            #   metric_name:http.server.throughput            (bytes/s)
            for key in ["http_teams", "http_m365"]:
                for location in LOCATIONS.keys():
                    tdef = TEST_DEFS[key][location]
                    is_degraded = (location == "atlanta" and is_outage and key == "http_teams") or \
                                  (location == "vienna" and is_vienna_issue)
                    if is_degraded:
                        avail      = round(random.uniform(0, 50), 2)
                        resp_sec   = round(random.randint(5000, 15000) / 1000.0, 3)
                        throughput = 0
                    elif location == "atlanta" and leak_impact:
                        avail      = round(random.uniform(92, 97), 2)
                        resp_sec   = round(random.uniform(1.5, 4.0), 3)
                        throughput = random.randint(800000, 2500000)
                    elif location == "berlin" and wan_impact:
                        avail      = round(random.uniform(97, 99.5), 2)
                        resp_sec   = round(random.uniform(0.8, 2.0), 3)
                        throughput = random.randint(2000000, 5000000)
                    else:
                        avail      = round(random.uniform(99, 100), 2)
                        resp_sec   = round(random.randint(100, 500) / 1000.0, 3)
                        throughput = random.randint(5000000, 10000000)

                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "metric_name:http.server.request.availability": avail,
                        "metric_name:http.client.request.duration":     resp_sec,
                        "metric_name:http.server.throughput":           throughput,
                    }
                    self.write_data("thousandeyes.json", event)

            # --- Network Tests agent-to-server (Teams Media) ---
            # KPI "ThousandEyes:KPI:Network":
            #   metric_name:network.latency  (Sekunden)
            #   metric_name:network.loss     (%)
            #   metric_name:network.jitter   (ms)
            tdef_net = TEST_DEFS["net_teams"]
            for location in LOCATIONS.keys():
                tdef = tdef_net[location]
                is_degraded = (location == "atlanta" and is_outage) or \
                              (location == "vienna" and is_vienna_issue)
                if is_degraded:
                    latency_sec = round(random.randint(500, 2000) / 1000.0, 3)
                    loss        = round(random.uniform(10, 30), 2)
                    jitter      = random.randint(50, 200)
                elif location == "berlin" and wan:
                    latency_sec = round(self.ramp(wan, 0.06, 0.24) + random.uniform(0, 0.04), 3)
                    loss        = round(self.ramp(wan, 0.5, 7) + random.uniform(0, 1.5), 2)
                    jitter      = int(self.ramp(wan, 10, 45) + random.randint(0, 10))
                elif location == "atlanta" and leak:
                    latency_sec = round(self.ramp(leak, 0.08, 0.26) + random.uniform(0, 0.04), 3)
                    loss        = round(self.ramp(leak, 0.3, 4) + random.uniform(0, 1), 2)
                    jitter      = int(self.ramp(leak, 8, 30) + random.randint(0, 8))
                else:
                    latency_sec = round(random.randint(20, 80) / 1000.0, 3)
                    loss        = round(random.uniform(0, 0.5), 2)
                    jitter      = random.randint(1, 15)

                event = {
                    "timestamp": timestamp,
                    "thousandeyes.test.type":      tdef["type"],
                    "thousandeyes.test.id":        tdef["id"],
                    "thousandeyes.test.name":      tdef["name"],
                    "thousandeyes.account.id":     ACCOUNT_ID,
                    "thousandeyes.agent.name":     f"te-agent-{location}-01",
                    "thousandeyes.agent.location": location,
                    "server.address":              tdef["server.address"],
                    "server.port":                 tdef["server.port"],
                    "metric_name:network.latency": latency_sec,
                    "metric_name:network.loss":    loss,
                    "metric_name:network.jitter":  jitter,
                }
                self.write_data("thousandeyes.json", event)

            # --- Agent-to-Agent Tests (DC connections over SD-WAN) ---
            # Berlin SD-WAN brownout: every path from/to Berlin shows loss, latency and jitter first.
            for key, src, tgt in [("a2a_atl_ber", "atlanta", "berlin"),
                                   ("a2a_atl_vie", "atlanta", "vienna"),
                                   ("a2a_ber_vie", "berlin",  "vienna"),
                                   ("a2a_ber_atl", "berlin",  "atlanta"),
                                   ("a2a_vie_atl", "vienna",  "atlanta"),
                                   ("a2a_vie_ber", "vienna",  "berlin"),
                                   ("a2a_atl_fra", "atlanta", "frankfurt"),
                                   ("a2a_ber_fra", "berlin",  "frankfurt"),
                                   ("a2a_vie_fra", "vienna",  "frankfurt")]:
                tdef = TEST_DEFS[key]
                transatlantic = "atlanta" in (src, tgt)
                base_latency = random.randint(95, 125) if transatlantic else random.randint(12, 22)
                latency_sec = base_latency / 1000.0
                loss = round(random.choice([0.0] * 8 + [round(random.uniform(0.1, 0.4), 2)] * 2), 2)
                jitter = random.randint(1, 5)
                if wan and "berlin" in (src, tgt):
                    latency_sec += self.ramp(wan, 0.03, 0.17) + random.uniform(0, 0.03)
                    loss = round(self.ramp(wan, 0.8, 6.5) + random.uniform(0, 1.5), 2)
                    jitter = int(self.ramp(wan, 8, 40) + random.randint(0, 8))
                if dc and tgt == "frankfurt":
                    latency_sec += self.ramp(dc, 0.05, 0.28) + random.uniform(0, 0.04)
                    loss = round(max(loss, self.ramp(dc, 1.5, 9) + random.uniform(0, 1.5)), 2)
                    jitter = max(jitter, int(self.ramp(dc, 10, 45) + random.randint(0, 10)))
                event = {
                    "timestamp": timestamp,
                    "thousandeyes.test.type":             tdef["type"],
                    "thousandeyes.test.id":               tdef["id"],
                    "thousandeyes.test.name":             tdef["name"],
                    "thousandeyes.account.id":            ACCOUNT_ID,
                    "thousandeyes.agent.name":            f"te-agent-{src}-01",
                    "thousandeyes.agent.location":        src,
                    "thousandeyes.target.agent.location": tgt,
                    "server.address":                     tdef["server.address"],
                    "server.port":                        tdef["server.port"],
                    "metric_name:network.latency": round(latency_sec, 3),
                    "metric_name:network.loss":    loss,
                    "metric_name:network.jitter":  jitter,
                }
                self.write_data("thousandeyes.json", event)

            # --- DNS Tests (dns-server) ---
            # KPI "ThousandEyes:KPI:DNS":
            #   metric_name:dns.lookup.availability  (%)
            #   metric_name:dns.lookup.duration      (Sekunden)
            tdef = TEST_DEFS["dns_teams"]
            for location in LOCATIONS.keys():
                dns_avail = 100.0
                dns_duration = random.randint(10, 100) / 1000.0
                if location == "atlanta" and leak:
                    dns_duration = self.ramp(leak, 0.12, 0.7) + random.uniform(0, 0.1)
                    if leak_impact:
                        dns_avail = round(random.uniform(90, 98), 2)
                event = {
                    "timestamp": timestamp,
                    "thousandeyes.test.type":      tdef["type"],
                    "thousandeyes.test.id":        tdef["id"],
                    "thousandeyes.test.name":      tdef["name"],
                    "thousandeyes.account.id":     ACCOUNT_ID,
                    "thousandeyes.agent.name":     f"te-agent-{location}-01",
                    "thousandeyes.agent.location": location,
                    "server.address":              tdef["server.address"],
                    "server.port":                 tdef["server.port"],
                    "metric_name:dns.lookup.availability": dns_avail,
                    "metric_name:dns.lookup.duration":     round(dns_duration, 3),
                }
                self.write_data("thousandeyes.json", event)

            # --- BGP Routing Tests ---
            # KPI "ThousandEyes:KPI:Routing":
            #   metric_name:bgp.reachability        (%)
            #   metric_name:bgp.updates.count
            #   metric_name:bgp.path_changes.count
            # Atlanta route leak: the agent reports every round with growing churn and lost reachability.
            report_bgp = random.random() < 0.3
            if report_bgp or leak:
                tdef = TEST_DEFS["bgp_ms"]
                for location in LOCATIONS.keys():
                    leaking = location == "atlanta" and leak
                    if not (report_bgp or leaking):
                        continue
                    if leaking:
                        reach = round(self.ramp(leak, 98, 62) + random.uniform(-3, 3), 2)
                        updates = int(self.ramp(leak, 15, 80) + random.randint(0, 15))
                        path_changes = int(self.ramp(leak, 4, 28) + random.randint(0, 5))
                        as_path = BGP_AS_PATH_LEAK
                    else:
                        reach = 100.0
                        updates = random.randint(0, 5)
                        path_changes = random.randint(0, 2)
                        as_path = BGP_AS_PATH_OK
                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "bgp.prefix":                  BGP_PREFIX,
                        "bgp.as_path":                 as_path,
                        "metric_name:bgp.reachability":       min(100.0, reach),
                        "metric_name:bgp.updates.count":      updates,
                        "metric_name:bgp.path_changes.count": path_changes,
                    }
                    self.write_data("thousandeyes.json", event)

            # --- HTTP-Server Tests: CoolaShaker Public Websites ---
            # KPI ThousandEyes:KPI:Web – gleiche Metriken wie Teams/M365
            for key in ["http_csa_www", "http_csa_b2b", "http_csa_support"]:
                for location in LOCATIONS.keys():
                    tdef = TEST_DEFS[key][location]
                    if location == "atlanta" and leak_impact:
                        avail, duration = round(random.uniform(94, 99), 2), random.uniform(1.2, 3.5)
                        throughput = random.randint(1500000, 4000000)
                    else:
                        avail, duration = round(random.uniform(99.5, 100), 2), random.randint(80, 350) / 1000.0
                        throughput = random.randint(8000000, 16000000)
                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "metric_name:http.server.request.availability": avail,
                        "metric_name:http.client.request.duration":     round(duration, 3),
                        "metric_name:http.server.throughput":           throughput,
                    }
                    self.write_data("thousandeyes.json", event)

            # --- Page-Load Tests: CoolaShaker Websites ---
            # KPI ThousandEyes:KPI:Web – Metriken: web.page_load.duration, web.page_load.completion
            for key in ["pageload_csa_www", "pageload_csa_b2b"]:
                for location in LOCATIONS.keys():
                    tdef = TEST_DEFS[key][location]
                    if location == "atlanta" and leak_impact:
                        duration, completion = random.uniform(4.5, 9.5), random.uniform(80, 95)
                    else:
                        duration, completion = random.randint(900, 2800) / 1000.0, random.uniform(98.5, 100)
                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "metric_name:web.page_load.duration":    round(duration, 3),
                        "metric_name:web.page_load.completion":  round(completion, 2),
                    }
                    self.write_data("thousandeyes.json", event)

            # --- Web-Transaction Tests: B2B Order-Flow ---
            # KPI ThousandEyes:KPI:Web – Metriken: web.transaction.duration/errors.count/completion
            for key in ["webtx_b2b_order"]:
                for location in LOCATIONS.keys():
                    tdef = TEST_DEFS[key][location]
                    duration = random.randint(2500, 9000) / 1000.0
                    errors, completion = 0, 100.0
                    if location == "atlanta" and leak_impact:
                        duration = random.uniform(12, 25)
                        errors = random.randint(1, 3)
                        completion = round(random.uniform(40, 75), 2)
                    elif random.random() < 0.01:              # occasional single failed step
                        errors, completion = 1, 80.0
                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "metric_name:web.transaction.duration":      round(duration, 3),
                        "metric_name:web.transaction.errors.count":  errors,
                        "metric_name:web.transaction.completion":    completion,
                    }
                    self.write_data("thousandeyes.json", event)

            # --- API Tests: Interne Tomcat-Produktions-Endpunkte ---
            # KPI ThousandEyes:KPI:Web – Metriken: api.duration, api.completion
            # HINWEIS: Berlin-Endpoint faellt zur vollen/halben Stunde aus (is_berlin_issue_time,
            # Szenario "berlin_db" – Schnittstelle zu den Berliner Produktionslinien).
            is_berlin_api_outage = self.is_berlin_issue_time()
            for key in ["api_tomcat_atl", "api_tomcat_ber", "api_tomcat_vie",
                        "api_ai_inference", "api_ai_assistant"]:
                for location in LOCATIONS.keys():
                    tdef = TEST_DEFS[key][location]
                    is_api_degraded = (key == "api_tomcat_ber" and is_berlin_api_outage)
                    # Tomcat endpoints across the WAN from/to Berlin
                    over_berlin_wan = key.startswith("api_tomcat") and wan_impact and \
                        ((key == "api_tomcat_ber") != (location == "berlin"))
                    if is_api_degraded:
                        api_duration    = round(random.randint(8000, 30000) / 1000.0, 3)
                        api_completion  = round(random.uniform(0, 25), 2)
                    elif key == "api_ai_inference":
                        api_duration    = random.uniform(0.08, 0.25)
                        api_completion  = 100.0
                        if location == "berlin" and wan_impact:
                            api_duration += random.uniform(1.0, 3.0)
                            api_completion = min(api_completion, round(random.uniform(88, 97), 2))
                    elif key == "api_ai_assistant":
                        api_duration    = random.uniform(0.6, 1.4)
                        api_completion  = 100.0
                        if location == "atlanta" and leak_impact:
                            api_duration   = random.uniform(4, 12)
                            api_completion = round(random.uniform(60, 90), 2)
                        if dc:
                            # retransmits on the Frankfurt path + retried prompts queueing on the GPUs
                            api_duration   = max(api_duration, self.ramp(dc, 2.5, 16) + random.uniform(0, 3))
                            api_completion = min(api_completion, round(self.ramp(dc, 97, 55) + random.uniform(-5, 5), 2))
                    elif over_berlin_wan:
                        api_duration    = random.uniform(1.5, 5.0)
                        api_completion  = round(random.uniform(85, 97), 2)
                    else:
                        api_duration    = round(random.randint(40, 450) / 1000.0, 3)
                        api_completion  = 100.0
                    api_duration = round(api_duration, 3)
                    event = {
                        "timestamp": timestamp,
                        "thousandeyes.test.type":      tdef["type"],
                        "thousandeyes.test.id":        tdef["id"],
                        "thousandeyes.test.name":      tdef["name"],
                        "thousandeyes.account.id":     ACCOUNT_ID,
                        "thousandeyes.agent.name":     f"te-agent-{location}-01",
                        "thousandeyes.agent.location": location,
                        "server.address":              tdef["server.address"],
                        "server.port":                 tdef["server.port"],
                        "metric_name:api.duration":    api_duration,
                        "metric_name:api.completion":  api_completion,
                    }
                    self.write_data("thousandeyes.json", event)

            yield 30  # Generate every 30 seconds

    # ==================== CISCO CATALYST CENTER ====================
    # Format: sourcetype="cisco:dnac:devicehealth"
    # KPI Base Searches erwarten:
    #   Location (= site_name, entity_split_field)
    #   HealthScore (1-10, threshold_field)
    #   DeviceRole: CORE / DISTRIBUTION / ACCESS
    #   DeviceFamily: "Switches and Hubs" / "Routers" / "Wireless Controller" / "Unified AP"
    #   Reachability: "Reachable" / "Unreachable"
    #   MemoryUtilization (%), DeviceName
    # Entity Import Search braucht zusätzlich:
    #   sourcetype="cisco:dnac:site:topology", type IN ("building","floor"),
    #   cisco_catalyst_host, nameHierarchy, id, floorNumber usw.
    # Outage Atlanta: Minute 40-45 → HealthScore sinkt, Reachability degradiert
    def generate_catalyst_center_data(self):
        """Generate Cisco Catalyst Center device health data for ITSI Content Pack"""

        # Feste Geräte pro Standort - DeviceName stabil für Entity-Matching
        DEVICES = {
            "atlanta": [
                {"DeviceName": "atl-core-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.10.1.1", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:1A:2B:3C:4D:01", "DeviceID": "DEV-ATL-C9500-01", "Manageability": "Manageable", "Uptime": 7862400},
                {"DeviceName": "atl-core-sw-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.10.1.2", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:1A:2B:3C:4D:02", "DeviceID": "DEV-ATL-C9500-02", "Manageability": "Manageable", "Uptime": 6912000},
                {"DeviceName": "atl-dist-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.10.2.1", "DeviceSeries": "Cisco Catalyst 9300 Series",     "MACAddress": "00:1A:2B:3C:4D:03", "DeviceID": "DEV-ATL-C9300-01", "Manageability": "Manageable", "Uptime": 5184000},
                {"DeviceName": "atl-dist-sw-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.10.2.2", "DeviceSeries": "Cisco Catalyst 9300 Series",     "MACAddress": "00:1A:2B:3C:4D:04", "DeviceID": "DEV-ATL-C9300-02", "Manageability": "Manageable", "Uptime": 4320000},
                {"DeviceName": "atl-acc-sw-01",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.10.3.1", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:1A:2B:3C:4D:05", "DeviceID": "DEV-ATL-C9200-01", "Manageability": "Manageable", "Uptime": 2592000},
                {"DeviceName": "atl-acc-sw-02",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.10.3.2", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:1A:2B:3C:4D:06", "DeviceID": "DEV-ATL-C9200-02", "Manageability": "Manageable", "Uptime": 1728000},
                {"DeviceName": "atl-acc-sw-03",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.10.3.3", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:1A:2B:3C:4D:07", "DeviceID": "DEV-ATL-C9200-03", "Manageability": "Manageable", "Uptime": 864000},
                {"DeviceName": "atl-router-01",   "DeviceFamily": "Routers",            "DeviceRole": "CORE",         "IpAddress": "10.10.0.1", "DeviceSeries": "Cisco ASR 1000 Series",          "MACAddress": "00:1A:2B:3C:4D:08", "DeviceID": "DEV-ATL-ASR1K-01", "Manageability": "Manageable", "Uptime": 15552000},
                {"DeviceName": "atl-router-02",   "DeviceFamily": "Routers",            "DeviceRole": "CORE",         "IpAddress": "10.10.0.2", "DeviceSeries": "Cisco ASR 1000 Series",          "MACAddress": "00:1A:2B:3C:4D:09", "DeviceID": "DEV-ATL-ASR1K-02", "Manageability": "Manageable", "Uptime": 12960000},
                {"DeviceName": "atl-wlc-01",      "DeviceFamily": "Wireless Controller","DeviceRole": "ACCESS",       "IpAddress": "10.10.4.1", "DeviceSeries": "Cisco Catalyst 9800 Series",     "MACAddress": "00:1A:2B:3C:4D:0A", "DeviceID": "DEV-ATL-C9800-01", "Manageability": "Manageable", "Uptime": 3456000},
                {"DeviceName": "atl-ap-01",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.10.5.1", "DeviceSeries": "Cisco Catalyst 9120 Series",     "MACAddress": "00:1A:2B:3C:4D:0B", "DeviceID": "DEV-ATL-AP9120-01","Manageability": "Manageable", "Uptime": 1296000},
                {"DeviceName": "atl-ap-02",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.10.5.2", "DeviceSeries": "Cisco Catalyst 9120 Series",     "MACAddress": "00:1A:2B:3C:4D:0C", "DeviceID": "DEV-ATL-AP9120-02","Manageability": "Manageable", "Uptime": 1209600},
                {"DeviceName": "atl-ap-03",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.10.5.3", "DeviceSeries": "Cisco Catalyst 9120 Series",     "MACAddress": "00:1A:2B:3C:4D:0D", "DeviceID": "DEV-ATL-AP9120-03","Manageability": "Manageable", "Uptime": 1036800},
            ],
            "berlin": [
                {"DeviceName": "ber-core-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.20.1.1", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:2B:3C:4D:5E:01", "DeviceID": "DEV-BER-C9500-01", "Manageability": "Manageable", "Uptime": 9331200},
                {"DeviceName": "ber-core-sw-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.20.1.2", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:2B:3C:4D:5E:02", "DeviceID": "DEV-BER-C9500-02", "Manageability": "Manageable", "Uptime": 8294400},
                {"DeviceName": "ber-dist-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.20.2.1", "DeviceSeries": "Cisco Catalyst 9300 Series",     "MACAddress": "00:2B:3C:4D:5E:03", "DeviceID": "DEV-BER-C9300-01", "Manageability": "Manageable", "Uptime": 6048000},
                {"DeviceName": "ber-dist-sw-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.20.2.2", "DeviceSeries": "Cisco Catalyst 9300 Series",     "MACAddress": "00:2B:3C:4D:5E:04", "DeviceID": "DEV-BER-C9300-02", "Manageability": "Manageable", "Uptime": 5616000},
                {"DeviceName": "ber-acc-sw-01",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.20.3.1", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:2B:3C:4D:5E:05", "DeviceID": "DEV-BER-C9200-01", "Manageability": "Manageable", "Uptime": 3024000},
                {"DeviceName": "ber-acc-sw-02",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.20.3.2", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:2B:3C:4D:5E:06", "DeviceID": "DEV-BER-C9200-02", "Manageability": "Manageable", "Uptime": 2160000},
                {"DeviceName": "ber-router-01",   "DeviceFamily": "Routers",            "DeviceRole": "CORE",         "IpAddress": "10.20.0.1", "DeviceSeries": "Cisco ASR 1000 Series",          "MACAddress": "00:2B:3C:4D:5E:07", "DeviceID": "DEV-BER-ASR1K-01", "Manageability": "Manageable", "Uptime": 18144000},
                {"DeviceName": "ber-wlc-01",      "DeviceFamily": "Wireless Controller","DeviceRole": "ACCESS",       "IpAddress": "10.20.4.1", "DeviceSeries": "Cisco Catalyst 9800 Series",     "MACAddress": "00:2B:3C:4D:5E:08", "DeviceID": "DEV-BER-C9800-01", "Manageability": "Manageable", "Uptime": 4147200},
                {"DeviceName": "ber-ap-01",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.20.5.1", "DeviceSeries": "Cisco Catalyst 9130 Series",     "MACAddress": "00:2B:3C:4D:5E:09", "DeviceID": "DEV-BER-AP9130-01","Manageability": "Manageable", "Uptime": 1555200},
                {"DeviceName": "ber-ap-02",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.20.5.2", "DeviceSeries": "Cisco Catalyst 9130 Series",     "MACAddress": "00:2B:3C:4D:5E:0A", "DeviceID": "DEV-BER-AP9130-02","Manageability": "Manageable", "Uptime": 1468800},
            ],
            "vienna": [
                {"DeviceName": "vie-core-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.30.1.1", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:3C:4D:5E:6F:01", "DeviceID": "DEV-VIE-C9500-01", "Manageability": "Manageable", "Uptime": 11232000},
                {"DeviceName": "vie-core-sw-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.30.1.2", "DeviceSeries": "Cisco Catalyst 9500 Series",     "MACAddress": "00:3C:4D:5E:6F:02", "DeviceID": "DEV-VIE-C9500-02", "Manageability": "Manageable", "Uptime": 10368000},
                {"DeviceName": "vie-dist-sw-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.30.2.1", "DeviceSeries": "Cisco Catalyst 9300 Series",     "MACAddress": "00:3C:4D:5E:6F:03", "DeviceID": "DEV-VIE-C9300-01", "Manageability": "Manageable", "Uptime": 7344000},
                {"DeviceName": "vie-acc-sw-01",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.30.3.1", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:3C:4D:5E:6F:04", "DeviceID": "DEV-VIE-C9200-01", "Manageability": "Manageable", "Uptime": 3888000},
                {"DeviceName": "vie-acc-sw-02",   "DeviceFamily": "Switches and Hubs",  "DeviceRole": "ACCESS",       "IpAddress": "10.30.3.2", "DeviceSeries": "Cisco Catalyst 9200 Series",     "MACAddress": "00:3C:4D:5E:6F:05", "DeviceID": "DEV-VIE-C9200-02", "Manageability": "Manageable", "Uptime": 3024000},
                {"DeviceName": "vie-router-01",   "DeviceFamily": "Routers",            "DeviceRole": "CORE",         "IpAddress": "10.30.0.1", "DeviceSeries": "Cisco ASR 1000 Series",          "MACAddress": "00:3C:4D:5E:6F:06", "DeviceID": "DEV-VIE-ASR1K-01", "Manageability": "Manageable", "Uptime": 20736000},
                {"DeviceName": "vie-wlc-01",      "DeviceFamily": "Wireless Controller","DeviceRole": "ACCESS",       "IpAddress": "10.30.4.1", "DeviceSeries": "Cisco Catalyst 9800 Series",     "MACAddress": "00:3C:4D:5E:6F:07", "DeviceID": "DEV-VIE-C9800-01", "Manageability": "Manageable", "Uptime": 5616000},
                {"DeviceName": "vie-ap-01",       "DeviceFamily": "Unified AP",         "DeviceRole": "ACCESS",       "IpAddress": "10.30.5.1", "DeviceSeries": "Cisco Catalyst 9130 Series",     "MACAddress": "00:3C:4D:5E:6F:08", "DeviceID": "DEV-VIE-AP9130-01","Manageability": "Manageable", "Uptime": 1814400},
                # AI fabric in the Vienna DC (lossless RoCEv2 for the GPU cluster)
                {"DeviceName": "vie-ai-spine-01", "DeviceFamily": "Switches and Hubs",  "DeviceRole": "CORE",         "IpAddress": "10.30.8.1", "DeviceSeries": "Cisco Catalyst 9500X Series",    "MACAddress": "00:3C:4D:5E:6F:21", "DeviceID": "DEV-VIE-C9500X-01","Manageability": "Manageable", "Uptime": 4406400, "Fabric": "ai-fabric"},
                {"DeviceName": "vie-ai-leaf-01",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.30.8.11","DeviceSeries": "Cisco Catalyst 9500X Series",    "MACAddress": "00:3C:4D:5E:6F:22", "DeviceID": "DEV-VIE-C9500X-11","Manageability": "Manageable", "Uptime": 4320000, "Fabric": "ai-fabric"},
                {"DeviceName": "vie-ai-leaf-02",  "DeviceFamily": "Switches and Hubs",  "DeviceRole": "DISTRIBUTION", "IpAddress": "10.30.8.12","DeviceSeries": "Cisco Catalyst 9500X Series",    "MACAddress": "00:3C:4D:5E:6F:23", "DeviceID": "DEV-VIE-C9500X-12","Manageability": "Manageable", "Uptime": 4233600, "Fabric": "ai-fabric"},
            ],
        }

        # Standort-Namen exakt wie in der Entity Import Search erwartet (nameHierarchy)
        SITE_NAMES = {
            "atlanta": "Global/North America/USA/Atlanta",
            "berlin":  "Global/Europe/Germany/Berlin",
            "vienna":  "Global/Europe/Austria/Vienna",
        }

        DNAC_HOST = "https://catalyst-center.coolashaker.com"

        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_atl_outage = self.is_atlanta_network_outage()

            for location, devices in DEVICES.items():
                site_name = SITE_NAMES[location]
                is_outage = (location == "atlanta" and is_atl_outage)
                vie_down = location == "vienna" and self.vienna_isolated()

                for dev in devices:
                    # HealthScore: 1-10 (10 = perfekt, <4 = critical für ITSI)
                    # Bei Outage: ACCESS und DISTRIBUTION in Atlanta stark degradiert
                    # CORE etwas weniger, um kaskadierende Auswirkung zu zeigen
                    if vie_down and dev.get("Fabric") != "ai-fabric":
                        health = 1
                        reachability = "Unreachable"
                        mem_util = random.uniform(20, 55)
                    elif is_outage:
                        if dev["DeviceRole"] in ("ACCESS",):
                            health = random.randint(1, 3)
                            reachability = random.choice(["Unreachable", "Unreachable", "Reachable"])
                            mem_util = random.uniform(85, 99)
                        elif dev["DeviceRole"] == "DISTRIBUTION":
                            health = random.randint(2, 5)
                            reachability = random.choice(["Reachable", "Unreachable"])
                            mem_util = random.uniform(75, 90)
                        else:  # CORE / Router
                            health = random.randint(4, 7)
                            reachability = "Reachable"
                            mem_util = random.uniform(60, 80)
                    else:
                        health = random.randint(8, 10)
                        reachability = "Reachable"
                        mem_util = random.uniform(20, 55)

                    # AI fabric of the Vienna GPU cluster: interface/queue telemetry
                    fabric_fields = {}
                    if dev.get("Fabric") == "ai-fabric":
                        fabric_fields = {
                            "InterfaceUtilization": round(random.uniform(25, 45), 1),
                            "OutputDrops":          random.randint(0, 20),
                            "PfcPauseFrames":       random.randint(0, 50),
                            "EcnMarkedPackets":     random.randint(0, 200),
                            "BufferUtilization":    round(random.uniform(10, 30), 1),
                        }

                    # Uptime: stabile Basis + 60s Inkrement pro Poll-Zyklus
                    # Bei Outage und Unreachable → Uptime reset (Reboot-Simulation)
                    base_uptime = dev["Uptime"]
                    uptime_increment = int(self.now_ts()) % 86400  # täglich rollierendes Inkrement
                    if reachability == "Unreachable":
                        current_uptime = random.randint(0, 300)   # frisch gebooted / unbekannt
                    else:
                        current_uptime = base_uptime + uptime_increment

                    event = {
                        "timestamp":         timestamp,
                        "sourcetype":        "cisco:dnac:devicehealth",
                        "cisco_catalyst_host": DNAC_HOST,
                        "DeviceName":        dev["DeviceName"],
                        "DeviceID":          dev["DeviceID"],
                        "DeviceFamily":      dev["DeviceFamily"],
                        "DeviceSeries":      dev["DeviceSeries"],
                        "DeviceRole":        dev["DeviceRole"],
                        "IpAddress":         dev["IpAddress"],
                        "MACAddress":        dev["MACAddress"],
                        "Location":          site_name,
                        "HealthScore":       health,
                        "Reachability":      reachability,
                        "Manageability":     "Unmanageable" if reachability == "Unreachable" else dev["Manageability"],
                        "MemoryUtilization": round(mem_util, 1),
                        "CpuUtilization":    round(random.uniform(5, 40) if not is_outage else random.uniform(60, 95), 1),
                        "OverallHealth":     health,
                        "Uptime":            current_uptime,
                        "site_name":         site_name,
                        "Fabric":            dev.get("Fabric", "campus"),
                    }
                    event.update(fabric_fields)
                    self.write_data("catalyst_center.json", event)

                # Site Topology Event (für Entity Import Search)
                # sourcetype="cisco:dnac:site:topology", type IN ("building","floor")
                topo = {
                    "timestamp":            timestamp,
                    "sourcetype":           "cisco:dnac:site:topology",
                    "cisco_catalyst_host":  DNAC_HOST,
                    "nameHierarchy":        site_name,
                    "id":                   f"site-{location}-001",
                    "type":                 "building",
                    "address":              {
                        "atlanta": "1 Peachtree St NE, Atlanta, GA 30303",
                        "berlin":  "Unter den Linden 1, 10117 Berlin",
                        "vienna":  "Rathausplatz 1, 1010 Vienna",
                    }[location],
                    "country":              LOCATIONS[location]["country"],
                    "latitude":             {"atlanta": 33.749, "berlin": 52.520, "vienna": 48.208}[location],
                    "longitude":            {"atlanta": -84.388, "berlin": 13.405, "vienna": 16.373}[location],
                }
                self.write_data("catalyst_center.json", topo)

            yield 60  # Catalyst Center pollt typischerweise jede Minute

    # ==================== CISCO DNA CENTER / CATALYST CENTER - SECURITY ADVISORIES ====================
    # sourcetype="cisco:dnac:securityadvisory"
    # Felder: advisoryId, advisorySeverity (CRITICAL/HIGH/MEDIUM/LOW), cveId, cvssScore,
    #         DeviceName, DeviceID, DeviceFamily, DeviceSeries, IpAddress, Location,
    #         affectedSoftwareRelease, fixedSoftwareRelease, publicationDate,
    #         status (active/patched/under_review), description, workaround, url
    # Strategie: Jedes Gerät hat 1-3 "sticky" Advisories die über Zeit bestehen bleiben.
    #            Gelegentlich wird ein Advisory als "patched" markiert, ein neues taucht auf.
    def generate_securityadvisory_data(self):
        """Generate Cisco DNA Center Security Advisory data"""

        DNAC_HOST = "https://catalyst-center.coolashaker.com"

        # Alle Geräte flach als Liste (DeviceName → statische Felder)
        ALL_DEVICES = [
            # Atlanta
            {"DeviceName": "atl-core-sw-01",  "DeviceID": "DEV-ATL-C9500-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.10.1.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-core-sw-02",  "DeviceID": "DEV-ATL-C9500-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.10.1.2", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-dist-sw-01",  "DeviceID": "DEV-ATL-C9300-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9300 Series",  "IpAddress": "10.10.2.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-dist-sw-02",  "DeviceID": "DEV-ATL-C9300-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9300 Series",  "IpAddress": "10.10.2.2", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-acc-sw-01",   "DeviceID": "DEV-ATL-C9200-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.10.3.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-acc-sw-02",   "DeviceID": "DEV-ATL-C9200-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.10.3.2", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-acc-sw-03",   "DeviceID": "DEV-ATL-C9200-03", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.10.3.3", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-router-01",   "DeviceID": "DEV-ATL-ASR1K-01", "DeviceFamily": "Routers",             "DeviceSeries": "Cisco ASR 1000 Series",       "IpAddress": "10.10.0.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-router-02",   "DeviceID": "DEV-ATL-ASR1K-02", "DeviceFamily": "Routers",             "DeviceSeries": "Cisco ASR 1000 Series",       "IpAddress": "10.10.0.2", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-wlc-01",      "DeviceID": "DEV-ATL-C9800-01", "DeviceFamily": "Wireless Controller", "DeviceSeries": "Cisco Catalyst 9800 Series",  "IpAddress": "10.10.4.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-ap-01",       "DeviceID": "DEV-ATL-AP9120-01","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9120 Series",  "IpAddress": "10.10.5.1", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-ap-02",       "DeviceID": "DEV-ATL-AP9120-02","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9120 Series",  "IpAddress": "10.10.5.2", "Location": "Global/North America/USA/Atlanta"},
            {"DeviceName": "atl-ap-03",       "DeviceID": "DEV-ATL-AP9120-03","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9120 Series",  "IpAddress": "10.10.5.3", "Location": "Global/North America/USA/Atlanta"},
            # Berlin
            {"DeviceName": "ber-core-sw-01",  "DeviceID": "DEV-BER-C9500-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.20.1.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-core-sw-02",  "DeviceID": "DEV-BER-C9500-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.20.1.2", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-dist-sw-01",  "DeviceID": "DEV-BER-C9300-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9300 Series",  "IpAddress": "10.20.2.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-dist-sw-02",  "DeviceID": "DEV-BER-C9300-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9300 Series",  "IpAddress": "10.20.2.2", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-acc-sw-01",   "DeviceID": "DEV-BER-C9200-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.20.3.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-acc-sw-02",   "DeviceID": "DEV-BER-C9200-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.20.3.2", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-router-01",   "DeviceID": "DEV-BER-ASR1K-01", "DeviceFamily": "Routers",             "DeviceSeries": "Cisco ASR 1000 Series",       "IpAddress": "10.20.0.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-wlc-01",      "DeviceID": "DEV-BER-C9800-01", "DeviceFamily": "Wireless Controller", "DeviceSeries": "Cisco Catalyst 9800 Series",  "IpAddress": "10.20.4.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-ap-01",       "DeviceID": "DEV-BER-AP9130-01","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9130 Series",  "IpAddress": "10.20.5.1", "Location": "Global/Europe/Germany/Berlin"},
            {"DeviceName": "ber-ap-02",       "DeviceID": "DEV-BER-AP9130-02","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9130 Series",  "IpAddress": "10.20.5.2", "Location": "Global/Europe/Germany/Berlin"},
            # Vienna
            {"DeviceName": "vie-core-sw-01",  "DeviceID": "DEV-VIE-C9500-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.30.1.1", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-core-sw-02",  "DeviceID": "DEV-VIE-C9500-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9500 Series",  "IpAddress": "10.30.1.2", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-dist-sw-01",  "DeviceID": "DEV-VIE-C9300-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9300 Series",  "IpAddress": "10.30.2.1", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-acc-sw-01",   "DeviceID": "DEV-VIE-C9200-01", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.30.3.1", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-acc-sw-02",   "DeviceID": "DEV-VIE-C9200-02", "DeviceFamily": "Switches and Hubs",   "DeviceSeries": "Cisco Catalyst 9200 Series",  "IpAddress": "10.30.3.2", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-router-01",   "DeviceID": "DEV-VIE-ASR1K-01", "DeviceFamily": "Routers",             "DeviceSeries": "Cisco ASR 1000 Series",       "IpAddress": "10.30.0.1", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-wlc-01",      "DeviceID": "DEV-VIE-C9800-01", "DeviceFamily": "Wireless Controller", "DeviceSeries": "Cisco Catalyst 9800 Series",  "IpAddress": "10.30.4.1", "Location": "Global/Europe/Austria/Vienna"},
            {"DeviceName": "vie-ap-01",       "DeviceID": "DEV-VIE-AP9130-01","DeviceFamily": "Unified AP",          "DeviceSeries": "Cisco Catalyst 9130 Series",  "IpAddress": "10.30.5.1", "Location": "Global/Europe/Austria/Vienna"},
        ]

        # Advisory-Katalog: realistische Cisco Security Advisories
        ADVISORY_CATALOG = [
            {
                "advisoryId":              "cisco-sa-cat9k-webui-rce-XwuVn3kP",
                "advisorySeverity":        "CRITICAL",
                "cveId":                   "CVE-2023-20198",
                "cvssScore":               10.0,
                "description":             "Privilege escalation via IOS XE Web UI allows unauthenticated remote code execution",
                "workaround":              "Disable HTTP Server feature or restrict access via ACL",
                "fixedSoftwareRelease":    "17.9.4a",
                "affectedFamilies":        ["Switches and Hubs", "Wireless Controller"],
            },
            {
                "advisoryId":              "cisco-sa-asr1k-ospf-dos-7jBf9LmK",
                "advisorySeverity":        "HIGH",
                "cveId":                   "CVE-2024-20307",
                "cvssScore":               8.6,
                "description":             "OSPF LSA processing vulnerability can cause router reload via crafted LSA packets",
                "workaround":              "Implement OSPF authentication; filter LSA packets at perimeter",
                "fixedSoftwareRelease":    "17.6.6",
                "affectedFamilies":        ["Routers"],
            },
            {
                "advisoryId":              "cisco-sa-iosxe-snmp-privesc-4tHpWqNz",
                "advisorySeverity":        "HIGH",
                "cveId":                   "CVE-2024-20410",
                "cvssScore":               7.8,
                "description":             "SNMP subsystem privilege escalation allows authenticated attacker to gain root access",
                "workaround":              "Restrict SNMP community strings; use SNMPv3 with authentication",
                "fixedSoftwareRelease":    "17.9.3",
                "affectedFamilies":        ["Switches and Hubs", "Routers"],
            },
            {
                "advisoryId":              "cisco-sa-ap-capwap-dos-2cPmRxVb",
                "advisorySeverity":        "HIGH",
                "cveId":                   "CVE-2024-20265",
                "cvssScore":               7.4,
                "description":             "CAPWAP control message handling flaw allows unauthenticated DoS on access points",
                "workaround":              "Enable CAPWAP DTLS encryption; isolate management traffic",
                "fixedSoftwareRelease":    "17.12.2",
                "affectedFamilies":        ["Unified AP", "Wireless Controller"],
            },
            {
                "advisoryId":              "cisco-sa-c9800-ssid-enum-5gKtLpMn",
                "advisorySeverity":        "MEDIUM",
                "cveId":                   "CVE-2024-20389",
                "cvssScore":               5.3,
                "description":             "Information disclosure in 9800 WLC allows unauthenticated SSID enumeration",
                "workaround":              "Enable SSID broadcast suppression; implement client isolation",
                "fixedSoftwareRelease":    "17.9.5",
                "affectedFamilies":        ["Wireless Controller"],
            },
            {
                "advisoryId":              "cisco-sa-iosxe-tls-mitm-8hRsQwYz",
                "advisorySeverity":        "MEDIUM",
                "cveId":                   "CVE-2024-20451",
                "cvssScore":               6.5,
                "description":             "TLS certificate validation flaw enables man-in-the-middle attack on management plane",
                "workaround":              "Enforce strict TLS certificate pinning; use PKI infrastructure",
                "fixedSoftwareRelease":    "17.9.4",
                "affectedFamilies":        ["Switches and Hubs", "Routers", "Wireless Controller"],
            },
            {
                "advisoryId":              "cisco-sa-cat9k-acl-bypass-3vNpJxBq",
                "advisorySeverity":        "MEDIUM",
                "cveId":                   "CVE-2024-20512",
                "cvssScore":               5.8,
                "description":             "VLAN ACL bypass allows lateral movement between network segments under specific conditions",
                "workaround":              "Apply explicit deny rules at end of each VACL; review VLAN design",
                "fixedSoftwareRelease":    "17.12.1",
                "affectedFamilies":        ["Switches and Hubs"],
            },
            {
                "advisoryId":              "cisco-sa-aironet-eap-info-9kMwTvCp",
                "advisorySeverity":        "LOW",
                "cveId":                   "CVE-2024-20318",
                "cvssScore":               3.7,
                "description":             "EAP identity response leaks client username in cleartext during authentication",
                "workaround":              "Use EAP-TLS with certificate-based authentication",
                "fixedSoftwareRelease":    "17.12.3",
                "affectedFamilies":        ["Unified AP"],
            },
        ]

        # Initialer Advisory-Status pro Gerät: zufällig 1-3 Advisories zuweisen
        # Status: "active" oder "patched" (wird über Zeit angepasst)
        device_advisories = {}
        for dev in ALL_DEVICES:
            eligible = [a for a in ADVISORY_CATALOG if dev["DeviceFamily"] in a["affectedFamilies"]]
            if eligible:
                assigned = random.sample(eligible, min(random.randint(1, 3), len(eligible)))
                device_advisories[dev["DeviceName"]] = [
                    {
                        "advisory": a,
                        "status":   random.choice(["active", "active", "active", "patched"]),
                        "affectedSoftwareRelease": f"17.{random.randint(6, 9)}.{random.randint(0, 3)}",
                        "publicationDate": (self.now() - timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
                    }
                    for a in assigned
                ]

        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()

            for dev in ALL_DEVICES:
                advisories = device_advisories.get(dev["DeviceName"], [])

                for adv_state in advisories:
                    # Kleine Chance: Advisory wird gepatcht oder reaktiviert
                    if random.random() < 0.005:
                        adv_state["status"] = "patched" if adv_state["status"] == "active" else "active"
                    # Sehr kleine Chance: neues Advisory taucht auf
                    if random.random() < 0.002:
                        eligible = [a for a in ADVISORY_CATALOG if dev["DeviceFamily"] in a["affectedFamilies"]]
                        if eligible:
                            new_adv = random.choice(eligible)
                            # Nur hinzufügen wenn nicht schon vorhanden
                            existing_ids = [x["advisory"]["advisoryId"] for x in advisories]
                            if new_adv["advisoryId"] not in existing_ids:
                                advisories.append({
                                    "advisory": new_adv,
                                    "status":   "active",
                                    "affectedSoftwareRelease": f"17.{random.randint(6, 9)}.{random.randint(0, 3)}",
                                    "publicationDate": self.now().strftime("%Y-%m-%d"),
                                })

                    adv = adv_state["advisory"]
                    event = {
                        "timestamp":                timestamp,
                        "sourcetype":               "cisco:dnac:securityadvisory",
                        "cisco_catalyst_host":       DNAC_HOST,
                        "advisoryId":               adv["advisoryId"],
                        "advisorySeverity":         adv["advisorySeverity"],
                        "cveId":                    adv["cveId"],
                        "cvssScore":                adv["cvssScore"],
                        "description":              adv["description"],
                        "workaround":               adv["workaround"],
                        "fixedSoftwareRelease":     adv["fixedSoftwareRelease"],
                        "affectedSoftwareRelease":  adv_state["affectedSoftwareRelease"],
                        "publicationDate":          adv_state["publicationDate"],
                        "status":                   adv_state["status"],
                        "DeviceName":               dev["DeviceName"],
                        "DeviceID":                 dev["DeviceID"],
                        "DeviceFamily":             dev["DeviceFamily"],
                        "DeviceSeries":             dev["DeviceSeries"],
                        "IpAddress":                dev["IpAddress"],
                        "Location":                 dev["Location"],
                        "url":                      f"https://sec.cloudapps.cisco.com/security/center/content/CiscoSecurityAdvisory/{adv['advisoryId']}",
                    }
                    self.write_data("catalyst_center.json", event)

            yield 300  # Security Advisories alle 5 Minuten pollen

    # ==================== CISCO MERAKI ====================
    # Format entspricht ITSI Content Pack for Cisco Enterprise Networks (Meraki-Teil)
    # KPI Base Searches erwarten:
    #   sourcetype="meraki:assurancealerts"
    #   organizationId, categoryType (configuration/connectivity/device_health/insights)
    #   network.name (= Network, entity_split_field)
    #   network.id   (= Network_ID)
    #   severity     (informational / warning / critical)
    # Entity Import braucht zusätzlich:
    #   sourcetype="meraki:organizationsnetworks": id, organizationId, name, timeZone, tags{}, url, notes
    #   sourcetype="meraki:organizations":         id, name, cloud.region.name, cloud.region.host.name
    # Outage Atlanta: Minute 40-45 → deutlich mehr connectivity + device_health Alerts
    def generate_meraki_data(self):
        """Generate Cisco Meraki assurance alert data for ITSI Content Pack"""

        ORG_ID   = "meraki-org-123456"
        ORG_NAME = "CoolaShaker Inc."

        # Feste Netzwerke pro Standort — Network ist entity_split_field
        NETWORKS = {
            "atlanta": [
                {"id": "N_atl_001", "name": "Atlanta-Corporate",    "tz": "America/New_York", "tags": ["corporate", "production"], "url": "n/Atlanta-Corporate"},
                {"id": "N_atl_002", "name": "Atlanta-Factory",      "tz": "America/New_York", "tags": ["factory", "iot"],          "url": "n/Atlanta-Factory"},
                {"id": "N_atl_003", "name": "Atlanta-Guest",        "tz": "America/New_York", "tags": ["guest"],                   "url": "n/Atlanta-Guest"},
            ],
            "berlin": [
                {"id": "N_ber_001", "name": "Berlin-Corporate",     "tz": "Europe/Berlin",    "tags": ["corporate"],               "url": "n/Berlin-Corporate"},
                {"id": "N_ber_002", "name": "Berlin-Factory",       "tz": "Europe/Berlin",    "tags": ["factory", "iot"],          "url": "n/Berlin-Factory"},
            ],
            "vienna": [
                {"id": "N_vie_001", "name": "Vienna-Corporate",     "tz": "Europe/Vienna",    "tags": ["corporate"],               "url": "n/Vienna-Corporate"},
                {"id": "N_vie_002", "name": "Vienna-Factory",       "tz": "Europe/Vienna",    "tags": ["factory", "iot"],          "url": "n/Vienna-Factory"},
            ],
        }

        # Realistische Alert-Beschreibungen pro categoryType
        ALERT_DETAILS = {
            "configuration": [
                {"type": "config_drift",          "description": "Device configuration drift detected",         "severity": "warning"},
                {"type": "firmware_mismatch",     "description": "Firmware version mismatch across devices",    "severity": "warning"},
                {"type": "vlan_misconfiguration", "description": "VLAN configuration inconsistency detected",   "severity": "warning"},
                {"type": "acl_change",            "description": "Access control list modified unexpectedly",   "severity": "critical"},
            ],
            "connectivity": [
                {"type": "uplink_loss",           "description": "WAN uplink connectivity lost",                "severity": "critical"},
                {"type": "high_latency",          "description": "High latency detected on uplink",             "severity": "warning"},
                {"type": "packet_loss",           "description": "Significant packet loss detected",            "severity": "warning"},
                {"type": "vpn_tunnel_down",       "description": "VPN tunnel to hub site is down",              "severity": "critical"},
            ],
            "device_health": [
                {"type": "high_cpu",              "description": "Device CPU utilization above threshold",       "severity": "warning"},
                {"type": "high_memory",           "description": "Device memory utilization critical",          "severity": "critical"},
                {"type": "device_offline",        "description": "Network device went offline",                 "severity": "critical"},
                {"type": "port_flapping",         "description": "Switch port flapping detected",               "severity": "warning"},
            ],
            "insights": [
                {"type": "client_vpn_issue",      "description": "Elevated Client VPN connection failures",     "severity": "warning"},
                {"type": "rogue_ap",              "description": "Rogue access point detected in vicinity",     "severity": "warning"},
                {"type": "channel_utilization",   "description": "WiFi channel utilization above 80%",          "severity": "informational"},
                {"type": "dhcp_exhaustion",       "description": "DHCP pool approaching exhaustion",            "severity": "warning"},
            ],
        }

        # Basis-Wahrscheinlichkeiten für Alerts pro categoryType (normal)
        BASE_ALERT_PROB = {
            "configuration": 0.05,
            "connectivity":  0.08,
            "device_health": 0.06,
            "insights":      0.12,
        }

        # Berlin SD-WAN brownout: MX uplink alerts (early warning -> failover)
        WAN_EARLY_ALERTS = [
            {"type": "high_latency",       "description": "High latency detected on uplink",                       "severity": "warning"},
            {"type": "packet_loss",        "description": "Significant packet loss detected",                      "severity": "warning"},
            {"type": "uplink_jitter",      "description": "WAN uplink jitter above SLA threshold",                 "severity": "warning"},
        ]
        WAN_IMPACT_ALERTS = [
            {"type": "uplink_failover",    "description": "Primary WAN uplink failed over to cellular",            "severity": "critical"},
            {"type": "vpn_tunnel_degraded","description": "AutoVPN tunnel to hub Vienna degraded (loss > 5%)",     "severity": "critical"},
            {"type": "packet_loss",        "description": "Significant packet loss detected",                      "severity": "warning"},
        ]
        WAN_MX = {"N_ber_001": "ber-corp-mx-01", "N_ber_002": "ber-fact-mx-01"}

        yield 0  # setup done
        while True:
            timestamp  = self.now().isoformat()
            is_atl_outage = self.is_atlanta_network_outage()
            wan = self.scenario_level("sdwan_brownout")

            # --- Organization Event (für Entity Import: meraki:organizations) ---
            org_event = {
                "timestamp":              timestamp,
                "sourcetype":             "meraki:organizations",
                "id":                     ORG_ID,
                "name":                   ORG_NAME,
                "cloud.region.name":      "EU",
                "cloud.region.host.name": "api.meraki.com",
            }
            self.write_data("meraki.json", org_event)

            vie_down = self.vienna_isolated()
            for location, networks in NETWORKS.items():
                is_outage = (location == "atlanta" and is_atl_outage) or (location == "vienna" and vie_down)

                for net in networks:
                    is_factory = "factory" in net["tags"]

                    # --- Network Event (für Entity Import: meraki:organizationsnetworks) ---
                    net_event = {
                        "timestamp":    timestamp,
                        "sourcetype":   "meraki:organizationsnetworks",
                        "id":           net["id"],
                        "organizationId": ORG_ID,
                        "name":         net["name"],
                        "timeZone":     net["tz"],
                        "tags{}":       net["tags"],
                        "url":          f"https://n.meraki.com/{net['url']}",
                        "notes":        f"Managed network for CoolaShaker {location.capitalize()} site",
                    }
                    self.write_data("meraki.json", net_event)

                    if wan and net["id"] in WAN_MX:
                        impact = wan >= IMPACT_LEVEL
                        for _ in range(2 if impact else 1):
                            if random.random() >= (0.9 if impact else 0.6):
                                continue
                            detail = random.choice(WAN_IMPACT_ALERTS if impact else WAN_EARLY_ALERTS)
                            alert_id = f"MERAKI-{random.randint(100000, 999999)}"
                            self.write_data("meraki.json", {
                                "timestamp":      timestamp,
                                "sourcetype":     "meraki:assurancealerts",
                                "organizationId": ORG_ID,
                                "id":             alert_id,
                                "alertId":        alert_id,
                                "startedAt":      timestamp,
                                "categoryType":   "connectivity",
                                "title":          detail["description"],
                                "network.name":   net["name"],
                                "network.id":     net["id"],
                                "severity":       detail["severity"],
                                "alertType":      detail["type"],
                                "description":    detail["description"],
                                "uplink":         "cellular" if impact else "wan1",
                                "scope": {
                                    "devices":      [{"name": WAN_MX[net["id"]],
                                                      "url": f"https://n.meraki.com/{net['url']}/n/{net['id']}/manage/nodes/new_list/appliance"}],
                                    "applications": [],
                                },
                            })

                    # --- Assurance Alerts (KPI Base Searches) ---
                    # sourcetype="meraki:assurancealerts"
                    # Bei Outage Atlanta: connectivity + device_health massiv erhöht
                    for category, base_prob in BASE_ALERT_PROB.items():
                        # Outage: connectivity und device_health in Atlanta stark erhöht
                        # factory-Netzwerke sind stärker betroffen (mehr IoT-Geräte)
                        if is_outage:
                            if category == "connectivity":
                                prob = 0.90 if is_factory else 0.75
                            elif category == "device_health":
                                prob = 0.80 if is_factory else 0.60
                            elif category == "configuration":
                                prob = 0.15  # leicht erhöht durch Auto-Reconnects
                            else:  # insights
                                prob = base_prob
                        else:
                            prob = base_prob

                        if random.random() < prob:
                            detail = random.choice(ALERT_DETAILS[category])
                            # Bei Outage immer critical/warning, nie informational
                            severity = detail["severity"]
                            if is_outage and severity == "informational":
                                severity = "warning"

                            # Scope: connectivity/device_health → Devices; insights/configuration → Applications
                            alert_id = f"MERAKI-{random.randint(100000, 999999)}"
                            device_names = [f"{net['name']}-{detail['type'][:6]}-{random.randint(1,5):02d}"]
                            device_url   = f"https://n.meraki.com/{net['url']}/n/{net['id']}/manage/nodes/new_list/{random.randint(100000,999999)}"
                            app_names    = [random.choice(["HTTPS", "DNS", "DHCP", "VPN Client", "Meraki Auth"])]
                            app_url      = f"https://n.meraki.com/{net['url']}/n/{net['id']}/manage/applications"

                            if category in ("connectivity", "device_health"):
                                scope_dev_name = device_names[0]
                                scope_dev_url  = device_url
                                scope_app_name = None
                                scope_app_url  = None
                            else:
                                scope_dev_name = None
                                scope_dev_url  = None
                                scope_app_name = app_names[0]
                                scope_app_url  = app_url

                            alert_event = {
                                "timestamp":      timestamp,
                                "sourcetype":     "meraki:assurancealerts",
                                "organizationId": ORG_ID,
                                "id":             alert_id,
                                "alertId":        alert_id,
                                "startedAt":      timestamp,
                                "categoryType":   category,
                                "title":          detail["description"],
                                "network.name":   net["name"],
                                "network.id":     net["id"],
                                "severity":       severity,
                                "alertType":      detail["type"],
                                "description":    detail["description"],
                                "scope": {
                                    "devices":      [{"name": scope_dev_name, "url": scope_dev_url}] if scope_dev_name else [],
                                    "applications": [{"name": scope_app_name, "url": scope_app_url}] if scope_app_name else [],
                                },
                            }
                            self.write_data("meraki.json", alert_event)

            yield 60  # Meraki Assurance Alerts kommen typischerweise minütlich

    # ==================== MERAKI DEVICE AVAILABILITY CHANGE HISTORY ====================
    # sourcetype="meraki:devicesavailabilitieschangehistory"
    # Felder: organizationId, network.id, network.name, device.serial, device.name,
    #         ts, details.old[].name, details.old[].value, details.new[].name, details.new[].value
    # Dashboard verwendet:
    #   - Offline Devices: dedup device.serial WHERE details.new{}.value="offline"
    #   - Device Change History: mvzip(details.old{}.name, details.old{}.value) != new
    def generate_meraki_device_availability_data(self):
        """Generate Meraki device availability change history"""

        ORG_ID = "meraki-org-123456"

        # Geräte pro Netzwerk mit stabilen Serials
        NETWORK_DEVICES = {
            # Atlanta
            "N_atl_001": {
                "name": "Atlanta-Corporate",
                "devices": [
                    {"serial": "Q2KD-ATL1-0001", "name": "atl-corp-mr-01", "model": "MR46"},
                    {"serial": "Q2KD-ATL1-0002", "name": "atl-corp-mr-02", "model": "MR46"},
                    {"serial": "Q2KD-ATL1-0003", "name": "atl-corp-ms-01", "model": "MS390"},
                    {"serial": "Q2KD-ATL1-0004", "name": "atl-corp-mx-01", "model": "MX95"},
                ]
            },
            "N_atl_002": {
                "name": "Atlanta-Factory",
                "devices": [
                    {"serial": "Q2KD-ATL2-0001", "name": "atl-fact-mr-01", "model": "MR36"},
                    {"serial": "Q2KD-ATL2-0002", "name": "atl-fact-ms-01", "model": "MS225"},
                    {"serial": "Q2KD-ATL2-0003", "name": "atl-fact-mx-01", "model": "MX67"},
                ]
            },
            "N_atl_003": {
                "name": "Atlanta-Guest",
                "devices": [
                    {"serial": "Q2KD-ATL3-0001", "name": "atl-guest-mr-01", "model": "MR28"},
                ]
            },
            # Berlin
            "N_ber_001": {
                "name": "Berlin-Corporate",
                "devices": [
                    {"serial": "Q2KD-BER1-0001", "name": "ber-corp-mr-01", "model": "MR46"},
                    {"serial": "Q2KD-BER1-0002", "name": "ber-corp-ms-01", "model": "MS390"},
                    {"serial": "Q2KD-BER1-0003", "name": "ber-corp-mx-01", "model": "MX95"},
                ]
            },
            "N_ber_002": {
                "name": "Berlin-Factory",
                "devices": [
                    {"serial": "Q2KD-BER2-0001", "name": "ber-fact-mr-01", "model": "MR36"},
                    {"serial": "Q2KD-BER2-0002", "name": "ber-fact-ms-01", "model": "MS225"},
                    {"serial": "Q2KD-BER2-0003", "name": "ber-fact-mx-01", "model": "MX68CW"},
                ]
            },
            # Vienna
            "N_vie_001": {
                "name": "Vienna-Corporate",
                "devices": [
                    {"serial": "Q2KD-VIE1-0001", "name": "vie-corp-mr-01", "model": "MR46"},
                    {"serial": "Q2KD-VIE1-0002", "name": "vie-corp-ms-01", "model": "MS390"},
                    {"serial": "Q2KD-VIE1-0003", "name": "vie-corp-mx-01", "model": "MX95"},
                ]
            },
            "N_vie_002": {
                "name": "Vienna-Factory",
                "devices": [
                    {"serial": "Q2KD-VIE2-0001", "name": "vie-fact-mr-01", "model": "MR36"},
                    {"serial": "Q2KD-VIE2-0002", "name": "vie-fact-ms-01", "model": "MS225"},
                ]
            },
        }

        # Gerätezustand cachen: serial → "online" oder "offline"
        device_state = {}
        for net_id, net_data in NETWORK_DEVICES.items():
            for dev in net_data["devices"]:
                device_state[dev["serial"]] = "online"

        CHANGE_ATTRIBUTES = [
            "status",
            "connectivity",
        ]

        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_atl_outage = self.is_atlanta_network_outage()
            wan = self.scenario_level("sdwan_brownout")

            vie_down = self.vienna_isolated()
            for net_id, net_data in NETWORK_DEVICES.items():
                is_atlanta = net_id.startswith("N_atl")
                is_outage = is_atlanta and is_atl_outage
                site_down = vie_down and net_id.startswith("N_vie")
                wan_mx = {d["name"] for d in net_data["devices"]
                          if wan and net_id.startswith("N_ber") and d["model"].startswith("MX")}

                for dev in net_data["devices"]:
                    serial = dev["serial"]
                    old_state = device_state[serial]

                    # Übergangswahrscheinlichkeit:
                    # Normal: 2% pro Zyklus; Outage Atlanta: 40% Chance offline zu gehen
                    if site_down:
                        new_state = "offline"
                    elif old_state == "online":
                        go_offline_prob = 0.40 if is_outage else 0.02
                        if random.random() < go_offline_prob:
                            new_state = "offline"
                        else:
                            new_state = "online"
                    else:  # currently offline
                        come_online_prob = 0.60 if not is_outage else 0.10
                        if random.random() < come_online_prob:
                            new_state = "online"
                        else:
                            new_state = "offline"

                    # Nur bei Zustandsänderung ein Event schreiben
                    if new_state != old_state:
                        device_state[serial] = new_state
                        event = {
                            "timestamp":      timestamp,
                            "sourcetype":     "meraki:devicesavailabilitieschangehistory",
                            "organizationId": ORG_ID,
                            "network": {
                                "id":   net_id,
                                "name": net_data["name"],
                            },
                            "device": {
                                "serial": serial,
                                "name":   dev["name"],
                                "model":  dev["model"],
                            },
                            "ts": timestamp,
                            "details": {
                                "old": [{"name": "status", "value": old_state}],
                                "new": [{"name": "status", "value": new_state}],
                            },
                        }
                        self.write_data("meraki.json", event)

                    # Zusätzliche Attribut-Änderungen (connectivity etc.) — immer als Hintergrundrauschen
                    if random.random() < 0.05:
                        attr = "connectivity"
                        old_val = random.choice(["good", "fair"])
                        new_val = "poor" if is_outage else random.choice(["good", "fair", "good"])
                        if old_val != new_val:
                            attr_event = {
                                "timestamp":      timestamp,
                                "sourcetype":     "meraki:devicesavailabilitieschangehistory",
                                "organizationId": ORG_ID,
                                "network": {
                                    "id":   net_id,
                                    "name": net_data["name"],
                                },
                                "device": {
                                    "serial": serial,
                                    "name":   dev["name"],
                                    "model":  dev["model"],
                                },
                                "ts": timestamp,
                                "details": {
                                    "old": [{"name": attr, "value": old_val}],
                                    "new": [{"name": attr, "value": new_val}],
                                },
                            }
                            self.write_data("meraki.json", attr_event)

                    # Berlin SD-WAN brownout: MX uplink quality drops, then failover to cellular
                    if dev["name"] in wan_mx and random.random() < 0.5:
                        impact = wan >= IMPACT_LEVEL
                        attr, old_val, new_val = random.choice(
                            [("connectivity", "fair", "poor"), ("activeUplink", "wan1", "cellular")] if impact
                            else [("connectivity", "good", "fair")])
                        self.write_data("meraki.json", {
                            "timestamp":      timestamp,
                            "sourcetype":     "meraki:devicesavailabilitieschangehistory",
                            "organizationId": ORG_ID,
                            "network": {"id": net_id, "name": net_data["name"]},
                            "device": {"serial": serial, "name": dev["name"], "model": dev["model"]},
                            "ts": timestamp,
                            "details": {
                                "old": [{"name": attr, "value": old_val}],
                                "new": [{"name": attr, "value": new_val}],
                            },
                        })

            yield 60

    # ==================== MERAKI WIRELESS PACKET LOSS ====================
    # sourcetype="meraki:wirelessdevicespacketlossbydevice"
    # Felder: organizationId, network.id, network.name,
    #         downstream.lost, downstream.lossPercentage,
    #         upstream.lost,   upstream.lossPercentage
    # Dashboard: timechart avg() → kontinuierliche Zeitreihe
    def generate_meraki_packet_loss_data(self):
        """Generate Meraki wireless device packet loss data"""

        ORG_ID = "meraki-org-123456"

        # Nur Netzwerke mit Wireless-Komponenten
        WIRELESS_NETWORKS = [
            {"id": "N_atl_001", "name": "Atlanta-Corporate",   "location": "atlanta"},
            {"id": "N_atl_002", "name": "Atlanta-Factory",     "location": "atlanta"},
            {"id": "N_atl_003", "name": "Atlanta-Guest",       "location": "atlanta"},
            {"id": "N_ber_001", "name": "Berlin-Corporate",    "location": "berlin"},
            {"id": "N_ber_002", "name": "Berlin-Factory",      "location": "berlin"},
            {"id": "N_vie_001", "name": "Vienna-Corporate",    "location": "vienna"},
            {"id": "N_vie_002", "name": "Vienna-Factory",      "location": "vienna"},
        ]

        # Wireless APs pro Netzwerk (jeweils 1-3 APs, von denen Daten kommen)
        WIRELESS_APS = {
            "N_atl_001": ["Q2LD-ATL1-AP01", "Q2LD-ATL1-AP02"],
            "N_atl_002": ["Q2LD-ATL2-AP01"],
            "N_atl_003": ["Q2LD-ATL3-AP01"],
            "N_ber_001":  ["Q2LD-BER1-AP01", "Q2LD-BER1-AP02"],
            "N_ber_002":  ["Q2LD-BER2-AP01"],
            "N_vie_001":  ["Q2LD-VIE1-AP01", "Q2LD-VIE1-AP02"],
            "N_vie_002":  ["Q2LD-VIE2-AP01"],
        }

        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_atl_outage = self.is_atlanta_network_outage()

            vie_down = self.vienna_isolated()
            for net in WIRELESS_NETWORKS:
                is_outage = (net["location"] == "atlanta" and is_atl_outage)
                site_down = vie_down and net["location"] == "vienna"
                aps = WIRELESS_APS.get(net["id"], ["Q2LD-UNK-AP01"])

                for ap_serial in aps:
                    # Normale Werte: sehr geringe Verluste (0-2%)
                    # Outage Atlanta: 5-25% Packet Loss
                    if site_down:
                        ds_loss_pct = round(random.uniform(85, 100), 2)
                        us_loss_pct = round(random.uniform(85, 100), 2)
                    elif is_outage:
                        ds_loss_pct = round(random.uniform(5, 25), 2)
                        us_loss_pct = round(random.uniform(3, 18), 2)
                    else:
                        ds_loss_pct = round(random.uniform(0, 1.5), 2)
                        us_loss_pct = round(random.uniform(0, 1.0), 2)

                    # Absolute Pakete hochrechnen (typisch ~1000-5000 Pakete/Minute)
                    ds_total = random.randint(2000, 5000)
                    us_total = random.randint(1500, 4000)
                    ds_lost  = int(ds_total * ds_loss_pct / 100)
                    us_lost  = int(us_total * us_loss_pct / 100)

                    event = {
                        "timestamp":      timestamp,
                        "sourcetype":     "meraki:wirelessdevicespacketlossbydevice",
                        "organizationId": ORG_ID,
                        "network": {
                            "id":   net["id"],
                            "name": net["name"],
                        },
                        "device": {
                            "serial": ap_serial,
                        },
                        "downstream": {
                            "total":          ds_total,
                            "lost":           ds_lost,
                            "lossPercentage": ds_loss_pct,
                        },
                        "upstream": {
                            "total":          us_total,
                            "lost":           us_lost,
                            "lossPercentage": us_loss_pct,
                        },
                    }
                    self.write_data("meraki.json", event)

            yield 60

    # ==================== CISCO AI DEFENSE ====================
    # sourcetype="cisco:ai:defense" (Cisco Security Cloud app): one event per inspected prompt/response
    # of the AI Support Bot. AI Defense does not see latency or GPUs - a slow model shows up as prompts
    # without a response and as users repeating the same prompt.
    def _ai_defense_event(self, offset, conv_id, user, location, message_type, action, guardrail=None):
        ts = self._ts + offset
        assoc = []
        if guardrail:
            ruleset, entity, rule = guardrail
            assoc = [{"policy_guardrail_assoc": {
                "pol_guardrail_assoc_id": "pga-%08x" % random.getrandbits(32),
                "guardrail_avail_ruleset": {"guardrail_ruleset_type": ruleset,
                                            "guardrail": {"guardrails_type": ruleset}},
                "guardrail_avail_entity": {"guardrail_entity_name": entity},
                "guardrail_avail_subcategory": {"guardrail_rule_name": rule},
            }}]
        bot = SUPPORT_BOT
        return {
            "id": "%032x" % random.getrandbits(128),
            "event_id": "%032x" % random.getrandbits(128),
            "event_date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "event_action": action,
            "event_message_type": message_type,
            "event_conversation_id": conv_id,
            "user_id": user,
            "src_location": location,
            "application_id": bot["application_id"],
            "genai_application": {"application_name": bot["application_name"], "connection_type": "Gateway"},
            "connection_id": bot["connection_id"],
            "connection": {"connection_name": bot["connection_name"]},
            "policy_id": bot["policy_id"],
            "policy": {"policy_name": bot["policy_name"]},
            "model": {"model_name": bot["model_name"], "model_provider_name": bot["model_provider_name"]},
            "resource_type": "application",
            "event_policy_guardrail_assocs": assoc,
        }

    @staticmethod
    def _guardrail_hit(direction):
        for ruleset, entity, rule, action, where, share in AI_GUARDRAILS:
            if where == direction and random.random() < share:
                return (ruleset, entity, rule), action
        return None, "Allow"

    def generate_ai_defense_data(self):
        yield 0  # setup done
        while True:
            dc = self.scenario_level("dc_frankfurt")
            leak_impact = self.scenario_impact("isp_route_leak")
            busy = 8 <= self.get_current_hour() <= 18
            for location in LOCATIONS:
                for _ in range(random.randint(2, 4) if busy else random.randint(0, 1)):
                    conv_id = "conv-%016x" % random.getrandbits(64)
                    user = "customer-%05d@%s.portal.coolashaker.com" % (random.randint(1, 99999), location)
                    questions = 1 + (random.random() < 0.15)
                    answer_rate = 0.995
                    retries = 0
                    if dc:
                        answer_rate = self.ramp(dc, 0.9, 0.45)
                        retries = int(self.ramp(dc, 0.3, 2.6) + random.random())
                    elif location == "atlanta" and leak_impact:
                        answer_rate, retries = 0.8, random.randint(0, 1)
                    offset = random.uniform(0, 20)
                    for _q in range(questions):
                        for _attempt in range(1 + retries):
                            guardrail, action = self._guardrail_hit("prompt")
                            self.write_data("ai_defense.json", self._ai_defense_event(
                                offset, conv_id, user, location, "prompt", action, guardrail))
                            offset += random.uniform(0.2, 1.5)
                            if action == "Block":
                                break
                            if random.random() < answer_rate:
                                guardrail, action = self._guardrail_hit("response")
                                self.write_data("ai_defense.json", self._ai_defense_event(
                                    offset, conv_id, user, location, "response", action, guardrail))
                                offset += random.uniform(1, 4)
                                break
                            offset += random.uniform(3, 8)
            yield 30


    def _write_gpu_metrics(self, epoch):
        """GPU clusters: Vienna DC (AI vision inspection) and Frankfurt DC (LLM of the AI Support Bot)."""
        for node in GPU_NODES:
            inference = node["workload"] == "ai-inference"
            if inference:
                util = random.uniform(55, 75)
                mem = random.uniform(50, 65)
                rdma = random.uniform(5, 15)
                latency = random.uniform(40, 90)
            else:
                util = random.uniform(20, 40)
                mem = random.uniform(30, 45)
                rdma = random.uniform(10, 40)
                latency = None
            values = {
                "vmware.vm.gpu.utilization.pct": util,
                "vmware.vm.gpu.memory.usage.pct": mem,
                "vmware.vm.gpu.rdma.tx.gbps": rdma,
            }
            if latency is not None:
                values["vmware.vm.gpu.inference.latency.ms"] = latency
            for metric_name, value in values.items():
                self.write_data("vmware_metrics.json", {
                    "time": epoch,
                    "metric_name": metric_name,
                    "_value": round(value, 2),
                    "vm_name": node["vm_name"],
                    "host": node["host"],
                    "location": "vienna",
                    "workload": node["workload"],
                    "gpu_model": "NVIDIA L40S",
                    "metric_type": "gpu_vm",
                })

        # Frankfurt LLM: answers that never reach the user are aborted after the GPU already worked on
        # them, and every retried prompt is queued again -> busy GPUs, long queue, slow first token
        dc = self.scenario_level("dc_frankfurt")
        for node in LLM_GPU_NODES:
            if dc:
                values = {
                    "vmware.vm.gpu.utilization.pct":        min(99.0, self.ramp(dc, 70, 94) + random.uniform(0, 4)),
                    "vmware.vm.gpu.memory.usage.pct":       min(99.0, self.ramp(dc, 72, 96) + random.uniform(0, 2)),
                    "vmware.vm.gpu.llm.requests.aborted.pct": self.ramp(dc, 6, 45) + random.uniform(0, 5),
                    "vmware.vm.gpu.llm.queue.depth":        int(self.ramp(dc, 5, 40) + random.randint(0, 6)),
                    "vmware.vm.gpu.llm.ttft.ms":            self.ramp(dc, 600, 4500) * random.uniform(0.85, 1.15),
                    "vmware.vm.gpu.llm.tokens.delivered.per_sec": self.ramp(dc, 1500, 350) * random.uniform(0.85, 1.15),
                }
            else:
                values = {
                    "vmware.vm.gpu.utilization.pct":        random.uniform(50, 65),
                    "vmware.vm.gpu.memory.usage.pct":       random.uniform(55, 70),
                    "vmware.vm.gpu.llm.requests.aborted.pct": random.uniform(0.2, 2),
                    "vmware.vm.gpu.llm.queue.depth":        random.randint(0, 3),
                    "vmware.vm.gpu.llm.ttft.ms":            random.uniform(250, 450),
                    "vmware.vm.gpu.llm.tokens.delivered.per_sec": random.uniform(1600, 2100),
                }
            for metric_name, value in values.items():
                self.write_data("vmware_metrics.json", {
                    "time": epoch,
                    "metric_name": metric_name,
                    "_value": round(value, 2),
                    "vm_name": node["vm_name"],
                    "host": node["host"],
                    "location": "frankfurt",
                    "workload": "llm-inference",
                    "gpu_model": "NVIDIA H100",
                    "metric_type": "gpu_vm",
                })

    def generate_vmware_data(self):
        """Generate VMware ESXi and VM metrics in Splunk Metrics format"""
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            epoch = int(self.now_ts())
            
            for location, servers in SERVERS.items():
                # ESXi Host Metrics - METRIC FORMAT
                for esxi_host in servers["esxi"]:
                    # CPU Usage
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.cpu.usage.pct",
                        "_value": round(random.uniform(20, 45), 2),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                    
                    # Memory Usage
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.memory.usage.pct",
                        "_value": round(random.uniform(50, 70), 2),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                    
                    # Network RX
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.network.rx.mbps",
                        "_value": round(random.uniform(100, 500), 2),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                    
                    # Network TX
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.network.tx.mbps",
                        "_value": round(random.uniform(100, 500), 2),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                    
                    # Disk Read IOPS
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.disk.read.iops",
                        "_value": random.randint(500, 2000),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                    
                    # Disk Write IOPS
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.esxi.disk.write.iops",
                        "_value": random.randint(500, 2000),
                        "host": esxi_host,
                        "location": location,
                        "metric_type": "esxi_host"
                    })
                
                if location == "vienna":
                    self._write_gpu_metrics(epoch)

                # VM Metrics - METRIC FORMAT
                for vm in servers["vms"] + SAP_SERVERS[location]:
                    # CPU Usage
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.vm.cpu.usage.pct",
                        "_value": round(random.uniform(10, 40), 2),
                        "vm_name": vm,
                        "location": location,
                        "host": random.choice(servers["esxi"]),
                        "metric_type": "vm"
                    })
                    
                    # Memory Usage GB
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.vm.memory.usage.gb",
                        "_value": round(random.uniform(4, 12), 2),
                        "vm_name": vm,
                        "location": location,
                        "metric_type": "vm"
                    })
                    
                    # Disk Usage
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.vm.disk.usage.pct",
                        "_value": round(random.uniform(40, 70), 2),
                        "vm_name": vm,
                        "location": location,
                        "metric_type": "vm"
                    })
                    
                    # Network RX
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.vm.network.rx.kbps",
                        "_value": round(random.uniform(1000, 10000), 2),
                        "vm_name": vm,
                        "location": location,
                        "metric_type": "vm"
                    })
                    
                    # Network TX
                    self.write_data("vmware_metrics.json", {
                        "time": epoch,
                        "metric_name": "vmware.vm.network.tx.kbps",
                        "_value": round(random.uniform(1000, 10000), 2),
                        "vm_name": vm,
                        "location": location,
                        "metric_type": "vm"
                    })
            
            yield 20  # Generate every 20 seconds

    # ==================== WINDOWS ====================
    def generate_windows_data(self):
        """Generate Windows events and performance metrics with REALISTIC event log format"""
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            epoch = int(self.now_ts())
            is_berlin_issue = self.is_berlin_issue_time()
            minute = self.get_current_minute()
            
            for location, servers in SERVERS.items():
                for vm in servers["vms"] + SAP_SERVERS[location]:
                    is_problem_server = (vm == PROBLEM_SERVER)
                    
                    # ✅ FIX: Use cached MSSQL performance data for database servers
                    if vm.endswith("db001") and vm in self.perf_cache:
                        # Use EXACT same values from MSSQL performance events
                        cached_data = self.perf_cache[vm]
                        cpu = cached_data["cpu_pct"]
                        memory = cached_data["memory_pct"]
                        # Calculate disk and other metrics based on same issue status
                        if is_problem_server and is_berlin_issue:
                            minutes_into_issue = minute if minute < 15 else minute - 30
                            issue_severity = minutes_into_issue / 15.0
                            disk = 50 + (issue_severity * 50)
                            page_rate = issue_severity * 5000
                            disk_queue = random.uniform(10, 50)
                            proc_queue = random.randint(10, 50)
                        else:
                            disk = random.uniform(40, 70)
                            page_rate = random.uniform(0, 100)
                            disk_queue = random.uniform(0, 2)
                            proc_queue = random.randint(0, 2)
                    else:
                        # Original calculation for non-database servers
                        if is_problem_server and is_berlin_issue:
                            # Escalating issues
                            minutes_into_issue = minute if minute < 15 else minute - 30
                            issue_severity = minutes_into_issue / 15.0
                            
                            cpu = 30 + (issue_severity * 60)
                            memory = 60 + (issue_severity * 38)
                            disk = 50 + (issue_severity * 50)
                            page_rate = issue_severity * 5000
                            disk_queue = random.uniform(10, 50)
                            proc_queue = random.randint(10, 50)
                        else:
                            cpu = random.uniform(10, 30)
                            memory = random.uniform(40, 60)
                            disk = random.uniform(40, 70)
                            page_rate = random.uniform(0, 100)
                            disk_queue = random.uniform(0, 2)
                            proc_queue = random.randint(0, 2)
                    
                    # ✅ FIX: Performance Metrics with correct host dimension
                    # CPU
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.cpu.usage.pct",
                        "_value": round(cpu, 2),
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Memory
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.memory.usage.pct",
                        "_value": round(memory, 2),
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Disk
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.disk.usage.pct",
                        "_value": round(disk, 2),
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Disk Queue Length
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.disk.queue.length",
                        "_value": round(disk_queue, 2),
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Pages per Second
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.memory.pages.per.sec",
                        "_value": round(page_rate, 2),
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Processor Queue Length
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.processor.queue.length",
                        "_value": proc_queue,
                        "metric_type": "gauge",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # Network Bytes Total
                    self.write_data("windows_metrics.json", {
                        "time": epoch,
                        "metric_name": "windows.network.bytes.total",
                        "_value": random.randint(1000000, 10000000),
                        "metric_type": "counter",
                        "server": vm,  # ✅ Use 'server' field instead of 'host'
                        "location": location
                    })
                    
                    # ===== REALISTIC WINDOWS EVENTS =====
                    if is_problem_server and is_berlin_issue:
                        # Password Change Event (Start der Issue - Minute 0 und 30)
                        if minute in [0, 30]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 4724,
                                "EventType": "Audit Success",
                                "Type": "Security",
                                "LogName": "Security",
                                "SourceName": "Microsoft-Windows-Security-Auditing",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Audit Success",
                                "Message": f"""An attempt was made to reset an accounts password.

Subject:
    Security ID:                S-1-5-21-3623811015-3361044348-30300820-1013
    Account Name:               Administrator
    Account Domain:             {location.upper()}
    Logon ID:           0x3E7

Target Account:
    Security ID:                S-1-5-21-3623811015-3361044348-30300820-1156
    Account Name:               winsched_service
    Account Domain:             {location.upper()}

Additional Information:
    Privileges:         SeEnableDelegationPrivilege
                SeSecurityPrivilege
                SeTakeOwnershipPrivilege""",
                                "SubjectUserName": "Administrator",
                                "SubjectDomainName": location.upper(),
                                "TargetUserName": "winsched_service",
                                "TargetDomainName": location.upper(),
                                "Category": "User Account Management",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                        
                        # Task Scheduler Fehler (1 Minute nach Password Change)
                        if minute in [1, 31]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 101,
                                "EventType": "Error",
                                "Type": "Error",
                                "LogName": "Microsoft-Windows-TaskScheduler/Operational",
                                "SourceName": "Microsoft-Windows-TaskScheduler",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Task Scheduler failed to start "\\Database Log Cleanup" task for user "BERLIN\\winsched_service". Additional Data: Error Value: 2147943726.""",
                                "TaskName": "\\Database Log Cleanup",
                                "UserName": f"{location.upper()}\\winsched_service",
                                "Category": "Task Start Failed",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                            
                            # Zusätzliches Task Scheduler Event
                            event2 = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 201,
                                "EventType": "Error",
                                "Type": "Error",
                                "LogName": "Microsoft-Windows-TaskScheduler/Operational",
                                "SourceName": "Microsoft-Windows-TaskScheduler",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Task Scheduler failed to launch action "C:\\Scripts\\CleanupDBLogs.ps1" in instance "{a4c37e4e-3cf1-4567-89ab-cdef12345678}" of task "\\Database Log Cleanup". Additional Data: Error Value: 2147943726.""",
                                "TaskName": "\\Database Log Cleanup",
                                "ActionName": "C:\\Scripts\\CleanupDBLogs.ps1",
                                "Category": "Task Action failed to start",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event2)
                        
                        # Disk Space Warnings (ab Minute 3)
                        if minute in [3, 5, 7, 9, 33, 35, 37, 39]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 2013,
                                "EventType": "Warning",
                                "Type": "Warning",
                                "LogName": "System",
                                "SourceName": "srv",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """The server was unable to allocate from the system nonpaged pool because the pool was empty.""",
                                "Category": "None",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                            
                            # NTFS Disk Full Warning
                            event2 = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 55,
                                "EventType": "Error",
                                "Type": "Error",
                                "LogName": "System",
                                "SourceName": "Ntfs",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """The file system structure on the disk is corrupt and unusable. Please run the chkdsk utility on the volume \\Device\\HarddiskVolume2.""",
                                "Category": "Disk",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event2)
                            
                            # Application Event: SQL Server Log Growth
                            event3 = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 1105,
                                "EventType": "Error",
                                "Type": "Error",
                                "LogName": "Application",
                                "SourceName": "MSSQLSERVER",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Could not allocate space for object 'dbo.TransactionLog'.'PK_TransactionLog' in database 'CoolaShakerProd' because the 'PRIMARY' filegroup is full. Create disk space by deleting unneeded files, dropping objects in the filegroup, adding additional files to the filegroup, or setting autogrowth on for existing files in the filegroup.""",
                                "DatabaseName": "CoolaShakerProd",
                                "Category": "None",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event3)
                        
                        # Memory Exhaustion Events (ab Minute 8)
                        if minute in [8, 10, 12, 38, 40, 42]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 2004,
                                "EventType": "Warning",
                                "Type": "Warning",
                                "LogName": "System",
                                "SourceName": "Resource-Exhaustion-Detector",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": f"""Windows successfully diagnosed a low virtual memory condition. The following programs consumed the most virtual memory: sqlservr.exe (3456) consumed {random.randint(8000000000, 12000000000)} bytes, w3wp.exe (2890) consumed {random.randint(2000000000, 4000000000)} bytes, and lsass.exe (668) consumed {random.randint(500000000, 1000000000)} bytes.""",
                                "Category": "Memory exhaustion diagnosis events",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                            
                            # Memory Resource Exhaustion
                            event2 = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 2020,
                                "EventType": "Warning",
                                "Type": "Warning",
                                "LogName": "System",
                                "SourceName": "Resource-Exhaustion-Resolver",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Windows is attempting to close a program to prevent a low memory condition. Memory available: 256 MB. Memory needed: 2048 MB.""",
                                "Category": "Memory exhaustion resolution events",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event2)
                        
                        # High Paging Activity (ab Minute 10)
                        if minute in [10, 11, 12, 13, 40, 41, 42, 43]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 26,
                                "EventType": "Warning",
                                "Type": "Warning",
                                "LogName": "System",
                                "SourceName": "Application Popup",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Application popup: Windows - Low On Virtual Memory : Your system is low on virtual memory. To ensure that Windows runs properly, increase the size of your virtual memory paging file.""",
                                "Category": "None",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                        
                        # Service Control Manager Warnings (ab Minute 11)
                        if minute in [11, 12, 41, 42]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 7031,
                                "EventType": "Error",
                                "Type": "Error",
                                "LogName": "System",
                                "SourceName": "Service Control Manager",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """The SQL Server (MSSQLSERVER) service terminated unexpectedly.  It has done this 1 time(s).  The following corrective action will be taken in 60000 milliseconds: Restart the service.""",
                                "ServiceName": "MSSQLSERVER",
                                "Category": "None",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                        
                        # Password Correction (Minute 14 und 44)
                        if minute in [14, 44]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 4724,
                                "EventType": "Audit Success",
                                "Type": "Security",
                                "LogName": "Security",
                                "SourceName": "Microsoft-Windows-Security-Auditing",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Audit Success",
                                "Message": f"""An attempt was made to reset an accounts password.

Subject:
    Security ID:                S-1-5-21-3623811015-3361044348-30300820-1013
    Account Name:               Administrator
    Account Domain:             {location.upper()}
    Logon ID:           0x3E7

Target Account:
    Security ID:                S-1-5-21-3623811015-3361044348-30300820-1156
    Account Name:               winsched_service
    Account Domain:             {location.upper()}

Additional Information:
    Privileges:         SeEnableDelegationPrivilege
                SeSecurityPrivilege
                SeTakeOwnershipPrivilege""",
                                "SubjectUserName": "Administrator",
                                "SubjectDomainName": location.upper(),
                                "TargetUserName": "winsched_service",
                                "TargetDomainName": location.upper(),
                                "Category": "User Account Management",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                        
                        # Task Success (Minute 15 und 45)
                        if minute in [15, 45]:
                            event = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 102,
                                "EventType": "Information",
                                "Type": "Information",
                                "LogName": "Microsoft-Windows-TaskScheduler/Operational",
                                "SourceName": "Microsoft-Windows-TaskScheduler",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Task Scheduler successfully completed task "\\Database Log Cleanup" , instance "{a4c37e4e-3cf1-4567-89ab-cdef12345678}" , action "C:\\Scripts\\CleanupDBLogs.ps1" with return code 0.""",
                                "TaskName": "\\Database Log Cleanup",
                                "UserName": f"{location.upper()}\\winsched_service",
                                "Category": "Task completed",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event)
                            
                            # Disk Space Recovery
                            event2 = {
                                "timestamp": timestamp,
                                "host": vm,
                                "location": location,
                                "ComputerName": vm.upper(),
                                "EventCode": 2004,
                                "EventType": "Information",
                                "Type": "Information",
                                "LogName": "System",
                                "SourceName": "Resource-Exhaustion-Detector",
                                "RecordNumber": random.randint(1000000, 9999999),
                                "Keywords": "Classic",
                                "Message": """Windows successfully resolved a low virtual memory condition. System resources have returned to normal levels.""",
                                "Category": "Memory exhaustion diagnosis events",
                                "OpCode": "Info"
                            }
                            self.write_data("windows_events.json", event2)
                    
                    # Normale System Events für alle Server (random)
                    if random.random() < 0.05:  # 5% Chance
                        normal_events = [
                            {
                                "EventCode": 7036,
                                "EventType": "Information",
                                "LogName": "System",
                                "SourceName": "Service Control Manager",
                                "Message": f"""The {random.choice(['Windows Update', 'Windows Time', 'Background Intelligent Transfer Service', 'Windows Search'])} service entered the running state.""",
                                "Category": "None"
                            },
                            {
                                "EventCode": 4624,
                                "EventType": "Audit Success",
                                "LogName": "Security",
                                "SourceName": "Microsoft-Windows-Security-Auditing",
                                "Message": f"""An account was successfully logged on.

Subject:
    Security ID:                S-1-5-18
    Account Name:               {vm.upper()}$
    Account Domain:             {location.upper()}
    Logon ID:           0x3E7

Logon Type:             5

New Logon:
    Security ID:                S-1-5-21-3623811015-3361044348-30300820-{random.randint(1000, 9999)}
    Account Name:               user{random.randint(1, 100):03d}
    Account Domain:             {location.upper()}
    Logon ID:           0x{random.randint(100000, 999999):X}""",
                                "Category": "Logon"
                            },
                            {
                                "EventCode": 1,
                                "EventType": "Information",
                                "LogName": "System",
                                "SourceName": "Microsoft-Windows-Power-Troubleshooter",
                                "Message": """The system has returned from a low power state.""",
                                "Category": "None"
                            }
                        ]
                        
                        selected_event = random.choice(normal_events)
                        event = {
                            "timestamp": timestamp,
                            "host": vm,
                            "location": location,
                            "ComputerName": vm.upper(),
                            "EventCode": selected_event["EventCode"],
                            "EventType": selected_event["EventType"],
                            "Type": selected_event["EventType"],
                            "LogName": selected_event["LogName"],
                            "SourceName": selected_event["SourceName"],
                            "RecordNumber": random.randint(1000000, 9999999),
                            "Keywords": "Classic",
                            "Message": selected_event["Message"],
                            "Category": selected_event["Category"],
                            "OpCode": "Info"
                        }
                        self.write_data("windows_events.json", event)
            
            yield 15  # Generate every 15 seconds

    # ==================== MSSQL ====================
    def generate_mssql_data(self):
        """Generate REALISTIC MSSQL database metrics and events"""
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_berlin_issue = self.is_berlin_issue_time()
            
            for location in LOCATIONS.keys():
                db_server = f"{location[:3]}db001"
                is_problem = (db_server == PROBLEM_SERVER and is_berlin_issue)
                
                # ✅ Calculate performance values (shared with Windows metrics)
                cpu_pct = round(random.uniform(80, 100) if is_problem else random.uniform(10, 30), 2)
                memory_mb = random.randint(12000, 15000) if is_problem else random.randint(4000, 8000)
                
                # ✅ CACHE: Store for Windows metrics sync
                self.perf_cache[db_server] = {
                    "cpu_pct": cpu_pct,
                    "memory_mb": memory_mb,
                    "memory_pct": round((memory_mb / 16000) * 100, 2),  # Assume 16GB total
                    "timestamp": timestamp
                }
                
                # Database performance metrics
                event = {
                    "timestamp": timestamp,
                    "host": db_server,
                    "location": location,
                    "instance": "MSSQLSERVER",
                    "database": "CoolaShakerProd",
                    "event_type": "performance",
                    "cpu_pct": cpu_pct,  # ✅ From cache
                    "memory_mb": memory_mb,  # ✅ From cache
                    "active_connections": random.randint(200, 500) if is_problem else random.randint(20, 100),
                    "transactions_per_sec": random.randint(5, 50) if is_problem else random.randint(100, 500),
                    "batch_requests_per_sec": random.randint(50, 200) if is_problem else random.randint(500, 2000),
                    "buffer_cache_hit_ratio": round(random.uniform(60, 75) if is_problem else random.uniform(95, 99), 2),
                    "page_life_expectancy": random.randint(50, 200) if is_problem else random.randint(5000, 10000),
                    "disk_queue_length": round(random.uniform(10, 50) if is_problem else random.uniform(0, 2), 2),
                    "lock_waits_per_sec": random.randint(50, 200) if is_problem else random.randint(0, 10),
                    "deadlocks_per_sec": random.randint(2, 10) if is_problem else 0
                }
                self.write_data("mssql.json", event)
                
                # Query performance
                if random.random() < 0.5:
                    queries = [
                        "SELECT * FROM ProductionData WHERE Timestamp > @start",
                        "UPDATE Inventory SET Quantity = Quantity - @amount WHERE ProductID = @id",
                        "INSERT INTO QualityChecks (LineID, Result, Timestamp) VALUES (@line, @result, @time)",
                        "SELECT AVG(ProductionRate) FROM ProductionLine WHERE Location = @loc"
                    ]
                    event = {
                        "timestamp": timestamp,
                        "host": db_server,
                        "location": location,
                        "instance": "MSSQLSERVER",
                        "database": "CoolaShakerProd",
                        "event_type": "query_performance",
                        "query": random.choice(queries),
                        "duration_ms": random.randint(5000, 30000) if is_problem else random.randint(10, 500),
                        "cpu_time_ms": random.randint(3000, 20000) if is_problem else random.randint(5, 300),
                        "logical_reads": random.randint(10000, 100000) if is_problem else random.randint(100, 5000),
                        "physical_reads": random.randint(5000, 50000) if is_problem else random.randint(0, 500),
                        "row_count": random.randint(100, 10000)
                    }
                    self.write_data("mssql.json", event)
                
                # Log file monitoring
                log_event = {
                    "timestamp": timestamp,
                    "host": db_server,
                    "location": location,
                    "instance": "MSSQLSERVER",
                    "database": "CoolaShakerProd",
                    "event_type": "log_status",
                    "log_file_size_mb": random.randint(50000, 100000) if is_problem else random.randint(5000, 15000),
                    "log_space_used_pct": round(random.uniform(90, 100) if is_problem else random.uniform(20, 60), 2),
                    "log_growth_rate_mb_per_min": random.randint(500, 2000) if is_problem else random.randint(10, 100)
                }
                self.write_data("mssql.json", log_event)
                
                if is_problem:
                    # Critical log growth alert
                    alert_event = {
                        "timestamp": timestamp,
                        "host": db_server,
                        "location": location,
                        "instance": "MSSQLSERVER",
                        "database": "CoolaShakerProd",
                        "event_type": "alert",
                        "severity": "critical",
                        "alert_type": "log_growth",
                        "message": "Transaction log is growing rapidly. Log cleanup job may have failed.",
                        "current_size_mb": random.randint(50000, 100000),
                        "growth_rate": "High"
                    }
                    self.write_data("mssql.json", alert_event)
                
                # Backup events
                if random.random() < 0.3:
                    backup_event = {
                        "timestamp": timestamp,
                        "host": db_server,
                        "location": location,
                        "instance": "MSSQLSERVER",
                        "database": "CoolaShakerProd",
                        "event_type": "backup",
                        "backup_type": random.choice(["full", "differential", "transaction_log"]),
                        "status": "failed" if is_problem else "success",
                        "duration_sec": random.randint(300, 600) if not is_problem else None,
                        "size_mb": random.randint(1000, 5000) if not is_problem else None,
                        "compressed_size_mb": random.randint(200, 1000) if not is_problem else None,
                        "backup_location": f"\\\\backup-server\\{location}\\CoolaShakerProd",
                        "error_message": "Insufficient disk space" if is_problem else None
                    }
                    self.write_data("mssql.json", backup_event)
                
                # Wait statistics
                if random.random() < 0.4:
                    wait_types = ["PAGEIOLATCH_SH", "WRITELOG", "ASYNC_NETWORK_IO", "CXPACKET", "LCK_M_S"]
                    event = {
                        "timestamp": timestamp,
                        "host": db_server,
                        "location": location,
                        "instance": "MSSQLSERVER",
                        "event_type": "wait_stats",
                        "wait_type": random.choice(wait_types),
                        "wait_time_ms": random.randint(1000, 10000) if is_problem else random.randint(10, 500),
                        "waiting_tasks_count": random.randint(20, 100) if is_problem else random.randint(0, 10)
                    }
                    self.write_data("mssql.json", event)
            
            yield 20  # Generate every 20 seconds

    # ==================== MES (Manufacturing Execution System) ====================
    # ✅ KORRIGIERT: Jede Produktionslinie bekommt UNTERSCHIEDLICHE Werte
    def generate_mes_data(self):
        """Generate REALISTIC MES production data"""
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            is_berlin_issue = self.is_berlin_issue_time()
            is_atl_network_outage = self.is_atlanta_mes_outage()
            hour = self.get_current_hour()

            # Production only during work shifts
            is_production_time = (6 <= hour < 22)

            wan = self.scenario_level("sdwan_brownout")
            # no production orders from SAP MII once its order buffer is empty
            sap_stop = is_production_time and self.scenario_impact("sap_idoc")

            for location in LOCATIONS.keys():
                is_problem = (location == "berlin" and is_berlin_issue) or \
                             (location == "atlanta" and is_atl_network_outage) or \
                             (location == "vienna" and self.vienna_isolated())
                # AI vision inspection is scored by the GPU cluster in Vienna; Berlin reaches it over SD-WAN
                wan_here = wan if location == "berlin" else 0.0
                no_orders = sap_stop and not is_problem
                ai_fallback_lines = set()
                if is_production_time and not is_problem and not no_orders and wan_here >= IMPACT_LEVEL:
                    ai_fallback_lines = {1, 2}
                
                # ✅ KORREKTUR: Production line data - EACH LINE GETS DIFFERENT VALUES
                for line_id in range(1, 4):
                    # ✅ Werte HIER berechnen - INNERHALB der line_id Schleife!
                    ai_latency = random.uniform(60, 120)
                    if wan_here:
                        ai_latency += self.ramp(wan_here, 150, 1800) * random.uniform(0.85, 1.15)
                    ai_fallback = line_id in ai_fallback_lines
                    if is_problem:
                        production_rate = random.randint(0, 50)
                        defect_rate = random.uniform(15, 30)
                        status = "degraded"
                        machine_status = "error"
                        cycle_time = random.uniform(10, 20)
                    elif no_orders:
                        production_rate = 0
                        defect_rate = 0
                        status = "stopped"
                        machine_status = "waiting_for_orders"
                        cycle_time = 0
                    elif is_production_time and ai_fallback:
                        # inline AI inspection timed out -> line slowed down for manual sampling
                        production_rate = random.randint(300, 390)
                        defect_rate = random.uniform(3.5, 6.5)
                        status = "degraded"
                        machine_status = "running"
                        cycle_time = random.uniform(4.8, 6.0)
                    elif is_production_time:
                        production_rate = random.randint(450, 550)
                        defect_rate = random.uniform(0.5, 2.5)
                        status = "operational"
                        machine_status = "running"
                        cycle_time = random.uniform(3.2, 3.8)
                    else:
                        production_rate = 0
                        defect_rate = 0
                        status = "idle"
                        machine_status = "stopped"
                        cycle_time = 0
                    if ai_fallback:
                        oee, perf = random.uniform(58, 72), random.uniform(62, 76)
                    elif is_problem:
                        oee, perf = random.uniform(10, 30), random.uniform(30, 50)
                    elif no_orders:
                        oee, perf = random.uniform(0, 5), 0.0
                    else:
                        oee, perf = random.uniform(85, 95), random.uniform(90, 100)
                    
                    production = {
                        "timestamp": timestamp,
                        "location": location,
                        "line_id": f"LINE-{line_id:02d}",
                        "product": "CoffeeCup_Standard_350ml",
                        "product_code": "CC-STD-350",
                        "production_rate_per_hour": production_rate,
                        "target_rate_per_hour": 500,
                        "units_produced_shift": random.randint(3000, 4000) if not (is_problem or no_orders) and is_production_time else random.randint(0, 500),
                        "units_produced_today": random.randint(8000, 12000) if not is_problem else random.randint(100, 2000),
                        "defect_rate_pct": round(defect_rate, 2),
                        "cycle_time_seconds": round(cycle_time, 2),
                        "machine_status": machine_status,
                        "oee_pct": round(oee, 2),
                        "availability_pct": round(random.uniform(20, 40), 2) if is_problem else round(random.uniform(0, 8), 2) if no_orders else round(random.uniform(95, 99), 2),
                        "performance_pct": round(perf, 2),
                        "quality_pct": round(100 - defect_rate, 2),
                        "operator": f"OPR-{random.randint(100, 999)}",
                        "shift": "Day" if 6 <= hour < 14 else "Evening" if 14 <= hour < 22 else "Night",
                        "status": status
                    }
                    if no_orders:
                        production["order_status"] = "no_order_released"
                    if is_production_time and not no_orders:
                        production.update({
                            "inspection_method": "manual_sampling" if ai_fallback else "ai_vision",
                            "ai_inspection_mode": "fallback_manual" if ai_fallback else "inline",
                            "ai_inspection_latency_ms": int(ai_latency),
                            "ai_inference_endpoint": "ai-inference.vie.coolashaker.int",
                        })
                    self.write_data("mes.json", production)
                    
                    # Machine alarms
                    if is_problem and random.random() < 0.5:
                        alarms = [
                            "Emergency stop activated",
                            "Material feed error",
                            "Temperature out of range",
                            "Pressure sensor fault",
                            "Quality gate failure"
                        ]
                        alarm = {
                            "timestamp": timestamp,
                            "location": location,
                            "line_id": f"LINE-{line_id:02d}",
                            "event_type": "alarm",
                            "alarm_code": f"ALM-{random.randint(1000, 9999)}",
                            "alarm_description": random.choice(alarms),
                            "severity": random.choice(["warning", "error", "critical"]),
                            "acknowledged": False
                        }
                        self.write_data("mes.json", alarm)
                    
                    # Quality control
                    if is_production_time and not no_orders:
                        quality = {
                            "timestamp": timestamp,
                            "location": location,
                            "line_id": f"LINE-{line_id:02d}",
                            "event_type": "quality_check",
                            "sample_id": f"QC-{random.randint(10000, 99999)}",
                            "sample_size": 100,
                            "passed": 100 - int(defect_rate) if not is_problem else random.randint(70, 85),
                            "failed": int(defect_rate) if not is_problem else random.randint(15, 30),
                            "defect_types": {
                                "cracks": random.randint(0, 5) if defect_rate > 0 else 0,
                                "color_mismatch": random.randint(0, 3) if defect_rate > 0 else 0,
                                "dimension_out_of_spec": random.randint(0, 2) if defect_rate > 0 else 0
                            },
                            "inspector": f"QC-{random.randint(100, 999)}",
                            "inspection_method": "manual_sampling" if ai_fallback else "ai_vision",
                        }
                        self.write_data("mes.json", quality)
                    
                    # Material consumption
                    if is_production_time and not no_orders and random.random() < 0.3:
                        material = {
                            "timestamp": timestamp,
                            "location": location,
                            "line_id": f"LINE-{line_id:02d}",
                            "event_type": "material_consumption",
                            "material_type": "Ceramic_Clay",
                            "batch_number": f"BATCH-{random.randint(1000, 9999)}",
                            "consumed_kg": round(random.uniform(50, 200), 2),
                            "remaining_kg": round(random.uniform(1000, 5000), 2)
                        }
                        self.write_data("mes.json", material)
                
                # Inventory
                inventory = {
                    "timestamp": timestamp,
                    "location": location,
                    "event_type": "inventory",
                    "raw_materials": {
                        "Ceramic_Clay": {
                            "quantity_kg": random.randint(5000, 10000),
                            "reorder_point_kg": 2000,
                            "status": "sufficient"
                        },
                        "Glaze_White": {
                            "quantity_liters": random.randint(500, 1500),
                            "reorder_point_liters": 300,
                            "status": "sufficient"
                        }
                    },
                    "finished_goods": random.randint(10000, 50000) if not is_problem else random.randint(1000, 5000),
                    "warehouse_capacity_pct": round(random.uniform(60, 85), 2)
                }
                self.write_data("mes.json", inventory)
                
                # System alerts for production issues
                if is_problem:
                    if location == "atlanta" and is_atl_network_outage:
                        alert_type = "network_outage"
                        message    = "Network infrastructure outage detected. Production line connectivity to control systems interrupted."
                        impact     = "Automated production control offline, manual override required"
                    else:
                        alert_type = "database_connection"
                        message    = "Production line database connection lost. Unable to record production data."
                        impact     = "Production tracking offline, manual logging required"
                    alert = {
                        "timestamp": timestamp,
                        "location": location,
                        "event_type": "system_alert",
                        "severity": "critical",
                        "alert_type": alert_type,
                        "message": message,
                        "affected_lines": ["LINE-01", "LINE-02", "LINE-03"],
                        "alert_id": f"ALERT-{random.randint(10000, 99999)}",
                        "impact": impact,
                    }
                    self.write_data("mes.json", alert)
                elif no_orders and random.random() < 0.5:
                    self.write_data("mes.json", {
                        "timestamp": timestamp,
                        "location": location,
                        "event_type": "system_alert",
                        "severity": "critical",
                        "alert_type": "order_data_missing",
                        "message": "No production orders received from SAP MII (%s). Order queue empty, "
                                   "lines waiting for order data." % SAP_MII[location],
                        "affected_lines": ["LINE-01", "LINE-02", "LINE-03"],
                        "alert_id": f"ALERT-{random.randint(10000, 99999)}",
                        "impact": "Production stopped on all lines until production orders arrive from SAP ERP",
                    })
                elif ai_fallback_lines and random.random() < 0.2:
                    alert_type = "wan_degraded"
                    message    = ("SD-WAN path to Vienna DC degraded. AI inspection and MES sync delayed, "
                                  "store-and-forward active.")
                    impact     = "Lines LINE-01/02 on manual sampling, ERP sync delayed"
                    self.write_data("mes.json", {
                        "timestamp": timestamp,
                        "location": location,
                        "event_type": "system_alert",
                        "severity": "high",
                        "alert_type": alert_type,
                        "message": message,
                        "affected_lines": [f"LINE-{i:02d}" for i in sorted(ai_fallback_lines)],
                        "alert_id": f"ALERT-{random.randint(10000, 99999)}",
                        "impact": impact,
                    })
            
            yield 10  # Generate every 10 seconds

    # ==================== SAP ERP / MII ====================
    def _sap(self, sourcetype, host, location, component, **fields):
        event = {"timestamp": self.now().isoformat(), "sourcetype": sourcetype, "host": host,
                 "location": location, "sap_component": component,
                 "sap_sid": SAP_ERP["sid"] if component == "ERP" else "MII"}
        event.update(fields)
        self.write_data("sap.json", event)

    def generate_sap_data(self):
        """SAP ERP PRD and SAP MII: system KPIs, the IDoc interface ERP -> MII per plant and the MII order buffer.
        Scenario sap_idoc: more and more tRFC calls to MII fail (the expired client certificate hits every TLS
        session that is renewed) until no order reaches MII; at IMPACT_LEVEL the order buffers are empty."""
        backlog = dict.fromkeys(SAP_MII, 0)
        docnum = random.randint(10 ** 15, 2 * 10 ** 15)
        order = random.randint(1000000, 1900000)
        yield 0  # setup done
        while True:
            hour = self.get_current_hour()
            production = 6 <= hour < 22
            business = 7 <= hour < 19
            level = self.scenario_level("sap_idoc")
            fail = min(1.0, level / IMPACT_LEVEL)

            users = random.randint(240, 320) if business else random.randint(25, 60)
            for i, server in enumerate(SAP_ERP["app_servers"]):
                self._sap("sap:erp:performance", server, SAP_ERP["location"], "ERP",
                          sap_client=SAP_ERP["client"], instance="%s_%s_%02d" % (server, SAP_ERP["sid"], i * 2),
                          dialog_response_time_ms=int(random.uniform(550, 850)),
                          db_request_time_ms=int(random.uniform(180, 320)),
                          active_users=users // 2 + random.randint(-12, 12),
                          dialog_wp_utilization_pct=round(random.uniform(30, 55) if business else random.uniform(8, 20), 1),
                          update_errors=1 if random.random() < 0.01 else 0,
                          short_dumps=1 if random.random() < 0.02 else 0,
                          # RSEOUT00 (IDoc dispatch) aborts when it cannot hand IDocs to the port
                          failed_background_jobs=(1 if i == 0 and fail and random.random() < 0.7 else 0)
                          + (1 if random.random() < 0.005 else 0))
            self._sap("sap:erp:performance", SAP_ERP["db_server"], SAP_ERP["location"], "ERP",
                      sap_client=SAP_ERP["client"], instance="HDB00",
                      hana_memory_used_pct=round(random.uniform(62, 70), 1),
                      hana_cpu_pct=round(random.uniform(20, 35) if business else random.uniform(8, 15), 1))

            for location, mii in SAP_MII.items():
                code = LOCATIONS[location]["code"].upper()
                partner, destination = "MII_" + code, "MII_%s_IDOC" % code
                plant = {"atlanta": "US10", "berlin": "DE10", "vienna": "AT10"}[location]
                created = random.randint(3, 6) if production else random.randint(0, 1)
                retries = min(backlog[location], 20) if fail else 0
                failed = sum(1 for _ in range(created) if random.random() < fail)
                if fail:
                    backlog[location] += failed
                    delivered = created - failed
                    latency = self.ramp(level, 4, 90) * random.uniform(0.8, 1.2)
                else:
                    resent = min(backlog[location], 40)
                    backlog[location] -= resent
                    delivered = created + resent
                    latency = random.uniform(2, 6) + (30 if resent else 0)
                for n in range(created):
                    docnum += 1
                    order += 1
                    ok = n >= failed
                    self._sap("sap:idoc", SAP_ERP["app_servers"][n % 2], SAP_ERP["location"], "ERP",
                              docnum=str(docnum), idoc_type="LOIPRO05", message_type="LOIPRO", direction="outbound",
                              partner=partner, rfc_destination=destination, plant=plant, target_location=location,
                              order_number=str(order), material="CC-STD-350", quantity=random.choice((500, 1000, 1500)),
                              status="03" if ok else "02",
                              status_text="Data passed to port OK" if ok else "Error passing data to port",
                              message="" if ok else "tRFC %s: %s" % (destination, SAP_CERT_ERROR))
                    if ok:
                        self._sap("sap:idoc", mii, location, "MII", docnum=str(docnum), idoc_type="LOIPRO05",
                                  message_type="LOIPRO", direction="inbound", partner=SAP_ERP["sid"], plant=plant,
                                  order_number=str(order), status="53", status_text="Production order released to MES")
                self._sap("sap:idoc:status", SAP_ERP["app_servers"][0], SAP_ERP["location"], "ERP",
                          partner=partner, rfc_destination=destination, plant=plant, target_location=location,
                          idoc_type="LOIPRO05", idocs_created=created, idocs_delivered=delivered,
                          idoc_outbound_backlog=backlog[location], idoc_error_count=failed + retries,
                          idoc_e2e_latency_s=round(latency, 1) if delivered else None,
                          trfc_queue_entries=backlog[location] + (random.randint(0, 1) if not fail else 0),
                          last_error=SAP_CERT_ERROR if failed or retries else "")

                if production:
                    buffer = round(SAP_MII_BUFFER * (1 - fail)) if fail else random.randint(20, 28)
                    dispatched = min(buffer, random.randint(3, 6))
                else:
                    buffer, dispatched = random.randint(24, 30), 0
                self._sap("sap:mii:performance", mii, location, "MII", plant=plant,
                          orders_received=delivered, mii_order_buffer=buffer, orders_dispatched_to_mes=dispatched,
                          confirmations_sent=dispatched, mii_message_queue_depth=random.randint(0, 3),
                          mii_response_time_ms=int(random.uniform(80, 200)),
                          mii_jvm_heap_used_pct=round(random.uniform(40, 60), 1))
            yield 60

    # ==================== DATACENTER INFRASTRUCTURE ====================
    def generate_infra_data(self):
        """Generate REALISTIC datacenter infrastructure monitoring data"""
        yield 0  # setup done
        while True:
            timestamp = self.now().isoformat()
            
            for location, details in LOCATIONS.items():
                # Temperature sensors (multiple zones)
                zones = {
                    "server_room": {"normal_range": (18, 24), "critical": 28},
                    "cooling_plant": {"normal_range": (10, 15), "critical": 20},
                    "ups_room": {"normal_range": (20, 26), "critical": 30},
                    "hot_aisle": {"normal_range": (25, 32), "critical": 38},
                    "cold_aisle": {"normal_range": (16, 22), "critical": 25}
                }
                
                for zone, config in zones.items():
                    temp_value = round(random.uniform(*config["normal_range"]), 1)
                    temp = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "temperature",
                        "zone": zone,
                        "sensor_id": f"{location[:3]}-temp-{zone}",
                        "value_celsius": temp_value,
                        "value_fahrenheit": round((temp_value * 9/5) + 32, 1),
                        "threshold_warning": config["critical"] - 3,
                        "threshold_critical": config["critical"],
                        "status": "normal" if temp_value < config["critical"] - 3 else "warning"
                    }
                    self.write_data("infra.json", temp)
                
                # Humidity sensors
                humidity_zones = ["server_room", "storage_room"]
                for zone in humidity_zones:
                    humidity_value = round(random.uniform(40, 60), 1)
                    humidity = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "humidity",
                        "zone": zone,
                        "sensor_id": f"{location[:3]}-humidity-{zone}",
                        "value_pct": humidity_value,
                        "threshold_min": 30,
                        "threshold_max": 70,
                        "status": "normal" if 30 <= humidity_value <= 70 else "warning"
                    }
                    self.write_data("infra.json", humidity)
                
                # Power consumption (multiple circuits)
                power_circuits = ["main", "backup", "hvac", "lighting"]
                if location == "vienna":
                    power_circuits.append("gpu_pod")   # GPU cluster for AI vision inspection
                total_power = 0
                for circuit in power_circuits:
                    if circuit == "gpu_pod":
                        power_kw = round(random.uniform(18, 25), 2)
                    elif circuit == "main":
                        power_kw = round(random.uniform(60, 90), 2)
                    elif circuit == "backup":
                        power_kw = round(random.uniform(5, 15), 2)
                    elif circuit == "hvac":
                        power_kw = round(random.uniform(20, 35), 2)
                    else:
                        power_kw = round(random.uniform(2, 5), 2)
                    
                    total_power += power_kw
                    
                    power = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "power",
                        "circuit": circuit,
                        "sensor_id": f"{location[:3]}-power-{circuit}",
                        "value_kw": power_kw,
                        "voltage_v": round(random.uniform(220, 240), 1),
                        "current_a": round(random.uniform(10, 100), 2),
                        "power_factor": round(random.uniform(0.85, 0.95), 2)
                    }
                    self.write_data("infra.json", power)
                
                # Total datacenter power
                total_power_event = {
                    "timestamp": timestamp,
                    "location": location,
                    "sensor_type": "power",
                    "system": "datacenter_total",
                    "sensor_id": f"{location[:3]}-power-total",
                    "value_kw": round(total_power, 2),
                    "capacity_kw": 200,
                    "utilization_pct": round((total_power / 200) * 100, 2),
                    "pue": round(random.uniform(1.4, 1.6), 2),
                    "status": "normal"
                }
                self.write_data("infra.json", total_power_event)
                
                # UPS systems (redundant)
                for ups_id in ["01", "02"]:
                    ups = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "ups",
                        "device_id": f"{location[:3]}-ups-{ups_id}",
                        "model": "APC Symmetra PX 100kW",
                        "battery_charge_pct": round(random.uniform(95, 100), 1),
                        "load_pct": round(random.uniform(30, 50), 1),
                        "runtime_minutes": random.randint(180, 240),
                        "input_voltage": round(random.uniform(220, 240), 1),
                        "output_voltage": round(random.uniform(220, 240), 1),
                        "output_frequency_hz": round(random.uniform(49.9, 50.1), 2),
                        "battery_temperature_c": round(random.uniform(20, 28), 1),
                        "status": random.choice(["online", "online", "online", "on_battery"]) if random.random() < 0.05 else "online",
                        "last_test": (self.now() - timedelta(days=random.randint(1, 30))).isoformat(),
                        "next_test": (self.now() + timedelta(days=random.randint(1, 30))).isoformat()
                    }
                    self.write_data("infra.json", ups)
                
                # Cooling systems (CRAC units)
                for crac_id in ["01", "02"]:
                    cooling = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "cooling",
                        "device_id": f"{location[:3]}-crac-{crac_id}",
                        "model": "Liebert DS",
                        "supply_temp_celsius": round(random.uniform(14, 18), 1),
                        "return_temp_celsius": round(random.uniform(22, 26), 1),
                        "airflow_cfm": random.randint(15000, 20000),
                        "fan_speed_pct": round(random.uniform(60, 80), 1),
                        "compressor_status": "running",
                        "refrigerant_pressure_psi": round(random.uniform(120, 140), 1),
                        "cooling_capacity_kw": round(random.uniform(25, 35), 2),
                        "status": "operational"
                    }
                    self.write_data("infra.json", cooling)
                
                # Fire suppression system
                if random.random() < 0.1:
                    fire_system = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "fire_suppression",
                        "system_type": "FM-200",
                        "device_id": f"{location[:3]}-fire-system",
                        "agent_level_pct": round(random.uniform(95, 100), 1),
                        "pressure_psi": round(random.uniform(580, 620), 1),
                        "system_armed": True,
                        "last_inspection": (self.now() - timedelta(days=random.randint(30, 90))).isoformat(),
                        "status": "normal"
                    }
                    self.write_data("infra.json", fire_system)
                
                # Leak detection
                if random.random() < 0.15:
                    leak_sensors = ["north_wall", "south_wall", "under_floor", "ceiling"]
                    leak = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "leak_detection",
                        "sensor_id": f"{location[:3]}-leak-{random.choice(leak_sensors)}",
                        "zone": random.choice(leak_sensors),
                        "moisture_detected": False,
                        "status": "normal"
                    }
                    self.write_data("infra.json", leak)
                
                # Access control
                if random.random() < 0.2:
                    access_events = [
                        {"event": "access_granted", "card_valid": True},
                        {"event": "access_granted", "card_valid": True},
                        {"event": "access_denied", "card_valid": False},
                    ]
                    selected = random.choice(access_events)
                    access = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "access_control",
                        "door_id": f"{location[:3]}-door-{random.choice(['main', 'server_room', 'loading_dock'])}",
                        "event": selected["event"],
                        "badge_id": f"BADGE-{random.randint(1000, 9999)}",
                        "employee": f"EMP-{random.randint(100, 999)}",
                        "employee_name": random.choice(USERS)["name"],
                        "card_valid": selected["card_valid"],
                        "reason": None if selected["card_valid"] else random.choice(["expired", "invalid", "revoked"])
                    }
                    self.write_data("infra.json", access)
                
                # Environmental monitoring
                if random.random() < 0.2:
                    env = {
                        "timestamp": timestamp,
                        "location": location,
                        "sensor_type": "environmental",
                        "sensor_id": f"{location[:3]}-env-main",
                        "air_quality_index": random.randint(10, 50),
                        "co2_ppm": random.randint(400, 800),
                        "dust_particles_pm25": round(random.uniform(5, 25), 1),
                        "status": "good"
                    }
                    self.write_data("infra.json", env)
            
            yield 15  # Generate every 15 seconds

    # ==================== TOMCAT ACCESS LOGS ====================
    # Erzeugt Apache Combined Log Format-Eintraege fuer web01/web02 aller drei Standorte.
    # Dateinamen: tomcat_<server>.log  (z.B. tomcat_berweb01.log)
    #
    # Waehrend is_berlin_dos_time() (volle + halbe Stunde, Szenario "berlin_dos"):
    #   - Berlin web01/web02 zeigen massiven Anfragen-Burst von wenigen Angreifer-IPs
    #   - Hohe 429/503/400-Rate, kurze Antwortzeiten (typisch fuer DOS)
    #   - Das ist zeitlich zufaellig identisch mit dem Berlin Tomcat-API-Ausfall
    #     und dem berdb001-Problem, hat aber nichts damit zu tun.
    def generate_tomcat_log_data(self):
        """Generate Apache/Tomcat access logs for web01/web02 at all locations."""

        TOMCAT_SERVERS = {
            "atlanta": ["atlweb01", "atlweb02"],
            "berlin":  ["berweb01", "berweb02"],
            "vienna":  ["vieweb01", "vieweb02"],
        }

        # Pfade fuer normale Betriebslast
        NORMAL_PATHS = [
            "/", "/index.html", "/products", "/products/cups",
            "/products/cups/standard-350ml", "/about", "/contact",
            "/api/v1/health", "/api/v1/products", "/api/v1/orders",
            "/api/v1/production/lines", "/api/v1/production/status",
            "/api/v1/mes/data", "/api/v1/inventory/sync",
            "/static/js/main.js", "/static/css/style.css",
            "/static/img/logo.png", "/favicon.ico",
        ]

        NORMAL_USER_AGENTS = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/123.0",
            "PostmanRuntime/7.36.0",
            "curl/7.81.0",
            "Python/3.11 aiohttp/3.9.1",
            "Jakarta Commons-HttpClient/3.1",
            "Apache-HttpClient/4.5.14 (Java/11.0.20)",
        ]

        # Feste Angreifer-IPs fuer das DOS-Szenario in Berlin
        DOS_IPS = [
            "185.220.101.47",   # Bekannter Tor-Exit-Node
            "45.142.212.100",   # Bullet-proof Hoster
            "91.240.118.222",   # Osteuropaeisches AS
        ]
        DOS_USER_AGENTS = [
            "python-requests/2.31.0",
            "Go-http-client/2.0",
            "curl/8.1.2",
            "masscan/1.3 (https://github.com/robertdavidgraham/masscan)",
            "-",
            "libwww-perl/6.72",
        ]
        # DOS-Ziele: Mix aus legitimen API-Endpoints und typischen Scanner-Targets
        DOS_PATHS = [
            "/api/v1/production/lines",
            "/api/v1/production/lines",
            "/api/v1/mes/data",
            "/api/v1/mes/data",
            "/admin",
            "/wp-admin/",
            "/.env",
            "/config.php",
            "/api/v1/production/lines?limit=99999",
            "//api/v1/production/lines",
            "/api/v1/production/lines/../../../etc/passwd",
            "/api/v1/orders?id=1 OR 1=1",
        ]

        WAN_BACKEND_PATHS = {"/api/v1/mes/data", "/api/v1/inventory/sync", "/api/v1/production/status"}

        yield 0  # setup done
        while True:
            now = self.now()
            is_berlin_dos = self.is_berlin_dos_time()
            wan_impact = self.scenario_impact("sdwan_brownout")
            ts_str = datetime.fromtimestamp(self._ts, self.tz).strftime("%d/%b/%Y:%H:%M:%S %z")

            for location, servers in TOMCAT_SERVERS.items():
                if location == "vienna" and self.vienna_isolated():
                    continue
                for server in servers:
                    filename = f"tomcat_{server}.log"
                    is_dos_target = (location == "berlin" and is_berlin_dos)

                    # Anzahl Requests pro Zyklus:
                    # Normal: 3-15, DOS-Berlin: 60-150 (Burst)
                    num_requests = random.randint(60, 150) if is_dos_target else random.randint(3, 15)

                    # FIX: Alle Zeilen pro Server in einem einzigen open() schreiben
                    # (vorher: 150x einzeln oeffnen = massiver I/O-Stress auf /tmp/demo_data)
                    lines = []
                    for _ in range(num_requests):
                        if is_dos_target:
                            # DOS-Muster: wenige Quell-IPs, aggressive Pfade, hohe Fehlerrate
                            src_ip     = random.choice(DOS_IPS)
                            method     = random.choice(["GET", "GET", "GET", "POST", "HEAD"])
                            path       = random.choice(DOS_PATHS)
                            # Viele 429 (Rate-Limit ueberschritten), 503 (Ueberlast), 400, 403
                            status     = random.choices(
                                [200, 400, 403, 404, 429, 500, 503],
                                weights=[5, 15, 10, 20, 25, 10, 15]
                            )[0]
                            resp_bytes = random.randint(50, 800)
                            ua         = random.choice(DOS_USER_AGENTS)
                        else:
                            # Normaler Betrieb: interne IPs, legitime Pfade, fast nur 200er
                            src_ip     = f"10.{random.randint(0, 3)}.{random.randint(0, 5)}.{random.randint(1, 50)}"
                            method     = random.choices(
                                ["GET", "POST", "PUT", "DELETE"],
                                weights=[65, 20, 10, 5]
                            )[0]
                            path       = random.choice(NORMAL_PATHS)
                            status     = random.choices(
                                [200, 201, 204, 301, 304, 400, 404, 500],
                                weights=[65, 8, 5, 5, 8, 3, 4, 2]
                            )[0]
                            resp_bytes = random.randint(512, 52000)
                            ua         = random.choice(NORMAL_USER_AGENTS)
                            # Berlin SD-WAN brownout: backend calls to the Vienna DC time out at the proxy
                            if location == "berlin" and wan_impact and path in WAN_BACKEND_PATHS \
                                    and random.random() < 0.6:
                                status, resp_bytes = 504, random.randint(150, 400)

                        lines.append(
                            f'{src_ip} - - [{ts_str}] '
                            f'"{method} {path} HTTP/1.1" '
                            f'{status} {resp_bytes} "-" "{ua}"\n'
                        )

                    # Einmaliges Schreiben pro Server pro Zyklus (statt N-mal oeffnen)
                    self.sink.emit_lines(server, lines, self._ts)

            # Schlafen: waehrend DOS kuerzere Zyklen fuer realistischen Burst
            if is_berlin_dos:
                yield 1
            else:
                yield 10


# =============================================================================
# HEC EDITION – runtime (routing, simulated clock, HEC client, CLI)
# Everything above this line is the original generator logic.
# =============================================================================
import ssl
import sys
import uuid
import urllib.error
import urllib.request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

DEFAULT_HOST = "coolashaker"
SOURCE = "coolashaker"

# former /tmp/demo_data/<file>  ->  (index, sourcetype, is_metric)   (from inputs.conf)
ROUTES = {
    "msteams.json":         ("demo_msteams",         "msteams:json",               False),
    "thousandeyes.json":    ("demo_thousendeyes",    "thousendeyes:json",          False),
    "catalyst_center.json": ("demo_cisco_catalyst",  "catalyst_center:json",       False),
    "meraki.json":          ("demo_cisco_meraki",    "meraki:json",                False),
    "vmware_metrics.json":  ("demo_vmware_metrics",  "vmware:metrics:json",        True),
    "windows_metrics.json": ("demo_windows_metrics", "webex:windows:metrics:json", True),
    "windows_events.json":  ("demo_windows_events",  "windows:events:json",        False),
    "mssql.json":           ("demo_mssql",           "mssql:json",                 False),
    "mes.json":             ("demo_mes",             "mes:json",                   False),
    "infra.json":           ("demo_infra",           "infra:json",                 False),
    "ai_defense.json":      ("demo_ai_defense",      "cisco:ai:defense",           False),
    "sap.json":             ("demo_sap",             "sap:json",                   False),
}
TOMCAT_ROUTE = ("demo_tomcat_logs", "tomcat:access")
# sourcetypes the old index-time TRANSFORMS used to take from the JSON "sourcetype" field
SOURCETYPE_OVERRIDE_PREFIX = {"catalyst_center.json": "cisco:dnac:", "meraki.json": "meraki:", "sap.json": "sap:"}

ALL_INDEXES = sorted({r[0] for r in ROUTES.values()} | {TOMCAT_ROUTE[0]})
METRIC_INDEXES = sorted({r[0] for r in ROUTES.values() if r[2]})

GENERATORS = [
    ("teams",                 "generate_teams_data"),
    ("thousandeyes",          "generate_thousandeyes_data"),
    ("catalyst_center",       "generate_catalyst_center_data"),
    ("security_advisories",   "generate_securityadvisory_data"),
    ("meraki",                "generate_meraki_data"),
    ("meraki_availability",   "generate_meraki_device_availability_data"),
    ("meraki_packet_loss",    "generate_meraki_packet_loss_data"),
    ("vmware",                "generate_vmware_data"),
    ("windows",               "generate_windows_data"),
    ("mssql",                 "generate_mssql_data"),
    ("mes",                   "generate_mes_data"),
    ("infra",                 "generate_infra_data"),
    ("tomcat",                "generate_tomcat_log_data"),
    ("ai_defense",            "generate_ai_defense_data"),
    ("sap",                   "generate_sap_data"),
]


def get_tz(name):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name or "Europe/Vienna")
    except Exception:
        return ZoneInfo("Europe/Vienna")


class Router:
    """
    Turns generator output into HEC-style payloads and hands them to `out(payload)`.
    payload = {"time", "host", "index", "source", "sourcetype", "event"[, "fields"]}
    Metric events use the HEC metrics format: event="metric" + fields{metric_name, _value, dims}.
    """

    def __init__(self, out, default_host=DEFAULT_HOST):
        self.out = out
        self.default_host = default_host
        self.count = 0

    def emit(self, filename, data, ts):
        index, sourcetype, is_metric = ROUTES[filename]
        prefix = SOURCETYPE_OVERRIDE_PREFIX.get(filename)
        st = data.get("sourcetype")
        if prefix and isinstance(st, str) and st.startswith(prefix):
            sourcetype = st
        host = data.get("host") if isinstance(data.get("host"), str) else self.default_host
        payload = {"time": round(ts, 3), "host": host, "index": index,
                   "source": SOURCE, "sourcetype": sourcetype}
        if is_metric:
            fields = {k: v for k, v in data.items() if k not in ("time", "host")}
            payload["event"] = "metric"
            payload["fields"] = fields
        else:
            payload["event"] = data
        self.count += 1
        self.out(payload)

    def emit_lines(self, server, lines, ts):
        index, sourcetype = TOMCAT_ROUTE
        for line in lines:
            self.count += 1
            self.out({"time": round(ts, 3), "host": server, "index": index,
                      "source": SOURCE, "sourcetype": sourcetype, "event": line.rstrip("\n")})


class Simulation:
    """
    Drives the 13 generators on a simulated clock. Each generator yields its own
    sleep interval, so their cadence (1 s … 300 s) and the minute-of-hour fault
    windows are reproduced exactly – in realtime, catch-up and backfill alike.
    Setup randomness (e.g. which devices get which advisory) is seeded, so it is
    identical across restarts.
    """

    def __init__(self, router, tz_name="Europe/Vienna", start_ts=None, seed="coolashaker", logger=None,
                 passthrough=(), scenarios=None, onset=None):
        self.gen = DataGenerator(router, get_tz(tz_name))
        self.passthrough = tuple(passthrough)   # output errors (e.g. HEC down) must reach the caller
        self.seed = seed
        self.logger = logger
        start_ts = time.time() if start_ts is None else start_ts
        self.gen._ts = start_ts
        self.set_scenarios(scenarios or {})
        # a restart must not replay the early-warning ramp of a scenario that was already running
        for name, ts in (onset or {}).items():
            if self.gen.scenario_on(name):
                self.gen.onset[name] = min(float(ts), start_ts)
        self.iters = {}
        for name, _ in GENERATORS:
            self.iters[name] = self._start(name, start_ts)
        self.due = {name: float(start_ts) for name, _ in GENERATORS}

    def _start(self, name, ts):
        meth = dict(GENERATORS)[name]
        self.gen._ts = ts
        random.seed("%s:%s" % (self.seed, name))
        it = getattr(self.gen, meth)()
        next(it)            # run the setup part only (up to `yield 0`)
        random.seed()       # back to OS entropy for the actual data
        return it

    def set_scenarios(self, flags):
        """flags: {scenario: bool}; unknown names are ignored, missing ones stay as they are.
        Returns the scenarios whose state changed."""
        changed = {}
        for name, on in flags.items():
            if name in SCENARIOS and self.gen.scenarios[name] != bool(on):
                self.gen.scenarios[name] = bool(on)
                changed[name] = bool(on)
                if on:
                    self.gen.onset[name] = self.gen._ts
                else:
                    self.gen.onset.pop(name, None)
        if changed:
            # Windows metrics reuse the last MSSQL sample – drop it so no stale fault value leaks through
            self.gen.perf_cache.clear()
        return changed

    def next_due(self):
        return min(self.due.values())

    def run_until(self, end_ts):
        steps = 0
        while True:
            name = min(self.due, key=self.due.get)
            t = self.due[name]
            if t > end_ts:
                return steps
            self.gen._ts = t
            try:
                delay = float(next(self.iters[name]))
            except self.passthrough:
                raise
            except Exception as exc:  # same idea as the old _resilient(): restart in 5 s
                if self.logger:
                    self.logger.warning("generator %s crashed: %r – restarting", name, exc)
                self.iters[name] = self._start(name, t)
                delay = 5.0
            self.due[name] = t + max(delay, 0.5)
            steps += 1


# ---------------------------------------------------------------------------
# Minimal HEC client for standalone use (the Splunk add-on brings its own)
# ---------------------------------------------------------------------------
class SimpleHec:
    def __init__(self, url, token, verify=True, batch_size=500):
        self.endpoint = url.rstrip("/") + "/services/collector/event"
        self.token, self.batch = token, batch_size
        self.ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
        self.channel = str(uuid.uuid4())
        self.buf = []

    def add(self, payload):
        self.buf.append(payload)
        if len(self.buf) >= self.batch:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        body = "\n".join(json.dumps(p, separators=(",", ":")) for p in self.buf).encode()
        req = urllib.request.Request(self.endpoint, data=body, method="POST")
        req.add_header("Authorization", "Splunk " + self.token)
        req.add_header("X-Splunk-Request-Channel", self.channel)
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30, context=self.ctx) as r:
                    r.read()
                break
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code in (429, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise SystemExit("HEC error %s: %s" % (e.code, text))
        self.buf = []


def main():
    import argparse
    p = argparse.ArgumentParser(description="CoolaShaker data generator – sends to Splunk HEC")
    p.add_argument("--hec-url", required=True, help="e.g. https://http-inputs-<stack>.splunkcloud.com:443")
    p.add_argument("--hec-token", required=True)
    p.add_argument("--no-verify", action="store_true", help="skip TLS verification (self-signed lab)")
    p.add_argument("--tz", default="Europe/Vienna", help="time zone for business hours (default Europe/Vienna)")
    p.add_argument("--backfill-minutes", type=int, default=0, help="generate N minutes of history first")
    p.add_argument("--dry-run", action="store_true", help="print events instead of sending")
    p.add_argument("--enable-scenario", action="append", default=[], choices=sorted(SCENARIOS),
                   metavar="NAME", help="switch a fault scenario on (repeatable, all are off by default): "
                   + ", ".join(sorted(SCENARIOS)))
    a = p.parse_args()

    if a.dry_run:
        out, flush = (lambda pl: print(json.dumps(pl)[:300])), (lambda: None)
    else:
        hec = SimpleHec(a.hec_url, a.hec_token, verify=not a.no_verify)
        out, flush = hec.add, hec.flush
    router = Router(out)
    now = time.time()
    sim = Simulation(router, a.tz, start_ts=now - a.backfill_minutes * 60,
                     scenarios={name: True for name in a.enable_scenario})
    print("CoolaShaker → HEC  indexes: %s" % ", ".join(ALL_INDEXES))
    try:
        while True:
            sim.run_until(time.time())
            flush()
            time.sleep(max(0.2, min(1.0, sim.next_due() - time.time())))
    except KeyboardInterrupt:
        flush()
        print("stopped – %d events sent" % router.count)


if __name__ == "__main__":
    main()
