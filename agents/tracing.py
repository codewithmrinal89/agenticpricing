"""Persisted agent execution traces.

Mirrors the lazy, additive migration pattern already established in
approvals_store.py (CREATE TABLE IF NOT EXISTS on first use) rather than
touching scripts/schema.sql, which is only applied by the destructive full
database rebuild in scripts/build_database.py. These tables are self
contained (no FK into the parts catalog) so they survive independently of
that rebuild.

Three levels are recorded, matching one pricing request end to end:
  pipeline_runs     -- one row per process_pricing_request_stream() call
  agent_executions  -- one row per specialist agent step inside that run
  tool_executions   -- one row per tool call inside an agent step (the data
                       agents may call a tool more than once per execution;
                       this is why "number of agent executions" and "number
                       of API calls" are tracked separately)

Both recorder classes are context managers with try/finally semantics: the
row is inserted as 'running' on __enter__ and always finalized to
'completed' or 'failed' on __exit__, even if the wrapped work raises. This
holds even under GeneratorExit (client disconnects mid SSE-stream), since
Python throws GeneratorExit into a suspended generator at its current yield
point, which still unwinds through any enclosing `with` block.
"""
import json
import time
import uuid
from datetime import datetime, timezone

from agents.db import get_connection

MAX_SUMMARY_STRING_LENGTH = 300


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id                 TEXT PRIMARY KEY,
            part_number        TEXT NOT NULL,
            rfq_id             TEXT,
            status             TEXT NOT NULL DEFAULT 'running'
                                   CHECK (status IN ('running', 'completed', 'failed')),
            started_at         TEXT NOT NULL,
            completed_at       TEXT,
            total_duration_ms  INTEGER,
            model_identifier   TEXT,
            error_summary      TEXT,
            created_at         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_executions (
            id                   TEXT PRIMARY KEY,
            pipeline_run_id      TEXT NOT NULL REFERENCES pipeline_runs(id),
            agent_name           TEXT NOT NULL,
            execution_order      INTEGER NOT NULL,
            status               TEXT NOT NULL DEFAULT 'running'
                                     CHECK (status IN ('running', 'completed', 'failed')),
            started_at           TEXT NOT NULL,
            completed_at         TEXT,
            duration_ms          INTEGER,
            output_summary_json  TEXT,
            error_code           TEXT,
            error_message        TEXT,
            prompt_tokens        INTEGER,
            completion_tokens    INTEGER,
            estimated_cost_usd   REAL
        );
        CREATE INDEX IF NOT EXISTS idx_agent_executions_run ON agent_executions(pipeline_run_id);

        CREATE TABLE IF NOT EXISTS tool_executions (
            id                              TEXT PRIMARY KEY,
            agent_execution_id              TEXT NOT NULL REFERENCES agent_executions(id),
            tool_name                       TEXT NOT NULL,
            status                          TEXT NOT NULL DEFAULT 'completed'
                                                CHECK (status IN ('completed', 'failed')),
            started_at                      TEXT NOT NULL,
            completed_at                    TEXT NOT NULL,
            duration_ms                     INTEGER,
            sanitized_arguments_json        TEXT,
            sanitized_result_summary_json   TEXT,
            error_message                   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tool_executions_agent ON tool_executions(agent_execution_id);
        """
    )


def _sanitize(value):
    """Cap outbound trace payloads so we never persist an unrestricted raw
    tool/LLM payload -- only flat, truncated, non-sensitive summaries."""
    if isinstance(value, str):
        return value[:MAX_SUMMARY_STRING_LENGTH]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_sanitize(v) for v in value[:20]]
    return value


def summarize_output(result) -> dict:
    """Concise, non-sensitive snapshot of what an agent step produced -- not
    the raw LLM response. Flat primitive fields only; nested structures are
    collapsed to a size marker."""
    if not isinstance(result, dict):
        return {"result": str(result)[:MAX_SUMMARY_STRING_LENGTH]}
    summary = {}
    for k, v in result.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            summary[k] = v[:MAX_SUMMARY_STRING_LENGTH] if isinstance(v, str) else v
        elif isinstance(v, dict):
            summary[k] = f"<{len(v)} fields>"
        elif isinstance(v, list):
            summary[k] = f"<{len(v)} items>"
    return summary


class PipelineRunRecorder:
    """One end-to-end pricing request."""

    def __init__(self, run_id: str, part_number: str, model_identifier: str, rfq_id: str | None = None):
        self.run_id = run_id
        self.part_number = part_number
        self.model_identifier = model_identifier
        self.rfq_id = rfq_id
        self._execution_order = 0
        self._started_monotonic = None

    def __enter__(self):
        conn = get_connection()
        _ensure_tables(conn)
        now = _now_iso()
        conn.execute(
            "INSERT INTO pipeline_runs (id, part_number, rfq_id, status, started_at, model_identifier, created_at) "
            "VALUES (?, ?, ?, 'running', ?, ?, ?)",
            (self.run_id, self.part_number, self.rfq_id, now, self.model_identifier, now),
        )
        conn.commit()
        conn.close()
        self._started_monotonic = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
        status = "failed" if exc_type else "completed"
        error_summary = f"{exc_type.__name__}: {exc_val}" if exc_type else None

        conn = get_connection()
        conn.execute(
            "UPDATE pipeline_runs SET status=?, completed_at=?, total_duration_ms=?, error_summary=? WHERE id=?",
            (status, _now_iso(), duration_ms, error_summary, self.run_id),
        )
        conn.commit()
        conn.close()
        return False  # never suppress the exception

    def agent(self, agent_name: str) -> "AgentExecutionRecorder":
        self._execution_order += 1
        return AgentExecutionRecorder(self.run_id, agent_name, self._execution_order)


class AgentExecutionRecorder:
    """One specialist agent's execution within a pipeline run."""

    def __init__(self, pipeline_run_id: str, agent_name: str, execution_order: int):
        self.id = str(uuid.uuid4())
        self.pipeline_run_id = pipeline_run_id
        self.agent_name = agent_name
        self.execution_order = execution_order
        self.output_summary = None
        self.prompt_tokens = None
        self.completion_tokens = None
        self.estimated_cost_usd = None
        self._started_monotonic = None

    def __enter__(self):
        conn = get_connection()
        _ensure_tables(conn)
        now = _now_iso()
        conn.execute(
            "INSERT INTO agent_executions (id, pipeline_run_id, agent_name, execution_order, status, started_at) "
            "VALUES (?, ?, ?, ?, 'running', ?)",
            (self.id, self.pipeline_run_id, self.agent_name, self.execution_order, now),
        )
        conn.commit()
        conn.close()
        self._started_monotonic = time.monotonic()
        return self

    def set_output_summary(self, result) -> None:
        self.output_summary = summarize_output(result)

    def set_token_usage(self, prompt_tokens, completion_tokens, estimated_cost_usd=None) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.estimated_cost_usd = estimated_cost_usd

    def record_tool_execution(self, tool_name, arguments, result, duration_ms, error_message=None) -> None:
        conn = get_connection()
        _ensure_tables(conn)
        now = _now_iso()
        conn.execute(
            """INSERT INTO tool_executions
               (id, agent_execution_id, tool_name, status, started_at, completed_at, duration_ms,
                sanitized_arguments_json, sanitized_result_summary_json, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()), self.id, tool_name,
                "failed" if error_message else "completed",
                now, now, duration_ms,
                json.dumps(_sanitize(arguments)), json.dumps(_sanitize(result)), error_message,
            ),
        )
        conn.commit()
        conn.close()

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
        status = "failed" if exc_type else "completed"
        error_code = exc_type.__name__ if exc_type else None
        error_message = str(exc_val) if exc_type else None

        conn = get_connection()
        conn.execute(
            """UPDATE agent_executions SET status=?, completed_at=?, duration_ms=?,
               output_summary_json=?, error_code=?, error_message=?,
               prompt_tokens=?, completion_tokens=?, estimated_cost_usd=?
               WHERE id=?""",
            (
                status, _now_iso(), duration_ms,
                json.dumps(self.output_summary) if self.output_summary is not None else None,
                error_code, error_message,
                self.prompt_tokens, self.completion_tokens, self.estimated_cost_usd,
                self.id,
            ),
        )
        conn.commit()
        conn.close()
        return False


# --- Query helpers for the API layer -----------------------------------

def list_pipeline_runs(limit: int = 50, offset: int = 0, status_filter: str | None = None) -> list[dict]:
    conn = get_connection()
    _ensure_tables(conn)
    query = "SELECT * FROM pipeline_runs"
    params: list = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        agg = conn.execute(
            """SELECT COUNT(*) AS agent_count,
                      COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                      COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                      COALESCE(SUM(estimated_cost_usd), 0) AS total_estimated_cost_usd
               FROM agent_executions WHERE pipeline_run_id = ?""",
            (d["id"],),
        ).fetchone()
        d.update(dict(agg))
        results.append(d)
    conn.close()
    return results


def get_pipeline_run(run_id: str) -> dict | None:
    conn = get_connection()
    _ensure_tables(conn)
    row = conn.execute("SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_agent_executions(pipeline_run_id: str) -> list[dict]:
    conn = get_connection()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT * FROM agent_executions WHERE pipeline_run_id = ? ORDER BY execution_order",
        (pipeline_run_id,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        d["output_summary"] = json.loads(d["output_summary_json"]) if d.get("output_summary_json") else None
        results.append(d)
    return results


def list_tool_executions(agent_execution_id: str) -> list[dict]:
    conn = get_connection()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT * FROM tool_executions WHERE agent_execution_id = ? ORDER BY started_at",
        (agent_execution_id,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        d["sanitized_arguments"] = json.loads(d["sanitized_arguments_json"]) if d.get("sanitized_arguments_json") else None
        d["sanitized_result_summary"] = (
            json.loads(d["sanitized_result_summary_json"]) if d.get("sanitized_result_summary_json") else None
        )
        results.append(d)
    return results
