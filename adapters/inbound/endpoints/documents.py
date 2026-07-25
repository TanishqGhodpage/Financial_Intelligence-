"""
Documents Upload Endpoints
===========================
Handles file uploads, triggers the ingestion pipeline (parse → normalise),
and creates an associated Job entity for tracking.

Phase 1: CSV and Excel only (synchronous processing).
Phase 3: PDF/Image (AI extraction, async workers).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import (
    AuditLogORM,
    CompanyORM,
    DocumentORM,
    JobORM,
    NormalizedMetricORM,
)
from configs.settings import get_settings
from core.domain.entities import AuditAction, AuditLog, Document, DocumentType, Job, JobStatus
from core.domain.value_objects import FiscalPeriod, FiscalPeriodType, SourceAuthority
from core.services.ingestion.normalizer import FinancialNormalizer
from core.services.ingestion.registry import parser_registry
from core.services.validation.rules import RuleValidator

# Import parsers so they self-register
import core.services.ingestion.csv_parser  # noqa: F401
import core.services.ingestion.xlsx_parser  # noqa: F401

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

MIME_TYPE_MAP: dict[str, str] = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

AUTHORITY_MAP: dict[str, SourceAuthority] = {
    "sec_filing": SourceAuthority.SEC_FILING,
    "earnings_call": SourceAuthority.EARNINGS_CALL,
    "press_release": SourceAuthority.PRESS_RELEASE,
    "third_party_api": SourceAuthority.THIRD_PARTY_API,
    "news": SourceAuthority.NEWS,
    "unknown": SourceAuthority.UNKNOWN,
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BatchDocumentResponse(BaseModel):
    files_processed: int
    total_rows_extracted: int
    total_rows_stored: int
    jobs: list[dict]
    errors: list[str]


# ---------------------------------------------------------------------------
# Background ingestion pipeline
# ---------------------------------------------------------------------------

async def _run_ingestion_pipeline(
    db: AsyncSession,
    job_id: str,
    document_id: str,
    company_id: str,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    source_authority: SourceAuthority,
    fiscal_year: Optional[int],
    fiscal_period: Optional[str],
) -> None:
    """
    Runs the full Phase 1 ingestion pipeline:
    Parse → Validate → Normalise → Store → Complete Job
    """
    # Fetch job
    result = await db.execute(select(JobORM).where(JobORM.id == job_id))
    job_orm = result.scalar_one_or_none()
    if not job_orm:
        return

    try:
        # ---- PARSING ----
        job_orm.status = JobStatus.PARSING.value
        await db.flush()

        parser = parser_registry.get_parser(mime_type)
        parse_result = parser.parse(
            file_bytes=file_bytes,
            filename=filename,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        )

        # ---- NORMALISING ----
        job_orm.status = JobStatus.NORMALIZING.value
        await db.flush()

        normalizer = FinancialNormalizer()
        metrics, norm_warnings = normalizer.normalize_batch(
            rows=parse_result.rows,
            company_id=company_id,
            document_id=document_id,
            source_authority=source_authority,
        )

        # ---- VALIDATION ----
        flat_metrics = {m.metric_key: m.metric_value for m in metrics}
        validator = RuleValidator()
        validation_result = validator.validate(flat_metrics)

        if validation_result.has_errors:
            error_msg = "; ".join(v.message for v in validation_result.violations if v.severity.value == "ERROR")
            job_orm.status = JobStatus.FAILED.value
            job_orm.error_message = f"Validation failed: {error_msg}"
            await db.flush()
            return

        # ---- STORING METRICS ----
        stored = 0
        for metric in metrics:
            fp = metric.fiscal_period
            orm = NormalizedMetricORM(
                id=metric.id,
                company_id=metric.company_id,
                document_id=metric.document_id,
                metric_key=metric.metric_key,
                metric_value=metric.metric_value,
                currency=metric.currency.code,
                fiscal_year=fp.year if fp else None,
                fiscal_period=fp.period_type.value if fp else None,
                confidence_score=metric.confidence.value,
                source_citation=metric.source_citation,
            )
            db.add(orm)
            stored += 1

        # ---- AUDIT LOG ----
        audit = AuditLogORM(
            id=AuditLog().id,
            action=AuditAction.NORMALIZATION.value,
            entity_type="document",
            entity_id=document_id,
            description=(
                f"Parsed {parse_result.row_count} rows, stored {stored} metrics. "
                f"Duplicates removed: {parse_result.duplicates_removed}. "
                f"Normalisation warnings: {len(norm_warnings)}."
            ),
            new_state={"metrics_stored": stored, "warnings": norm_warnings},
        )
        db.add(audit)

        # ---- COMPLETE ----
        job_orm.status = JobStatus.COMPLETED.value
        await db.flush()

    except Exception as exc:
        logger.exception("Ingestion pipeline failed for job %s: %s", job_id, exc)
        job_orm.status = JobStatus.FAILED.value
        job_orm.error_message = str(exc)
        await db.flush()


# ---------------------------------------------------------------------------
# Upload Endpoint
# ---------------------------------------------------------------------------

@router.post("", response_model=BatchDocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    company_id: str = Form(...),
    fiscal_year: Optional[int] = Form(None),
    fiscal_period: Optional[str] = Form(None),
    source_authority: str = Form("unknown"),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> BatchDocumentResponse:
    """
    Upload financial documents (CSV or Excel) for a company.
    Triggers the ETL ingestion pipeline and returns a Batch Response.
    """
    # --- Validate company exists ---
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    total_rows_extracted = 0
    total_rows_stored = 0
    jobs_info = []
    errors = []

    for file in files:
        try:
            # --- File size check ---
            file_bytes = await file.read()
            size_mb = len(file_bytes) / 1024 / 1024
            if size_mb > settings.max_upload_size_mb:
                errors.append(f"{file.filename}: File too large ({size_mb:.1f}MB)")
                continue

            # --- Determine MIME type ---
            suffix = Path(file.filename or "").suffix.lower()
            mime_type = MIME_TYPE_MAP.get(suffix)
            if not mime_type:
                errors.append(f"{file.filename}: Unsupported file type '{suffix}'")
                continue

            # --- Duplicate detection via SHA-256 ---
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            dup_result = await db.execute(
                select(DocumentORM).where(DocumentORM.file_hash == file_hash)
            )
            if dup_result.scalar_one_or_none():
                errors.append(f"{file.filename}: Duplicate file detected")
                continue

            # --- Persist document record ---
            storage_path = Path(settings.storage_base_path) / company_id / (file.filename or "upload")
            storage_path.parent.mkdir(parents=True, exist_ok=True)
            storage_path.write_bytes(file_bytes)

            doc_entity = Document(
                company_id=company_id,
                filename=file.filename or "upload",
                storage_url=str(storage_path),
                document_type=DocumentType.CSV if suffix == ".csv" else DocumentType.EXCEL,
                file_hash=file_hash,
                fiscal_period=(
                    FiscalPeriod(year=fiscal_year, period_type=FiscalPeriodType(fiscal_period.upper()))
                    if fiscal_year and fiscal_period else None
                ),
                source_authority=AUTHORITY_MAP.get(source_authority.lower(), SourceAuthority.UNKNOWN),
            )
            doc_orm = DocumentORM(
                id=doc_entity.id,
                company_id=company_id,
                filename=doc_entity.filename,
                storage_url=doc_entity.storage_url,
                document_type=doc_entity.document_type.value,
                file_hash=file_hash,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                source_authority=doc_entity.source_authority.name,
            )
            db.add(doc_orm)

            # --- Create Job ---
            job_entity = Job(document_id=doc_entity.id, company_id=company_id)
            job_orm = JobORM(
                id=job_entity.id,
                document_id=doc_entity.id,
                company_id=company_id,
                status=JobStatus.UPLOADED.value,
            )
            db.add(job_orm)
            await db.flush()

            # --- Audit log for upload ---
            audit = AuditLogORM(
                id=AuditLog().id,
                action=AuditAction.INGESTION.value,
                entity_type="document",
                entity_id=doc_entity.id,
                description=f"Document '{file.filename}' uploaded for company {company_id}.",
                new_state={"file_hash": file_hash, "size_mb": round(size_mb, 2)},
            )
            db.add(audit)
            await db.flush()

            # --- Run ingestion pipeline synchronously (Phase 1) ---
            await _run_ingestion_pipeline(
                db=db,
                job_id=job_entity.id,
                document_id=doc_entity.id,
                company_id=company_id,
                file_bytes=file_bytes,
                filename=file.filename or "upload",
                mime_type=mime_type,
                source_authority=doc_entity.source_authority,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
            )

            # Fetch final job status
            await db.refresh(job_orm)

            # Count stored metrics
            metrics_result = await db.execute(
                select(NormalizedMetricORM).where(NormalizedMetricORM.document_id == doc_entity.id)
            )
            stored_metrics = metrics_result.scalars().all()
            
            num_stored = len(stored_metrics)
            total_rows_extracted += num_stored
            total_rows_stored += num_stored

            jobs_info.append({
                "job_id": job_entity.id,
                "document_id": doc_entity.id,
                "filename": file.filename,
                "status": job_orm.status,
                "rows_stored": num_stored
            })
            
        except Exception as e:
            logger.exception("Failed processing file %s", file.filename)
            errors.append(f"{file.filename}: {str(e)}")

    return BatchDocumentResponse(
        files_processed=len(files),
        total_rows_extracted=total_rows_extracted,
        total_rows_stored=total_rows_stored,
        jobs=jobs_info,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Market Data Fetch Endpoint
# ---------------------------------------------------------------------------

class MarketDataRequest(BaseModel):
    company_id: str
    ticker: str
    start_date: str   # ISO format: YYYY-MM-DD
    end_date: str     # ISO format: YYYY-MM-DD


class MarketDataResponse(BaseModel):
    job_id: str
    document_id: str
    ticker: str
    start_date: str
    end_date: str
    filename: str
    saved_path: str
    rows_fetched: int
    rows_stored: int
    status: str
    warnings: list[str]


@router.post(
    "/fetch-market-data",
    response_model=MarketDataResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def fetch_market_data_endpoint(
    payload: MarketDataRequest,
    db: AsyncSession = Depends(get_db),
) -> MarketDataResponse:
    """
    Fetch historical stock market data (OHLCV) from Yahoo Finance for a
    given ticker and date range. The data is automatically saved as a CSV,
    and the full ingestion pipeline (parse → normalise → store) is executed.
    """
    from datetime import date as date_type
    from core.services.ingestion.market_data import fetch_market_data

    # --- Validate company exists ---
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == payload.company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    # --- Parse dates ---
    try:
        start = date_type.fromisoformat(payload.start_date)
        end = date_type.fromisoformat(payload.end_date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid date format. Use ISO format: YYYY-MM-DD",
        )

    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="start_date must be before end_date.",
        )

    # --- Fetch market data via yfinance ---
    try:
        fetch_result = fetch_market_data(
            ticker=payload.ticker,
            start_date=start,
            end_date=end,
            storage_base="./data",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # --- Create document + job records ---
    file_hash = hashlib.sha256(fetch_result.csv_bytes).hexdigest()

    # Check for duplicate (same file already fetched)
    dup_result = await db.execute(
        select(DocumentORM).where(DocumentORM.file_hash == file_hash)
    )
    if dup_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=(
                "This exact market data has already been fetched and ingested "
                "(duplicate SHA-256 hash). Try a different date range."
            ),
        )

    doc_entity = Document(
        company_id=payload.company_id,
        filename=fetch_result.csv_filename,
        storage_url=fetch_result.saved_path,
        document_type=DocumentType.CSV,
        file_hash=file_hash,
        source_authority=SourceAuthority.THIRD_PARTY_API,
    )
    doc_orm = DocumentORM(
        id=doc_entity.id,
        company_id=payload.company_id,
        filename=doc_entity.filename,
        storage_url=doc_entity.storage_url,
        document_type=doc_entity.document_type.value,
        file_hash=file_hash,
        source_authority="THIRD_PARTY_API",
    )
    db.add(doc_orm)

    job_entity = Job(document_id=doc_entity.id, company_id=payload.company_id)
    job_orm = JobORM(
        id=job_entity.id,
        document_id=doc_entity.id,
        company_id=payload.company_id,
        status=JobStatus.UPLOADED.value,
    )
    db.add(job_orm)

    # Audit
    audit = AuditLogORM(
        id=AuditLog().id,
        action=AuditAction.INGESTION.value,
        entity_type="document",
        entity_id=doc_entity.id,
        description=(
            f"Market data fetched for {payload.ticker} "
            f"({payload.start_date} to {payload.end_date}). "
            f"{fetch_result.rows_fetched} data points."
        ),
        new_state={
            "ticker": payload.ticker,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "rows_fetched": fetch_result.rows_fetched,
        },
    )
    db.add(audit)
    await db.flush()

    # --- Run ingestion pipeline ---
    await _run_ingestion_pipeline(
        db=db,
        job_id=job_entity.id,
        document_id=doc_entity.id,
        company_id=payload.company_id,
        file_bytes=fetch_result.csv_bytes,
        filename=fetch_result.csv_filename,
        mime_type="text/csv",
        source_authority=SourceAuthority.THIRD_PARTY_API,
        fiscal_year=None,
        fiscal_period=None,
    )

    # Refresh final state
    await db.refresh(job_orm)

    metrics_result = await db.execute(
        select(NormalizedMetricORM).where(NormalizedMetricORM.document_id == doc_entity.id)
    )
    stored_metrics = metrics_result.scalars().all()

    return MarketDataResponse(
        job_id=job_entity.id,
        document_id=doc_entity.id,
        ticker=payload.ticker.upper(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        filename=fetch_result.csv_filename,
        saved_path=fetch_result.saved_path,
        rows_fetched=fetch_result.rows_fetched,
        rows_stored=len(stored_metrics),
        status=job_orm.status,
        warnings=fetch_result.warnings,
    )
