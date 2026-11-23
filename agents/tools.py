"""Lookup functions the agent can call as tools.

Each one is a SQL query against data/pricing.db (see scripts/build_database.py
for the schema and seed data) -- not an in-memory dict. Unlike Gemini (which
can build a tool schema straight from a function's docstring and type
hints), the OpenAI Chat Completions API needs an explicit JSON schema per
tool -- TOOL_SCHEMAS below. TOOL_FUNCTIONS maps each schema's name back to
the actual Python function so the agent's manual tool-calling loop can
execute whichever one the model asks for.
"""
from agents.db import get_connection


def get_part_master(part_number: str) -> dict:
    """Look up master data for a spare part: description, category, aircraft program, and lifecycle status.

    Args:
        part_number: The part number to look up, e.g. "GE90-FB-7421".
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT p.part_number, p.description, c.name AS category, ap.code AS aircraft_program,
               ls.name AS lifecycle_status, p.uom, m.name AS manufacturer
        FROM parts p
        JOIN categories c ON c.id = p.category_id
        JOIN aircraft_programs ap ON ap.id = p.aircraft_program_id
        JOIN lifecycle_statuses ls ON ls.id = p.lifecycle_status_id
        JOIN manufacturers m ON m.id = p.manufacturer_id
        WHERE p.part_number = ?
        """,
        (part_number,),
    ).fetchone()
    conn.close()

    if row is None:
        return {"error": f"Part {part_number} not found in parts master."}
    return dict(row)


def get_cost_data(part_number: str) -> dict:
    """Look up standard and actual manufacturing cost for a spare part.

    Args:
        part_number: The part number to look up.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT part_number, standard_cost, actual_cost, currency FROM costs WHERE part_number = ?",
        (part_number,),
    ).fetchone()
    conn.close()

    if row is None:
        return {"error": f"No cost data found for {part_number}."}
    return dict(row)


def get_inventory_status(part_number: str) -> dict:
    """Look up on-hand quantity, available quantity, shipability, and lead time for a spare part.

    Args:
        part_number: The part number to look up.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT i.part_number, i.on_hand_qty, i.allocated_qty, i.available_qty,
               w.name AS warehouse, i.shipable, i.lead_time_days
        FROM inventory i
        JOIN warehouses w ON w.id = i.warehouse_id
        WHERE i.part_number = ?
        """,
        (part_number,),
    ).fetchone()
    conn.close()

    if row is None:
        return {"error": f"No inventory data found for {part_number}."}
    result = dict(row)
    result["shipable"] = bool(result["shipable"])
    return result


def get_price_history(part_number: str) -> dict:
    """Look up current list price, last sold price/date, and transaction volume for a spare part.

    Args:
        part_number: The part number to look up.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT part_number, current_list_price, last_sold_price, last_sold_date, transactions_ttm, currency
        FROM price_history WHERE part_number = ?
        """,
        (part_number,),
    ).fetchone()
    conn.close()

    if row is None:
        return {"error": f"No price history found for {part_number}."}
    return dict(row)


def list_all_parts() -> list[dict]:
    """Return the full parts master list, sorted by part number. Used by the web UI's part picker."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT p.part_number, p.description, c.name AS category, ap.code AS aircraft_program,
               ls.name AS lifecycle_status, p.uom, m.name AS manufacturer
        FROM parts p
        JOIN categories c ON c.id = p.category_id
        JOIN aircraft_programs ap ON ap.id = p.aircraft_program_id
        JOIN lifecycle_statuses ls ON ls.id = p.lifecycle_status_id
        JOIN manufacturers m ON m.id = p.manufacturer_id
        ORDER BY p.part_number
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_all_categories() -> list[str]:
    """Distinct category names from the catalog -- used to populate the
    category picker when an admin assigns an approver."""
    conn = get_connection()
    rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
    conn.close()
    return [row["name"] for row in rows]


def _schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "part_number": {"type": "string", "description": "The part number to look up."}
                },
                "required": ["part_number"],
            },
        },
    }


_PART_MASTER_SCHEMA = _schema("get_part_master", "Look up master data for a spare part: description, category, aircraft program, and lifecycle status.")
_COST_DATA_SCHEMA = _schema("get_cost_data", "Look up standard and actual manufacturing cost for a spare part.")
_INVENTORY_SCHEMA = _schema("get_inventory_status", "Look up on-hand quantity, available quantity, shipability, and lead time for a spare part.")
_PRICE_HISTORY_SCHEMA = _schema("get_price_history", "Look up current list price, last sold price/date, and transaction volume for a spare part.")

# Each specialist agent gets only the tool schema(s) relevant to its job --
# this mirrors the diagram's system boundaries: Enterprise Data Retrieval,
# Inventory & Shipability, and Cost & Margin each own a different "system."
DATA_RETRIEVAL_TOOL_SCHEMAS = [_PART_MASTER_SCHEMA]
INVENTORY_TOOL_SCHEMAS = [_INVENTORY_SCHEMA]
COST_MARGIN_TOOL_SCHEMAS = [_COST_DATA_SCHEMA, _PRICE_HISTORY_SCHEMA]

TOOL_FUNCTIONS = {
    "get_part_master": get_part_master,
    "get_cost_data": get_cost_data,
    "get_inventory_status": get_inventory_status,
    "get_price_history": get_price_history,
}
