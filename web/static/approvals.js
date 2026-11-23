// Approval Queue page: list pending/approved/rejected decisions and let a
// pricing leader actually approve or reject them. Real mutation against
// the backend (agents/approvals_store.py) -- nothing here is simulated.

let activeStatusFilter = "pending";

async function loadApprovals() {
  const url = activeStatusFilter ? `/api/approvals?status=${activeStatusFilter}` : "/api/approvals";
  const res = await fetch(url);
  const records = await res.json();
  renderApprovals(records);
}

function renderApprovals(records) {
  const container = document.getElementById("approvals-list");
  const emptyState = document.getElementById("approvals-empty");
  document.getElementById("approvals-count").textContent = `${records.length} decision(s)`;

  if (records.length === 0) {
    container.innerHTML = "";
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;

  container.innerHTML = records.map(buildApprovalCardHTML).join("");

  container.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleReviewAction(btn.dataset.requestId, btn.dataset.action));
  });

  focusRequestedCard();
}

function focusRequestedCard() {
  const focusId = new URLSearchParams(window.location.search).get("focus");
  if (!focusId) return;
  const el = document.getElementById(`approval-${focusId}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("is-focused");
  setTimeout(() => el.classList.remove("is-focused"), 2200);
}

function buildApprovalCardHTML(r) {
  const status = r.review.status;
  const arrow = r.price_change_pct >= 0 ? "↑" : "↓";

  const statusBadge = {
    pending: '<span class="badge badge--warning">Pending review</span>',
    approved: '<span class="badge badge--good">Approved</span>',
    rejected: '<span class="badge badge--critical">Rejected</span>',
  }[status];

  const actionsHTML =
    status === "pending"
      ? `
      <div class="approval-card__actions">
        <button class="btn btn--approve" data-request-id="${r.request_id}" data-action="approve">Approve</button>
        <button class="btn btn--reject" data-request-id="${r.request_id}" data-action="reject">Reject</button>
      </div>`
      : `
      <p class="muted approval-card__reviewed">
        ${status === "approved" ? "Approved" : "Rejected"} ${dateTime(r.review.reviewed_at)}${
          r.review.reviewer_note ? ` &mdash; &ldquo;${r.review.reviewer_note}&rdquo;` : ""
        }
      </p>`;

  const flagsHTML =
    r.flags && r.flags.length > 0
      ? `<ul class="flags">${r.flags.map((f) => `<li>${f}</li>`).join("")}</ul>`
      : "";

  return `
    <article class="approval-card" id="approval-${r.request_id}">
      <div class="approval-card__head">
        <div>
          <h3>${r.part_number}</h3>
          <p class="muted">${r.description} &middot; ${r.category} &middot; ${r.lifecycle_status}</p>
          <p class="muted" style="font-size:0.7rem;">Request ${r.request_id.slice(0, 8)}</p>
        </div>
        ${statusBadge}
      </div>
      <div class="approval-card__prices">
        <span>${currency(r.current_list_price)} &rarr; <strong>${currency(r.recommended_price)}</strong></span>
        <span class="muted">${arrow} ${Math.abs(r.price_change_pct).toFixed(1)}%</span>
        <span class="muted">Submitted ${dateTime(r.timestamp)}</span>
      </div>
      ${flagsHTML}
      <p class="approval-card__summary">${r.decision_summary}</p>
      ${actionsHTML}
    </article>`;
}

async function handleReviewAction(requestId, action) {
  const verb = action === "approve" ? "approve" : "reject";
  if (!confirm(`Are you sure you want to ${verb} this pricing recommendation?`)) return;

  let note = null;
  if (action === "reject") {
    note = prompt("Optional note for this rejection:") || null;
  }

  const res = await fetch(`/api/approvals/${requestId}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });

  if (!res.ok) {
    alert("Failed to update review status.");
    return;
  }

  await loadApprovals();
  if (typeof updateSidebarBadge === "function") updateSidebarBadge();
}

document.querySelectorAll("#approval-filters .filter-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#approval-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    activeStatusFilter = tab.dataset.status;
    loadApprovals();
  });
});

loadApprovals();
