"""Inventory & Shipability Agent.

Owns one system boundary: on-hand/available quantity, shipability, and lead
time -- in a real system, this would be a separate inventory/logistics
service from the parts master.
"""
from agents.llm_client import run_tool_calling_agent
from agents.tools import INVENTORY_TOOL_SCHEMAS

SYSTEM_INSTRUCTION = """You are the Inventory & Shipability Agent for an aerospace spare parts
pricing system. Given a part number, call the available tool to check its inventory status.

Respond with ONLY a single JSON object (no markdown fences, no extra text) with these
exact keys: part_number, available_qty, shipable, lead_time_days

If the tool returns an error, include an "error" key explaining what's missing
instead of guessing values.
"""


def gather_inventory_status(part_number: str, execution=None) -> dict:
    """Run the Inventory & Shipability Agent for one part number."""
    print("--- Inventory & Shipability Agent ---")
    result = run_tool_calling_agent(
        system_instruction=SYSTEM_INSTRUCTION,
        user_message=f"Check inventory and shipability for part number {part_number}.",
        tool_schemas=INVENTORY_TOOL_SCHEMAS,
        execution=execution,
    )
    print("--------------------------------------")
    return result


if __name__ == "__main__":
    import json
    import sys

    part_number = sys.argv[1] if len(sys.argv) > 1 else "GE90-FB-7421"
    print(json.dumps(gather_inventory_status(part_number), indent=2))
