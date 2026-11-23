// Admin > Global Policy: the margin/approval thresholds applied to every
// part unless a category or lifecycle override takes precedence.

async function loadGlobalPolicy() {
  const policy = await fetch("/api/admin/policy").then((r) => r.json());
  document.getElementById("policy-min-margin").value = policy.global.min_margin_pct;
  document.getElementById("policy-target-margin").value = policy.global.target_margin_pct;
  document.getElementById("policy-max-margin").value = policy.global.max_margin_pct;
  document.getElementById("policy-max-increase").value = policy.global.max_price_increase_pct_without_approval;
  document.getElementById("policy-max-decrease").value = policy.global.max_price_decrease_pct_without_approval;
}

document.getElementById("global-policy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("global-policy-error");
  const successEl = document.getElementById("global-policy-success");
  errorEl.hidden = true;
  successEl.hidden = true;

  const res = await fetch("/api/admin/policy/global", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      min_margin_pct: parseFloat(document.getElementById("policy-min-margin").value),
      target_margin_pct: parseFloat(document.getElementById("policy-target-margin").value),
      max_margin_pct: parseFloat(document.getElementById("policy-max-margin").value),
      max_price_increase_pct_without_approval: parseFloat(document.getElementById("policy-max-increase").value),
      max_price_decrease_pct_without_approval: parseFloat(document.getElementById("policy-max-decrease").value),
    }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    errorEl.textContent = data.detail || "Failed to save policy.";
    errorEl.hidden = false;
    return;
  }
  successEl.hidden = false;
});

loadGlobalPolicy();
