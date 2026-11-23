"""Human-in-the-loop review state for pending pricing decisions.

The audit log (audit_log.py) is an immutable, append-only record of what
the AI decided -- it should never be mutated, that's the point of an audit
trail. Whether a pricing leader has since approved or rejected a flagged
decision is separate, *mutable* state, so it lives in its own small SQLite
table instead of editing log entries in place.
"""
from datetime import datetime, timezone

from agents.audit_log import read_log
from agents.db import get_connection

VALID_STATUSES = {"pending", "approved", "rejected"}


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_reviews (
            request_id    TEXT PRIMARY KEY,
            status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
            reviewed_at   TEXT,
            reviewer_note TEXT
        )
        """
    )


def _review_for(conn, request_id: str) -> dict:
    row = conn.execute(
        "SELECT status, reviewed_at, reviewer_note FROM approval_reviews WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        return {"status": "pending", "reviewed_at": None, "reviewer_note": None}
    return dict(row)


def list_approvals(status_filter: str | None = None, categories: list[str] | None = None) -> list[dict]:
    """Every PENDING_PRICING_LEADER_APPROVAL decision, newest first, each
    carrying its current review status. Optionally filter by that status
    (pending/approved/rejected) and/or by a set of allowed categories --
    the latter is how an approver's queue is scoped to only the
    categories they've been assigned (None/omitted means no restriction,
    i.e. an admin's view)."""
    conn = get_connection()
    _ensure_table(conn)

    records = [r for r in read_log() if r["decision"] == "PENDING_PRICING_LEADER_APPROVAL"]
    for r in records:
        r["review"] = _review_for(conn, r["request_id"])
    conn.close()

    records.reverse()  # newest first
    if status_filter:
        records = [r for r in records if r["review"]["status"] == status_filter]
    if categories is not None:
        allowed = set(categories)
        records = [r for r in records if r.get("category") in allowed]
    return records


def get_category_for_request(request_id: str) -> str | None:
    """Look up which category a given pending-approval request belongs to
    -- used to authorize whether a specific approver may act on it."""
    for r in read_log():
        if r["request_id"] == request_id:
            return r.get("category")
    return None


def set_review_status(request_id: str, status: str, note: str | None = None) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")

    conn = get_connection()
    _ensure_table(conn)

    # Only decisions the audit log actually flagged for review can be reviewed.
    flagged_ids = {r["request_id"] for r in read_log() if r["decision"] == "PENDING_PRICING_LEADER_APPROVAL"}
    if request_id not in flagged_ids:
        conn.close()
        raise KeyError(f"No pending-review decision with request_id {request_id!r}")

    reviewed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO approval_reviews (request_id, status, reviewed_at, reviewer_note)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(request_id) DO UPDATE SET
            status = excluded.status,
            reviewed_at = excluded.reviewed_at,
            reviewer_note = excluded.reviewer_note
        """,
        (request_id, status, reviewed_at, note),
    )
    conn.commit()
    result = _review_for(conn, request_id)
    conn.close()
    return result
