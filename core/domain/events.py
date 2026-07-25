"""
Domain Events
=============
Lightweight event objects that represent something that happened in the domain.

Events are immutable (frozen dataclasses) and carry all information needed
by downstream handlers. The platform's pipeline is modelled as a sequence
of domain events, which makes it naturally decoupled and testable.

Currently processed synchronously (Phase 1); can be routed through a message
broker (Celery/Kafka) in Phase 9 with no core changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    occurred_at: datetime = field(default_factory=_now)


# ---------------------------------------------------------------------------
# Ingestion events
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentUploaded(DomainEvent):
    """
    Fired when a raw document has been received and persisted to storage.
    Triggers the parsing stage of the ingestion pipeline.
    """

    job_id: str = ""
    document_id: str = ""
    company_id: str = ""
    filename: str = ""
    document_type: str = ""


@dataclass(frozen=True)
class DocumentParsed(DomainEvent):
    """
    Fired when raw text/tables have been extracted from a document.
    Carries the number of rows extracted for monitoring.
    Triggers the normalisation stage.
    """

    job_id: str = ""
    document_id: str = ""
    rows_extracted: int = 0
    parser_used: str = ""
    confidence_avg: float = 0.0


@dataclass(frozen=True)
class DocumentNormalized(DomainEvent):
    """
    Fired when all extracted rows have been mapped to canonical metric keys
    and persisted as NormalizedMetric entities.
    Triggers the analytics stage.
    """

    job_id: str = ""
    document_id: str = ""
    metrics_stored: int = 0
    conflicts_detected: int = 0


@dataclass(frozen=True)
class AnalysisCompleted(DomainEvent):
    """
    Fired when the deterministic calculation engine has run all registered
    metrics for the given company and fiscal period.
    """

    job_id: str = ""
    company_id: str = ""
    metrics_calculated: int = 0


@dataclass(frozen=True)
class JobFailed(DomainEvent):
    """
    Fired whenever a job fails at any stage. Contains the stage name
    and error message for observability and alerting.
    """

    job_id: str = ""
    stage: str = ""
    error_message: str = ""
