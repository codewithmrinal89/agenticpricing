"""Shared test fixtures.

Every test that touches the database gets an isolated temp SQLite file via
`temp_db` -- never the real data/pricing.db -- so test runs can't corrupt
real audit history or pending approvals.
"""
import sqlite3

import pytest

import agents.audit_log as audit_log_module
import agents.db as db_module


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_pricing.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    yield db_path


@pytest.fixture
def temp_log(tmp_path, monkeypatch):
    log_path = tmp_path / "test_audit.jsonl"
    monkeypatch.setattr(audit_log_module, "LOG_PATH", log_path)
    yield log_path


@pytest.fixture
def temp_catalog_db(temp_db):
    """A temp DB with the minimal catalog tables policy_store.py needs
    (categories, lifecycle_statuses, policy_global, and the two override
    tables), seeded with a couple of rows -- without pulling in the full
    parts/inventory schema, which policy_store never touches."""
    conn = sqlite3.connect(temp_db)
    conn.executescript(
        """
        CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE lifecycle_statuses (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);

        CREATE TABLE policy_global (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            min_margin_pct REAL NOT NULL,
            target_margin_pct REAL NOT NULL,
            max_margin_pct REAL NOT NULL,
            max_price_increase_pct_without_approval REAL NOT NULL,
            max_price_decrease_pct_without_approval REAL NOT NULL
        );

        CREATE TABLE category_policy_overrides (
            category_id INTEGER PRIMARY KEY REFERENCES categories(id),
            target_margin_pct REAL,
            min_margin_pct REAL
        );

        CREATE TABLE lifecycle_policy_overrides (
            lifecycle_status_id INTEGER PRIMARY KEY REFERENCES lifecycle_statuses(id),
            min_margin_pct REAL,
            requires_approval INTEGER NOT NULL DEFAULT 0 CHECK (requires_approval IN (0, 1)),
            note TEXT
        );

        INSERT INTO categories (id, name) VALUES (1, 'Avionics'), (2, 'Structural');
        INSERT INTO lifecycle_statuses (id, name) VALUES (1, 'Active'), (2, 'Obsolete');
        INSERT INTO policy_global (id, min_margin_pct, target_margin_pct, max_margin_pct,
            max_price_increase_pct_without_approval, max_price_decrease_pct_without_approval)
            VALUES (1, 25.0, 40.0, 60.0, 10.0, 10.0);
        """
    )
    conn.commit()
    conn.close()
    yield temp_db
