"""Audit log: every pricing decision gets a durable, append-only record.

Uses JSON Lines (one JSON object per line) instead of a single JSON array
so that appending never requires reading and rewriting the whole file --
the same reason real audit logs are append-only.
"""
import json
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "audit_log.jsonl"


def log_decision(record: dict) -> None:
    """Append one decision record to the audit log."""
    LOG_PATH.parent.mkdir(exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def read_log() -> list[dict]:
    """Read every record from the audit log, oldest first."""
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def _breakdown_by(records: list[dict], key: str) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in records:
        if key not in r:
            continue  # older record from before this field was added to the schema
        group = groups.setdefault(r[key], {"auto_approved": 0, "pending": 0})
        if r["decision"] == "AUTO_APPROVED":
            group["auto_approved"] += 1
        else:
            group["pending"] += 1
    return [{"name": name, **counts} for name, counts in sorted(groups.items())]


def compute_dashboard_stats() -> dict:
    """Aggregate the audit log into the numbers a leadership pitch actually
    wants: straight-through rate, average speed, and the dollar impact of
    what the agents recommended -- computed from already-logged decisions,
    no separate tracking needed."""
    records = read_log()
    total = len(records)

    if total == 0:
        return {
            "total_requests": 0,
            "auto_approved_count": 0,
            "pending_approval_count": 0,
            "auto_approval_rate_pct": 0,
            "avg_duration_seconds": 0,
            "total_price_adjustment_dollars": 0,
            "avg_price_change_pct": 0,
            "by_category": [],
            "by_lifecycle": [],
        }

    auto_approved_count = sum(1 for r in records if r["decision"] == "AUTO_APPROVED")
    pending_count = total - auto_approved_count

    return {
        "total_requests": total,
        "auto_approved_count": auto_approved_count,
        "pending_approval_count": pending_count,
        "auto_approval_rate_pct": round(auto_approved_count / total * 100, 1),
        "avg_duration_seconds": round(sum(r["duration_seconds"] for r in records) / total, 1),
        "total_price_adjustment_dollars": round(sum(r["recommended_price"] - r["current_list_price"] for r in records), 2),
        "avg_price_change_pct": round(sum(abs(r["price_change_pct"]) for r in records) / total, 1),
        "by_category": _breakdown_by(records, "category"),
        "by_lifecycle": _breakdown_by(records, "lifecycle_status"),
    }
