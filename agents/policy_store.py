"""Read/write access to the pricing policy tables (policy_global,
category_policy_overrides, lifecycle_policy_overrides).

These tables are part of the catalog schema (scripts/schema.sql) and are
populated by scripts/build_database.py, so -- unlike users_store.py /
tracing.py -- there's no lazy CREATE TABLE here; they're assumed to
already exist. get_policy() reassembles the same {global,
category_overrides, lifecycle_overrides} shape pricing_engine.py has
always used internally; the write functions back the admin UI's policy
editor.
"""
from agents.db import get_connection


def get_policy() -> dict:
    conn = get_connection()

    g = conn.execute("SELECT * FROM policy_global WHERE id = 1").fetchone()
    global_policy = {
        "min_margin_pct": g["min_margin_pct"],
        "target_margin_pct": g["target_margin_pct"],
        "max_margin_pct": g["max_margin_pct"],
        "max_price_increase_pct_without_approval": g["max_price_increase_pct_without_approval"],
        "max_price_decrease_pct_without_approval": g["max_price_decrease_pct_without_approval"],
    }

    category_overrides = {}
    for row in conn.execute(
        "SELECT c.name, o.target_margin_pct, o.min_margin_pct "
        "FROM category_policy_overrides o JOIN categories c ON c.id = o.category_id"
    ):
        override = {}
        if row["target_margin_pct"] is not None:
            override["target_margin_pct"] = row["target_margin_pct"]
        if row["min_margin_pct"] is not None:
            override["min_margin_pct"] = row["min_margin_pct"]
        category_overrides[row["name"]] = override

    lifecycle_overrides = {}
    for row in conn.execute(
        "SELECT ls.name, o.min_margin_pct, o.requires_approval, o.note "
        "FROM lifecycle_policy_overrides o JOIN lifecycle_statuses ls ON ls.id = o.lifecycle_status_id"
    ):
        override = {"requires_approval": bool(row["requires_approval"])}
        if row["min_margin_pct"] is not None:
            override["min_margin_pct"] = row["min_margin_pct"]
        if row["note"]:
            override["note"] = row["note"]
        lifecycle_overrides[row["name"]] = override

    conn.close()
    return {"global": global_policy, "category_overrides": category_overrides, "lifecycle_overrides": lifecycle_overrides}


def update_global_policy(fields: dict) -> dict:
    """Partial update of the singleton policy_global row. `fields` may
    contain any subset of: min_margin_pct, target_margin_pct,
    max_margin_pct, max_price_increase_pct_without_approval,
    max_price_decrease_pct_without_approval."""
    allowed = {
        "min_margin_pct",
        "target_margin_pct",
        "max_margin_pct",
        "max_price_increase_pct_without_approval",
        "max_price_decrease_pct_without_approval",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_policy()["global"]

    conn = get_connection()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE policy_global SET {set_clause} WHERE id = 1", list(updates.values()))
    conn.commit()
    conn.close()
    return get_policy()["global"]


def _category_id(conn, category: str) -> int | None:
    row = conn.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()
    return row["id"] if row else None


def set_category_override(category: str, target_margin_pct: float | None, min_margin_pct: float | None) -> None:
    conn = get_connection()
    category_id = _category_id(conn, category)
    if category_id is None:
        conn.close()
        raise ValueError(f"Unknown category {category!r}")
    conn.execute(
        """INSERT INTO category_policy_overrides (category_id, target_margin_pct, min_margin_pct)
           VALUES (?, ?, ?)
           ON CONFLICT(category_id) DO UPDATE SET
               target_margin_pct = excluded.target_margin_pct,
               min_margin_pct = excluded.min_margin_pct""",
        (category_id, target_margin_pct, min_margin_pct),
    )
    conn.commit()
    conn.close()


def clear_category_override(category: str) -> None:
    conn = get_connection()
    category_id = _category_id(conn, category)
    if category_id is not None:
        conn.execute("DELETE FROM category_policy_overrides WHERE category_id = ?", (category_id,))
        conn.commit()
    conn.close()


def _lifecycle_status_id(conn, status: str) -> int | None:
    row = conn.execute("SELECT id FROM lifecycle_statuses WHERE name = ?", (status,)).fetchone()
    return row["id"] if row else None


def set_lifecycle_override(status: str, min_margin_pct: float | None, requires_approval: bool, note: str | None) -> None:
    conn = get_connection()
    status_id = _lifecycle_status_id(conn, status)
    if status_id is None:
        conn.close()
        raise ValueError(f"Unknown lifecycle status {status!r}")
    conn.execute(
        """INSERT INTO lifecycle_policy_overrides (lifecycle_status_id, min_margin_pct, requires_approval, note)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(lifecycle_status_id) DO UPDATE SET
               min_margin_pct = excluded.min_margin_pct,
               requires_approval = excluded.requires_approval,
               note = excluded.note""",
        (status_id, min_margin_pct, 1 if requires_approval else 0, note),
    )
    conn.commit()
    conn.close()


def clear_lifecycle_override(status: str) -> None:
    conn = get_connection()
    status_id = _lifecycle_status_id(conn, status)
    if status_id is not None:
        conn.execute("DELETE FROM lifecycle_policy_overrides WHERE lifecycle_status_id = ?", (status_id,))
        conn.commit()
    conn.close()


def list_lifecycle_statuses() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT name FROM lifecycle_statuses ORDER BY name").fetchall()
    conn.close()
    return [r["name"] for r in rows]
