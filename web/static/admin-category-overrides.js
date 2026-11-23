// Admin > Category Overrides: per-category target/min margin overrides.

let allCategories = [];

async function loadCategoryOverrides() {
  const [policy, categories] = await Promise.all([
    fetch("/api/admin/policy").then((r) => r.json()),
    fetch("/api/admin/categories").then((r) => r.json()),
  ]);
  allCategories = categories;
  renderCategoryOverrides(policy.category_overrides);
}

function renderCategoryOverrides(overrides) {
  const tbody = document.getElementById("category-overrides-body");
  tbody.innerHTML = allCategories
    .map((c) => {
      const o = overrides[c] || {};
      return `
        <tr data-category="${c}">
          <td>${c}</td>
          <td><input class="field-select override-target" type="number" step="0.1" value="${o.target_margin_pct ?? ""}" placeholder="(global)" /></td>
          <td><input class="field-select override-min" type="number" step="0.1" value="${o.min_margin_pct ?? ""}" placeholder="(global)" /></td>
          <td>
            <button class="filter-tab save-category-override" data-category="${c}">Save</button>
            <button class="filter-tab clear-category-override" data-category="${c}">Clear</button>
          </td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".save-category-override").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = tbody.querySelector(`tr[data-category="${btn.dataset.category}"]`);
      const target = row.querySelector(".override-target").value;
      const min = row.querySelector(".override-min").value;
      await fetch(`/api/admin/policy/category/${encodeURIComponent(btn.dataset.category)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_margin_pct: target === "" ? null : parseFloat(target),
          min_margin_pct: min === "" ? null : parseFloat(min),
        }),
      });
      loadCategoryOverrides();
    });
  });

  tbody.querySelectorAll(".clear-category-override").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`/api/admin/policy/category/${encodeURIComponent(btn.dataset.category)}`, { method: "DELETE" });
      loadCategoryOverrides();
    });
  });
}

loadCategoryOverrides();
