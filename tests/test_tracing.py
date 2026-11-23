"""Tests for agents/tracing.py: the persisted execution-trace recorders and
their query helpers. No network calls -- these exercise the recorder
lifecycle and DB persistence directly.
"""
import uuid

import pytest

from agents.tracing import (
    PipelineRunRecorder,
    get_pipeline_run,
    list_agent_executions,
    list_pipeline_runs,
    list_tool_executions,
)


def test_pipeline_run_success_is_persisted(temp_db):
    run_id = str(uuid.uuid4())
    with PipelineRunRecorder(run_id, "PN-1", "gpt-4o-mini") as run:
        with run.agent("Test Agent") as execution:
            execution.set_output_summary({"ok": True})

    row = get_pipeline_run(run_id)
    assert row["status"] == "completed"
    assert row["completed_at"] is not None
    assert row["total_duration_ms"] >= 0
    assert row["error_summary"] is None


def test_pipeline_run_failure_is_recorded(temp_db):
    run_id = str(uuid.uuid4())
    with pytest.raises(ValueError):
        with PipelineRunRecorder(run_id, "PN-2", "gpt-4o-mini") as run:
            with run.agent("Failing Agent"):
                raise ValueError("boom")

    row = get_pipeline_run(run_id)
    assert row["status"] == "failed"
    assert "boom" in row["error_summary"]


def test_agent_execution_timing_and_order(temp_db):
    run_id = str(uuid.uuid4())
    with PipelineRunRecorder(run_id, "PN-3", "gpt-4o-mini") as run:
        with run.agent("First Agent") as e1:
            e1.set_output_summary({"a": 1})
        with run.agent("Second Agent") as e2:
            e2.set_output_summary({"b": 2})

    executions = list_agent_executions(run_id)
    assert [e["agent_name"] for e in executions] == ["First Agent", "Second Agent"]
    assert [e["execution_order"] for e in executions] == [1, 2]
    assert all(e["status"] == "completed" for e in executions)
    assert all(e["duration_ms"] is not None for e in executions)
    assert executions[0]["output_summary"] == {"a": 1}


def test_agent_execution_failure_records_error_without_killing_other_rows(temp_db):
    run_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        with PipelineRunRecorder(run_id, "PN-4", "gpt-4o-mini") as run:
            with run.agent("Good Agent") as e1:
                e1.set_output_summary({"ok": True})
            with run.agent("Bad Agent"):
                raise RuntimeError("tool unavailable")

    executions = list_agent_executions(run_id)
    assert executions[0]["status"] == "completed"
    assert executions[1]["status"] == "failed"
    assert executions[1]["error_code"] == "RuntimeError"
    assert "tool unavailable" in executions[1]["error_message"]


def test_tool_execution_recorded_under_its_agent_execution(temp_db):
    run_id = str(uuid.uuid4())
    with PipelineRunRecorder(run_id, "PN-5", "gpt-4o-mini") as run:
        with run.agent("Tool Agent") as execution:
            execution.record_tool_execution("get_part", {"part_number": "PN-5"}, {"found": True}, 42)

    executions = list_agent_executions(run_id)
    tools = list_tool_executions(executions[0]["id"])
    assert len(tools) == 1
    assert tools[0]["tool_name"] == "get_part"
    assert tools[0]["duration_ms"] == 42
    assert tools[0]["status"] == "completed"
    assert tools[0]["sanitized_arguments"] == {"part_number": "PN-5"}


def test_no_llm_call_leaves_token_fields_null_not_zero(temp_db):
    """Decision Gate makes zero LLM calls -- token/cost fields must be NULL,
    never 0, so 'no usage recorded' isn't confused with 'zero tokens used'."""
    run_id = str(uuid.uuid4())
    with PipelineRunRecorder(run_id, "PN-6", "gpt-4o-mini") as run:
        with run.agent("Decision Gate") as execution:
            execution.set_output_summary({"decision": "AUTO_APPROVED"})

    executions = list_agent_executions(run_id)
    assert executions[0]["prompt_tokens"] is None
    assert executions[0]["completion_tokens"] is None
    assert executions[0]["estimated_cost_usd"] is None


def test_concurrent_runs_are_isolated(temp_db):
    """Two separate pipeline runs must never cross-contaminate each other's
    agent_executions -- each row stays scoped to its own pipeline_run_id and
    keeps its own independent execution_order sequence starting at 1."""
    run_id_a = str(uuid.uuid4())
    run_id_b = str(uuid.uuid4())

    with PipelineRunRecorder(run_id_a, "PN-A", "gpt-4o-mini") as run_a:
        with run_a.agent("Agent X"):
            pass

    with PipelineRunRecorder(run_id_b, "PN-B", "gpt-4o-mini") as run_b:
        with run_b.agent("Agent Y"):
            pass
        with run_b.agent("Agent Z"):
            pass

    execs_a = list_agent_executions(run_id_a)
    execs_b = list_agent_executions(run_id_b)
    assert [e["agent_name"] for e in execs_a] == ["Agent X"]
    assert [e["execution_order"] for e in execs_a] == [1]
    assert [e["agent_name"] for e in execs_b] == ["Agent Y", "Agent Z"]
    assert [e["execution_order"] for e in execs_b] == [1, 2]

    all_runs = {r["id"] for r in list_pipeline_runs(limit=50)}
    assert {run_id_a, run_id_b} <= all_runs


def test_sanitize_truncates_oversized_strings(temp_db):
    run_id = str(uuid.uuid4())
    huge_value = "x" * 10_000
    with PipelineRunRecorder(run_id, "PN-7", "gpt-4o-mini") as run:
        with run.agent("Verbose Agent") as execution:
            execution.record_tool_execution("lookup", {"q": huge_value}, {"text": huge_value}, 1)

    executions = list_agent_executions(run_id)
    tools = list_tool_executions(executions[0]["id"])
    assert len(tools[0]["sanitized_arguments"]["q"]) <= 300
    assert len(tools[0]["sanitized_result_summary"]["text"]) <= 300


def test_list_pipeline_runs_status_filter(temp_db):
    ok_id, fail_id = str(uuid.uuid4()), str(uuid.uuid4())
    with PipelineRunRecorder(ok_id, "PN-8", "gpt-4o-mini"):
        pass
    try:
        with PipelineRunRecorder(fail_id, "PN-9", "gpt-4o-mini"):
            raise ValueError("x")
    except ValueError:
        pass

    completed = {r["id"] for r in list_pipeline_runs(status_filter="completed")}
    failed = {r["id"] for r in list_pipeline_runs(status_filter="failed")}
    assert ok_id in completed and ok_id not in failed
    assert fail_id in failed and fail_id not in completed
