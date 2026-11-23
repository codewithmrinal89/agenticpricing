// Pricing Workspace page: part search, the live agent-flow pipeline, and
// result cards. Uses currency(), dateTime(), marginSeverity() from shared.js.

let parts = [];
const selectedParts = new Set(); // insertion order preserved

// ---------- Part combobox (multi-select) ----------

async function loadParts() {
  const res = await fetch("/api/parts");
  parts = await res.json();

  const searchInput = document.getElementById("part-search");
  searchInput.addEventListener("focus", () => renderComboboxList(searchInput.value));
  searchInput.addEventListener("input", () => renderComboboxList(searchInput.value));

  document.addEventListener("click", (e) => {
    if (!document.getElementById("part-combobox").contains(e.target)) {
      hideComboboxList();
    }
  });
}

function renderComboboxList(filterText) {
  const list = document.getElementById("part-list");
  const needle = filterText.trim().toLowerCase();

  const matches = parts.filter(
    (p) =>
      !selectedParts.has(p.part_number) &&
      (p.part_number.toLowerCase().includes(needle) || p.description.toLowerCase().includes(needle))
  );

  if (matches.length === 0) {
    list.innerHTML = `<li class="combobox__empty">No matching parts</li>`;
  } else {
    list.innerHTML = matches
      .map(
        (p) => `
        <li class="combobox__item" data-part-number="${p.part_number}">
          <span class="combobox__item-number">${p.part_number}</span>
          <span class="combobox__item-desc">${p.description}</span>
        </li>`
      )
      .join("");

    list.querySelectorAll(".combobox__item").forEach((item) => {
      item.addEventListener("click", () => addPart(item.dataset.partNumber));
    });
  }

  list.hidden = false;
}

function hideComboboxList() {
  document.getElementById("part-list").hidden = true;
}

function addPart(partNumber) {
  selectedParts.add(partNumber);
  const searchInput = document.getElementById("part-search");
  searchInput.value = "";
  searchInput.focus();
  hideComboboxList();
  renderSelectedChips();
}

function removePart(partNumber) {
  selectedParts.delete(partNumber);
  renderSelectedChips();
}

function renderSelectedChips() {
  const row = document.getElementById("selected-chips");
  row.innerHTML = Array.from(selectedParts)
    .map(
      (pn) => `
      <span class="chip-removable" data-part-number="${pn}">
        ${pn}
        <button type="button" aria-label="Remove ${pn}">&times;</button>
      </span>`
    )
    .join("");

  row.querySelectorAll(".chip-removable button").forEach((btn) => {
    btn.addEventListener("click", () => removePart(btn.parentElement.dataset.partNumber));
  });

  const button = document.getElementById("run-button");
  const n = selectedParts.size;
  button.disabled = n === 0;
  button.textContent = n > 1 ? `Run AI pricing analysis (${n})` : "Run AI pricing analysis";
}

// ---------- Live agent flow (node-graph pipeline, which agent is working now) ----------

const ALL_FLOW_NODES = [
  "Enterprise Data Retrieval Agent",
  "Inventory & Shipability Agent",
  "Cost & Margin Agent",
  "Pricing Strategy Agent",
  "Decision Gate",
  "Approval Agent",
];

function showAgentFlow(partNumber, current, total) {
  document.getElementById("agent-flow").hidden = false;
  document.getElementById("agent-flow-part").textContent =
    total > 1 ? `Processing ${current} of ${total}: ${partNumber}` : `Processing ${partNumber}`;

  // Reset every node to pending, and hide the Approval node/arrow until (and
  // unless) this part's pipeline actually reaches it.
  ALL_FLOW_NODES.forEach((agent) => {
    const node = document.querySelector(`.flow__node[data-node="${agent}"]`);
    if (node) node.className = node.classList.contains("flow__node--mini") ? "flow__node flow__node--mini" : "flow__node";
  });
  document.getElementById("flow-node-approval").hidden = true;
  document.getElementById("flow-arrow-approval").hidden = true;
}

function hideAgentFlow() {
  document.getElementById("agent-flow").hidden = true;
}

