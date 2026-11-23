"""Web UI backend: a thin FastAPI wrapper around the agent pipeline.

Nothing agentic happens in this file -- it just exposes the Supervisor,
the audit log, and the approval queue over HTTP so the frontend can call
them. All the actual agent logic still lives in agents/.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import json

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from agents.approvals_store import get_category_for_request, list_approvals, set_review_status
from agents.audit_log import compute_dashboard_stats, read_log
from agents.llm_client import MODEL
from agents.policy_store import (
    clear_category_override,
    clear_lifecycle_override,
    get_policy,
    list_lifecycle_statuses,
    set_category_override,
    set_lifecycle_override,
    update_global_policy,
)
from agents.supervisor import process_pricing_request, process_pricing_request_stream
from agents.tools import list_all_categories, list_all_parts
from agents.tracing import get_pipeline_run, list_agent_executions, list_pipeline_runs, list_tool_executions
from agents.users_store import (
    authenticate,
    count_active_admins,
    count_users,
    create_session,
    create_user,
    delete_session,
    delete_user,
    get_user_by_id,
    list_users,
    set_user_active,
    set_user_categories,
)
from web.auth import SESSION_COOKIE_NAME, block_approvers, get_current_user, require_admin, require_login

app = FastAPI(title="Pricing Agent Console")


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """This is an actively-edited dev server -- browsers aggressively cache
    CSS/JS by default, which silently serves stale UI after every change.
    Force revalidation on every request instead of hunting cache bugs."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/") or not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheStaticMiddleware)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _tojson_for_script(value) -> "Markup":
    """Jinja's autoescaping HTML-entity-escapes filter output by default,
    which corrupts JSON embedded in a <script> block (quotes become
    &#34; -- invalid JS, silently breaks whatever reads that variable).
    Mirrors Flask's real `tojson`: escape </script>-breaking characters as
    unicode escapes (valid inside both JSON and JS), then mark the result
    safe so autoescaping doesn't re-encode it."""
    return Markup(json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


templates.env.filters["tojson"] = _tojson_for_script


class PriceRequestBody(BaseModel):
    part_number: str


class ReviewBody(BaseModel):
    note: str | None = None


class LoginBody(BaseModel):
    username: str
    password: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    display_name: str
    role: str
    categories: list[str] = []


class CategoriesBody(BaseModel):
    categories: list[str]


class ActiveBody(BaseModel):
    is_active: bool


class SetupBody(BaseModel):
    username: str
    password: str
    display_name: str


class GlobalPolicyBody(BaseModel):
    min_margin_pct: float | None = None
    target_margin_pct: float | None = None
    max_margin_pct: float | None = None
    max_price_increase_pct_without_approval: float | None = None
    max_price_decrease_pct_without_approval: float | None = None


class CategoryOverrideBody(BaseModel):
    target_margin_pct: float | None = None
    min_margin_pct: float | None = None


class LifecycleOverrideBody(BaseModel):
    min_margin_pct: float | None = None
    requires_approval: bool = False
    note: str | None = None


def _page_context(request: Request, active_page: str, **extra) -> dict:
    return {"active_page": active_page, "current_user": get_current_user(request), **extra}


def _require_login_page(request: Request, path: str):
    """Shared guard for every page in the app: redirect to /login if
    signed out. Returns a RedirectResponse to send back immediately, or
    None if the request may proceed."""
    if get_current_user(request) is None:
        return RedirectResponse(url=f"/login?next={path}")
    return None


# ---------- Pages ----------

@app.get("/")
def page_overview(request: Request):
    return _require_login_page(request, "/") or templates.TemplateResponse(
        request, "overview.html", _page_context(request, "overview")
    )


@app.get("/workspace")
def page_workspace(request: Request):
    return _require_login_page(request, "/workspace") or templates.TemplateResponse(
        request, "workspace.html", _page_context(request, "workspace")
    )


@app.get("/approvals")
def page_approvals(request: Request):
    return _require_login_page(request, "/approvals") or templates.TemplateResponse(
        request, "approvals.html", _page_context(request, "approvals")
    )


def _blocked_for_approvers(request: Request):
    """Decision History and Agent Activity are hidden from approvers --
    those pages span decisions/traces beyond a category-scoped approver's
    assigned scope. Admins are unaffected."""
    user = get_current_user(request)
    if user is not None and user["role"] == "approver":
        return RedirectResponse(url="/")
    return None


@app.get("/history")
def page_history(request: Request):
    return (
        _require_login_page(request, "/history")
        or _blocked_for_approvers(request)
        or templates.TemplateResponse(request, "history.html", _page_context(request, "history"))
    )


@app.get("/agent-activity")
def page_agent_activity(request: Request):
    return (
        _require_login_page(request, "/agent-activity")
        or _blocked_for_approvers(request)
        or templates.TemplateResponse(request, "agent_activity.html", _page_context(request, "agent-activity"))
    )


@app.get("/login")
def page_login(request: Request, next: str = "/"):
    if get_current_user(request) is not None:
        return RedirectResponse(url=next)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"active_page": "login", "next": next, "current_user": None, "needs_setup": count_users() == 0},
    )


