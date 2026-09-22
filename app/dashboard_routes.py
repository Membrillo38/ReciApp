from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dashboard_auth import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session_token,
    dashboard_enabled,
    read_session_token,
    set_session_cookie,
    totp_required,
    verify_password,
    verify_totp,
)
from app.dashboard_stats import (
    dashboard_ip_detail,
    dashboard_ips,
    dashboard_overview,
    dashboard_threats,
    list_usage,
)
from app.db import fetch_all
from app.security import request_ip, require_rate_limit
from app.store import list_jobs, list_live_queue_jobs, list_profiles, list_recipes

# Tailscale / cpanel only — public Host is blocked in main middleware.
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ctx(request: Request, tab: str, **extra):
    return {
        "request": request,
        "show_nav": True,
        "tab": tab,
        "flash": request.query_params.get("ok"),
        "error": request.query_params.get("err"),
        **extra,
    }


def _require_admin(request: Request) -> RedirectResponse | None:
    """Fail closed: no secrets or session means no dashboard data."""
    if not dashboard_enabled():
        return RedirectResponse("/dashboard/login?err=Dashboard+sin+configurar", status_code=303)
    if read_session_token(request.cookies.get(COOKIE_NAME)):
        return None
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        f"/dashboard/login?next={next_path}",
        status_code=303,
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if dashboard_enabled() and read_session_token(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        "dashboard/login.html",
        {
            "request": request,
            "show_nav": False,
            "tab": "login",
            "flash": request.query_params.get("ok"),
            "error": request.query_params.get("err"),
            "configured": dashboard_enabled(),
            "totp_required": totp_required(),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(""),
    totp: str = Form(""),
):
    require_rate_limit(
        request,
        key=f"dashboard-login-ip:{request_ip(request)}",
        limit=10,
        window_seconds=300,
        event="dashboard_login_rate_limited",
        retry_after_seconds=300,
    )
    if not dashboard_enabled():
        return RedirectResponse("/dashboard/login?err=Dashboard+sin+configurar", status_code=303)
    if not (verify_password(password) and verify_totp(totp.strip())):
        return RedirectResponse("/dashboard/login?err=Password+o+TOTP+incorrecto", status_code=303)
    response = RedirectResponse("/dashboard", status_code=303)
    set_session_cookie(response, create_session_token())
    return response


@router.get("/logout")
def logout_redirect():
    response = RedirectResponse("/dashboard/login?ok=Sesion+cerrada", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/overview.html",
        _ctx(request, "overview", o=dashboard_overview()),
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/users.html",
        _ctx(request, "users", users=list_profiles(200)),
    )


@router.get("/recipes", response_class=HTMLResponse)
def recipes_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/recipes.html",
        _ctx(request, "recipes", recipes=list_recipes(100)),
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
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
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/usage.html",
        _ctx(request, "usage", usage=list_usage(150)),
    )


@router.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    rows = fetch_all("select * from api_request_logs order by created_at desc limit 200")
    return templates.TemplateResponse(
        "dashboard/requests.html",
        _ctx(request, "requests", requests=rows),
    )


@router.get("/threats", response_class=HTMLResponse)
def threats_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/threats.html",
        _ctx(request, "threats", t=dashboard_threats()),
    )


@router.get("/ips", response_class=HTMLResponse)
def ips_page(request: Request):
    gate = _require_admin(request)
    if gate:
        return gate
    return templates.TemplateResponse(
        "dashboard/ips.html",
        _ctx(request, "ips", i=dashboard_ips()),
    )


@router.get("/ips/{ip}", response_class=HTMLResponse)
def ips_detail_page(request: Request, ip: str):
    gate = _require_admin(request)
    if gate:
        return gate
    try:
        ip = str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        return RedirectResponse("/dashboard/ips?err=IP+invalida", status_code=303)
    detail = dashboard_ip_detail(ip)
    if detail is None:
        return RedirectResponse("/dashboard/ips?err=IP+no+encontrada", status_code=303)
    return templates.TemplateResponse(
        "dashboard/ip_detail.html",
        _ctx(request, "ips", d=detail),
    )
