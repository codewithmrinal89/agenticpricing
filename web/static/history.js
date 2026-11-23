// Decision History page: audit trail table with client-side search and
// decision filter. Uses currency()/dateTime() from shared.js.

let allRecords = [];
let activeDecisionFilter = "";

async function loadAuditLog() {
  const res = await fetch("/api/audit-log");
  allRecords = await res.json();
  renderHistoryTable();
}

function renderHistoryTable() {
  const needle = document.getElementById("history-search").value.trim().toLowerCase();

  const filtered = allRecords.filter((r) => {
    const matchesSearch = !needle || r.part_number.toLowerCase().includes(needle);
    const matchesDecision = !activeDecisionFilter || r.decision === activeDecisionFilter;
    return matchesSearch && matchesDecision;
  });

  document.getElementById("audit-count").textContent =
    `${filtered.length} of ${allRecords.length} decision(s)`;

  const tbody = document.getElementById("audit-table-body");
  const emptyState = document.getElementById("history-empty");

  if (filtered.length === 0) {
    tbody.innerHTML = "";
    emptyState.hidden = allRecords.length === 0 ? true : false;
    emptyState.querySelector("p").textContent =
      allRecords.length === 0 ? "No decisions logged yet." : "No decisions match this filter.";
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;

  tbody.innerHTML = filtered
    .map((r) => {
      const isAutoApproved = r.decision === "AUTO_APPROVED";
      const chipClass = isAutoApproved ? "chip--good" : "chip--warning";
      const chipLabel = isAutoApproved ? "Auto-approved" : "Pending approval";
      return `
        <tr>
          <td>${dateTime(r.timestamp)}</td>
          <td>${r.part_number}</td>
          <td><span class="chip ${chipClass}">${chipLabel}</span></td>
          <td>${currency(r.current_list_price)}</td>
          <td>${currency(r.recommended_price)}</td>
          <td>${r.flags.length}</td>
          <td>${r.duration_seconds}s</td>
        </tr>`;
    })
    .join("");
}

document.getElementById("history-search").addEventListener("input", renderHistoryTable);

document.querySelectorAll("#history-filters .filter-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("#history-filters .filter-tab").forEach((t) => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    activeDecisionFilter = tab.dataset.decision;
    renderHistoryTable();
  });
});

loadAuditLog();