def _require_admin_page(request: Request, path: str):
    """Shared guard for the 4 admin pages: redirect to login if signed
    out, or home if signed in but not an admin. Returns a RedirectResponse
    to send back immediately, or None if the request may proceed."""
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url=f"/login?next={path}")
    if user["role"] != "admin":
        return RedirectResponse(url="/")
    return None


@app.get("/admin")
def page_admin_index(request: Request):
    return RedirectResponse(url="/admin/users")


@app.get("/admin/global-policy")
def page_admin_global_policy(request: Request):
    return _require_admin_page(request, "/admin/global-policy") or templates.TemplateResponse(
        request, "admin_global_policy.html", _page_context(request, "admin-global-policy")
    )


@app.get("/admin/category-overrides")
def page_admin_category_overrides(request: Request):
    return _require_admin_page(request, "/admin/category-overrides") or templates.TemplateResponse(
        request, "admin_category_overrides.html", _page_context(request, "admin-category-overrides")
    )


@app.get("/admin/lifecycle-overrides")
def page_admin_lifecycle_overrides(request: Request):
    return _require_admin_page(request, "/admin/lifecycle-overrides") or templates.TemplateResponse(
        request, "admin_lifecycle_overrides.html", _page_context(request, "admin-lifecycle-overrides")
    )


@app.get("/admin/users")
def page_admin_users(request: Request):
    return _require_admin_page(request, "/admin/users") or templates.TemplateResponse(
        request, "admin_users.html", _page_context(request, "admin-users")
    )


# ---------- API ----------

@app.get("/api/health")
def api_health():
    return {"status": "ok", "model": MODEL}


@app.get("/api/parts")
def api_list_parts(_: dict = Depends(require_login)):
    return list_all_parts()


@app.post("/api/price-request")
def api_price_request(body: PriceRequestBody, _: dict = Depends(require_login)):
    try:
        return process_pricing_request(body.part_number)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/price-request-stream")
def api_price_request_stream(part_number: str, _: dict = Depends(require_login)):
    """Server-Sent Events version of /api/price-request: streams a
    step_start/step_done pair for each agent as it runs, then a final
    result event. Lets the UI show which agent is working right now
    instead of a cosmetic progress animation."""

    def event_source():
        try:
            for event in process_pricing_request_stream(part_number):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/api/audit-log")
def api_audit_log(_: dict = Depends(block_approvers)):
    return list(reversed(read_log()))


@app.get("/api/dashboard-stats")
def api_dashboard_stats(_: dict = Depends(require_login)):
    return compute_dashboard_stats()


@app.get("/api/approvals")
def api_list_approvals(status: str | None = None, user: dict = Depends(require_login)):
    # Admins see every pending-review decision; approvers only see the
    # categories they've been explicitly assigned by an admin.
    categories = None if user["role"] == "admin" else user["categories"]
    return list_approvals(status_filter=status, categories=categories)


def _authorize_review_action(request_id: str, user: dict) -> None:
    if user["role"] == "admin":
        return
    category = get_category_for_request(request_id)
    if category is None or category not in user["categories"]:
        raise HTTPException(status_code=403, detail="You are not an assigned approver for this part's category")


