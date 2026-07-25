"""
PostgreSQL Database Schema (SQLAlchemy ORM)
============================================
Defines the ORM models that map to PostgreSQL tables.

Important: these models are ADAPTERS — they live in adapters/outbound/postgres/
and must NEVER be imported by core domain code.

Tables:
  companies            – tracked financial entities
  documents            – uploaded source files
  jobs                 – ingestion pipeline state machine
  normalized_metrics   – extracted financial data points
  calculated_metrics   – deterministic calculation results
  audit_logs           – immutable event trail
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

class CompanyORM(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    documents: Mapped[list["DocumentORM"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["JobORM"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    source_authority: Mapped[str] = mapped_column(String(50), default="UNKNOWN")
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    company: Mapped["CompanyORM"] = relationship(back_populates="documents")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobORM(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    company: Mapped["CompanyORM"] = relationship(back_populates="jobs")


# ---------------------------------------------------------------------------
# Normalized Metrics
# ---------------------------------------------------------------------------

class NormalizedMetricORM(Base):
    __tablename__ = "normalized_metrics"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "metric_key", "fiscal_year", "fiscal_period", "document_id",
            name="uq_metric_per_doc_period",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    fiscal_period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_citation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Calculated Metrics
# ---------------------------------------------------------------------------

class CalculatedMetricORM(Base):
    __tablename__ = "calculated_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    fiscal_period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    inputs_lineage: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    formula_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Audit Logs (Immutable — no update/delete ever)
# ---------------------------------------------------------------------------

class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class ReportORM(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    report_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    company: Mapped["CompanyORM"] = relationship()
