"""Cookie-session auth helpers for the FastAPI app.

Server-side sessions (agents/users_store.py) rather than JWTs, since this
is a server-rendered Jinja2 app, not an SPA. Two dependency shapes are
provided: the `require_*` functions raise HTTPException (401/403) for use
in API routes, while page routes call `get_current_user` directly and
return a RedirectResponse themselves -- an HTTPException on a page route
would render a bare JSON error instead of sending the user to /login.
"""
from fastapi import HTTPException, Request

from agents.users_store import get_user_by_session_token

SESSION_COOKIE_NAME = "session_token"


def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return get_user_by_session_token(token)


def require_login(request: Request) -> dict:
    user = get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def block_approvers(request: Request) -> dict:
    """Requires login (like require_login) and additionally rejects the
    approver role -- for Decision History / Agent Activity endpoints,
    which span categories beyond an approver's assigned scope."""
    user = require_login(request)
    if user["role"] == "approver":
        raise HTTPException(status_code=403, detail="Not available to approver accounts")
    return user
