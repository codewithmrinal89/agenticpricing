-- Normalized schema for the pricing agent MVP.
-- Lookup tables (categories, aircraft_programs, manufacturers, lifecycle_statuses,
-- warehouses) exist so parts/inventory reference IDs, not repeated strings --
-- this is what makes it "proper relational" rather than a JSON dump in SQLite.

PRAGMA foreign_keys = ON;

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE aircraft_programs (
    id   INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);

CREATE TABLE manufacturers (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE lifecycle_statuses (
    id   INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE warehouses (
    id       INTEGER PRIMARY KEY,
    name     TEXT UNIQUE NOT NULL,
    location TEXT NOT NULL
);

CREATE TABLE parts (
    part_number         TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    category_id         INTEGER NOT NULL REFERENCES categories(id),
    aircraft_program_id INTEGER NOT NULL REFERENCES aircraft_programs(id),
    manufacturer_id      INTEGER NOT NULL REFERENCES manufacturers(id),
    lifecycle_status_id INTEGER NOT NULL REFERENCES lifecycle_statuses(id),
    uom                 TEXT NOT NULL DEFAULT 'EA'
);
CREATE INDEX idx_parts_category ON parts(category_id);
CREATE INDEX idx_parts_program ON parts(aircraft_program_id);
CREATE INDEX idx_parts_lifecycle ON parts(lifecycle_status_id);

CREATE TABLE costs (
    part_number   TEXT PRIMARY KEY REFERENCES parts(part_number),
    standard_cost REAL NOT NULL,
    actual_cost   REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'USD'
);

CREATE TABLE inventory (
    part_number    TEXT PRIMARY KEY REFERENCES parts(part_number),
    on_hand_qty    INTEGER NOT NULL,
    allocated_qty  INTEGER NOT NULL,
    available_qty  INTEGER NOT NULL,
    warehouse_id   INTEGER NOT NULL REFERENCES warehouses(id),
    shipable       INTEGER NOT NULL CHECK (shipable IN (0, 1)),
    lead_time_days INTEGER NOT NULL
);
CREATE INDEX idx_inventory_warehouse ON inventory(warehouse_id);

CREATE TABLE price_history (
    part_number        TEXT PRIMARY KEY REFERENCES parts(part_number),
    current_list_price REAL NOT NULL,
    last_sold_price     REAL NOT NULL,
    last_sold_date      TEXT NOT NULL,
    transactions_ttm    INTEGER NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'USD'
);

-- Pricing policy, normalized instead of a nested JSON blob.
CREATE TABLE policy_global (
    id                                       INTEGER PRIMARY KEY CHECK (id = 1),
    min_margin_pct                           REAL NOT NULL,
    target_margin_pct                        REAL NOT NULL,
    max_margin_pct                           REAL NOT NULL,
    max_price_increase_pct_without_approval REAL NOT NULL,
    max_price_decrease_pct_without_approval REAL NOT NULL
);

CREATE TABLE category_policy_overrides (
    category_id       INTEGER PRIMARY KEY REFERENCES categories(id),
    target_margin_pct REAL,
    min_margin_pct    REAL
);

CREATE TABLE lifecycle_policy_overrides (
    lifecycle_status_id INTEGER PRIMARY KEY REFERENCES lifecycle_statuses(id),
    min_margin_pct       REAL,
    requires_approval    INTEGER NOT NULL DEFAULT 0 CHECK (requires_approval IN (0, 1)),
    note                 TEXT
);
