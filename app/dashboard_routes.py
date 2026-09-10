from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.dashboard_stats import dashboard_overview, list_usage
from app.db import fetch_all
from app.store import list_jobs, list_live_queue_jobs, list_profiles, list_recipes

# ponytail: open read-only ops UI (no login). Prefer Tailscale/Homepage link; public URL exposes metrics.
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


@router.get("/login", response_class=HTMLResponse)
def login_redirect():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
def logout_redirect():
    return RedirectResponse("/dashboard", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def overview(request: Request):
    return templates.TemplateResponse(
        "dashboard/overview.html",
        _ctx(request, "overview", o=dashboard_overview()),
    )


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    return templates.TemplateResponse(
        "dashboard/users.html",
        _ctx(request, "users", users=list_profiles(200)),
    )


@router.get("/recipes", response_class=HTMLResponse)
def recipes_page(request: Request):
    return templates.TemplateResponse(
        "dashboard/recipes.html",
        _ctx(request, "recipes", recipes=list_recipes(100)),
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
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
    return templates.TemplateResponse(
        "dashboard/usage.html",
        _ctx(request, "usage", usage=list_usage(150)),
    )


@router.get("/requests", response_class=HTMLResponse)
def requests_page(request: Request):
    rows = fetch_all("select * from api_request_logs order by created_at desc limit 200")
    return templates.TemplateResponse(
        "dashboard/requests.html",
        _ctx(request, "requests", requests=rows),
    )
