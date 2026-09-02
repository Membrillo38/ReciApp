from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from uuid import UUID

from app.config import settings
from app.models import (
    ExtractJobResponse,
    ExtractRequest,
    HealthResponse,
    JobResponse,
    JobStatus,
)
from app.pipeline import jobs, run_extract_job

app = FastAPI(title="Recipe Extractor API", version="1.0.0")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/v1/extract", response_model=ExtractJobResponse)
def extract_recipe(
    body: ExtractRequest,
    background: BackgroundTasks,
    _: None = Depends(require_api_key),
) -> ExtractJobResponse:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    job = jobs.create()
    background.add_task(run_extract_job, job.job_id, str(body.url))
    return ExtractJobResponse(job_id=job.job_id, status=JobStatus.pending)


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    _: None = Depends(require_api_key),
) -> JobResponse:
    record = jobs.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobResponse(
        job_id=record.job_id,
        status=record.status,
        recipe=record.recipe,
        error=record.error,
    )
