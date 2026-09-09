from __future__ import annotations

import time
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dashboard_auth import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session_token,
    csrf_for_request,
    csrf_matches,
    dashboard_enabled,
    read_session_token,
    set_session_cookie,
    verify_password,
    verify_totp,
)
from app.config import settings
from app.security import audit_security_event, allow_rate_limit, request_ip
from app.dashboard_stats import dashboard_overview, list_usage
from app.db import get_supabase
from app.store import anonymize_user_data, list_jobs, list_live_queue_jobs, list_profiles, list_recipes, soft_delete_profile

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _authed(request: Request) -> bool:
    return read_session_token(request.cookies.get(COOKIE_NAME))


def _guard(request: Request) -> RedirectResponse | None:
    if not dashboard_enabled():
        return RedirectResponse("/dashboard/login?err=disabled", status_code=303)
    if not _authed(request):
        return RedirectResponse("/dashboard/login", status_code=303)
    return None


def _ctx(request: Request, tab: str, **extra):
    return {
        "request": request,
        "show_nav": True,
        "tab": tab,
        "csrf": csrf_for_request(request),
        "flash": request.query_params.get("ok"),
        "error": request.query_params.get("err"),
        **extra,
    }


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if _authed(request):
        return RedirectResponse("/dashboard", status_code=303)
    err = request.query_params.get("err")
    msg = None
    if err == "bad":
        msg = "Credenciales incorrectas"
    elif err == "disabled":
        msg = "Configura DASHBOARD_PASSWORD, DASHBOARD_SESSION_SECRET y DASHBOARD_TOTP_SECRET en Render"
    elif err == "rate":
        msg = "Demasiados intentos; espera unos minutos"
    return templates.TemplateResponse(
        "dashboard/login.html",
        {"request": request, "show_nav": False, "tab": "login", "error": msg, "flash": None},
    )


@router.post("/login")
def login_submit(request: Request, password: str = Form(...), totp: str = Form(...)):
    ip = request_ip(request)
    if not allow_rate_limit(f"dashboard-login:{ip}", limit=5, window_seconds=15 * 60):
        audit_security_event(event="dashboard_login_rate_limited", request=request)
        return RedirectResponse("/dashboard/login?err=rate", status_code=303)
    if not dashboard_enabled() or not verify_password(password) or not verify_totp(totp):
        audit_security_event(event="dashboard_login_rejected", request=request)
        return RedirectResponse("/dashboard/login?err=bad", status_code=303)
    token = create_session_token()
    resp = RedirectResponse("/dashboard", status_code=303)
    set_session_cookie(resp, token)
    audit_security_event(event="dashboard_login_accepted", request=request)
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/dashboard/login", status_code=303)
    clear_session_cookie(resp)
    return resp


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    if redir := _guard(request):
        return redir
    return templates.TemplateResponse(
        "dashboard/overview.html",
        _ctx(request, "overview", o=dashboard_overview()),
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    if redir := _guard(request):
        return redir
    return templates.TemplateResponse(
        "dashboard/users.html",
        _ctx(request, "users", users=list_profiles(200)),
    )


@router.post("/users/{user_id}/pro")
def toggle_pro(request: Request, user_id: UUID, csrf: str = Form(...), is_pro: str = Form(...)):
    if redir := _guard(request):
        return redir
    if not csrf_matches(request, csrf):
        return RedirectResponse("/dashboard/users?err=csrf", status_code=303)
    get_supabase().table("profiles").update({"is_pro": is_pro == "1"}).eq(
        "id", str(user_id)
    ).execute()
    audit_security_event(event="dashboard_pro_changed", request=request, user_id=str(user_id), metadata={"is_pro": is_pro == "1"})
    return RedirectResponse("/dashboard/users?ok=updated", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(request: Request, user_id: UUID, csrf: str = Form(...)):
    if redir := _guard(request):
        return redir
    if not csrf_matches(request, csrf):
        return RedirectResponse("/dashboard/users?err=csrf", status_code=303)
    anonymize_user_data(user_id)
    soft_delete_profile(user_id)
    try:
        get_supabase().auth.admin.delete_user(str(user_id))
    except Exception:
        pass
    audit_security_event(event="dashboard_user_deleted", request=request, user_id=str(user_id))
    return RedirectResponse("/dashboard/users?ok=deleted", status_code=303)


@router.get("/recipes", response_class=HTMLResponse)
def recipes_page(request: Request):
    if redir := _guard(request):
        return redir
    return templates.TemplateResponse(
        "dashboard/recipes.html",
        _ctx(request, "recipes", recipes=list_recipes(100)),
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    if redir := _guard(request):
        return redir
    queue = list_live_queue_jobs(limit=100)
    for index, row in enumerate(queue):
        row["queue_position"] = index + 1
    live = {
        "queue": queue,
        "processing_count": sum(1 for row in queue if row.get("status") == "processing"),
        "pending_count": sum(1 for row in queue if row.get("status") == "pending"),
    }
    return templates.TemplateResponse(
        "dashboard/jobs.html",
        _ctx(request, "jobs", jobs=list_jobs(100), live=live),
    )


@router.get("/usage", response_class=HTMLResponse)
def usage_page(request: Request):
    if redir := _guard(request):
        return redir
    return templates.TemplateResponse(
        "dashboard/usage.html",
        _ctx(request, "usage", usage=list_usage(150)),
    )


@router.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request):
    if redir := _guard(request):
        return redir
    rows = (
        get_supabase()
        .table("api_request_logs")
        .select("*")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
        or []
    )
    return templates.TemplateResponse(
        "dashboard/requests.html",
        _ctx(request, "requests", requests=rows),
    )
