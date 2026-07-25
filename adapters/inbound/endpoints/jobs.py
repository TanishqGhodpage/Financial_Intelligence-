"""
Jobs Endpoints
==============
Allows clients to poll the status of ingestion pipeline jobs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import JobORM

router = APIRouter()


class JobResponse(BaseModel):
    id: str
    document_id: str
    company_id: str
    status: str
    error_message: str | None


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Poll the status of an ingestion pipeline job."""
    result = await db.execute(select(JobORM).where(JobORM.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse(
        id=job.id,
        document_id=job.document_id,
        company_id=job.company_id,
        status=job.status,
        error_message=job.error_message,
    )
