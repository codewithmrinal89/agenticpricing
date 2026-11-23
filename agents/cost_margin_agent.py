"""Cost & Margin Agent.

Owns one system boundary: cost and price history -- in a real system, this
would be a cost-accounting system plus historical sales data, separate from
both the parts master and inventory systems. Uses two tools, unlike the
other two data agents, since this is genuinely "cost AND price history"
per the diagram's own description of this box.
"""
from agents.llm_client import run_tool_calling_agent
from agents.tools import COST_MARGIN_TOOL_SCHEMAS

SYSTEM_INSTRUCTION = """You are the Cost & Margin Agent for an aerospace spare parts pricing
system. Given a part number, call the available tools to pull its cost data AND price history.

Respond with ONLY a single JSON object (no markdown fences, no extra text) with these
exact keys: part_number, actual_cost, current_list_price, last_sold_date, transactions_ttm

If a tool returns an error, include an "error" key explaining what's missing
instead of guessing values.
"""


def gather_cost_and_price(part_number: str, execution=None) -> dict:
    """Run the Cost & Margin Agent for one part number."""
    print("--- Cost & Margin Agent ---")
    result = run_tool_calling_agent(
        system_instruction=SYSTEM_INSTRUCTION,
        user_message=f"Pull cost data and price history for part number {part_number}.",
        tool_schemas=COST_MARGIN_TOOL_SCHEMAS,
        execution=execution,
    )
    print("----------------------------")
    return result


if __name__ == "__main__":
    import json
    import sys

    part_number = sys.argv[1] if len(sys.argv) > 1 else "GE90-FB-7421"
    print(json.dumps(gather_cost_and_price(part_number), indent=2))
