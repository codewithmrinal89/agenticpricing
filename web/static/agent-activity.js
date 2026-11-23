// Agent Activity page: list of persisted pipeline runs (agents/tracing.py),
// with a click-through detail view of each agent execution's timing, token
// usage, and tool calls. Uses currency()/dateTime() from shared.js.

let activeStatusFilter = "";

async function loadRuns() {
  const url = activeStatusFilter ? `/api/agent-runs?status=${activeStatusFilter}` : "/api/agent-runs";
  const res = await fetch(url);
  const runs = await res.json();
  renderRuns(runs);
}

function renderRuns(runs) {
  const tbody = document.getElementById("runs-table-body");
  const emptyState = document.getElementById("runs-empty");
  document.getElementById("runs-count").textContent = `${runs.length} run(s)`;

  if (runs.length === 0) {
    tbody.innerHTML = "";
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;

  const statusChip = {
    completed: '<span class="chip chip--good">Completed</span>',
    failed: '<span class="chip chip--critical">Failed</span>',
    running: '<span class="chip chip--warning">Running</span>',
  };

  tbody.innerHTML = runs
    .map((r) => {
      const tokens = r.total_prompt_tokens + r.total_completion_tokens;
      const duration = r.total_duration_ms != null ? `${(r.total_duration_ms / 1000).toFixed(2)}s` : "—";
      const cost = r.total_estimated_cost_usd ? `$${r.total_estimated_cost_usd.toFixed(4)}` : "—";
      return `
        <tr class="run-row" data-run-id="${r.id}">
          <td>${dateTime(r.started_at)}</td>
          <td>${r.part_number}</td>
          <td>${statusChip[r.status] || r.status}</td>
          <td>${r.agent_count}</td>
          <td>${duration}</td>
          <td>${tokens || "—"}</td>
          <td>${cost}</td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".run-row").forEach((row) => {
    row.addEventListener("click", () => openRunDetail(row.dataset.runId));
  });
}

async function openRunDetail(runId) {
  const [run, executions] = await Promise.all([
    fetch(`/api/agent-runs/${runId}`).then((r) => r.json()),
    fetch(`/api/agent-runs/${runId}/executions`).then((r) => r.json()),
  ]);

  const panel = document.getElementById("run-detail-panel");
  const body = document.getElementById("run-detail-body");
  document.getElementById("run-detail-title").textContent = `Run detail — ${run.part_number}`;
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });

  body.innerHTML = executions
    .map((e, i) => {
      const statusChip =
        e.status === "completed"
          ? '<span class="chip chip--good">Completed</span>'
          : e.status === "failed"
          ? '<span class="chip chip--critical">Failed</span>'
          : '<span class="chip chip--warning">Running</span>';
      const duration = e.duration_ms != null ? `${e.duration_ms}ms` : "—";
      const tokens = e.prompt_tokens != null ? `${e.prompt_tokens} in / ${e.completion_tokens} out` : "no LLM call";
      const errorHTML = e.error_message ? `<p class="muted agent-timeline__error">Error: ${e.error_message}</p>` : "";
      return `
        <article class="agent-timeline__item">
          <div class="agent-timeline__head">
            <strong>${i + 1}. ${e.agent_name}</strong>
            ${statusChip}
          </div>
          <p class="muted">${duration} &middot; ${tokens}</p>
          ${errorHTML}
          <button class="filter-tab agent-timeline__toggle" data-execution-id="${e.id}">Show tool calls</button>
          <div class="agent-timeline__tools" id="tools-${e.id}" hidden></div>
        </article>`;
    })
    .join("");

  body.querySelectorAll(".agent-timeline__toggle").forEach((btn) => {
    btn.addEventListener("click", () => toggleTools(btn.dataset.executionId, btn));
  });
}

async function toggleTools(executionId, btn) {
  const container = document.getElementById(`tools-${executionId}`);
  if (!container.hidden) {
    container.hidden = true;
    btn.textContent = "Show tool calls";
    return;
  }

  if (!container.dataset.loaded) {
    const tools = await fetch(`/api/agent-executions/${executionId}/tools`).then((r) => r.json());
    container.innerHTML =
      tools.length === 0
        ? '<p class="muted">No tool calls recorded for this step.</p>'
        : tools
            .map(
              (t) => `
          <div class="agent-timeline__tool">
            <code>${t.tool_name}</code>
            <span class="muted">${t.duration_ms}ms</span>
          </div>`
            )
            .join("");
    container.dataset.loaded = "1";
  }
  container.hidden = false;
  btn.textContent = "Hide tool calls";
}

document.getElementById("run-detail-close").addEventListener("click", () => {
  document.getElementById("run-detail-panel").hidden = true;
});

document.querySelectorAll("#run-filters .filter-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#run-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    activeStatusFilter = tab.dataset.status;
    loadRuns();
  });
});

loadRuns();
