"""
Outbound Ports (Interfaces)
============================
Abstract interfaces that the domain core depends on.
All infrastructure concerns (databases, AI providers, storage) implement
these interfaces as Adapters in adapters/outbound/.

The domain never imports SQLAlchemy, FastAPI, or any external SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.domain.entities import (
    AuditLog,
    CalculatedMetric,
    Company,
    Document,
    Job,
    NormalizedMetric,
)
from core.domain.value_objects import FiscalPeriod


# ---------------------------------------------------------------------------
# Database Port
# ---------------------------------------------------------------------------

class DatabasePort(ABC):
    """
    Outbound port for all persistence operations.
    The PostgreSQL repository adapter implements this interface.
    """

    # Companies ----------------------------------------------------------------

    @abstractmethod
    def save_company(self, company: Company) -> Company:
        ...

    @abstractmethod
    def get_company_by_id(self, company_id: str) -> Company | None:
        ...

    @abstractmethod
    def get_company_by_ticker(self, ticker: str) -> Company | None:
        ...

    @abstractmethod
    def list_companies(self) -> list[Company]:
        ...

    # Documents ----------------------------------------------------------------

    @abstractmethod
    def save_document(self, document: Document) -> Document:
        ...

    @abstractmethod
    def get_document_by_id(self, document_id: str) -> Document | None:
        ...

    @abstractmethod
    def document_exists_by_hash(self, file_hash: str) -> bool:
        """Used to detect duplicate uploads before any parsing occurs."""
        ...

    # Jobs ---------------------------------------------------------------------

    @abstractmethod
    def save_job(self, job: Job) -> Job:
        ...

    @abstractmethod
    def get_job_by_id(self, job_id: str) -> Job | None:
        ...

    @abstractmethod
    def update_job(self, job: Job) -> Job:
        ...

    # Metrics ------------------------------------------------------------------

    @abstractmethod
    def save_normalized_metric(self, metric: NormalizedMetric) -> NormalizedMetric:
        ...

    @abstractmethod
    def get_normalized_metrics(
        self,
        company_id: str,
        fiscal_period: FiscalPeriod | None = None,
    ) -> list[NormalizedMetric]:
        ...

    @abstractmethod
    def save_calculated_metric(self, metric: CalculatedMetric) -> CalculatedMetric:
        ...

    @abstractmethod
    def get_calculated_metrics(
        self,
        company_id: str,
        fiscal_period: FiscalPeriod | None = None,
    ) -> list[CalculatedMetric]:
        ...

    # Audit --------------------------------------------------------------------

    @abstractmethod
    def append_audit_log(self, log: AuditLog) -> None:
        """Appends an immutable audit entry. Must never update or delete."""
        ...

    @abstractmethod
    def get_audit_logs(
        self,
        entity_id: str,
        entity_type: str | None = None,
    ) -> list[AuditLog]:
        ...


# ---------------------------------------------------------------------------
# Extraction Provider Port (Phase 3)
# ---------------------------------------------------------------------------

class ExtractionProviderPort(ABC):
    """
    Outbound port for AI-assisted document extraction.
    Adapters implement this for: Gemini API, OpenAI, Claude, or local OCR.

    The finance engine never knows which provider is in use.
    Swapping providers (e.g. Gemini → Claude) requires zero core changes.
    """

    @abstractmethod
    def extract_financial_data(
        self,
        file_bytes: bytes,
        content_type: str,
        filename: str,
    ) -> list[dict[str, Any]]:
        """
        Extract financial rows from raw file bytes.

        Returns a list of raw extraction dicts:
        [
          {
            "raw_key": "Net Sales",
            "raw_value": "98,456",
            "currency": "USD",
            "fiscal_year": 2024,
            "fiscal_period": "FY",
            "page": 42,
            "section": "Consolidated Statements of Operations",
            "confidence": 0.97
          },
          ...
        ]
        """
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name of the extraction provider, e.g. 'gemini-1.5-flash'."""
        ...


# ---------------------------------------------------------------------------
# Storage Port
# ---------------------------------------------------------------------------

class StoragePort(ABC):
    """
    Outbound port for object/file storage.
    Adapters implement for: local disk (Phase 1), S3/GCS (Phase 8+).
    """

    @abstractmethod
    def save_file(self, file_bytes: bytes, filename: str) -> str:
        """
        Persist file bytes and return the storage URL / path.
        """
        ...

    @abstractmethod
    def get_file(self, storage_url: str) -> bytes:
        """
        Retrieve raw bytes from a previously stored file.
        """
        ...
