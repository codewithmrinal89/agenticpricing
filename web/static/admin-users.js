// Admin > Users: create users, assign per-category approvers,
// activate/deactivate/delete accounts. All against the real backend
// (agents/users_store.py) -- nothing here is simulated.

let allCategories = [];
let selectedNewCategories = new Set();

async function loadCategories() {
  const res = await fetch("/api/admin/categories");
  allCategories = await res.json();
  renderCategoryPicker("new-categories-picker", allCategories, selectedNewCategories, () => {});
}

function renderCategoryPicker(containerId, categories, selectedSet, onToggle) {
  const container = document.getElementById(containerId);
  container.innerHTML = categories
    .map(
      (c) => `<span class="category-chip ${selectedSet.has(c) ? "is-selected" : ""}" data-category="${c}">${c}</span>`
    )
    .join("");
  container.querySelectorAll(".category-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const c = chip.dataset.category;
      if (selectedSet.has(c)) {
        selectedSet.delete(c);
        chip.classList.remove("is-selected");
      } else {
        selectedSet.add(c);
        chip.classList.add("is-selected");
      }
      onToggle(selectedSet);
    });
  });
}

document.getElementById("new-role").addEventListener("change", (e) => {
  document.getElementById("new-categories-wrap").hidden = e.target.value === "admin";
});

document.getElementById("create-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("create-user-error");
  errorEl.hidden = true;

  const body = {
    username: document.getElementById("new-username").value.trim(),
    password: document.getElementById("new-password").value,
    display_name: document.getElementById("new-display-name").value.trim(),
    role: document.getElementById("new-role").value,
    categories: Array.from(selectedNewCategories),
  };

  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    errorEl.textContent = data.detail || "Failed to create user.";
    errorEl.hidden = false;
    return;
  }

  document.getElementById("create-user-form").reset();
  selectedNewCategories = new Set();
  renderCategoryPicker("new-categories-picker", allCategories, selectedNewCategories, () => {});
  await loadUsers();
});

async function loadUsers() {
  const res = await fetch("/api/admin/users");
  const users = await res.json();
  document.getElementById("users-count").textContent = `${users.length} user(s)`;

  const tbody = document.getElementById("users-table-body");
  tbody.innerHTML = users
    .map((u) => {
      const statusChip = u.is_active
        ? '<span class="chip chip--good">Active</span>'
        : '<span class="chip chip--critical">Disabled</span>';
      const categoriesHTML =
        u.role === "admin"
          ? '<span class="muted">All categories</span>'
          : u.categories.length === 0
          ? '<span class="muted">None assigned</span>'
          : u.categories.map((c) => `<span class="category-chip is-selected">${c}</span>`).join(" ");
      return `
        <tr data-user-id="${u.id}">
          <td>${u.username}</td>
          <td>${u.display_name}</td>
          <td>${u.role}</td>
          <td><div class="category-picker" id="categories-${u.id}">${categoriesHTML}</div>
            ${u.role === "approver" ? `<button class="filter-tab edit-categories-btn" data-user-id="${u.id}">Edit</button>` : ""}
          </td>
          <td>${statusChip}</td>
          <td><button class="filter-tab toggle-active-btn" data-user-id="${u.id}" data-active="${u.is_active}">${
        u.is_active ? "Disable" : "Enable"
      }</button></td>
          <td><button class="filter-tab delete-user-btn" data-user-id="${u.id}" data-username="${u.username}">Delete</button></td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll(".toggle-active-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const userId = btn.dataset.userId;
      const nextActive = btn.dataset.active !== "true";
      await fetch(`/api/admin/users/${userId}/active`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: nextActive }),
      });
      loadUsers();
    });
  });

  tbody.querySelectorAll(".edit-categories-btn").forEach((btn) => {
    btn.addEventListener("click", () => editCategories(btn.dataset.userId, users));
  });

  tbody.querySelectorAll(".delete-user-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Permanently delete user ${btn.dataset.username}? This cannot be undone.`)) return;
      const res = await fetch(`/api/admin/users/${btn.dataset.userId}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || "Failed to delete user.");
        return;
      }
      loadUsers();
    });
  });
}

function editCategories(userId, users) {
  const user = users.find((u) => String(u.id) === String(userId));
  const selected = new Set(user.categories);
  const container = document.getElementById(`categories-${userId}`);
  container.innerHTML = "";
  renderCategoryPicker(`categories-${userId}`, allCategories, selected, () => {});

  const saveBtn = document.createElement("button");
  saveBtn.className = "filter-tab";
  saveBtn.textContent = "Save";
  saveBtn.addEventListener("click", async () => {
    await fetch(`/api/admin/users/${userId}/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ categories: Array.from(selected) }),
    });
    loadUsers();
  });
  container.parentElement.appendChild(saveBtn);
}

async function init() {
  await loadCategories();
  await loadUsers();
}

init();
