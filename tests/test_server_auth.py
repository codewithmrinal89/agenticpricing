"""End-to-end tests for the auth/authorization layer through the real
FastAPI app (TestClient), hitting the actual route handlers, cookie
handling, and the category-based approval authorization -- not just the
underlying store functions in isolation.
"""
from fastapi.testclient import TestClient

from agents.audit_log import log_decision
from agents.users_store import create_user
from web.server import app


def _flagged_record(request_id: str, category: str) -> dict:
    return {
        "request_id": request_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "duration_seconds": 1.0,
        "part_number": f"PN-{request_id}",
        "description": "d",
        "category": category,
        "lifecycle_status": "Active",
        "decision": "PENDING_PRICING_LEADER_APPROVAL",
        "actual_cost": 1,
        "current_list_price": 2,
        "recommended_price": 3,
        "current_margin_pct": 1,
        "price_change_pct": 1,
        "thresholds": {},
        "scenarios": {},
        "flags": ["x"],
        "narrative": "n",
        "decision_summary": "d",
        "margin_analysis": "m",
        "lifecycle_analysis": "l",
        "price_change_analysis": "p",
        "recommendation": "r",
        "approval_request": "please review",
    }


def test_approvals_api_requires_login(temp_db, temp_log):
    client = TestClient(app)
    res = client.get("/api/approvals")
    assert res.status_code == 401


def test_login_with_wrong_password_rejected(temp_db, temp_log):
    create_user("wendy", "correct-pw", "Wendy", "admin")
    client = TestClient(app)
    res = client.post("/api/login", json={"username": "wendy", "password": "wrong"})
    assert res.status_code == 401


def test_login_sets_cookie_and_me_reflects_it(temp_db, temp_log):
    create_user("wendy", "correct-pw", "Wendy", "admin")
    client = TestClient(app)

    res = client.post("/api/login", json={"username": "wendy", "password": "correct-pw"})
    assert res.status_code == 200
    assert "session_token" in res.cookies

    me = client.get("/api/me")
    assert me.json()["username"] == "wendy"


def test_logout_clears_session(temp_db, temp_log):
    create_user("wendy", "pw", "Wendy", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "wendy", "password": "pw"})

    client.post("/api/logout")
    assert client.get("/api/me").json() is None
    assert client.get("/api/approvals").status_code == 401


def test_admin_endpoints_reject_non_admin(temp_db, temp_log):
    create_user("leader", "pw", "Leader", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "leader", "password": "pw"})

    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={
        "username": "x", "password": "y", "display_name": "z", "role": "approver", "categories": [],
    }).status_code == 403


def test_admin_can_create_user_and_assign_categories(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    res = client.post("/api/admin/users", json={
        "username": "newleader", "password": "pw2", "display_name": "New Leader",
        "role": "approver", "categories": ["Engine"],
    })
    assert res.status_code == 200
    assert res.json()["categories"] == ["Engine"]

    users = client.get("/api/admin/users").json()
    assert any(u["username"] == "newleader" for u in users)


def test_approver_queue_is_scoped_to_assigned_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Avionics"))
    log_decision(_flagged_record("r2", "Structural"))

    create_user("avionics_lead", "pw", "Avionics Lead", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "avionics_lead", "password": "pw"})

    queue = client.get("/api/approvals").json()
    assert {r["request_id"] for r in queue} == {"r1"}


def test_admin_queue_sees_every_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Avionics"))
    log_decision(_flagged_record("r2", "Structural"))

    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    queue = client.get("/api/approvals").json()
    assert {r["request_id"] for r in queue} == {"r1", "r2"}


def test_approver_cannot_act_outside_assigned_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Structural"))
    create_user("avionics_lead", "pw", "Avionics Lead", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "avionics_lead", "password": "pw"})

    res = client.post("/api/approvals/r1/approve", json={"note": None})
    assert res.status_code == 403


