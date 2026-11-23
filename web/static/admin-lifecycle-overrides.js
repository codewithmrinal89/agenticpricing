// Admin > Lifecycle Overrides: per-lifecycle-status min margin / forced
// approval overrides (e.g. Obsolete parts always require review).

let allLifecycleStatuses = [];

async function loadLifecycleOverrides() {
  const [policy, statuses] = await Promise.all([
    fetch("/api/admin/policy").then((r) => r.json()),
    fetch("/api/admin/policy/lifecycle-statuses").then((r) => r.json()),
  ]);
  allLifecycleStatuses = statuses;
  renderLifecycleOverrides(policy.lifecycle_overrides);
}

function renderLifecycleOverrides(overrides) {
  const tbody = document.getElementById("lifecycle-overrides-body");
  tbody.innerHTML = allLifecycleStatuses
    .map((status) => {
      const o = overrides[status] || {};
      return `
        <tr data-status="${status}">
          <td>${status}</td>
          <td><input class="field-select override-min" type="number" step="0.1" value="${o.min_margin_pct ?? ""}" placeholder="(global)" /></td>
          <td><input class="override-requires" type="checkbox" ${o.requires_approval ? "checked" : ""} /></td>
          <td><input class="field-select override-note" type="text" value="${o.note || ""}" placeholder="optional note" /></td>
          <td>
            <button class="filter-tab save-lifecycle-override" data-status="${status}">Save</button>
            <button class="filter-tab clear-lifecycle-override" data-status="${status}">Clear</button>
          </td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".save-lifecycle-override").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = tbody.querySelector(`tr[data-status="${btn.dataset.status}"]`);
      const min = row.querySelector(".override-min").value;
      await fetch(`/api/admin/policy/lifecycle/${encodeURIComponent(btn.dataset.status)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          min_margin_pct: min === "" ? null : parseFloat(min),
          requires_approval: row.querySelector(".override-requires").checked,
          note: row.querySelector(".override-note").value || null,
        }),
      });
      loadLifecycleOverrides();
    });
  });

  tbody.querySelectorAll(".clear-lifecycle-override").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/admin/policy/lifecycle/${encodeURIComponent(btn.dataset.status)}`, { method: "DELETE" });
      loadLifecycleOverrides();
    });
  });
}

loadLifecycleOverrides();
