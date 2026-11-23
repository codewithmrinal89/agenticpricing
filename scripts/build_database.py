"""Build the pricing-agent SQLite database: schema + a large, realistic
synthetic dataset.

This is NOT real GE Aerospace or any proprietary data -- that isn't public,
for obvious reasons. It's a procedurally generated dataset (~150 parts)
with internally consistent cost/margin/inventory/lifecycle logic, built
from the same pricing policy the agents actually enforce, so the generated
data exercises the same auto-approve/exception paths as the hand-picked
12-part demo did -- just at realistic scale.

Run with: python -m scripts.build_database
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "pricing.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

RNG = random.Random(42)  # fixed seed -> reproducible dataset across re-runs
TODAY = date(2026, 11, 19)
PART_COUNT = 150

# ---------- Reference data ----------

CATEGORIES = [
    "Fastener", "Seal", "Bearing", "Structural", "Electrical",
    "Hydraulic Component", "Landing Gear Component",
    "Fuel System Component", "Avionics", "Turbine Component",
]

# How many of the 150 parts fall in each category (sums to PART_COUNT).
CATEGORY_WEIGHTS = [30, 20, 15, 15, 10, 15, 10, 5, 15, 15]

AIRCRAFT_PROGRAMS = [
    ("737NG", "Boeing 737NG"), ("737MAX", "Boeing 737 MAX"),
    ("A320", "Airbus A320ceo"), ("A320neo", "Airbus A320neo"),
    ("A330", "Airbus A330"), ("A350", "Airbus A350"),
    ("777", "Boeing 777"), ("777X", "Boeing 777X"),
    ("787", "Boeing 787"), ("CRJ900", "Bombardier CRJ900"),
    ("E175", "Embraer E175"), ("757", "Boeing 757"),
]

MANUFACTURERS = [
    "Boeing", "Airbus", "GE Aerospace", "CFM International", "Honeywell",
    "Collins Aerospace", "Parker Aerospace", "SKF Aerospace", "Safran",
    "Eaton Aerospace", "Moog Inc.", "Woodward Inc.", "Raytheon Technologies",
]

LIFECYCLE_STATUSES = ["Active", "Obsolete", "Life-Time-Buy"]
LIFECYCLE_WEIGHTS = [0.82, 0.10, 0.08]

WAREHOUSES = [
    "Evendale, OH", "Wichita, KS", "Cincinnati, OH", "Everett, WA",
    "Celma, Brazil", "Villaroche, France", "Cedar Rapids, IA",
    "Phoenix, AZ", "Irvine, CA", "Singapore",
]

# cost range ($), lead-time range (days), on-hand stock range, manufacturer pool
CATEGORY_PROFILE = {
    "Fastener":                {"cost": (0.40, 15),    "lead": (1, 5),    "stock": (5000, 150000), "mfrs": ["Boeing", "Airbus"]},
    "Seal":                    {"cost": (0.40, 60),     "lead": (1, 7),    "stock": (2000, 80000),  "mfrs": ["Parker Aerospace", "Eaton Aerospace"]},
    "Bearing":                 {"cost": (15, 600),      "lead": (5, 21),   "stock": (100, 3000),    "mfrs": ["SKF Aerospace", "Moog Inc."]},
    "Structural":              {"cost": (40, 2500),     "lead": (3, 30),   "stock": (20, 1000),     "mfrs": ["Boeing", "Airbus"]},
    "Electrical":              {"cost": (80, 6000),     "lead": (7, 45),   "stock": (10, 500),      "mfrs": ["Honeywell", "Collins Aerospace", "Raytheon Technologies"]},
    "Hydraulic Component":     {"cost": (400, 18000),   "lead": (14, 45),  "stock": (3, 80),        "mfrs": ["Parker Aerospace", "Eaton Aerospace", "Moog Inc."]},
    "Landing Gear Component":  {"cost": (800, 35000),   "lead": (21, 90),  "stock": (2, 40),        "mfrs": ["Boeing", "Airbus", "Safran"]},
    "Fuel System Component":   {"cost": (150, 9000),    "lead": (10, 40),  "stock": (3, 60),        "mfrs": ["Parker Aerospace", "Woodward Inc."]},
    "Avionics":                {"cost": (1500, 65000),  "lead": (14, 120), "stock": (0, 20),        "mfrs": ["Honeywell", "Collins Aerospace", "Raytheon Technologies"]},
    "Turbine Component":       {"cost": (4000, 160000), "lead": (21, 90),  "stock": (0, 15),        "mfrs": ["GE Aerospace", "CFM International", "Safran"]},
}

DESC_TEMPLATES = {
    "Fastener":                {"types": ["Bolt", "Screw", "Washer", "Nut", "Rivet", "Pin"], "attrs": ["Hex Head", "Pan Head", "Flat Head", "Close Tolerance", "Self-Locking"], "materials": ["Titanium", "Corrosion Resistant Steel", "Cadmium Plated Steel", "Inconel"]},
    "Seal":                    {"types": ["O-Ring", "Gasket", "Labyrinth Seal", "Lip Seal", "Backup Ring"], "attrs": ["Fuel System", "Hydraulic System", "HPT Stage 1", "HPT Stage 2", "LPT Stage 1"], "materials": ["Viton", "Silicone", "PTFE", "Nitrile"]},
    "Bearing":                 {"types": ["Ball Bearing", "Roller Bearing", "Thrust Bearing", "Needle Bearing"], "attrs": ["Sealed", "Shielded", "Actuator Shaft", "Main Shaft"], "materials": ["Chrome Steel", "Ceramic Hybrid", "Stainless Steel"]},
    "Structural":              {"types": ["Bracket", "Fitting", "Rib", "Spar Segment", "Panel"], "attrs": ["Mounting", "Avionics Bay", "Wing Root", "Fuselage Frame"], "materials": ["Aluminum 7075", "Titanium", "Carbon Composite"]},
    "Electrical":              {"types": ["Relay", "Connector", "Wiring Harness", "Circuit Breaker", "Sensor"], "attrs": ["Power Distribution", "Cockpit", "Engine Monitoring", "Cabin"], "materials": ["Aerospace Grade", "Hermetically Sealed"]},
    "Hydraulic Component":     {"types": ["Valve", "Actuator", "Pump", "Manifold", "Accumulator"], "attrs": ["Fuel Metering", "Landing Gear", "Flight Control", "Brake System"], "materials": []},
    "Landing Gear Component":  {"types": ["Actuator", "Strut", "Axle", "Trunnion", "Brake Assembly"], "attrs": ["Main Gear", "Nose Gear", "Retract", "Steering"], "materials": []},
    "Fuel System Component":   {"types": ["Pump", "Valve", "Sensor", "Filter", "Controller"], "attrs": ["Fuel Metering", "Tank Level", "Boost Pump", "Shutoff"], "materials": []},
    "Avionics":                {"types": ["Flight Management Computer", "Display Unit", "Transponder", "Autopilot Computer", "Radio Altimeter"], "attrs": ["Dual Channel", "Primary", "Backup", "Integrated"], "materials": []},
    "Turbine Component":       {"types": ["Fan Blade", "Combustor Casing Segment", "Turbine Disk", "Nozzle Guide Vane", "Compressor Blade"], "attrs": ["Stage 1", "Stage 2", "Stage 3", "HPT", "LPT"], "materials": []},
}

# ---------- Pricing policy (same values used by pricing_engine.py's thresholds) ----------

POLICY_GLOBAL = {
    "min_margin_pct": 25.0,
    "target_margin_pct": 45.0,
    "max_margin_pct": 65.0,
    "max_price_increase_pct_without_approval": 10.0,
    "max_price_decrease_pct_without_approval": 10.0,
}

CATEGORY_OVERRIDES = {
    "Fastener": {"target_margin_pct": 45.0, "min_margin_pct": 30.0},
    "Turbine Component": {"target_margin_pct": 42.0, "min_margin_pct": 25.0},
    "Avionics": {"target_margin_pct": 40.0, "min_margin_pct": 25.0},
}

LIFECYCLE_OVERRIDES = {
    "Obsolete": {"requires_approval": True, "note": "Obsolete parts require pricing leader approval regardless of margin."},
    "Life-Time-Buy": {"min_margin_pct": 15.0, "requires_approval": True, "note": "LTB parts have constrained supply; min margin floor relaxed but still flagged for review."},
}


def resolve_thresholds(category: str, lifecycle: str) -> dict:
    thresholds = dict(POLICY_GLOBAL)
    thresholds.update(CATEGORY_OVERRIDES.get(category, {}))
    lifecycle_override = LIFECYCLE_OVERRIDES.get(lifecycle, {})
    if "min_margin_pct" in lifecycle_override:
        thresholds["min_margin_pct"] = lifecycle_override["min_margin_pct"]
    return thresholds


# ---------- Generators ----------

_used_part_numbers = set()


def gen_part_number(category: str) -> str:
    n = lambda a, b: RNG.randint(a, b)
    for _ in range(50):
        if category == "Fastener":
            prefix = RNG.choice(["NAS", "MS", "BAC"])
            pn = f"{prefix}{n(1000, 9999)}-{n(1, 9)}-{n(1, 30)}"
        elif category == "Seal":
            pn = f"SEAL-{RNG.choice(['OR', 'GSK', 'LBY'])}-{n(1000, 9999)}-{RNG.choice(['V', 'S', 'P'])}"
        elif category == "Bearing":
            pn = f"BRG-{n(10000, 99999)}-{RNG.choice(['2RS', 'ZZ', 'OPEN'])}"
        elif category == "Structural":
            pn = f"BRK-{n(1000000, 9999999)}-{n(100, 999)}"
        elif category == "Electrical":
            pn = f"ELEC-{RNG.choice(['REL', 'CON', 'WH', 'CB'])}-{n(1000, 9999)}"
        elif category == "Hydraulic Component":
            pn = f"HYD-{RNG.choice(['VLV', 'ACT', 'PMP'])}-{n(10000, 99999)}"
        elif category == "Landing Gear Component":
            pn = f"LG-{RNG.choice(['ACT', 'STR', 'AXL'])}-{n(10000, 99999)}"
        elif category == "Fuel System Component":
            pn = f"FUEL-{RNG.choice(['PMP', 'VLV', 'SNS'])}-{n(1000, 9999)}"
        elif category == "Avionics":
            pn = f"AV-{RNG.choice(['FMS', 'DU', 'XPDR', 'AP'])}-{n(1000, 9999)}-R{n(1, 3)}"
        else:  # Turbine Component
            program_prefix = RNG.choice(["GE90", "GE9X", "LEAP-1A", "LEAP-1B", "CFM56-7B", "CF34"])
            pn = f"{program_prefix}-{RNG.choice(['FB', 'CC', 'TD', 'NGV'])}-{n(1000, 9999)}"

        if pn not in _used_part_numbers:
            _used_part_numbers.add(pn)
            return pn
    raise RuntimeError(f"Could not generate a unique part number for {category}")


def gen_description(category: str) -> str:
    t = DESC_TEMPLATES[category]
    pieces = [RNG.choice(t["types"])]
    if t["attrs"]:
        pieces.append(RNG.choice(t["attrs"]))
    if t["materials"]:
        pieces.append(RNG.choice(t["materials"]))
    return ", ".join(pieces)


def gen_pricing(category: str, lifecycle: str, cost: float) -> float:
    """Pick a current_list_price. Most parts land near the target margin
    (compliant); a slice land below the margin floor, and another slice
    land far from the target margin (compliant on margin, but a big enough
    price swing to trip the price-change-without-approval flag) -- this is
    what keeps the Decision Gate's exception paths exercised at scale."""
    thresholds = resolve_thresholds(category, lifecycle)
    roll = RNG.random()

    if roll < 0.82:
        margin = thresholds["target_margin_pct"] + RNG.uniform(-1.5, 1.5)
    elif roll < 0.92:
        margin = thresholds["min_margin_pct"] - RNG.uniform(1, 10)  # can go negative
    else:
        direction = RNG.choice([-1, 1])
        margin = thresholds["target_margin_pct"] + direction * RNG.uniform(15, 25)
        margin = max(margin, thresholds["min_margin_pct"] + 2)

    margin = min(margin, 90)
    return round(cost / (1 - margin / 100), 2)


