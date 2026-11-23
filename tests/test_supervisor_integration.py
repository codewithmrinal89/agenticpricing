"""Integration tests for the instrumented supervisor pipeline.

The 5 LLM-calling agent functions are monkeypatched with canned responses
so these tests run fast, free, and deterministically -- no real OpenAI
calls. This exercises the orchestration/tracing wiring (SSE event shape,
DB persistence, audit-log regression), not agent prompt quality.
"""
import agents.audit_log as audit_log_module
import agents.supervisor as supervisor
from agents.tracing import list_agent_executions, list_pipeline_runs

FAKE_MASTER = {
    "part_number": "PN-TEST",
    "description": "Test Bracket",
    "category": "Structural",
    "aircraft_program": "A320",
    "lifecycle_status": "Active",
}
FAKE_INVENTORY = {"part_number": "PN-TEST", "available_qty": 10, "shipable": True, "lead_time_days": 5}
FAKE_COST = {
    "part_number": "PN-TEST",
    "actual_cost": 100.0,
    "current_list_price": 150.0,
    "last_sold_date": "2026-01-01",
    "transactions_ttm": 20,
}
FAKE_PRICING = {
    "description": "Test Bracket",
    "category": "Structural",
    "lifecycle_status": "Active",
    "actual_cost": 100.0,
    "current_list_price": 150.0,
    "recommended_price": 155.0,
    "current_margin_pct": 33.3,
    "price_change_pct": 3.3,
    "thresholds": {},
    "scenarios": {},
    "flags": [],
    "requires_approval": False,
    "narrative": "n",
    "decision_summary": "d",
    "margin_analysis": "m",
    "lifecycle_analysis": "l",
    "price_change_analysis": "p",
    "recommendation": "r",
}


def _patch_happy_path(monkeypatch):
    monkeypatch.setattr(supervisor, "gather_part_master", lambda pn, execution=None: FAKE_MASTER)
    monkeypatch.setattr(supervisor, "gather_inventory_status", lambda pn, execution=None: FAKE_INVENTORY)
    monkeypatch.setattr(supervisor, "gather_cost_and_price", lambda pn, execution=None: FAKE_COST)
    monkeypatch.setattr(supervisor, "recommend_price", lambda facts, execution=None: FAKE_PRICING)


def test_stream_events_carry_run_and_execution_ids(temp_db, monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log_module, "LOG_PATH", tmp_path / "audit.jsonl")
    _patch_happy_path(monkeypatch)

    events = list(supervisor.process_pricing_request_stream("PN-TEST"))

    step_events = [e for e in events if e["type"] in ("step_start", "step_done")]
    assert len(step_events) > 0
    run_ids = {e["pipeline_run_id"] for e in step_events}
    assert len(run_ids) == 1  # every event in one request shares the same run id

    for e in step_events:
        assert "agent_execution_id" in e and e["agent_execution_id"]

    result_events = [e for e in events if e["type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["data"]["decision"] == "AUTO_APPROVED"


def test_happy_path_persists_five_agent_executions(temp_db, monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log_module, "LOG_PATH", tmp_path / "audit.jsonl")
    _patch_happy_path(monkeypatch)

    events = list(supervisor.process_pricing_request_stream("PN-TEST"))
    run_id = next(e["pipeline_run_id"] for e in events if e["type"] == "step_start")

    executions = list_agent_executions(run_id)
    names = [e["agent_name"] for e in executions]
    # Auto-approved path: no Approval Agent step.
    assert names == [
        "Enterprise Data Retrieval Agent",
        "Inventory & Shipability Agent",
        "Cost & Margin Agent",
        "Pricing Strategy Agent",
        "Decision Gate",
    ]
    assert all(e["status"] == "completed" for e in executions)

    run_row = next(r for r in list_pipeline_runs(limit=10) if r["id"] == run_id)
    assert run_row["status"] == "completed"


def test_pending_approval_path_adds_approval_agent_step(temp_db, monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log_module, "LOG_PATH", tmp_path / "audit.jsonl")
    _patch_happy_path(monkeypatch)
    flagged_pricing = {**FAKE_PRICING, "requires_approval": True, "flags": ["margin below floor"]}
    monkeypatch.setattr(supervisor, "recommend_price", lambda facts, execution=None: flagged_pricing)
    monkeypatch.setattr(supervisor, "draft_approval_request", lambda pricing, execution=None: "Please review.")

    events = list(supervisor.process_pricing_request_stream("PN-TEST"))
    run_id = next(e["pipeline_run_id"] for e in events if e["type"] == "step_start")

    names = [e["agent_name"] for e in list_agent_executions(run_id)]
    assert names[-1] == "Approval Agent"

    result = next(e for e in events if e["type"] == "result")["data"]
    assert result["decision"] == "PENDING_PRICING_LEADER_APPROVAL"
    assert result["approval_request"] == "Please review."


def test_agent_failure_marks_pipeline_run_failed_and_still_raises(temp_db, monkeypatch, tmp_path):
    monkeypatch.setattr(audit_log_module, "LOG_PATH", tmp_path / "audit.jsonl")

    def boom(pn, execution=None):
        raise RuntimeError("upstream system down")

    monkeypatch.setattr(supervisor, "gather_part_master", boom)

    collected = []
    raised = None
    try:
        for event in supervisor.process_pricing_request_stream("PN-TEST"):
            collected.append(event)
    except RuntimeError as e:
        raised = e

    assert raised is not None and "upstream system down" in str(raised)

    run_id = collected[0]["pipeline_run_id"]
    run_row = next(r for r in list_pipeline_runs(limit=10) if r["id"] == run_id)
    assert run_row["status"] == "failed"
    assert "upstream system down" in run_row["error_summary"]

    executions = list_agent_executions(run_id)
    assert executions[0]["status"] == "failed"


def test_audit_log_still_written_regression(temp_db, monkeypatch, tmp_path):
    """Confirms Module 1 instrumentation didn't break the pre-existing
    audit-log side effect that the Approval Queue / Decision History pages
    depend on."""
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log_module, "LOG_PATH", log_path)
    _patch_happy_path(monkeypatch)

    list(supervisor.process_pricing_request_stream("PN-TEST"))

    assert log_path.exists()
    records = audit_log_module.read_log()
    assert len(records) == 1
    assert records[0]["part_number"] == "PN-TEST"