@app.post("/api/approvals/{request_id}/approve")
def api_approve(request_id: str, body: ReviewBody | None = None, user: dict = Depends(require_login)):
    _authorize_review_action(request_id, user)
    try:
        return set_review_status(request_id, "approved", body.note if body else None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/approvals/{request_id}/reject")
def api_reject(request_id: str, body: ReviewBody | None = None, user: dict = Depends(require_login)):
    _authorize_review_action(request_id, user)
    try:
        return set_review_status(request_id, "rejected", body.note if body else None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/agent-runs")
def api_list_agent_runs(
    limit: int = 50, offset: int = 0, status: str | None = None, _: dict = Depends(block_approvers)
):
    return list_pipeline_runs(limit=limit, offset=offset, status_filter=status)


@app.get("/api/agent-runs/{run_id}")
def api_get_agent_run(run_id: str, _: dict = Depends(block_approvers)):
    run = get_pipeline_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="pipeline run not found")
    return run


@app.get("/api/agent-runs/{run_id}/executions")
def api_list_run_executions(run_id: str, _: dict = Depends(block_approvers)):
    return list_agent_executions(run_id)


@app.get("/api/agent-executions/{execution_id}/tools")
def api_list_execution_tools(execution_id: str, _: dict = Depends(block_approvers)):
    return list_tool_executions(execution_id)


# ---------- Auth ----------

@app.post("/api/login")
def api_login(body: LoginBody, response: Response):
    user = authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password, or account disabled")
    token = create_session(user["id"])
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
    return user


@app.post("/api/logout")
def api_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        delete_session(token)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "ok"}


@app.get("/api/me")
def api_me(request: Request):
    return get_current_user(request)


# ---------- Admin ----------

@app.get("/api/admin/users")
def api_admin_list_users(_: dict = Depends(require_admin)):
    return list_users()


@app.post("/api/admin/users")
def api_admin_create_user(body: CreateUserBody, _: dict = Depends(require_admin)):
    try:
        return create_user(body.username, body.password, body.display_name, body.role, body.categories)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=409, detail=f"Username {body.username!r} is already taken")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/users/{user_id}/categories")
def api_admin_set_categories(user_id: int, body: CategoriesBody, _: dict = Depends(require_admin)):
    if get_user_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    set_user_categories(user_id, body.categories)
    return get_user_by_id(user_id)


@app.post("/api/admin/users/{user_id}/active")
def api_admin_set_active(user_id: int, body: ActiveBody, _: dict = Depends(require_admin)):
    if get_user_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    set_user_active(user_id, body.is_active)
    return get_user_by_id(user_id)


@app.get("/api/admin/categories")
def api_admin_list_categories(_: dict = Depends(require_admin)):
    return list_all_categories()


@app.delete("/api/admin/users/{user_id}")
def api_admin_delete_user(user_id: int, current: dict = Depends(require_admin)):
    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target["id"] == current["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account while logged in as it")
    if target["role"] == "admin" and target["is_active"] and count_active_admins() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    delete_user(user_id)
    return {"status": "deleted", "id": user_id}


# ---------- First-run setup (no auth required, only works with zero users) ----------

@app.post("/api/setup/create-first-admin")
def api_setup_create_first_admin(body: SetupBody, response: Response):
    if count_users() > 0:
        raise HTTPException(status_code=403, detail="Setup already completed -- an account already exists")
    user = create_user(body.username, body.password, body.display_name, role="admin")
    token = create_session(user["id"])
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
    return user


# ---------- Admin: pricing policy ----------

@app.get("/api/admin/policy")
def api_admin_get_policy(_: dict = Depends(require_admin)):
    return get_policy()


@app.get("/api/admin/policy/lifecycle-statuses")
def api_admin_list_lifecycle_statuses(_: dict = Depends(require_admin)):
    return list_lifecycle_statuses()


@app.post("/api/admin/policy/global")
def api_admin_update_global_policy(body: GlobalPolicyBody, _: dict = Depends(require_admin)):
    return update_global_policy({k: v for k, v in body.model_dump().items() if v is not None})


@app.post("/api/admin/policy/category/{category}")
def api_admin_set_category_override(category: str, body: CategoryOverrideBody, _: dict = Depends(require_admin)):
    try:
        set_category_override(category, body.target_margin_pct, body.min_margin_pct)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return get_policy()["category_overrides"].get(category, {})


@app.delete("/api/admin/policy/category/{category}")
def api_admin_clear_category_override(category: str, _: dict = Depends(require_admin)):
    clear_category_override(category)
    return {"status": "cleared"}


@app.post("/api/admin/policy/lifecycle/{status}")
def api_admin_set_lifecycle_override(status: str, body: LifecycleOverrideBody, _: dict = Depends(require_admin)):
    try:
        set_lifecycle_override(status, body.min_margin_pct, body.requires_approval, body.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return get_policy()["lifecycle_overrides"].get(status, {})


@app.delete("/api/admin/policy/lifecycle/{status}")
def api_admin_clear_lifecycle_override(status: str, _: dict = Depends(require_admin)):
    clear_lifecycle_override(status)
    return {"status": "cleared"}
