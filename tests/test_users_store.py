"""Tests for agents/users_store.py: password hashing, authentication,
sessions, and category-approver assignment. No network calls.
"""
from datetime import datetime, timedelta, timezone

import agents.db as db_module
import agents.users_store as users_store


def test_create_and_authenticate_user(temp_db):
    users_store.create_user("alice", "s3cret", "Alice Avionics", "approver", ["Avionics"])

    user = users_store.authenticate("alice", "s3cret")
    assert user is not None
    assert user["username"] == "alice"
    assert user["role"] == "approver"
    assert user["categories"] == ["Avionics"]
    assert "password_hash" not in user  # never exposed outward


def test_authenticate_rejects_wrong_password(temp_db):
    users_store.create_user("bob", "correct-pw", "Bob", "approver")
    assert users_store.authenticate("bob", "wrong-pw") is None


def test_authenticate_rejects_unknown_username(temp_db):
    assert users_store.authenticate("nobody", "whatever") is None


def test_authenticate_rejects_disabled_account(temp_db):
    user = users_store.create_user("carol", "pw", "Carol", "admin")
    users_store.set_user_active(user["id"], False)
    assert users_store.authenticate("carol", "pw") is None


def test_session_lifecycle(temp_db):
    user = users_store.create_user("dave", "pw", "Dave", "admin")
    token = users_store.create_session(user["id"])

    fetched = users_store.get_user_by_session_token(token)
    assert fetched["username"] == "dave"

    users_store.delete_session(token)
    assert users_store.get_user_by_session_token(token) is None


def test_expired_session_is_rejected(temp_db, monkeypatch):
    user = users_store.create_user("erin", "pw", "Erin", "admin")
    token = users_store.create_session(user["id"])

    # Force the session row into the past without waiting 7 real days.
    conn = db_module.get_connection()
    users_store._ensure_tables(conn)
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (expired, token))
    conn.commit()
    conn.close()

    assert users_store.get_user_by_session_token(token) is None


def test_set_user_categories_replaces_full_set(temp_db):
    user = users_store.create_user("frank", "pw", "Frank", "approver", ["Avionics"])
    users_store.set_user_categories(user["id"], ["Structural", "Engine"])

    refreshed = users_store.get_user_by_id(user["id"])
    assert refreshed["categories"] == ["Engine", "Structural"]  # alphabetical, per ORDER BY


def test_get_approvers_for_category_only_returns_active_assigned_users(temp_db):
    active_user = users_store.create_user("grace", "pw", "Grace", "approver", ["Avionics"])
    disabled_user = users_store.create_user("hank", "pw", "Hank", "approver", ["Avionics"])
    users_store.set_user_active(disabled_user["id"], False)

    approvers = users_store.get_approvers_for_category("Avionics")
    usernames = {a["username"] for a in approvers}
    assert usernames == {"grace"}
    assert active_user["username"] in usernames


def test_list_users_includes_categories(temp_db):
    users_store.create_user("ivan", "pw", "Ivan", "approver", ["Engine"])
    users = users_store.list_users()
    ivan = next(u for u in users if u["username"] == "ivan")
    assert ivan["categories"] == ["Engine"]


def test_delete_user_cascades_sessions_and_categories(temp_db):
    user = users_store.create_user("jill", "pw", "Jill", "approver", ["Avionics"])
    token = users_store.create_session(user["id"])

    users_store.delete_user(user["id"])

    assert users_store.get_user_by_id(user["id"]) is None
    assert users_store.get_user_by_session_token(token) is None
    assert users_store.get_approvers_for_category("Avionics") == []


def test_count_users_and_count_active_admins(temp_db):
    assert users_store.count_users() == 0
    assert users_store.count_active_admins() == 0

    admin = users_store.create_user("boss", "pw", "Boss", "admin")
    users_store.create_user("leader", "pw", "Leader", "approver")
    assert users_store.count_users() == 2
    assert users_store.count_active_admins() == 1

    users_store.set_user_active(admin["id"], False)
    assert users_store.count_active_admins() == 0