def gen_inventory(category: str, lifecycle: str):
    profile = CATEGORY_PROFILE[category]
    lead_lo, lead_hi = profile["lead"]
    stock_lo, stock_hi = profile["stock"]

    if lifecycle == "Obsolete":
        on_hand = 0 if RNG.random() < 0.6 else RNG.randint(0, max(1, stock_lo // 10))
        lead_time = lead_hi * RNG.randint(2, 4)
    elif lifecycle == "Life-Time-Buy":
        on_hand = RNG.randint(max(1, stock_lo // 20), max(2, stock_lo // 5))
        lead_time = int(lead_hi * RNG.uniform(1.5, 2.5))
    else:
        on_hand = RNG.randint(stock_lo, stock_hi)
        lead_time = RNG.randint(lead_lo, lead_hi)

    allocated = int(on_hand * RNG.uniform(0.05, 0.3))
    available = max(0, on_hand - allocated)
    shipable = available > 0
    warehouse = RNG.choice(WAREHOUSES)

    return on_hand, allocated, available, warehouse, shipable, lead_time


def gen_sales_history(category: str, lifecycle: str):
    stock_ceiling = CATEGORY_PROFILE[category]["stock"][1]

    if lifecycle == "Obsolete":
        days_ago = RNG.randint(400, 900)
        ttm = RNG.choice([0, 0, 0, 1, 2])
    elif lifecycle == "Life-Time-Buy":
        days_ago = RNG.randint(60, 300)
        ttm = RNG.randint(1, 10)
    else:
        days_ago = RNG.randint(0, 45)
        if stock_ceiling >= 50000:
            ttm = RNG.randint(400, 1500)
        elif stock_ceiling < 5000:
            ttm = RNG.randint(5, 50)
        else:
            ttm = RNG.randint(20, 300)

    last_sold_date = (TODAY - timedelta(days=days_ago)).isoformat()
    return last_sold_date, ttm


def build():
    DB_PATH.parent.mkdir(exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text())

    # Lookup tables -- insert in fixed order so id == list index + 1.
    conn.executemany("INSERT INTO categories (id, name) VALUES (?, ?)", list(enumerate(CATEGORIES, start=1)))
    category_ids = {name: i for i, name in enumerate(CATEGORIES, start=1)}

    conn.executemany(
        "INSERT INTO aircraft_programs (id, code, name) VALUES (?, ?, ?)",
        [(i, code, name) for i, (code, name) in enumerate(AIRCRAFT_PROGRAMS, start=1)],
    )
    program_ids = {code: i for i, (code, _) in enumerate(AIRCRAFT_PROGRAMS, start=1)}

    conn.executemany("INSERT INTO manufacturers (id, name) VALUES (?, ?)", list(enumerate(MANUFACTURERS, start=1)))
    manufacturer_ids = {name: i for i, name in enumerate(MANUFACTURERS, start=1)}

    conn.executemany("INSERT INTO lifecycle_statuses (id, name) VALUES (?, ?)", list(enumerate(LIFECYCLE_STATUSES, start=1)))
    lifecycle_ids = {name: i for i, name in enumerate(LIFECYCLE_STATUSES, start=1)}

    conn.executemany(
        "INSERT INTO warehouses (id, name, location) VALUES (?, ?, ?)",
        [(i, name, name) for i, name in enumerate(WAREHOUSES, start=1)],
    )
    warehouse_ids = {name: i for i, name in enumerate(WAREHOUSES, start=1)}

    # Pricing policy tables
    conn.execute(
        "INSERT INTO policy_global VALUES (1, ?, ?, ?, ?, ?)",
        (
            POLICY_GLOBAL["min_margin_pct"], POLICY_GLOBAL["target_margin_pct"], POLICY_GLOBAL["max_margin_pct"],
            POLICY_GLOBAL["max_price_increase_pct_without_approval"], POLICY_GLOBAL["max_price_decrease_pct_without_approval"],
        ),
    )
    for category, override in CATEGORY_OVERRIDES.items():
        conn.execute(
            "INSERT INTO category_policy_overrides (category_id, target_margin_pct, min_margin_pct) VALUES (?, ?, ?)",
            (category_ids[category], override.get("target_margin_pct"), override.get("min_margin_pct")),
        )
    for lifecycle, override in LIFECYCLE_OVERRIDES.items():
        conn.execute(
            "INSERT INTO lifecycle_policy_overrides (lifecycle_status_id, min_margin_pct, requires_approval, note) VALUES (?, ?, ?, ?)",
            (lifecycle_ids[lifecycle], override.get("min_margin_pct"), int(override.get("requires_approval", False)), override.get("note")),
        )

    # ---------- Generate parts ----------
    category_sequence = []
    for category, weight in zip(CATEGORIES, CATEGORY_WEIGHTS):
        category_sequence.extend([category] * weight)
    RNG.shuffle(category_sequence)
    assert len(category_sequence) == PART_COUNT

    stats = {"Active": 0, "Obsolete": 0, "Life-Time-Buy": 0, "flagged": 0}

    for category in category_sequence:
        part_number = gen_part_number(category)
        description = gen_description(category)
        program_code = RNG.choice(AIRCRAFT_PROGRAMS)[0]
        manufacturer = RNG.choice(CATEGORY_PROFILE[category]["mfrs"])
        lifecycle = RNG.choices(LIFECYCLE_STATUSES, weights=LIFECYCLE_WEIGHTS, k=1)[0]
        stats[lifecycle] += 1

        conn.execute(
            "INSERT INTO parts (part_number, description, category_id, aircraft_program_id, manufacturer_id, lifecycle_status_id, uom) "
            "VALUES (?, ?, ?, ?, ?, ?, 'EA')",
            (part_number, description, category_ids[category], program_ids[program_code], manufacturer_ids[manufacturer], lifecycle_ids[lifecycle]),
        )

        cost_lo, cost_hi = CATEGORY_PROFILE[category]["cost"]
        standard_cost = round(RNG.uniform(cost_lo, cost_hi), 2)
        actual_cost = round(standard_cost * RNG.uniform(0.95, 1.08), 2)
        conn.execute(
            "INSERT INTO costs (part_number, standard_cost, actual_cost, currency) VALUES (?, ?, ?, 'USD')",
            (part_number, standard_cost, actual_cost),
        )

        on_hand, allocated, available, warehouse, shipable, lead_time = gen_inventory(category, lifecycle)
        conn.execute(
            "INSERT INTO inventory (part_number, on_hand_qty, allocated_qty, available_qty, warehouse_id, shipable, lead_time_days) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (part_number, on_hand, allocated, available, warehouse_ids[warehouse], int(shipable), lead_time),
        )

        list_price = gen_pricing(category, lifecycle, actual_cost)
        last_sold_price = round(list_price * RNG.uniform(0.96, 0.995), 2)
        last_sold_date, ttm = gen_sales_history(category, lifecycle)
        conn.execute(
            "INSERT INTO price_history (part_number, current_list_price, last_sold_price, last_sold_date, transactions_ttm, currency) "
            "VALUES (?, ?, ?, ?, ?, 'USD')",
            (part_number, list_price, last_sold_price, last_sold_date, ttm),
        )

        thresholds = resolve_thresholds(category, lifecycle)
        margin_pct = (list_price - actual_cost) / list_price * 100
        recommended = round(actual_cost / (1 - thresholds["target_margin_pct"] / 100), 2)
        price_change_pct = (recommended - list_price) / list_price * 100
        flagged = (
            margin_pct < thresholds["min_margin_pct"]
            or lifecycle in LIFECYCLE_OVERRIDES
            or abs(price_change_pct) > thresholds["max_price_increase_pct_without_approval"]
        )
        if flagged:
            stats["flagged"] += 1

    conn.commit()
    conn.close()

    print(f"Built {DB_PATH} with {PART_COUNT} parts.")
    print(f"  Lifecycle: {stats['Active']} Active, {stats['Obsolete']} Obsolete, {stats['Life-Time-Buy']} Life-Time-Buy")
    print(f"  Would route to pricing leader review: {stats['flagged']} of {PART_COUNT} ({stats['flagged'] / PART_COUNT * 100:.0f}%)")


if __name__ == "__main__":
    build()
