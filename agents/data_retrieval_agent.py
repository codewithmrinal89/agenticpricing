"""Enterprise Data Retrieval Agent.

Owns one system boundary: the parts master (in a real system, this would be
the ERP/Oracle parts catalog). Given a part number, pulls description,
category, aircraft program, and lifecycle status.
"""
from agents.llm_client import run_tool_calling_agent
from agents.tools import DATA_RETRIEVAL_TOOL_SCHEMAS

SYSTEM_INSTRUCTION = """You are the Enterprise Data Retrieval Agent for an aerospace spare parts
pricing system. Given a part number, call the available tool to pull its master data.

Respond with ONLY a single JSON object (no markdown fences, no extra text) with these
exact keys: part_number, description, category, aircraft_program, lifecycle_status

If the tool returns an error, include an "error" key explaining what's missing
instead of guessing values.
"""


def gather_part_master(part_number: str, execution=None) -> dict:
    """Run the Enterprise Data Retrieval Agent for one part number.

    `execution` is an optional agents.tracing.AgentExecutionRecorder for the
    current pipeline step; when provided, token usage and tool calls are
    persisted to it.
    """
    print("--- Enterprise Data Retrieval Agent ---")
    result = run_tool_calling_agent(
        system_instruction=SYSTEM_INSTRUCTION,
        user_message=f"Pull master data for part number {part_number}.",
        tool_schemas=DATA_RETRIEVAL_TOOL_SCHEMAS,
        execution=execution,
    )
    print("----------------------------------------")
    return result


if __name__ == "__main__":
    import json
    import sys

    part_number = sys.argv[1] if len(sys.argv) > 1 else "GE90-FB-7421"
    print(json.dumps(gather_part_master(part_number), indent=2))
