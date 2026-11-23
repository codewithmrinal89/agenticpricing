"""Tests for the category-scoping added to agents/approvals_store.py --
this is what makes an approver's queue show only their assigned
categories instead of every pending decision in the system.
"""
from agents.approvals_store import get_category_for_request, list_approvals
from agents.audit_log import log_decision


def _flagged_record(request_id: str, category: str) -> dict:
    return {
        "request_id": request_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "duration_seconds": 1.0,
        "part_number": f"PN-{request_id}",
        "description": "d",
        "category": category,
        "lifecycle_status": "Active",
        "decision": "PENDING_PRICING_LEADER_APPROVAL",
        "actual_cost": 1,
        "current_list_price": 2,
        "recommended_price": 3,
        "current_margin_pct": 1,
        "price_change_pct": 1,
        "thresholds": {},
        "scenarios": {},
        "flags": ["x"],
        "narrative": "n",
        "decision_summary": "d",
        "margin_analysis": "m",
        "lifecycle_analysis": "l",
        "price_change_analysis": "p",
        "recommendation": "r",
        "approval_request": "please review",
    }


def test_list_approvals_filters_by_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Avionics"))
    log_decision(_flagged_record("r2", "Structural"))
    log_decision(_flagged_record("r3", "Avionics"))

    avionics_only = list_approvals(categories=["Avionics"])
    assert {r["request_id"] for r in avionics_only} == {"r1", "r3"}

    unfiltered = list_approvals(categories=None)
    assert {r["request_id"] for r in unfiltered} == {"r1", "r2", "r3"}


def test_get_category_for_request(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Engine"))
    assert get_category_for_request("r1") == "Engine"
    assert get_category_for_request("unknown-id") is None
