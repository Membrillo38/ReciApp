from __future__ import annotations

import json
import secrets
import time
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import AuthUser, current_user, require_api_key
from app.config import settings
from app.dashboard_routes import router as dashboard_router
from app.dashboard_stats import log_request
from app.db import get_supabase
from app.models import (
    AdminUserCreate,
    AdminUserPatch,
    ExtractJobResponse,
    ExtractRequest,
    HealthResponse,
    JobResponse,
    JobStatus,
    ListResponse,
    MeResponse,
    OkResponse,
    RecipeListResponse,
    RecipePublic,
)
from app.pipeline import run_extract_job
from app.quota import assert_can_extract, get_quota, record_usage
from app.store import (
    create_job,
    delete_user_recipe,
    get_job,
    get_recipe,
    list_jobs,
    list_profiles,
    list_recipes,
    list_user_recipe_summaries,
    recipe_public_from_row,
    save_user_recipe,
    soft_delete_profile,
    user_owns_recipe,
)
from app.superwall import apply_superwall_event
from app.url_norm import normalize_url

app = FastAPI(title="ReciApp API", version="1.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dashboard_router)


@app.middleware("http")
async def request_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    # Fire-and-forget style (sync insert; keep tiny)
    try:
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else None
        )
        log_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=None,
            ip=ip,
        )
    except Exception:
        pass
    return response


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/v1/webhooks/superwall")
async def superwall_webhook(
    request: Request,
    svix_id: str | None = Header(default=None, alias="svix-id"),
    svix_timestamp: str | None = Header(default=None, alias="svix-timestamp"),
    svix_signature: str | None = Header(default=None, alias="svix-signature"),
) -> JSONResponse:
    raw = await request.body()
    if settings.superwall_webhook_secret:
        try:
            from svix.webhooks import Webhook, WebhookVerificationError

            wh = Webhook(settings.superwall_webhook_secret)
            payload = wh.verify(
                raw,
                {
                    "svix-id": svix_id or "",
                    "svix-timestamp": svix_timestamp or "",
                    "svix-signature": svix_signature or "",
                },
            )
        except WebhookVerificationError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Webhook verify failed: {exc}") from exc
    else:
        # Dev only — set SUPERWALL_WEBHOOK_SECRET in production
        payload = json.loads(raw.decode("utf-8"))

    if isinstance(payload, (bytes, str)):
        payload = json.loads(payload)

    app_id = payload.get("applicationId")
    if app_id is not None and int(app_id) != settings.superwall_application_id:
        return JSONResponse({"ok": True, "skipped": "wrong_application"})

    result = apply_superwall_event(payload)
    return JSONResponse({"ok": True, **result})


@app.get("/v1/me", response_model=MeResponse)
def me(user: AuthUser = Depends(current_user)) -> MeResponse:
    q = get_quota(user)
    return MeResponse(
        id=user.id,
        display_name=user.display_name,
        is_pro=user.is_pro,
        pro_expires_at=user.pro_expires_at,
        free_used_this_week=q.free_used_this_week,
        free_limit=q.free_limit,
        free_remaining=q.free_remaining,
        pro_remaining_cents=q.pro_remaining_cents if user.is_pro else None,
    )


@app.delete("/v1/me", response_model=OkResponse)
def delete_me(user: AuthUser = Depends(current_user)) -> OkResponse:
    soft_delete_profile(user.id)
    try:
        get_supabase().auth.admin.delete_user(str(user.id))
    except Exception:
        pass
    return OkResponse()


