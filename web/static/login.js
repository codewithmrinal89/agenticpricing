// Login page: posts credentials (or, on first run, creates the first admin
// account), sets the session cookie server-side, then redirects to
// wherever the user was headed (LOGIN_NEXT, injected by login.html from
// the ?next= query param).

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    const errorEl = document.getElementById("login-error");
    errorEl.hidden = true;

    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      errorEl.textContent = data.detail || "Login failed.";
      errorEl.hidden = false;
      return;
    }

    window.location.href = LOGIN_NEXT || "/";
  });
}

const setupForm = document.getElementById("setup-form");
if (setupForm) {
  setupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("setup-error");
    errorEl.hidden = true;

    const body = {
      username: document.getElementById("setup-username").value.trim(),
      display_name: document.getElementById("setup-display-name").value.trim(),
      password: document.getElementById("setup-password").value,
    };

    const res = await fetch("/api/setup/create-first-admin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      errorEl.textContent = data.detail || "Setup failed.";
      errorEl.hidden = false;
      return;
    }

    window.location.href = "/admin";
  });
}