def test_approver_can_act_within_assigned_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Avionics"))
    create_user("avionics_lead", "pw", "Avionics Lead", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "avionics_lead", "password": "pw"})

    res = client.post("/api/approvals/r1/approve", json={"note": "looks good"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"


def test_admin_can_act_on_any_category(temp_db, temp_log):
    log_decision(_flagged_record("r1", "Structural"))
    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    res = client.post("/api/approvals/r1/reject", json={"note": "not now"})
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"


def test_first_admin_setup_only_works_with_zero_users(temp_db, temp_log):
    client = TestClient(app)

    res = client.post("/api/setup/create-first-admin", json={
        "username": "root", "password": "pw", "display_name": "Root Admin",
    })
    assert res.status_code == 200
    assert res.json()["role"] == "admin"
    assert "session_token" in res.cookies  # setup logs the new admin straight in

    # A second attempt must be refused now that an account exists.
    res2 = client.post("/api/setup/create-first-admin", json={
        "username": "intruder", "password": "pw", "display_name": "Intruder",
    })
    assert res2.status_code == 403


def test_login_page_shows_setup_when_no_users_exist(temp_db, temp_log):
    client = TestClient(app)
    res = client.get("/login")
    assert "Create the first admin account" in res.text


def test_admin_delete_user(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    create_user("leader", "pw2", "Leader", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    res = client.delete("/api/admin/users/2")
    assert res.status_code == 200
    users = client.get("/api/admin/users").json()
    assert all(u["username"] != "leader" for u in users)


def test_admin_cannot_delete_self(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    res = client.delete("/api/admin/users/1")
    assert res.status_code == 400


def test_deleting_another_admin_is_fine_when_not_the_last_one(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    create_user("boss2", "pw2", "Boss2", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    # boss deletes boss2 -- fine, boss is still an active admin afterward.
    # (The system can never reach zero active admins through the API: the
    # only path to delete an admin is to be logged in as a *different*
    # active admin, and the self-delete guard prevents that last admin
    # from ever deleting themselves.)
    assert client.delete("/api/admin/users/2").status_code == 200
    remaining_usernames = {u["username"] for u in client.get("/api/admin/users").json()}
    assert remaining_usernames == {"boss"}


def test_decision_history_and_agent_activity_require_login(temp_db, temp_log):
    client = TestClient(app)
    assert client.get("/api/audit-log").status_code == 401
    assert client.get("/api/agent-runs").status_code == 401
    assert client.get("/history", follow_redirects=False).status_code == 307
    assert client.get("/agent-activity", follow_redirects=False).status_code == 307


def test_every_page_requires_login(temp_db, temp_log):
    client = TestClient(app)
    for path in ["/", "/workspace", "/approvals", "/history", "/agent-activity"]:
        res = client.get(path, follow_redirects=False)
        assert res.status_code == 307, f"{path} should redirect anonymous visitors to /login"
        assert res.headers["location"].startswith("/login")


def test_every_page_works_once_logged_in(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})
    for path in ["/", "/workspace", "/approvals", "/history", "/agent-activity"]:
        assert client.get(path).status_code == 200


def test_core_apis_require_login(temp_db, temp_log):
    client = TestClient(app)
    assert client.get("/api/parts").status_code == 401
    assert client.get("/api/dashboard-stats").status_code == 401
    assert client.post("/api/price-request", json={"part_number": "X"}).status_code == 401


def test_decision_history_and_agent_activity_blocked_for_approver(temp_db, temp_log):
    create_user("leader", "pw", "Leader", "approver", ["Avionics"])
    client = TestClient(app)
    client.post("/api/login", json={"username": "leader", "password": "pw"})

    assert client.get("/api/audit-log").status_code == 403
    assert client.get("/api/agent-runs").status_code == 403
    assert client.get("/history", follow_redirects=False).status_code == 307
    assert client.get("/agent-activity", follow_redirects=False).status_code == 307


def test_decision_history_and_agent_activity_open_to_admin(temp_db, temp_log):
    create_user("boss", "pw", "Boss", "admin")
    client = TestClient(app)
    client.post("/api/login", json={"username": "boss", "password": "pw"})

    assert client.get("/api/audit-log").status_code == 200
    assert client.get("/api/agent-runs").status_code == 200
    assert client.get("/history", follow_redirects=False).status_code == 200
    assert client.get("/agent-activity", follow_redirects=False).status_code == 200