@app.post("/v1/extract", response_model=ExtractJobResponse)
def extract_recipe(
    body: ExtractRequest,
    background: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> ExtractJobResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    url = str(body.url)
    url_norm = normalize_url(url)

    from app.store import get_recipe_by_norm

    cached = get_recipe_by_norm(url_norm)
    cache_hit = cached is not None
    assert_can_extract(user, cache_hit=cache_hit)

    if cache_hit and cached:
        recipe_id = UUID(cached["id"])
        job = create_job(
            user_id=user.id,
            source_url_raw=url,
            source_url_norm=url_norm,
            status=JobStatus.completed.value,
            cache_hit=True,
            recipe_id=recipe_id,
            cost_cents=0,
        )
        save_user_recipe(user.id, recipe_id)
        record_usage(
            user_id=user.id,
            kind="extract_hit",
            cost_cents=0,
            recipe_id=recipe_id,
            job_id=UUID(job["id"]),
        )
        return ExtractJobResponse(
            job_id=UUID(job["id"]),
            status=JobStatus.completed,
            cache_hit=True,
        )

    job = create_job(
        user_id=user.id,
        source_url_raw=url,
        source_url_norm=url_norm,
        status=JobStatus.pending.value,
        cache_hit=False,
    )
    job_id = UUID(job["id"])
    background.add_task(run_extract_job, job_id, user.id, url, url_norm)
    return ExtractJobResponse(job_id=job_id, status=JobStatus.pending, cache_hit=False)


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: UUID,
    user: AuthUser = Depends(current_user),
) -> JobResponse:
    row = get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row.get("user_id") and str(row["user_id"]) != str(user.id):
        raise HTTPException(status_code=403, detail="Not your job")

    recipe = None
    if row.get("recipe_id"):
        r = get_recipe(UUID(row["recipe_id"]))
        if r:
            recipe = recipe_public_from_row(r)

    return JobResponse(
        job_id=UUID(row["id"]),
        status=JobStatus(row["status"]),
        cache_hit=bool(row.get("cache_hit")),
        recipe=recipe,
        error=row.get("error"),
    )


@app.get("/v1/me/recipes", response_model=RecipeListResponse)
def my_recipes(user: AuthUser = Depends(current_user)) -> RecipeListResponse:
    return RecipeListResponse(items=list_user_recipe_summaries(user.id))


@app.delete("/v1/me/recipes/{recipe_id}", response_model=OkResponse)
def remove_my_recipe(
    recipe_id: UUID,
    user: AuthUser = Depends(current_user),
) -> OkResponse:
    ok = delete_user_recipe(user.id, recipe_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Recipe not in your list")
    return OkResponse()


@app.get("/v1/recipes/{recipe_id}", response_model=RecipePublic)
def recipe_detail(
    recipe_id: UUID,
    user: AuthUser = Depends(current_user),
) -> RecipePublic:
    if not user_owns_recipe(user.id, recipe_id):
        raise HTTPException(status_code=403, detail="Recipe not in your list")
    row = get_recipe(recipe_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe_public_from_row(row)


# --- Admin ---


@app.get("/v1/admin/users", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_list_users(limit: int = Query(100, ge=1, le=500)) -> ListResponse:
    return ListResponse(items=list_profiles(limit=limit))


@app.post("/v1/admin/users", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_create_user(body: AdminUserCreate) -> ListResponse:
    sb = get_supabase()
    attrs: dict = {"email": body.email, "email_confirm": True}
    attrs["password"] = body.password or secrets.token_urlsafe(24)
    try:
        created = sb.auth.admin.create_user(attrs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = created.user
    if not user:
        raise HTTPException(status_code=400, detail="User create failed")

    payload = {
        "id": str(user.id),
        "display_name": body.display_name or body.email,
        "is_pro": body.is_pro,
    }
    sb.table("profiles").upsert(payload).execute()
    return ListResponse(items=[payload])


@app.patch("/v1/admin/users/{user_id}", dependencies=[Depends(require_api_key)])
def admin_patch_user(user_id: UUID, body: AdminUserPatch):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = (
        get_supabase()
        .table("profiles")
        .update(fields)
        .eq("id", str(user_id))
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")
    return res.data[0]


@app.delete("/v1/admin/users/{user_id}", response_model=OkResponse, dependencies=[Depends(require_api_key)])
def admin_delete_user(user_id: UUID) -> OkResponse:
    soft_delete_profile(user_id)
    try:
        get_supabase().auth.admin.delete_user(str(user_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OkResponse()


@app.get("/v1/admin/recipes", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_list_recipes(limit: int = Query(50, ge=1, le=500)) -> ListResponse:
    return ListResponse(items=list_recipes(limit=limit))


@app.get("/v1/admin/jobs", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_list_jobs(limit: int = Query(50, ge=1, le=500)) -> ListResponse:
    return ListResponse(items=list_jobs(limit=limit))


@app.get("/v1/admin/usage", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_usage(limit: int = Query(100, ge=1, le=1000)) -> ListResponse:
    res = (
        get_supabase()
        .table("usage_events")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return ListResponse(items=res.data or [])
