from __future__ import annotations

import json
import logging
import secrets
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import AuthUser, current_user, require_api_key
from app.apple_notifications import process_signed_notification
from app.config import settings
from app.dashboard_routes import router as dashboard_router
from app.dashboard_stats import log_request
from app.db import get_supabase, reset_supabase
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
from app.pipeline import run_extract_job, run_translation_job
from app.quota import assert_can_extract, get_quota, record_usage
from app.job_guard import claim as claim_job, release as release_job
from app.localization import normalize_language
from app.security import audit_security_event, new_correlation_id, pseudonymous_ip, request_ip, require_rate_limit, validate_public_url
from app.spend import reserve_spend, settle_spend
from app.store import (
    create_job,
    delete_user_recipe,
    get_job,
    get_active_job,
    grant_job_access,
    get_recipe,
    get_recipe_by_norm,
    JobAccessUnavailable,
    list_jobs,
    list_profiles,
    list_recipes,
    list_user_recipe_summaries,
    recipe_public_from_row,
    save_user_recipe,
    soft_delete_profile,
    anonymize_user_data,
    update_job,
    user_can_access_job,
    user_owns_recipe,
)
from app.superwall import apply_superwall_event
from app.url_norm import normalize_url
from app.translation_cache import localized_recipe_row

app = FastAPI(title="ReciApp API", version="1.3.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Correlation-ID"],
)
app.include_router(dashboard_router)

_STALE_JOB_ERROR = "Job expired before completion. Retry the import."


@app.exception_handler(httpx.RequestError)
async def upstream_request_error(request: Request, exc: httpx.RequestError) -> JSONResponse:
    """Turn transient upstream disconnects into an iOS-retryable response."""
    reset_supabase()
    logger.warning(
        "upstream request failed path=%s error_type=%s correlation_id=%s",
        request.url.path,
        type(exc).__name__,
        getattr(request.state, "correlation_id", "unknown"),
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Backend temporarily unavailable. Retry."},
        headers={"Retry-After": "1"},
    )


def _job_is_stale(row: dict) -> bool:
    if row.get("status") not in {JobStatus.pending.value, JobStatus.processing.value}:
        return False
    raw = row.get("updated_at") or row.get("created_at")
    if not raw:
        return False
    try:
        timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - timestamp).total_seconds() > settings.job_ttl_seconds


def _expire_stale_job(row: dict) -> bool:
    if not _job_is_stale(row):
        return False
    job_id = UUID(str(row["id"]))
    update_job(
        job_id,
        status=JobStatus.failed.value,
        progress=0,
        lease_until=None,
        error=_STALE_JOB_ERROR,
    )
    settle_spend(job_id=job_id, actual_cents=0, status="failed")
    return True


def _share_job_or_http(row: dict, user: AuthUser) -> None:
    """Grant access only when a caller joins another user's active job."""
    if str(row.get("user_id") or "") == str(user.id):
        return
    try:
        grant_job_access(job_id=UUID(str(row["id"])), user_id=user.id)
    except JobAccessUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "JOB_ACCESS_UNAVAILABLE", "message": "Job access temporarily unavailable."},
        ) from exc


def _ensure_translation_job(
    *,
    user: AuthUser,
    recipe_id: UUID,
    source_url_raw: str,
    source_url_norm: str,
    language_code: str,
    background: BackgroundTasks,
) -> dict:
    language_code = normalize_language(language_code)
    active = get_active_job(
        source_url_norm=source_url_norm,
        language_code=language_code,
        job_kind="translation",
        recipe_id=recipe_id,
    )
    if active:
        if _expire_stale_job(active):
            active = None
        else:
            _share_job_or_http(active, user)
            return active

    assert_can_extract(user, cache_hit=False)
    local_claimed = not settings.worker_enabled
    if local_claimed:
        claim_job(user.id)
    try:
        job = create_job(
            user_id=user.id,
            source_url_raw=source_url_raw,
            source_url_norm=source_url_norm,
            language_code=language_code,
            job_kind="translation",
            status=JobStatus.pending.value,
            cache_hit=False,
            recipe_id=recipe_id,
        )
        job_id = UUID(job["id"])
        reserve_spend(user_id=user.id, job_id=job_id)
    except Exception:
        if "job_id" in locals():
            update_job(job_id, status=JobStatus.failed.value, error="Usage protection unavailable")
            if local_claimed:
                release_job(user.id)
            raise
        active = get_active_job(
            source_url_norm=source_url_norm,
            language_code=language_code,
            job_kind="translation",
            recipe_id=recipe_id,
        )
        if active:
            _share_job_or_http(active, user)
            if local_claimed:
                release_job(user.id)
            return active
        if local_claimed:
            release_job(user.id)
        raise
    if not settings.worker_enabled:
        background.add_task(run_translation_job, job_id, user.id, recipe_id, language_code)
    return job