function setFlowNodeState(agent, state) {
  if (agent === "Approval Agent") {
    document.getElementById("flow-node-approval").hidden = false;
    document.getElementById("flow-arrow-approval").hidden = false;
  }
  const node = document.querySelector(`.flow__node[data-node="${agent}"]`);
  if (!node) return;
  const base = node.classList.contains("flow__node--mini") ? "flow__node flow__node--mini" : "flow__node";
  node.className = `${base} ${state}`;
}

// Decision Gate is plain Python with no LLM call -- it resolves in
// microseconds, so without a floor its node would flip straight to "done"
// and never visibly pulse. This minimum keeps every step perceivable; it's
// a no-op for the LLM-backed agents, which already take well over this long.
const MIN_STEP_VISIBLE_MS = 700;
const stepStartedAt = {};

// Wraps the SSE stream for one part in a Promise so the batch loop below can
// just `await` it like a normal request -- the live flow diagram updates as
// a side effect of the step_start/step_done events along the way.
function runSingleRequestWithProgress(partNumber) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/price-request-stream?part_number=${encodeURIComponent(partNumber)}`);

    // Tracks the in-flight "flip this node to is-done" delay for whichever
    // step finished most recently. The result/error handler below awaits it
    // before resolving -- without that, "result" (which the server sends
    // right after the last step_done) can arrive and resolve this promise
    // while that last node's artificial pause is still pending, so the
    // batch loop moves on and the viewer never actually sees it finish.
    let pendingStepDelay = Promise.resolve();

    es.onmessage = async (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "step_start") {
        stepStartedAt[data.agent] = Date.now();
        setFlowNodeState(data.agent, "is-active");
      } else if (data.type === "step_done") {
        const elapsed = Date.now() - (stepStartedAt[data.agent] ?? Date.now());
        const remaining = MIN_STEP_VISIBLE_MS - elapsed;
        pendingStepDelay =
          remaining > 0
            ? new Promise((r) => setTimeout(r, remaining)).then(() => setFlowNodeState(data.agent, "is-done"))
            : Promise.resolve(setFlowNodeState(data.agent, "is-done"));
      } else if (data.type === "result") {
        await pendingStepDelay;
        es.close();
        resolve(data.data);
      } else if (data.type === "error") {
        await pendingStepDelay;
        es.close();
        reject(new Error(data.message));
      }
    };

    es.onerror = () => {
      es.close();
      reject(new Error("Connection to server lost"));
    };
  });
}

// ---------- Running requests (sequential batch) ----------

async function runPricingRequests() {
  const partNumbers = Array.from(selectedParts);
  if (partNumbers.length === 0) return;

  const button = document.getElementById("run-button");
  const container = document.getElementById("results-container");

  button.disabled = true;
  document.getElementById("empty-state").hidden = true;
  container.innerHTML = "";

  for (let i = 0; i < partNumbers.length; i++) {
    const partNumber = partNumbers[i];
    showAgentFlow(partNumber, i + 1, partNumbers.length);

    try {
      const result = await runSingleRequestWithProgress(partNumber);
      container.insertAdjacentHTML("beforeend", buildResultCardHTML(result));
    } catch (e) {
      container.insertAdjacentHTML(
        "beforeend",
        `<div class="result-card result-card--error">Failed for ${partNumber}: ${e.message}</div>`
      );
    }
  }

  hideAgentFlow();
  button.disabled = false;
  if (typeof updateSidebarBadge === "function") updateSidebarBadge();
}

// ---------- Building a result card ----------

function buildResultCardHTML(r) {
  const isAutoApproved = r.decision === "AUTO_APPROVED";
  const severity = marginSeverity(r.current_margin_pct, r.thresholds);
  const arrow = r.price_change_pct >= 0 ? "↑" : "↓";

  const flagsHTML =
    r.flags && r.flags.length > 0
      ? `
      <div class="viz-block">
        <div class="viz-block__header"><span>Flags</span></div>
        <ul class="flags">${r.flags.map((f) => `<li>${f}</li>`).join("")}</ul>
      </div>`
      : "";

  const approvalHTML = r.approval_request
    ? `
      <div class="viz-block viz-block--highlight">
        <div class="viz-block__header"><span>Approval request drafted for pricing leader</span></div>
        <p class="narrative">${r.approval_request}</p>
      </div>`
    : "";

  return `
    <article class="result-card">
      <div class="result-head">
        <div>
          <h2>${r.part_number}</h2>
          <p class="muted">${r.description} · ${r.category} · ${r.lifecycle_status}</p>
        </div>
        <span class="badge ${isAutoApproved ? "badge--good" : "badge--warning"}">
          ${isAutoApproved ? "Auto-approved" : "Pending human review"}
        </span>
      </div>

      <div class="stat-row">
        <div class="stat-tile">
          <span class="stat-tile__label">Current price</span>
          <span class="stat-tile__value">${currency(r.current_list_price)}</span>
        </div>
        <div class="stat-tile stat-tile--focal">
          <span class="stat-tile__label">AI recommended price</span>
          <span class="stat-tile__value">${currency(r.recommended_price)}</span>
          <span class="stat-tile__delta">${arrow} ${Math.abs(r.price_change_pct).toFixed(1)}% vs current</span>
        </div>
        <div class="stat-tile">
          <span class="stat-tile__label">Current margin</span>
          <span class="stat-tile__value stat-tile__value--${severity}">${r.current_margin_pct.toFixed(1)}%</span>
        </div>
      </div>

      ${buildRecommendedMarginHTML(r)}
      ${buildMarginMeterHTML(r, severity)}
      ${flagsHTML}

      <div class="viz-block">
        <div class="viz-block__header"><span>Decision rationale report</span></div>
        <div class="report">
          <div class="report__item report__item--summary">
            <h4>Decision summary</h4>
            <p>${r.decision_summary}</p>
          </div>
          <div class="report__item">
            <h4>Margin analysis</h4>
            <p>${r.margin_analysis}</p>
          </div>
          <div class="report__item">
            <h4>Lifecycle &amp; inventory considerations</h4>
            <p>${r.lifecycle_analysis}</p>
          </div>
          <div class="report__item">
            <h4>Price change analysis</h4>
            <p>${r.price_change_analysis}</p>
          </div>
          <div class="report__item report__item--recommendation">
            <h4>Recommendation</h4>
            <p>${r.recommendation}</p>
          </div>
        </div>
      </div>

      ${approvalHTML}
    </article>`;
}

function buildRecommendedMarginHTML(r) {
  const target = r.thresholds.target_margin_pct;
  return `
    <div class="viz-block">
      <div class="viz-block__header"><span>Recommended margin</span></div>
      <div class="recommended-margin">
        <span class="recommended-margin__value">${target}%</span>
        <p class="recommended-margin__why">${r.margin_analysis}</p>
      </div>
    </div>`;
}

function buildMarginMeterHTML(r, severity) {
  const { min_margin_pct, target_margin_pct, max_margin_pct } = r.thresholds;
  const current = r.current_margin_pct;

  const domainMin = Math.min(0, current, min_margin_pct) - 5;
  const domainMax = Math.max(max_margin_pct, current) + 5;
  const span = domainMax - domainMin;
  const pct = (value) => ((value - domainMin) / span) * 100;

  const fillWidth = Math.max(0, Math.min(100, pct(current)));

  return `
    <div class="viz-block">
      <div class="viz-block__header">
        <span>Margin position</span>
        <span class="muted">${current.toFixed(1)}% current · ${min_margin_pct}% floor · ${target_margin_pct}% target</span>
      </div>
      <div class="meter">
        <div class="meter__track">
          <div class="meter__fill" style="width: ${fillWidth}%; background: var(--status-${severity});"></div>
          <div class="meter__tick" style="left: ${pct(min_margin_pct)}%;"><span>min</span></div>
          <div class="meter__tick" style="left: ${pct(target_margin_pct)}%;"><span>target</span></div>
        </div>
      </div>
    </div>`;
}

document.getElementById("run-button").addEventListener("click", runPricingRequests);

loadParts();
