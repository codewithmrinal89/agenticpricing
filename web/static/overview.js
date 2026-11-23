// Overview page: hero summary, premium KPI cards, pending-approvals
// preview, agent-activity timeline, decision-mix breakdown, and an
// agent-performance panel. All numbers come from /api/dashboard-stats,
// /api/approvals, and /api/agent-runs -- nothing here is simulated.

function setHeroGreeting() {
  const greetingEl = document.getElementById("hero-greeting");
  const dateEl = document.getElementById("hero-date");
  const now = new Date();

  if (greetingEl) {
    const hour = now.getHours();
    const timeOfDay = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
    greetingEl.innerHTML = greetingEl.innerHTML.replace("Welcome", `Good ${timeOfDay}`);
  }
  if (dateEl) {
    dateEl.textContent = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  }
}

function animateCount(el, target, formatter) {
  if (!el) return;
  const duration = 500;
  const start = performance.now();
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = formatter(target * eased);
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = formatter(target);
  }
  requestAnimationFrame(tick);
}

function setRingProgress(circleEl, pct) {
  if (!circleEl) return;
  const r = circleEl.r.baseVal.value;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  // Explicit "paint this many units, then gap the rest" dasharray --
  // the colored arc length is directly pct% of the circumference, with
  // no reliance on single-value dasharray duplication + offset-phase
  // arithmetic (that indirection was rendering the *complement* of the
  // intended percentage).
  const arcLength = (clamped / 100) * circumference;
  circleEl.style.strokeDasharray = `${arcLength} ${circumference - arcLength}`;
  circleEl.style.strokeDashoffset = "0";
}

async function loadDashboardStats() {
  const res = await fetch("/api/dashboard-stats");
  const s = await res.json();

  document.getElementById("hero-summary").textContent =
    s.total_requests === 0
      ? "No parts priced yet -- submit your first pricing request to get started."
      : `${s.total_requests} part(s) processed, ${s.pending_approval_count} awaiting review, ` +
        `${s.auto_approved_count} completed straight-through.`;

  animateCount(document.getElementById("kpi-total-requests"), s.total_requests, (v) => Math.round(v));
  animateCount(document.getElementById("kpi-total-impact"), s.total_price_adjustment_dollars, (v) => currency(v));
  document.getElementById("kpi-avg-change-detail").textContent =
    s.total_requests === 0 ? "" : `${s.avg_price_change_pct}% average change`;

  document.getElementById("kpi-pending-count").textContent = s.pending_approval_count;
  document.getElementById("kpi-avg-duration").textContent =
    s.total_requests === 0 ? "—" : `${s.avg_duration_seconds}s`;
  document.getElementById("kpi-avg-change").textContent =
    s.total_requests === 0 ? "—" : `${s.avg_price_change_pct}%`;

  document.getElementById("performance-rate").textContent =
    s.total_requests === 0 ? "—" : `${s.auto_approval_rate_pct}%`;
  setRingProgress(document.getElementById("performance-circle"), s.auto_approval_rate_pct || 0);

  renderBreakdown("breakdown-category", s.by_category);
  renderBreakdown("breakdown-lifecycle", s.by_lifecycle);
}

function renderBreakdown(containerId, groups) {
  const container = document.getElementById(containerId);

  if (!groups || groups.length === 0) {
    container.innerHTML = `<p class="muted">No requests processed yet.</p>`;
    return;
  }

  container.innerHTML = groups
    .map((g) => {
      const total = g.auto_approved + g.pending;
      const goodPct = (g.auto_approved / total) * 100;
      const warningPct = (g.pending / total) * 100;
      return `
        <div class="breakdown-row">
          <div class="breakdown-row__label">
            <strong>${g.name}</strong>
            <span>${g.auto_approved} auto &middot; ${g.pending} pending</span>
          </div>
          <div class="breakdown-row__bar">
            ${g.auto_approved > 0 ? `<div class="breakdown-row__segment breakdown-row__segment--good" style="width: ${goodPct}%;" title="${g.auto_approved} auto-approved"></div>` : ""}
            ${g.pending > 0 ? `<div class="breakdown-row__segment breakdown-row__segment--warning" style="width: ${warningPct}%;" title="${g.pending} pending review"></div>` : ""}
          </div>
        </div>`;
    })
    .join("");
}

