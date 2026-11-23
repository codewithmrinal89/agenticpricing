"""Supervisor Agent (Orchestrator).

This is plain Python, not an LLM call -- the supervisor's job is to plan
and sequence work, not to reason freely. It calls each specialist agent in
order, merges their output into one facts packet, and applies the Decision
Gate: clean requests auto-approve, flagged requests route to pricing
leader review with a drafted approval request.

This mirrors the top two layers of the target architecture: the Supervisor
Agent box (orchestration) and the Decision Gate box (routing).
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone

from agents.approval_agent import draft_approval_request
from agents.audit_log import log_decision
from agents.cost_margin_agent import gather_cost_and_price
from agents.data_retrieval_agent import gather_part_master
from agents.inventory_agent import gather_inventory_status
from agents.llm_client import MODEL
from agents.pricing_strategy_agent import recommend_price
from agents.tracing import PipelineRunRecorder


def gather_all_facts(part_number: str) -> dict:
    """Delegate to the three data agents and merge their results into one facts packet."""
    master = gather_part_master(part_number)
    inventory = gather_inventory_status(part_number)
    cost_and_price = gather_cost_and_price(part_number)
    return {**master, **inventory, **cost_and_price}


def process_pricing_request_stream(part_number: str):
    """Run the full pipeline for one part, yielding a progress event before and
    after each agent runs, then a final {"type": "result", "data": record}.

    This is what lets the web UI show which agent is working right now --
    process_pricing_request() below just drains this generator and returns
    the final record, for callers (the CLI) that don't need live progress.
    """
    request_id = str(uuid.uuid4())
    started_at = time.monotonic()
    print(f"\n[SUPERVISOR] New pricing request {request_id} received for part {part_number}")

    run = PipelineRunRecorder(request_id, part_number, MODEL)
    run.__enter__()

    def step_start(agent, execution_id):
        print(f"[SUPERVISOR] -- delegating to {agent}...")
        return {
            "type": "step_start",
            "agent": agent,
            "part_number": part_number,
            "pipeline_run_id": request_id,
            "agent_execution_id": execution_id,
        }

    def step_done(agent, execution_id, status="completed"):
        return {
            "type": "step_done",
            "agent": agent,
            "part_number": part_number,
            "pipeline_run_id": request_id,
            "agent_execution_id": execution_id,
            "status": status,
        }

    try:
        execution = run.agent("Enterprise Data Retrieval Agent")
        with execution:
            yield step_start(execution.agent_name, execution.id)
            master = gather_part_master(part_number, execution=execution)
            execution.set_output_summary(master)
        yield step_done(execution.agent_name, execution.id)

        execution = run.agent("Inventory & Shipability Agent")
        with execution:
            yield step_start(execution.agent_name, execution.id)
            inventory = gather_inventory_status(part_number, execution=execution)
            execution.set_output_summary(inventory)
        yield step_done(execution.agent_name, execution.id)

        execution = run.agent("Cost & Margin Agent")
        with execution:
            yield step_start(execution.agent_name, execution.id)
            cost_and_price = gather_cost_and_price(part_number, execution=execution)
            execution.set_output_summary(cost_and_price)
        yield step_done(execution.agent_name, execution.id)

        facts = {**master, **inventory, **cost_and_price}

        execution = run.agent("Pricing Strategy Agent")
        with execution:
            yield step_start(execution.agent_name, execution.id)
            pricing = recommend_price(facts, execution=execution)
            execution.set_output_summary(pricing)
        yield step_done(execution.agent_name, execution.id)

        execution = run.agent("Decision Gate")
        with execution:
            yield step_start(execution.agent_name, execution.id)
            if pricing["requires_approval"]:
                decision = "PENDING_PRICING_LEADER_APPROVAL"
                print(f"[SUPERVISOR] Decision Gate: EXCEPTION -- routing to pricing leader review ({len(pricing['flags'])} flag(s))")
            else:
                decision = "AUTO_APPROVED"
                print("[SUPERVISOR] Decision Gate: standard, compliant case -- auto-approved")
            execution.set_output_summary({"decision": decision, "flag_count": len(pricing["flags"])})
        yield step_done(execution.agent_name, execution.id)

        if decision == "PENDING_PRICING_LEADER_APPROVAL":
            execution = run.agent("Approval Agent")
            with execution:
                yield step_start(execution.agent_name, execution.id)
                approval_request = draft_approval_request(pricing, execution=execution)
                execution.set_output_summary({"approval_request": approval_request})
            yield step_done(execution.agent_name, execution.id)
        else:
            approval_request = None
    except BaseException:
        # BaseException, not Exception: a client disconnecting mid-stream
        # throws GeneratorExit in here (which isn't an Exception subclass),
        # and the pipeline_runs row must still be finalized rather than left
        # stuck as 'running' forever.
        run.__exit__(*sys.exc_info())
        raise
    else:
        run.__exit__(None, None, None)

    duration_seconds = round(time.monotonic() - started_at, 2)
    print(f"[SUPERVISOR] Done. Final decision: {decision} ({duration_seconds}s)\n")

    record = {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": duration_seconds,
        "part_number": part_number,
        "description": pricing["description"],
        "category": pricing["category"],
        "lifecycle_status": pricing["lifecycle_status"],
        "decision": decision,
        "actual_cost": pricing["actual_cost"],
        "current_list_price": pricing["current_list_price"],
        "recommended_price": pricing["recommended_price"],
        "current_margin_pct": pricing["current_margin_pct"],
        "price_change_pct": pricing["price_change_pct"],
        "thresholds": pricing["thresholds"],
        "scenarios": pricing["scenarios"],
        "flags": pricing["flags"],
        "narrative": pricing["narrative"],
        "decision_summary": pricing["decision_summary"],
        "margin_analysis": pricing["margin_analysis"],
        "lifecycle_analysis": pricing["lifecycle_analysis"],
        "price_change_analysis": pricing["price_change_analysis"],
        "recommendation": pricing["recommendation"],
        "approval_request": approval_request,
    }
    log_decision(record)
    print(f"[SUPERVISOR] Decision logged to audit trail (request_id={request_id})")

    yield {"type": "result", "data": record}


def process_pricing_request(part_number: str) -> dict:
    """Run the full pipeline for one part number and return the final decision."""
    for event in process_pricing_request_stream(part_number):
        if event["type"] == "result":
            return event["data"]
    raise RuntimeError("pipeline ended without producing a result")


def process_pricing_requests(part_numbers: list[str]) -> list[dict]:
    """Run the pipeline for multiple part numbers, one at a time.

    Sequential on purpose: each request already makes 5-6 LLM calls, so running
    several requests concurrently multiplies rate-limit risk fast. A failure
    on one part doesn't stop the batch -- it's recorded and the rest continue.
    """
    results = []
    for i, part_number in enumerate(part_numbers, start=1):
        print(f"\n[SUPERVISOR] ===== Batch {i}/{len(part_numbers)}: {part_number} =====")
        try:
            results.append(process_pricing_request(part_number))
        except Exception as e:
            print(f"[SUPERVISOR] FAILED for {part_number}: {e}")
            results.append({"part_number": part_number, "decision": "ERROR", "error": str(e)})
    return results


if __name__ == "__main__":
    part_numbers = sys.argv[1:] or ["GE90-FB-7421"]
    results = process_pricing_requests(part_numbers)
    print(json.dumps(results, indent=2))
