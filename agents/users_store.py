"""User accounts, sessions, and category-approver assignments.

Same lazy, additive migration pattern as approvals_store.py and
tracing.py: tables are created with CREATE TABLE IF NOT EXISTS on first
use, independent of scripts/build_database.py's destructive catalog
rebuild.

Roles:
  admin    -- can create/manage users and assign approvers to categories;
              can act on any pending approval regardless of category.
  approver -- a "pricing leader" who can act only on pending approvals in
              the categories they've been explicitly assigned to. A
              category may have multiple approvers (any of them can act).

Passwords are hashed with bcrypt; only password_hash is ever persisted.
Sessions are server-side rows (token -> user_id) rather than JWTs, since
this is a server-rendered app, not an SPA -- a session can be revoked
immediately by deleting its row.
"""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

from agents.db import get_connection

VALID_ROLES = {"admin", "approver"}
SESSION_TTL_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            role          TEXT NOT NULL CHECK (role IN ('admin', 'approver')),
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS category_approvers (
            category TEXT NOT NULL,
            user_id  INTEGER NOT NULL REFERENCES users(id),
            PRIMARY KEY (category, user_id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _user_row_to_dict(row, categories=None) -> dict:
    d = {k: row[k] for k in row.keys() if k != "password_hash"}
    d["is_active"] = bool(d["is_active"])
    if categories is not None:
        d["categories"] = categories
    return d


def create_user(username: str, password: str, display_name: str, role: str, categories: list[str] | None = None) -> dict:
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}, got {role!r}")

    conn = get_connection()
    _ensure_tables(conn)
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, hash_password(password), display_name, role, _now_iso()),
        )
        user_id = cursor.lastrowid
        if categories:
            conn.executemany(
                "INSERT OR IGNORE INTO category_approvers (category, user_id) VALUES (?, ?)",
                [(c, user_id) for c in categories],
            )
        conn.commit()
    except Exception:
        conn.close()
        raise
    user = get_user_by_id(user_id)
    conn.close()
    return user


def get_user_by_username(username: str) -> dict | None:
    conn = get_connection()
    _ensure_tables(conn)
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return _user_row_to_dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    _ensure_tables(conn)
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    categories = [r["category"] for r in conn.execute(
        "SELECT category FROM category_approvers WHERE user_id = ? ORDER BY category", (user_id,)
    ).fetchall()]
    conn.close()
    return _user_row_to_dict(row, categories=categories)


def list_users() -> list[dict]:
    conn = get_connection()
    _ensure_tables(conn)
    rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    results = []
    for row in rows:
        categories = [r["category"] for r in conn.execute(
            "SELECT category FROM category_approvers WHERE user_id = ? ORDER BY category", (row["id"],)
        ).fetchall()]
        results.append(_user_row_to_dict(row, categories=categories))
    conn.close()
    return results


def set_user_categories(user_id: int, categories: list[str]) -> list[str]:
    """Replace the full set of categories a user approves for."""
    conn = get_connection()
    _ensure_tables(conn)
    conn.execute("DELETE FROM category_approvers WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO category_approvers (category, user_id) VALUES (?, ?)",
        [(c, user_id) for c in categories],
    )
    conn.commit()
    conn.close()
    return categories


def set_user_active(user_id: int, is_active: bool) -> None:
    conn = get_connection()
    _ensure_tables(conn)
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
    conn.commit()
    conn.close()


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials. Returns the user dict on success, None on any
    failure (unknown username, wrong password, or deactivated account) --
    deliberately not distinguishing which, so a login form can't be used
    to enumerate valid usernames."""
    conn = get_connection()
    _ensure_tables(conn)
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row is None or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return get_user_by_id(row["id"])


def create_session(user_id: int) -> str:
    conn = get_connection()
    _ensure_tables(conn)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=SESSION_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now.isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def get_user_by_session_token(token: str) -> dict | None:
    if not token:
        return None
    conn = get_connection()
    _ensure_tables(conn)
    row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
    conn.close()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        delete_session(token)
        return None
    user = get_user_by_id(row["user_id"])
    if user is None or not user["is_active"]:
        return None
    return user


def delete_session(token: str) -> None:
    conn = get_connection()
    _ensure_tables(conn)
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def count_users() -> int:
    conn = get_connection()
    _ensure_tables(conn)
    count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    conn.close()
    return count


def count_active_admins() -> int:
    conn = get_connection()
    _ensure_tables(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1"
    ).fetchone()["n"]
    conn.close()
    return count


def delete_user(user_id: int) -> None:
    """Hard-delete a user and cascade to their sessions and category
    assignments. These lazily-created tables never enable
    PRAGMA foreign_keys, so the cascade has to be done explicitly rather
    than relying on ON DELETE CASCADE."""
    conn = get_connection()
    _ensure_tables(conn)
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM category_approvers WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_approvers_for_category(category: str) -> list[dict]:
    conn = get_connection()
    _ensure_tables(conn)
    rows = conn.execute(
        """SELECT u.* FROM users u
           JOIN category_approvers ca ON ca.user_id = u.id
           WHERE ca.category = ? AND u.is_active = 1""",
        (category,),
    ).fetchall()
    conn.close()
    return [_user_row_to_dict(r) for r in rows]
