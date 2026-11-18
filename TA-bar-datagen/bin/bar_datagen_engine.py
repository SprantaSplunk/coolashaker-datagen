"""
Buttercup Rocks – bar simulation engine
conf26: ITSIncredible – The AI Fast-Track

Pure-stdlib port of the original datagen.py. No I/O here: every generated event
is handed to an `emit(event: dict, sourcetype: str, epoch: float)` callback, and
all state lives in a JSON-serialisable dict so it survives between modular input
runs (stored in the KV store checkpoint).
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

# ---------------------------------------------------------------------------
# Static bar configuration (from config.py)
# ---------------------------------------------------------------------------
MAX_CAPACITY = 80
REALTIME_STEP_SEC = 10
BACKFILL_STEP_SEC = 300

MENU = [
    ("Coors Banquet Pint",          "beer",       6.00, 0.72),
    ("Breckenridge Avalanche Amber", "beer",      7.00, 0.70),
    ("Blue Moon Pint",              "beer",       6.50, 0.71),
    ("New Belgium Fat Tire Pint",   "beer",       7.00, 0.70),
    ("Odell IPA Pint",              "beer",       7.50, 0.68),
    ("Colorado Lager Pint",         "beer",       6.00, 0.72),
    ("Old Fashioned",               "cocktail",  12.00, 0.62),
    ("Whiskey Sour",                "cocktail",  11.00, 0.60),
    ("Moscow Mule",                 "cocktail",  12.00, 0.62),
    ("Margarita",                   "cocktail",  11.00, 0.61),
    ("Gin & Tonic",                 "cocktail",  10.00, 0.63),
    ("Long Island Iced Tea",        "cocktail",  13.00, 0.58),
    ("Bourbon Shot",                "spirits",    6.00, 0.75),
    ("Tequila Shot",                "spirits",    6.00, 0.76),
    ("Vodka Shot",                  "spirits",    5.00, 0.75),
    ("Jameson Shot",                "spirits",    7.00, 0.74),
    ("Cabernet Sauvignon (6oz)",    "wine",       9.00, 0.70),
    ("Chardonnay (6oz)",            "wine",       8.00, 0.70),
    ("Coke / Diet Coke",            "softdrink",  4.00, 0.82),
    ("Sparkling Water",             "softdrink",  3.00, 0.84),
    ("Red Bull",                    "softdrink",  5.00, 0.78),
    ("Smash Burger",                "food",      16.00, 0.55),
    ("Loaded Nachos",               "food",      12.00, 0.58),
    ("Soft Pretzel & Mustard",      "food",       8.00, 0.63),
    ("Buffalo Wings (6pc)",         "food",      13.00, 0.56),
]

KEGS = [
    {"keg_id": "KEG-01", "beer_type": "Coors Banquet",          "tap": "TAP-01", "capacity_l": 58},
    {"keg_id": "KEG-02", "beer_type": "Breckenridge Avalanche", "tap": "TAP-02", "capacity_l": 50},
    {"keg_id": "KEG-03", "beer_type": "Blue Moon",              "tap": "TAP-03", "capacity_l": 50},
    {"keg_id": "KEG-04", "beer_type": "Odell IPA",              "tap": "TAP-04", "capacity_l": 29},
    {"keg_id": "KEG-05", "beer_type": "New Belgium Fat Tire",   "tap": "TAP-05", "capacity_l": 50},
    {"keg_id": "KEG-06", "beer_type": "Colorado Lager",         "tap": "TAP-06", "capacity_l": 29},
]
KEG_BY_ID = {k["keg_id"]: k for k in KEGS}
# Menu beer -> keg it is poured from
BEER_TO_KEG = {
    "Coors Banquet Pint": "KEG-01",
    "Breckenridge Avalanche Amber": "KEG-02",
    "Blue Moon Pint": "KEG-03",
    "Odell IPA Pint": "KEG-04",
    "New Belgium Fat Tire Pint": "KEG-05",
    "Colorado Lager Pint": "KEG-06",
}

BARTENDERS = ["Jake", "Megan", "Tyler", "Ashley", "Brandon", "Caitlin"]
POS_TERMINALS = ["POS-01", "POS-02", "POS-03"]
PAYMENT_TERMINALS = ["PAY-01", "PAY-02", "PAY-03"]

TEMP_SENSORS = [
    {"sensor_id": "TEMP-01", "location": "beer_cooler_1",  "setpoint_c": 5.0},
    {"sensor_id": "TEMP-02", "location": "beer_cooler_2",  "setpoint_c": 5.0},
    {"sensor_id": "TEMP-03", "location": "wine_fridge",    "setpoint_c": 12.0},
    {"sensor_id": "TEMP-04", "location": "ice_machine",    "setpoint_c": -8.0},
    {"sensor_id": "TEMP-05", "location": "cellar_storage", "setpoint_c": 10.0},
]

SYNTHETIC_CHECKS = [
    ("pos_api_health",       "APP_POS_P", 220,  30, 0.995),
    ("pos_e2e_order",        "APP_POS_P", 850, 150, 0.990),
    ("tap_pressure_probe",   "APP_BEV_P", 120,  20, 0.998),
    ("keg_sensor_heartbeat", "APP_BEV_P",  50,  10, 0.999),
    ("payment_auth_test",    "APP_PAY_P", 340,  60, 0.993),
    ("payment_gw_ping",      "APP_PAY_P",  80,  15, 0.997),
    ("inventory_api_check",  "APP_INV_P", 190,  30, 0.995),
    ("smoke_detector_test",  "APP_FAC_P",  40,   5, 0.999),
    ("co2_threshold_check",  "APP_FAC_P",  30,   5, 0.999),
    ("qb_api_availability",  "APP_QBK_P", 410,  80, 0.992),
]

# A business day starts at 06:00 local, so the night 18:00–01:00 belongs to one day
BUSINESS_DAY_OFFSET = timedelta(hours=6)


def get_tz(name):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("America/Denver")


# ---------------------------------------------------------------------------
# Opening hours / load
# ---------------------------------------------------------------------------
def load_factor(local):
    """0.0 (closed) … 1.0 (peak). Open Tue–Sun 18:00–01:00, closed Monday night."""
    h = local.hour + local.minute / 60.0
    if h < 1.0:
        night_of = local - timedelta(days=1)   # 00:xx belongs to the previous evening
        h += 24.0
    else:
        night_of = local
    if night_of.weekday() == 0:                # Monday night closed
        return 0.0
    if h < 18.0 or h >= 25.0:
        return 0.0
    if h < 20.0:
        return 0.25 + (h - 18.0) / 2.0 * 0.35
    if h < 22.0:
        return 0.60 + (h - 20.0) / 2.0 * 0.35
    if h < 24.0:
        return 0.95
    return max(0.65, 0.95 - (h - 24.0) * 0.30)


def business_date(local):
    return (local - BUSINESS_DAY_OFFSET).date().isoformat()


def is_quickbooks_window(local):
    """Nightly batch 01:00–02:00 after an open night (not after Monday)."""
    return local.hour == 1 and (local - timedelta(days=1)).weekday() != 0


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
def new_state():
    return {
        "keg_fill": {k["keg_id"]: random.uniform(0.50, 0.95) for k in KEGS},
        "inventory": {
            "spirits_total_ml": random.uniform(8000, 12000),
            "wine_bottles": random.randint(30, 50),
            "softdrinks_units": random.randint(80, 120),
            "food_stock_pct": random.uniform(70, 95),
        },
        "daily_revenue": 0.0,
        "daily_transactions": 0,
        "business_date": None,
        "last_qb_date": None,
        "last_15m_bucket": None,
    }


class Simulator:
    def __init__(self, state, tz_name, emit):
        self.s = state
        self.tz = get_tz(tz_name)
        self.emit = emit

    # -- state helpers --------------------------------------------------------
    def _roll_business_day(self, local):
        bd = business_date(local)
        if bd == self.s["business_date"]:
            return
        self.s["business_date"] = bd
        self.s["daily_revenue"] = 0.0
        self.s["daily_transactions"] = 0
        # Morning deliveries: empty-ish kegs replaced, stock topped up
        for kid, fill in self.s["keg_fill"].items():
            if fill < 0.25 and random.random() < 0.7:
                self.s["keg_fill"][kid] = random.uniform(0.90, 1.0)
        inv = self.s["inventory"]
        if inv["spirits_total_ml"] < 4000:
            inv["spirits_total_ml"] = random.uniform(10000, 12000)
        if inv["wine_bottles"] < 15:
            inv["wine_bottles"] = random.randint(40, 50)
        if inv["softdrinks_units"] < 40:
            inv["softdrinks_units"] = random.randint(100, 120)
        inv["food_stock_pct"] = random.uniform(85, 98)

    def _consume(self, name, cat, qty):
        inv = self.s["inventory"]
        if cat == "beer":
            kid = BEER_TO_KEG.get(name) or random.choice(KEGS)["keg_id"]
            cap = KEG_BY_ID[kid]["capacity_l"]
            self.s["keg_fill"][kid] = max(0.02, self.s["keg_fill"][kid] - 0.473 * qty / cap)
        elif cat in ("cocktail", "spirits"):
            inv["spirits_total_ml"] = max(0.0, inv["spirits_total_ml"] - 45 * qty)
        elif cat == "wine":
            inv["wine_bottles"] = max(0, inv["wine_bottles"] - (1 if random.random() < 0.2 * qty else 0))
        elif cat == "softdrink":
            inv["softdrinks_units"] = max(0, inv["softdrinks_units"] - qty)
        elif cat == "food":
            inv["food_stock_pct"] = max(0.0, inv["food_stock_pct"] - 0.15 * qty)

    # -- generators ------------------------------------------------------------
    def pos_transactions(self, t, lf, scale):
        expected = random.betavariate(2, 5) * lf * 5 * scale
        count = int(expected + random.random())
        for _ in range(count):
            n_items = random.choices([1, 2, 3, 4], weights=[40, 35, 20, 5])[0]
            items, subtotal = [], 0.0
            for _ in range(n_items):
                name, cat, price, _margin = random.choice(MENU)
                qty = random.choices([1, 2], weights=[75, 25])[0]
                items.append({"name": name, "category": cat, "price": price,
                              "qty": qty, "line_total": round(price * qty, 2)})
                subtotal += price * qty
                self._consume(name, cat, qty)
            subtotal = round(subtotal, 2)
            tip = round(subtotal * random.uniform(0, 0.12), 2) if random.random() < 0.6 else 0.0
            total = round(subtotal + tip, 2)
            self.s["daily_revenue"] += total
            self.s["daily_transactions"] += 1
            txn_id = "TXN-" + uuid.uuid4().hex[:8].upper()
            # spread transactions across the tick window
            et = t + random.uniform(0, REALTIME_STEP_SEC * scale)
            self.emit({
                "transaction_id": txn_id,
                "terminal_id": random.choice(POS_TERMINALS),
                "bartender": random.choice(BARTENDERS),
                "table_id": "T-%02d" % random.randint(1, 20),
                "items": items,
                "item_count": sum(i["qty"] for i in items),
                "subtotal_usd": subtotal,
                "tip_usd": tip,
                "total_usd": total,
                "payment_method": random.choices(["contactless", "card", "cash"], weights=[55, 30, 15])[0],
                "duration_sec": random.randint(20, 90),
            }, "bar:pos:transactions", et)
            self.payment_terminal(et + random.uniform(1, 5), txn_id, total, lf)

    def payment_terminal(self, t, txn_id, amount, lf):
        self.emit({
            "terminal_id": random.choice(PAYMENT_TERMINALS),
            "transaction_id": txn_id,
            "amount_usd": amount,
            "payment_method": random.choices(["contactless", "chip", "swipe"], weights=[60, 35, 5])[0],
            "response_ms": max(50, int(random.gauss(350, 80) + lf * 120)),
            "result": "approved" if random.random() > 0.02 else "declined",
            "card_type": random.choice(["visa", "mastercard", "amex"]),
        }, "bar:payment:terminal", t)

    def queue_sensor(self, t, lf):
        guests = min(int(lf * MAX_CAPACITY * random.uniform(0.85, 1.10)), MAX_CAPACITY + 10)
        self.emit({
            "zone": "main_bar",
            "guests_present": guests,
            "max_capacity": MAX_CAPACITY,
            "occupancy_pct": round(guests / MAX_CAPACITY * 100, 1),
            "queue_length": max(0, guests - MAX_CAPACITY),
            "avg_wait_min": max(0, int(lf * random.gauss(4, 1.5))),
            "bartenders_active": max(1, sum(1 for _ in range(3) if random.random() < lf)),
        }, "bar:queue:sensor", t)

    def revenue_snapshot(self, t, lf):
        cats = {}
        for _name, cat, price, margin in MENU:
            c = cats.setdefault(cat, {"revenue": 0.0, "margin": 0.0, "count": 0})
            sold = max(0, int(random.gauss(lf * 4, 1)))
            c["revenue"] += sold * price
            c["margin"] += sold * price * margin
            c["count"] += sold
        for cat, d in cats.items():
            self.emit({
                "category": cat,
                "revenue_usd": round(d["revenue"], 2),
                "margin_usd": round(d["margin"], 2),
                "units_sold": d["count"],
                "margin_pct": round(d["margin"] / d["revenue"] * 100, 1) if d["revenue"] > 0 else 0,
                "period_min": 15,
            }, "bar:revenue:events", t)

    def keg_pressure(self, t, lf):
        for keg in KEGS:
            fill = self.s["keg_fill"][keg["keg_id"]]
            psi = round(max(0.0, 10 + fill * 4 + random.gauss(0, 0.3 + lf * 0.4)), 2)
            self.emit({
                "keg_id": keg["keg_id"],
                "beer_type": keg["beer_type"],
                "tap_line": keg["tap"],
                "pressure_psi": psi,
                "pressure_ok": 8.0 <= psi <= 14.5,
                "temp_c": round(random.gauss(5.2, 0.3), 1),
                "fill_level_pct": round(fill * 100, 1),
                "co2_flow_rate": round(random.uniform(0.05, 0.25) * lf, 3),
                "alert": psi < 8.0 or fill < 0.10,
            }, "bar:keg:pressure", t)

    def temp_sensors(self, t):
        for s in TEMP_SENSORS:
            sp = s["setpoint_c"]
            temp = round(sp + random.gauss(0.2, 0.4), 1)
            self.emit({
                "sensor_id": s["sensor_id"],
                "location": s["location"],
                "temp_c": temp,
                "setpoint_c": sp,
                "delta_c": round(temp - sp, 2),
                "humidity_pct": round(random.uniform(55, 75), 1),
                "alert": abs(temp - sp) > 3.0,
            }, "bar:temp:sensor", t)

    def co2_occupancy(self, t, lf):
        guests = int(lf * MAX_CAPACITY) if lf > 0 else 0
        co2 = int(400 + guests * 7 + random.gauss(0, 30))
        self.emit({
            "sensor_id": "ENV-01",
            "zone": "main_bar",
            "co2_ppm": co2,
            "co2_alert_threshold": 1500,
            "co2_alert": co2 > 1500,
            "occupancy_count": guests,
            "max_capacity": MAX_CAPACITY,
            "occupancy_pct": round(guests / MAX_CAPACITY * 100, 1),
            "smoke_detector_status": "ok",
            "door_open": random.random() < (0.3 * lf),
        }, "bar:co2:occupancy", t)

    def inventory(self, t):
        inv, kf = self.s["inventory"], self.s["keg_fill"]
        items = [
            ("ITEM-001", "Coors Banquet Keg", "beer_keg", kf["KEG-01"] * 100, 15, "Coors Brewing Co."),
            ("ITEM-002", "Breckenridge Keg", "beer_keg", kf["KEG-02"] * 100, 15, "Breckenridge Brewery"),
            ("ITEM-003", "Spirits assorted", "spirits", inv["spirits_total_ml"] / 12000 * 100, 20, "Colorado Beverage Dist."),
            ("ITEM-004", "Wine bottles", "wine", inv["wine_bottles"] / 50 * 100, 25, "Rocky Mountain Wine Co."),
            ("ITEM-005", "Soft drinks", "softdrink", inv["softdrinks_units"] / 120 * 100, 20, "Colorado Beverage Dist."),
            ("ITEM-006", "Food stock", "food", inv["food_stock_pct"], 30, "Denver Fresh Market"),
        ]
        for item_id, name, cat, level, reorder, supplier in items:
            self.emit({
                "item_id": item_id,
                "name": name,
                "category": cat,
                "current_level_pct": round(level, 1),
                "reorder_threshold_pct": reorder,
                "below_reorder": level < reorder,
                "supplier": supplier,
            }, "bar:inventory:log", t)

    def infrastructure(self, t, lf):
        for tid in POS_TERMINALS:
            self.emit({
                "terminal_id": tid,
                "cpu_pct": max(1.0, min(95.0, round(random.gauss(25 + lf * 35, 5), 1))),
                "mem_pct": round(random.gauss(45 + lf * 20, 5), 1),
                "disk_free_gb": round(random.uniform(8, 20), 1),
                "net_latency_ms": max(0.5, round(random.gauss(4 + lf * 6, 1), 1)),
                "db_connections_active": random.randint(1, max(1, int(lf * 10))),
                "db_connections_max": 20,
                "uptime_sec": random.randint(3600, 864000),
                "app_version": "4.2.1",
            }, "bar:pos:infrastructure", t)
        self.emit({
            "gateway_id": "BEV-GW-01",
            "connected_sensors": len(KEGS) + len(TEMP_SENSORS),
            "packet_loss_pct": round(max(0, random.gauss(0.5, 0.3)), 2),
            "avg_rssi_dbm": round(random.gauss(-62, 4), 1),
            "sensor_battery_low": sum(1 for _ in KEGS if random.random() < 0.05),
            "uptime_sec": random.randint(86400, 2592000),
        }, "bar:bev:infrastructure", t)
        self.emit({
            "gateway_id": "PAY-GW-01",
            "api_latency_ms": round(random.gauss(180 + lf * 60, 20), 1),
            "tls_cert_days_left": random.randint(30, 365),
            "connection_status": "ok",
            "provider": "Stripe",
        }, "bar:pay:infrastructure", t)
        self.emit({
            "zone": "main_bar",
            "power_draw_kw": round(random.gauss(12 + lf * 8, 1), 2),
            "hvac_temp_c": round(random.gauss(21, 0.5), 1),
            "hvac_setpoint_c": 21.0,
            "ups_status": "online",
            "iot_gw_uptime_pct": round(random.uniform(99.0, 100.0), 2),
        }, "bar:fac:infrastructure", t)

    def synthetics(self, t, lf):
        for name, app, base_ms, std_ms, ok_prob in SYNTHETIC_CHECKS:
            ok = random.random() < ok_prob
            self.emit({
                "check_name": name,
                "app": app,
                "bubble": "Synthetics",
                "result": "success" if ok else "failure",
                "response_ms": max(10, int(random.gauss(base_ms + lf * base_ms * 0.3, std_ms))),
                "http_status": 200 if ok else random.choice([500, 503, 408]),
            }, "bar:synthetics", t)

    def quickbooks_batch(self, t, report_date):
        pos_total = round(self.s["daily_revenue"], 2)
        drift = round(random.gauss(0, 1.5), 2)
        self.emit({
            "report_date": report_date,
            "pos_total_usd": pos_total,
            "pos_transactions": self.s["daily_transactions"],
            "qb_booked_usd": round(pos_total + drift, 2),
            "reconciliation_drift_usd": drift,
            "reconciliation_ok": abs(drift) < 5.0,
            "invoices_created": random.randint(1, 5),
            "expenses_logged": random.randint(5, 20),
            "bank_feed_transactions": random.randint(30, 80),
            "bank_feed_sync_age_min": random.randint(5, 30),
            "open_invoices_count": random.randint(0, 4),
            "open_invoices_total_usd": round(random.uniform(0, 1500), 2),
            "qb_api_response_ms": random.randint(300, 800),
            "sync_status": "success" if random.random() > 0.03 else "partial",
            "software": "QuickBooks Online",
        }, "bar:quickbooks:daily", t)

    # -- one simulated point in time --------------------------------------------
    def tick(self, t, step_sec):
        """Generate all events for epoch `t` covering `step_sec` seconds."""
        local = datetime.fromtimestamp(t, tz=self.tz)
        self._roll_business_day(local)
        lf = load_factor(local)
        scale = step_sec / float(REALTIME_STEP_SEC)

        self.keg_pressure(t, lf)
        self.temp_sensors(t)
        self.co2_occupancy(t, lf)
        self.infrastructure(t, lf)
        self.synthetics(t, lf)

        bucket = int(t // 900)
        new_15m = bucket != self.s["last_15m_bucket"]
        if new_15m:
            self.s["last_15m_bucket"] = bucket
            self.inventory(t)

        if lf > 0:
            self.pos_transactions(t, lf, scale)
            self.queue_sensor(t, lf)
            if new_15m:
                self.revenue_snapshot(t, lf)

        if is_quickbooks_window(local):
            bd = business_date(local)
            if bd != self.s["last_qb_date"]:
                self.s["last_qb_date"] = bd
                self.quickbooks_batch(t, bd)
