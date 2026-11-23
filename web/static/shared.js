// ---------- Shared helpers (used by every page script) ----------

const currency = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

const dateTime = (iso) =>
  new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const marginSeverity = (current, { min_margin_pct, target_margin_pct }) => {
  if (current < min_margin_pct) return "critical";
  if (current < target_margin_pct) return "warning";
  return "good";
};

// ---------- Sidebar collapse (narrow viewports) ----------

const sidebarToggle = document.getElementById("sidebar-toggle");
if (sidebarToggle) {
  sidebarToggle.addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("is-open");
  });
}

// ---------- Sidebar expand/collapse (desktop icon-rail vs. labeled), persisted ----------

const SIDEBAR_EXPANDED_KEY = "aeroprice-sidebar-expanded";
const sidebarEl = document.getElementById("sidebar");
if (sidebarEl) {
  if (localStorage.getItem(SIDEBAR_EXPANDED_KEY) === "1") {
    sidebarEl.classList.add("is-expanded");
  }
  const setExpanded = (expanded) => {
    sidebarEl.classList.toggle("is-expanded", expanded);
    localStorage.setItem(SIDEBAR_EXPANDED_KEY, expanded ? "1" : "0");
  };
  document.getElementById("sidebar-expand-pill")?.addEventListener("click", () => setExpanded(true));
  document.getElementById("sidebar-collapse-toggle")?.addEventListener("click", () => setExpanded(false));
}

// ---------- AI status pill: a real reachability check, not a fabricated uptime claim ----------

async function checkAiStatus() {
  const dot = document.querySelector("#ai-status-pill .status-pill__dot");
  const text = document.getElementById("ai-status-text");
  if (!dot || !text) return;

  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error("unhealthy");
    const data = await res.json();
    dot.className = "status-pill__dot status-pill__dot--good";
    text.textContent = "AI System: Operational";
    const modelText = document.getElementById("ai-model-text");
    if (modelText) modelText.textContent = `Model: ${data.model}`;
  } catch (e) {
    dot.className = "status-pill__dot status-pill__dot--critical";
    text.textContent = "AI System: Unreachable";
  }
}

checkAiStatus();

// ---------- Pending-approvals badges (sidebar + topbar bell), one real count from the backend ----------

async function updateSidebarBadge() {
  const sidebarBadge = document.getElementById("sidebar-pending-badge");
  const bellBadge = document.getElementById("topbar-bell-badge");
  if (!sidebarBadge && !bellBadge) return;

  try {
    const res = await fetch("/api/approvals?status=pending");
    const data = await res.json();
    const count = Array.isArray(data) ? data.length : 0;
    [sidebarBadge, bellBadge].forEach((badge) => {
      if (!badge) return;
      if (count > 0) {
        badge.textContent = count;
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    });
  } catch (e) {
    if (sidebarBadge) sidebarBadge.hidden = true;
    if (bellBadge) bellBadge.hidden = true;
  }
}

updateSidebarBadge();

// ---------- Logout ----------

const logoutBtn = document.getElementById("logout-btn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
  });
}