@app.middleware("http")
async def request_metrics(request: Request, call_next):
    start = time.perf_counter()
    client_request_id = request.headers.get("x-request-id", "")
    correlation_id = (
        client_request_id
        if 8 <= len(client_request_id) <= 64
        and all(character.isalnum() or character == "-" for character in client_request_id)
        else new_correlation_id()
    )
    request.state.correlation_id = correlation_id
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_body_bytes:
        response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
        return response
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    # Fire-and-forget style (sync insert; keep tiny)
    try:
        log_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=None,
            ip=pseudonymous_ip(request_ip(request)),
            correlation_id=correlation_id,
        )
    except Exception:
        pass
    logger.info(
        "request completed method=%s path=%s status=%s duration_ms=%s correlation_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        correlation_id,
    )
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/dashboard"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
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
    if len(raw) > settings.max_request_body_bytes:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    if not settings.superwall_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook verification unavailable")
    try:
        from svix.webhooks import Webhook

        wh = Webhook(settings.superwall_webhook_secret)
        payload = wh.verify(
            raw,
            {
                "svix-id": svix_id or "",
                "svix-timestamp": svix_timestamp or "",
                "svix-signature": svix_signature or "",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    app_id = payload.get("applicationId")
    if app_id is not None:
        try:
            app_id = int(app_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid application id") from exc
        if app_id != settings.superwall_application_id:
            return JSONResponse({"ok": True, "skipped": "wrong_application"})

    try:
        result = apply_superwall_event(payload, event_id=svix_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Webhook event id required") from exc
    return JSONResponse({"ok": True, **result})


@app.post("/v1/webhooks/apple")
async def apple_webhook(request: Request) -> JSONResponse:
    raw = await request.body()
    if len(raw) > settings.max_request_body_bytes:
        raise HTTPException(status_code=413, detail="Apple notification payload too large")
    try:
        body = json.loads(raw.decode("utf-8"))
        signed_payload = body.get("signedPayload") if isinstance(body, dict) else None
        if not isinstance(signed_payload, str):
            raise ValueError("signedPayload required")
        result = process_signed_notification(signed_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid signed Apple notification") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Apple notification verification unavailable") from exc
    return JSONResponse(result)


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
    anonymize_user_data(user.id)
    soft_delete_profile(user.id)
    try:
        get_supabase().auth.admin.delete_user(str(user.id))
    except Exception:
        pass
    return OkResponse()


@app.post("/v1/extract", response_model=ExtractJobResponse)
def extract_recipe(
    request: Request,
    body: ExtractRequest,
    background: BackgroundTasks,
    user: AuthUser = Depends(current_user),
) -> ExtractJobResponse:
    url = str(body.url)
    language_code = normalize_language(body.language)
    require_rate_limit(
        request,
        key=f"extract-ip:{request_ip(request)}",
        limit=settings.rate_limit_per_ip_per_minute,
        window_seconds=60,
        event="extract_ip_rate_limited",
    )
    require_rate_limit(
        request,
        key=f"extract-user:{user.id}",
        limit=settings.rate_limit_per_user_per_minute,
        window_seconds=60,
        event="extract_user_rate_limited",
    )
    try:
        validate_public_url(
            url,
            allowed_hosts={"youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch"},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported or unsafe URL") from exc
    url_norm = normalize_url(url)

    cached = get_recipe_by_norm(url_norm)
    if cached:
        recipe_id = UUID(cached["id"])
        localized = localized_recipe_row(cached, language_code)
        if localized is not None:
            job = create_job(
                user_id=user.id,
                source_url_raw=url,
                source_url_norm=url_norm,
                language_code=language_code,
                status=JobStatus.completed.value,
                cache_hit=True,
                recipe_id=recipe_id,
                cost_cents=0,
            )
            try:
                save_user_recipe(user.id, recipe_id)
            except Exception as exc:
                # A transient attachment failure must not turn a cache hit
                # into a missing recipe response.
                logger.warning(
                    "cached recipe attach failed recipe_id=%s error_type=%s",
                    recipe_id,
                    type(exc).__name__,
                )
            try:
                record_usage(
                    user_id=user.id,
                    kind="extract_hit",
                    cost_cents=0,
                    recipe_id=recipe_id,
                    job_id=UUID(job["id"]),
                )
            except Exception:
                # A usage-log outage must not hide a recipe that is already
                # cached and attached to the user.
                pass
            return ExtractJobResponse(
                job_id=UUID(job["id"]),
                status=JobStatus.completed,
                cache_hit=True,
                progress=100,
            )

        if not settings.openai_api_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

        job = _ensure_translation_job(
            user=user,
            recipe_id=recipe_id,
            source_url_raw=url,
            source_url_norm=url_norm,
            language_code=language_code,
            background=background,
        )
        return ExtractJobResponse(
            job_id=UUID(job["id"]),
            status=JobStatus(job["status"]),
            cache_hit=False,
            progress=int(job.get("progress") or 0),
        )

    active = get_active_job(source_url_norm=url_norm, job_kind="extract")
    if active:
        if not _expire_stale_job(active):
            _share_job_or_http(active, user)
            return ExtractJobResponse(
                job_id=UUID(active["id"]),
                status=JobStatus(active["status"]),
                cache_hit=False,
                progress=int(active.get("progress") or 0),
            )

    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    assert_can_extract(user, cache_hit=False)

    local_claimed = not settings.worker_enabled
    if local_claimed:
        claim_job(user.id)
    try:
        job = create_job(
            user_id=user.id,
            source_url_raw=url,
            source_url_norm=url_norm,
            language_code=language_code,
            job_kind="extract",
            status=JobStatus.pending.value,
            cache_hit=False,
        )
        job_id = UUID(job["id"])
        reserve_spend(user_id=user.id, job_id=job_id)
    except Exception:
        if "job_id" in locals():
            update_job(job_id, status=JobStatus.failed.value, error="Usage protection unavailable")
            if local_claimed:
                release_job(user.id)
            raise
        active = get_active_job(source_url_norm=url_norm, job_kind="extract")
        if active and not _expire_stale_job(active):
            _share_job_or_http(active, user)
            if local_claimed:
                release_job(user.id)
            return ExtractJobResponse(
                job_id=UUID(active["id"]),
                status=JobStatus(active["status"]),
                cache_hit=False,
                progress=int(active.get("progress") or 0),
            )
        if local_claimed:
            release_job(user.id)
        raise
    if not settings.worker_enabled:
        background.add_task(run_extract_job, job_id, user.id, url, url_norm, language_code)
    return ExtractJobResponse(job_id=job_id, status=JobStatus.pending, cache_hit=False)


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: UUID,
    background: BackgroundTasks,
    language: str = Query("en-US"),
    user: AuthUser = Depends(current_user),
) -> JobResponse:
    row = get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        can_access = user_can_access_job(job_id=job_id, user_id=user.id, row=row)
    except JobAccessUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "JOB_ACCESS_UNAVAILABLE", "message": "Job access temporarily unavailable."},
        ) from exc
    if not can_access:
        raise HTTPException(status_code=403, detail="Not your job")

    if _expire_stale_job(row):
        row = dict(row)
        row.update(status=JobStatus.failed.value, progress=0, error=_STALE_JOB_ERROR)

    recipe = None
    next_job_id = None
    if row.get("recipe_id"):
        r = get_recipe(UUID(row["recipe_id"]))
        if r:
            try:
                save_user_recipe(user.id, UUID(row["recipe_id"]))
            except Exception as exc:
                # A transient attachment failure must not hide a recipe that
                # was already completed and can be returned to the client.
                logger.warning(
                    "job recipe attach failed job_id=%s error_type=%s",
                    job_id,
                    type(exc).__name__,
                )
            requested_language = normalize_language(language)
            row_language = normalize_language(row.get("language_code"))
            resolution_language = row_language if row.get("job_kind") == "translation" else requested_language
            localized = localized_recipe_row(r, resolution_language)
            if (
                row.get("job_kind") == "extract"
                and row.get("status") == JobStatus.completed.value
                and localized is None
                and requested_language != row_language
            ):
                translation_job = _ensure_translation_job(
                    user=user,
                    recipe_id=UUID(row["recipe_id"]),
                    source_url_raw=row.get("source_url_raw") or r.get("source_url_raw") or "",
                    source_url_norm=row.get("source_url_norm") or r.get("source_url_norm") or "",
                    language_code=requested_language,
                    background=background,
                )
                next_job_id = UUID(translation_job["id"])
                return JobResponse(
                    job_id=next_job_id,
                    status=JobStatus(translation_job["status"]),
                    cache_hit=False,
                    recipe=None,
                    recipe_id=UUID(row["recipe_id"]),
                    error=None,
                    progress=int(translation_job.get("progress") or 0),
                )
            recipe = recipe_public_from_row(localized or r)

    return JobResponse(
        job_id=UUID(row["id"]),
        status=JobStatus(row["status"]),
        cache_hit=bool(row.get("cache_hit")),
        recipe=recipe,
        recipe_id=UUID(row["recipe_id"]) if row.get("recipe_id") else None,
        error=row.get("error"),
        progress=int(row.get("progress") or 0),
        next_job_id=next_job_id,
    )


@app.get("/v1/me/recipes", response_model=RecipeListResponse)
def my_recipes(
    language: str = Query("en-US"),
    user: AuthUser = Depends(current_user),
) -> RecipeListResponse:
    return RecipeListResponse(
        items=list_user_recipe_summaries(user.id, normalize_language(language))
    )


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
    language: str = Query("en-US"),
    user: AuthUser = Depends(current_user),
) -> RecipePublic:
    if not user_owns_recipe(user.id, recipe_id):
        raise HTTPException(status_code=403, detail="Recipe not in your list")
    row = get_recipe(recipe_id)
    if not row:
        raise HTTPException(status_code=404, detail="Recipe not found")
    localized = localized_recipe_row(row, normalize_language(language))
    return recipe_public_from_row(localized or row)


# --- Admin ---


@app.get("/v1/admin/users", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_list_users(limit: int = Query(100, ge=1, le=500)) -> ListResponse:
    return ListResponse(items=list_profiles(limit=limit))


@app.post("/v1/admin/users", response_model=ListResponse, dependencies=[Depends(require_api_key)])
def admin_create_user(request: Request, body: AdminUserCreate) -> ListResponse:
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
    audit_security_event(event="admin_user_created", request=request, user_id=str(user.id), metadata={"is_pro": body.is_pro})
    return ListResponse(items=[payload])


@app.patch("/v1/admin/users/{user_id}", dependencies=[Depends(require_api_key)])
def admin_patch_user(request: Request, user_id: UUID, body: AdminUserPatch):
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
    audit_security_event(event="admin_user_changed", request=request, user_id=str(user_id), metadata={"fields": sorted(fields)})
    return res.data[0]


@app.delete("/v1/admin/users/{user_id}", response_model=OkResponse, dependencies=[Depends(require_api_key)])
def admin_delete_user(request: Request, user_id: UUID) -> OkResponse:
    anonymize_user_data(user_id)
    soft_delete_profile(user_id)
    try:
        get_supabase().auth.admin.delete_user(str(user_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_security_event(event="admin_user_deleted", request=request, user_id=str(user_id))
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
