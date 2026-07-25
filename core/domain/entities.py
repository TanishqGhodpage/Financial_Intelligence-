"""
Domain Entities
===============
Core business objects modelling the Financial Intelligence Platform.

Rules:
  - No SQLAlchemy, FastAPI, or third-party SDK imports allowed here.
  - Every entity is a pure Python dataclass with typed fields.
  - Mutable state (e.g. Job status transitions) is guarded by the entity itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from core.domain.value_objects import (
    ConfidenceScore,
    Currency,
    FiscalPeriod,
    SourceAuthority,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

@dataclass
class Company:
    """Represents a tracked financial entity (public or private company)."""

    id: str = field(default_factory=_new_id)
    ticker: str = ""
    name: str = ""
    sector: str = ""
    industry: str = ""
    currency: Currency = field(default_factory=Currency.usd)
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        self.ticker = self.ticker.upper().strip()
        if not self.name:
            raise ValueError("Company name cannot be empty.")


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class DocumentType(str, Enum):
    CSV = "csv"
    EXCEL = "xlsx"
    PDF = "pdf"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    IMAGE = "image"


@dataclass
class Document:
    """
    Represents an uploaded financial document (annual report, transcript, etc.)
    A SHA-256 hash enforces deduplication at the domain level.
    """

    id: str = field(default_factory=_new_id)
    company_id: str = ""
    filename: str = ""
    storage_url: str = ""       # path in object storage
    document_type: DocumentType = DocumentType.PDF
    file_hash: str = ""         # SHA-256 of raw bytes
    fiscal_period: FiscalPeriod | None = None
    source_authority: SourceAuthority = SourceAuthority.UNKNOWN
    uploaded_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.filename:
            raise ValueError("Document filename cannot be empty.")
        if not self.file_hash:
            raise ValueError("Document must have a SHA-256 file_hash for deduplication.")


# ---------------------------------------------------------------------------
# Job (State Machine)
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    PENDING = "PENDING"
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Valid state transitions
_VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.PENDING:     {JobStatus.UPLOADED, JobStatus.FAILED},
    JobStatus.UPLOADED:    {JobStatus.PARSING, JobStatus.FAILED},
    JobStatus.PARSING:     {JobStatus.NORMALIZING, JobStatus.FAILED},
    JobStatus.NORMALIZING: {JobStatus.ANALYZING, JobStatus.FAILED},
    JobStatus.ANALYZING:   {JobStatus.COMPLETED, JobStatus.FAILED},
    JobStatus.COMPLETED:   set(),
    JobStatus.FAILED:      set(),
}


@dataclass
class Job:
    """
    Tracks the lifecycle of an ingestion pipeline run for a single document.

    A Job drives the Document through its state machine:
        PENDING → UPLOADED → PARSING → NORMALIZING → ANALYZING → COMPLETED | FAILED
    """

    id: str = field(default_factory=_new_id)
    document_id: str = ""
    company_id: str = ""
    status: JobStatus = JobStatus.PENDING
    error_message: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def transition(self, new_status: JobStatus) -> None:
        """
        Advance the job to a new state. Raises ValueError for illegal transitions.
        Enforces the state machine contract at the domain level.
        """
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid job transition: {self.status.value} → {new_status.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self.status = new_status
        self.updated_at = _now()

    def fail(self, reason: str) -> None:
        """Convenience helper for marking a job as failed with a reason."""
        self.error_message = reason
        self.transition(JobStatus.FAILED)

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED)


# ---------------------------------------------------------------------------
# Normalized Metric (extracted from a document)
# ---------------------------------------------------------------------------

@dataclass
class NormalizedMetric:
    """
    A single financial data point extracted and normalised from a document.
    Every metric stores its source citation so lineage is never lost.
    """

    id: str = field(default_factory=_new_id)
    company_id: str = ""
    document_id: str = ""
    metric_key: str = ""                  # Standardised key, e.g. 'revenue'
    metric_value: float = 0.0
    currency: Currency = field(default_factory=Currency.usd)
    fiscal_period: FiscalPeriod | None = None
    confidence: ConfidenceScore = field(default_factory=ConfidenceScore.certain)
    source_citation: dict[str, Any] = field(default_factory=dict)
    # Example citation:
    # { "page": 82, "section": "Income Statement",
    #   "raw_text": "Revenue: $100M", "authority": "SEC_FILING" }
    created_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.metric_key:
            raise ValueError("metric_key cannot be empty.")


# ---------------------------------------------------------------------------
# Calculated Metric (deterministic computation result)
# ---------------------------------------------------------------------------

@dataclass
class CalculatedMetric:
    """
    A financial metric produced by a deterministic computation.
    Stores a full lineage of input metric IDs and the formula applied.
    Confidence is propagated from its inputs.
    """

    id: str = field(default_factory=_new_id)
    company_id: str = ""
    metric_key: str = ""                  # e.g. 'operating_margin', 'dcf_valuation'
    metric_value: float = 0.0
    fiscal_period: FiscalPeriod | None = None
    confidence: ConfidenceScore = field(default_factory=ConfidenceScore.certain)
    inputs_lineage: list[dict[str, Any]] = field(default_factory=list)
    # Each entry: { "metric_id": "uuid", "metric_key": "revenue", "value": 100.0 }
    formula_description: str = ""
    created_at: datetime = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Audit Log (immutable)
# ---------------------------------------------------------------------------

class AuditAction(str, Enum):
    INGESTION = "ingestion"
    NORMALIZATION = "normalization"
    CORRECTION = "correction"
    CALCULATION = "calculation"
    JOB_TRANSITION = "job_transition"
    CONFLICT_DETECTED = "conflict_detected"


@dataclass(frozen=True)
class AuditLog:
    """
    Immutable record of every state change in the platform.
    Frozen dataclass prevents any post-creation mutation.
    """

    id: str = field(default_factory=_new_id)
    action: AuditAction = AuditAction.INGESTION
    entity_type: str = ""
    entity_id: str = ""
    description: str = ""
    old_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=_now)