async function loadApprovalPreview() {
  const listEl = document.getElementById("approval-preview-list");
  const countEl = document.getElementById("approval-preview-count");
  try {
    const res = await fetch("/api/approvals?status=pending");
    if (!res.ok) throw new Error("not available");
    const records = await res.json();
    countEl.textContent = `${records.length} pending`;

    if (records.length === 0) {
      listEl.innerHTML = `<div class="empty-state-inline">No pending decisions right now.</div>`;
      return;
    }

    // Show every pending record -- the panel has a fixed visible height
    // (~3-4 rows) and scrolls internally rather than truncating the list.
    listEl.innerHTML = records
      .map((r) => {
        const risk = r.flags.length >= 2 ? "critical" : r.flags.length === 1 ? "warning" : "good";
        return `
          <a class="approval-preview__item" href="/approvals?focus=${r.request_id}">
            <span class="approval-preview__risk approval-preview__risk--${risk}"></span>
            <span style="flex:1; min-width:0;">
              <span class="approval-preview__part">${r.part_number}</span>
              <span class="approval-preview__price">${currency(r.current_list_price)} &rarr; ${currency(r.recommended_price)}</span>
              <span class="approval-preview__meta">Submitted ${dateTime(r.timestamp)} &middot; ${r.request_id.slice(0, 8)}</span>
            </span>
            <span class="btn btn--tertiary" style="padding:0;">Review</span>
          </a>`;
      })
      .join("");
  } catch (e) {
    listEl.innerHTML = `<div class="empty-state-inline">Sign in as an approver or admin to see pending decisions.</div>`;
    countEl.textContent = "";
  }
}

let latestRunExecutions = null;
let latestRunMeta = null; // { id, part_number, status } of the most recent persisted pipeline run

// ---------- Hero network: real execution states on the agent nodes ----------

function initHeroNetwork() {
  const svg = document.querySelector(".hero-network");
  if (!svg) return;

  // Pause ambient particle/glow animation when the tab is hidden or the
  // user prefers reduced motion -- no point animating off-screen or
  // against an explicit accessibility preference.
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const applyPauseState = () => {
    svg.classList.toggle("is-paused", reduceMotion || document.hidden);
  };
  applyPauseState();
  document.addEventListener("visibilitychange", applyPauseState);

  const tooltip = document.getElementById("hero-network-tooltip");
  const container = document.getElementById("hero-visual");

  svg.querySelectorAll(".hero-network__node").forEach((node) => {
    const show = () => showNodeTooltip(node, tooltip, container);
    const hide = () => { tooltip.hidden = true; };
    node.addEventListener("mouseenter", show);
    node.addEventListener("mouseleave", hide);
    node.addEventListener("focus", show);
    node.addEventListener("blur", hide);
  });
}

function showNodeTooltip(node, tooltip, container) {
  const stageName = node.dataset.stage;
  const execution = latestRunExecutions ? latestRunExecutions.find((e) => e.agent_name === stageName) : null;

  let html = `<strong>${stageName}</strong>`;
  if (execution) {
    const duration = execution.duration_ms != null ? `${(execution.duration_ms / 1000).toFixed(1)}s` : "in progress";
    html += `<span class="muted">Status: ${execution.status} &middot; ${duration}</span><br/>`;
    html += `<span class="muted">Last run: ${dateTime(execution.started_at)}</span>`;
  } else {
    html += `<br/><span class="muted">No execution recorded yet</span>`;
  }
  tooltip.innerHTML = html;

  const nodeRect = node.getBoundingClientRect();
  const containerRect = container.getBoundingClientRect();
  tooltip.style.left = `${nodeRect.left + nodeRect.width / 2 - containerRect.left}px`;
  tooltip.style.top = `${nodeRect.top - containerRect.top - 8}px`;
  tooltip.hidden = false;
}

function applyHeroNetworkState(run, executions) {
  const svg = document.querySelector(".hero-network");
  const pipelineStatusEl = document.getElementById("hero-pipeline-status");
  if (!svg || !pipelineStatusEl) return;

  svg.querySelectorAll(".hero-network__node").forEach((node) => {
    node.classList.remove("is-completed", "is-failed", "is-running", "is-awaiting");
    const stage = executions.find((e) => e.agent_name === node.dataset.stage);
    if (stage) node.classList.add(`is-${stage.status}`);
  });

  // Highlight the spoke feeding whichever node is currently running, if any.
  svg.querySelectorAll(".hero-network__particle").forEach((p) => p.classList.remove("is-active"));
  const runningIndex = ["Enterprise Data Retrieval Agent", "Inventory & Shipability Agent", "Cost & Margin Agent",
    "Pricing Strategy Agent", "Decision Gate", "Approval Agent"]
    .findIndex((name) => executions.some((e) => e.agent_name === name && e.status === "running"));
  if (runningIndex >= 0) {
    svg.querySelector(`.hero-network__particle[data-spoke="${runningIndex}"]`)?.classList.add("is-active");
  }

  const label = run.status === "running" ? "In progress" : run.status === "failed" ? "Failed" : "Completed";
  pipelineStatusEl.textContent = `Last run (${run.part_number}): ${label}`;
}

// Best-effort: if this run's decision is still awaiting a human review,
// recolor Decision Gate + Approval Agent amber instead of green. Uses the
// same /api/approvals data the pending-approvals panel already relies on;
// if it's not visible to this account (e.g. outside an approver's
// assigned categories), the run simply falls back to its execution-status
// coloring -- never fabricated.
async function applyAwaitingApprovalState(run) {
  try {
    const approvals = await fetch("/api/approvals").then((r) => r.json());
    const match = approvals.find((a) => a.request_id === run.id);
    if (!match || match.review.status !== "pending") return;

    const svg = document.querySelector(".hero-network");
    ["Decision Gate", "Approval Agent"].forEach((stage) => {
      const node = svg?.querySelector(`.hero-network__node[data-stage="${stage}"]`);
      if (node) {
        node.classList.remove("is-completed");
        node.classList.add("is-awaiting");
      }
    });
    const pipelineStatusEl = document.getElementById("hero-pipeline-status");
    if (pipelineStatusEl) pipelineStatusEl.textContent = `Last run (${run.part_number}): Awaiting approval`;
  } catch (e) {
    // Not available to this account -- leave execution-status coloring as-is.
  }
}

async function loadActivityTimeline() {
  const el = document.getElementById("activity-timeline");
  const pipelineStatusEl = document.getElementById("hero-pipeline-status");
  try {
    const runsRes = await fetch("/api/agent-runs?limit=1");
    if (!runsRes.ok) throw new Error("not available");
    const runs = await runsRes.json();

    if (runs.length === 0) {
      el.innerHTML = `<div class="empty-state-inline">No agent runs recorded yet.</div>`;
      if (pipelineStatusEl) pipelineStatusEl.textContent = "Idle -- no pipeline runs yet";
      return;
    }

    const run = runs[0];
    latestRunMeta = run;
    const executions = await fetch(`/api/agent-runs/${run.id}/executions`).then((r) => r.json());
    latestRunExecutions = executions;

    el.innerHTML = executions
      .map((e, i) => {
        const dotClass = e.status === "completed" ? "completed" : e.status === "failed" ? "failed" : "running";
        const meta = e.duration_ms != null ? `${(e.duration_ms / 1000).toFixed(1)}s` : "running…";
        return `
          <div class="activity-timeline-compact__item" data-index="${i}" tabindex="0" role="button" aria-expanded="false">
            <span class="activity-timeline-compact__dot activity-timeline-compact__dot--${dotClass}"></span>
            <span class="activity-timeline-compact__name">${e.agent_name}</span>
            <span class="activity-timeline-compact__meta">${meta}</span>
          </div>
          <div class="activity-timeline-compact__detail" id="activity-detail-${i}" hidden></div>`;
      })
      .join("");

    el.querySelectorAll(".activity-timeline-compact__item").forEach((item) => {
      const toggle = () => toggleExecutionDetail(item);
      item.addEventListener("click", toggle);
      item.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggle();
        }
      });
    });

    applyHeroNetworkState(run, executions);
    if (run.status === "completed") await applyAwaitingApprovalState(run);
  } catch (e) {
    el.innerHTML = `<div class="empty-state-inline">Agent activity isn't available for this account.</div>`;
    if (pipelineStatusEl) pipelineStatusEl.textContent = "Pipeline status unavailable";
  }
}

async function toggleExecutionDetail(item) {
  const index = item.dataset.index;
  const detailEl = document.getElementById(`activity-detail-${index}`);
  const isOpen = !detailEl.hidden;
  item.setAttribute("aria-expanded", String(!isOpen));

  if (isOpen) {
    detailEl.hidden = true;
    return;
  }

  const execution = latestRunExecutions[index];
  if (!detailEl.dataset.loaded) {
    let toolsHTML = "";
    try {
      const tools = await fetch(`/api/agent-executions/${execution.id}/tools`).then((r) => r.json());
      toolsHTML =
        tools.length === 0
          ? ""
          : `<p class="activity-timeline-compact__detail-label">Tool calls</p>` +
            tools.map((t) => `<code class="activity-timeline-compact__tool">${t.tool_name} (${t.duration_ms}ms)</code>`).join(" ");
    } catch (e) {
      // Tool trace unavailable for this account/role -- show execution summary only.
    }

    detailEl.innerHTML = `
      <p><span class="muted">Execution</span> ${execution.id.slice(0, 8)}</p>
      <p><span class="muted">Started</span> ${dateTime(execution.started_at)}${
        execution.completed_at ? ` &rarr; ${dateTime(execution.completed_at)}` : ""
      }</p>
      ${execution.error_message ? `<p style="color:var(--status-critical);">${execution.error_message}</p>` : ""}
      ${toolsHTML}`;
    detailEl.dataset.loaded = "1";
  }
  detailEl.hidden = false;
}

async function loadAgentExecutionSuccessRate() {
  const el = document.getElementById("perf-success-rate");
  try {
    const res = await fetch("/api/agent-runs?limit=200");
    if (!res.ok) throw new Error("not available");
    const runs = await res.json();
    const finished = runs.filter((r) => r.status === "completed" || r.status === "failed");
    if (finished.length === 0) {
      el.textContent = "No runs recorded";
      return;
    }
    const completed = finished.filter((r) => r.status === "completed").length;
    el.textContent = `${((completed / finished.length) * 100).toFixed(1)}%`;
  } catch (e) {
    el.textContent = "—";
  }
}

setHeroGreeting();
initHeroNetwork();
loadDashboardStats();
loadApprovalPreview();
loadActivityTimeline();
loadAgentExecutionSuccessRate();
