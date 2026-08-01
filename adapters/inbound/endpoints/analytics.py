"""
Analytics Endpoints
===================
Runs deterministic financial calculations (ratios, DCF) using the
MetricRegistry and returns results with full confidence propagation and
input lineage.

Separates calculation from report rendering — this endpoint returns
structured data; rendering to PDF/HTML is a separate concern (Phase 7).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import (
    CalculatedMetricORM,
    CompanyORM,
    NormalizedMetricORM,
    ReportORM,
)
from core.domain.entities import AuditAction, AuditLog, CalculatedMetric
from core.domain.value_objects import ConfidenceScore, FiscalPeriod, FiscalPeriodType, CalculationContext, Currency
from core.services.calculation.registry import metric_registry
from core.services.calculation.engine import CalculationEngine
from core.services.calculation.valuation import DCFValuationStrategy
from core.services.etl.auto_ingest import auto_ingest_financials
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MetricOut(BaseModel):
    """Full explainability response for a single calculated metric."""
    key: str
    name: str | None = None
    category: str | None = None
    value: float
    unit: str = "absolute"
    currency: str = "USD"
    fiscal_period_label: str | None = None
    confidence: float = 0.0
    status: str = "success"
    description: str = ""
    formula_display: str = ""
    formula_version: str = "v1"
    engine_version: str = "v2.0"
    configuration_version: str = "2026.08"
    calculation_strategy: str = "deterministic"
    calculation_timestamp: str | None = None
    inputs_used: dict[str, float] = {}
    validation_messages: list[str] = []
    references: list[dict[str, str]] = []
    data_lineage: list[str] = ["RawMetric", "NormalizedMetric", "CalculatedMetric"]


class AnalyticsResponse(BaseModel):
    company_id: str
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]
    metrics: list[MetricOut]
    warnings: list[str]


class DCFRequest(BaseModel):
    free_cash_flows: list[float]
    wacc: float
    terminal_growth_rate: float
    net_debt: float = 0.0


class DCFResponse(BaseModel):
    enterprise_value: float
    equity_value: float
    terminal_value: float
    discounted_fcfs: list[float]
    confidence: float
    assumptions: dict[str, float]

class ReportResponse(BaseModel):
    id: str
    company_id: str
    name: str
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]
    report_data: dict
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{company_id}", response_model=AnalyticsResponse)
async def run_analytics(
    company_id: str,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> AnalyticsResponse:
    """
    Run all registered deterministic financial metrics for a company.
    Fetches NormalizedMetrics from DB, feeds them into MetricRegistry,
    and stores results with lineage.
    """
    # Validate company exists
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    # Fetch normalized metrics
    query = select(NormalizedMetricORM).where(NormalizedMetricORM.company_id == company_id)
    if fiscal_year:
        query = query.where(NormalizedMetricORM.fiscal_year == fiscal_year)
    if fiscal_period:
        query = query.where(NormalizedMetricORM.fiscal_period == fiscal_period.upper())

    raw = await db.execute(query)
    norm_metrics = raw.scalars().all()

    if not norm_metrics:
        raise HTTPException(
            status_code=404,
            detail="No normalized metrics found for this company and period.",
        )

    # Build inputs and confidences dicts
    inputs: dict[str, float] = {}
    confidences: dict[str, ConfidenceScore] = {}
    for m in norm_metrics:
        # Latest-wins strategy if multiple docs for same key
        if m.metric_key not in inputs or m.confidence_score > confidences[m.metric_key].value:
            inputs[m.metric_key] = m.metric_value
            confidences[m.metric_key] = ConfidenceScore(value=m.confidence_score)

    # Create Context and Engine
    fp = None
    if fiscal_year and fiscal_period:
        try:
            fp = FiscalPeriod(year=fiscal_year, period_type=FiscalPeriodType(fiscal_period.upper()))
        except ValueError:
            fp = FiscalPeriod(year=fiscal_year or 2024, period_type=FiscalPeriodType.ANNUAL)
    else:
        fp = FiscalPeriod(year=2024, period_type=FiscalPeriodType.ANNUAL)

    context = CalculationContext(
        company_id=company_id,
        fiscal_period=fp,
        currency=Currency.usd(),
        engine_version="v2.0"
    )
    
    engine = CalculationEngine(metric_registry)
    results = engine.calculate_all(context=context, inputs=inputs, confidences=confidences)
    warnings: list[str] = []

    if not results:
        warnings.append(
            "No metrics could be calculated. Ensure the uploaded data includes "
            "at least two complementary metrics (e.g. revenue + net_income)."
        )

    metric_out_list: list[MetricOut] = []
    for res in results:
        calc_orm = CalculatedMetricORM(
            id=CalculatedMetric().id,
            company_id=company_id,
            metric_key=res.key,
            metric_value=res.value,
            fiscal_year=fp.year if fp else None,
            fiscal_period=fp.period_type.value if fp else None,
            confidence_score=res.confidence.value,
            inputs_lineage=[{"key": k, "value": v} for k, v in res.trace.inputs_used.items()],
            formula_description=res.trace.formula_version,
        )
        db.add(calc_orm)

        metric_out_list.append(
            MetricOut(
                key=res.key,
                name=res.name,
                category=res.category,
                value=round(res.value, 6),
                unit=res.unit,
                currency=context.currency.code,
                fiscal_period_label=fp.label if fp else None,
                confidence=round(res.confidence.value, 4),
                status=res.status.value,
                description=res.description,
                formula_display=res.formula_display,
                formula_version=res.trace.formula_version,
                engine_version=res.trace.engine_version,
                configuration_version=res.trace.configuration_version,
                calculation_strategy=res.trace.calculation_strategy,
                calculation_timestamp=res.trace.timestamp,
                inputs_used=res.trace.inputs_used,
                validation_messages=res.validation_messages,
                references=res.references,
            )
        )

    await db.flush()

    return AnalyticsResponse(
        company_id=company_id,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        metrics=metric_out_list,
        warnings=warnings,
    )


@router.post("/{company_id}/dcf", response_model=DCFResponse)
async def run_dcf(
    company_id: str,
    payload: DCFRequest,
    db: AsyncSession = Depends(get_db),
) -> DCFResponse:
    """
    Run a Discounted Cash Flow (DCF) valuation for a company.
    All inputs are provided by the caller (analyst-driven assumptions).
    The calculation is fully deterministic.
    """
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == company_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found.")

    try:
        context = CalculationContext(
            company_id=company_id,
            fiscal_period=FiscalPeriod(year=2024, period_type=FiscalPeriodType.ANNUAL),
            currency=Currency.usd(),
            engine_version="v2.0"
        )
        strategy = DCFValuationStrategy()
        dcf_inputs = {
            "wacc": payload.wacc,
            "terminal_growth_rate": payload.terminal_growth_rate,
            "free_cash_flow": payload.free_cash_flows[-1] if payload.free_cash_flows else 0,
            "total_liabilities": payload.net_debt,
            "cash_and_equivalents": 0.0
        }
        
        results = strategy.calculate(
            inputs=dcf_inputs,
            confidences={"free_cash_flow": ConfidenceScore(1.0)},
            context=context
        )
        
        # Parse the standard CalculationResults into DCFResponse for backwards compatibility
        ev = next((r.value for r in results if r.key == "enterprise_value"), 0.0)
        eq = next((r.value for r in results if r.key == "equity_value"), 0.0)
        
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return DCFResponse(
        enterprise_value=ev,
        equity_value=eq,
        terminal_value=0.0,
        discounted_fcfs=[],
        confidence=0.5,
        assumptions=dcf_inputs,
    )


@router.get("/{company_id}/metrics/available")
async def list_available_metrics(company_id: str) -> dict:
    """Returns metadata about all registered metrics in the system."""
    return {"metrics": metric_registry.list_metrics()}

@router.post("/{company_id}/auto-run", response_model=ReportResponse)
async def auto_run_analysis(
    company_id: str,
    start_year: int = 2024,
    end_year: int = 2026,
    fiscal_period: str = "FY",
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """
    1-click workflow:
    Fetches yfinance financials, normalizes them, runs all analytical models, 
    and saves the persistent Report.
    """
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    # 1. Auto-fetch financial statements via API
    try:
        # Clear old normalized metrics for auto-ingest to prevent clashes
        await db.execute(
            NormalizedMetricORM.__table__.delete().where(
                (NormalizedMetricORM.company_id == company_id) & 
                (NormalizedMetricORM.document_id == None)
            )
        )
        domain_metrics = await auto_ingest_financials(company_id, company.ticker, start_year, end_year, fiscal_period)
        for m in domain_metrics:
            orm = NormalizedMetricORM(
                id=m.id,
                company_id=m.company_id,
                document_id=None,
                metric_key=m.metric_key,
                metric_value=m.metric_value,
                currency=m.currency.code,
                fiscal_year=m.fiscal_period.year if m.fiscal_period else None,
                fiscal_period=m.fiscal_period.period_type.value if m.fiscal_period else None,
                confidence_score=m.confidence.value,
                source_citation=m.source_citation
            )
            db.add(orm)
        await db.flush()
    except Exception as e:
        logger.error(f"Auto-ingest failed for {company.ticker}: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # 2. Run deterministic calculations (same logic as run_analytics)
    query = (
        select(NormalizedMetricORM)
        .where(NormalizedMetricORM.company_id == company_id)
        .where(NormalizedMetricORM.fiscal_year >= start_year)
        .where(NormalizedMetricORM.fiscal_year <= end_year)
        .where(NormalizedMetricORM.fiscal_period == fiscal_period)
    )
    raw = await db.execute(query)
    norm_metrics = raw.scalars().all()
    
    from collections import defaultdict
    metrics_by_year = defaultdict(list)
    for m in norm_metrics:
        if m.fiscal_year is not None:
            metrics_by_year[m.fiscal_year].append(m)

    report_data_years = {}
    for year, metrics in metrics_by_year.items():
        inputs = {}
        confidences = {}
        for m in metrics:
            if m.metric_key not in inputs or m.confidence_score > confidences[m.metric_key].value:
                inputs[m.metric_key] = m.metric_value
                confidences[m.metric_key] = ConfidenceScore(value=m.confidence_score)
        fp = FiscalPeriod(year=year, period_type=FiscalPeriodType(fiscal_period.upper()))
        context = CalculationContext(
            company_id=company_id,
            fiscal_period=fp,
            currency=Currency.usd(),
            engine_version="v2.0"
        )
        engine = CalculationEngine(metric_registry)
        results = engine.calculate_all(context=context, inputs=inputs, confidences=confidences)
        metrics_list = []
        for res in results:
            metrics_list.append({
                "key": res.key,
                "name": res.name,
                "category": res.category,
                "value": res.value,
                "unit": res.unit,
                "confidence": round(res.confidence.value, 4),
                "status": res.status.value,
                "description": res.description,
                "formula_display": res.formula_display,
                "formula_version": res.trace.formula_version,
                "engine_version": res.trace.engine_version,
                "configuration_version": res.trace.configuration_version,
                "calculation_strategy": res.trace.calculation_strategy,
                "calculation_timestamp": res.trace.timestamp,
                "inputs_used": res.trace.inputs_used,
                "validation_messages": res.validation_messages,
                "references": res.references,
            })
        report_data_years[str(year)] = {
            "metrics": metrics_list,
            "inputs_used": inputs
        }
        
    if not report_data_years:
        raise HTTPException(status_code=400, detail="Not enough data fetched from API to calculate ratios.")

    # 3. Create a unified Report
    report_id = str(uuid.uuid4())
    report_data = {
        "years": report_data_years
    }
    
    report_orm = ReportORM(
        id=report_id,
        company_id=company_id,
        name=f"{company.ticker} Multi-Year Analysis ({start_year}-{end_year}) - {fiscal_period}",
        fiscal_year=None,
        fiscal_period=fiscal_period,
        report_data=report_data
    )
    db.add(report_orm)
    await db.flush()
    await db.refresh(report_orm)

    return ReportResponse(
        id=report_orm.id,
        company_id=report_orm.company_id,
        name=report_orm.name,
        fiscal_year=report_orm.fiscal_year,
        fiscal_period=report_orm.fiscal_period,
        report_data=report_orm.report_data,
        created_at=report_orm.created_at
    )

@router.get("/{company_id}/reports", response_model=list[ReportResponse])
async def list_reports(
    company_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ReportResponse]:
    """Returns all saved analysis reports for a company."""
    result = await db.execute(
        select(ReportORM)
        .where(ReportORM.company_id == company_id)
        .order_by(ReportORM.created_at.desc())
    )
    reports = result.scalars().all()
    return [
        ReportResponse(
            id=r.id,
            company_id=r.company_id,
            name=r.name,
            fiscal_year=r.fiscal_year,
            fiscal_period=r.fiscal_period,
            report_data=r.report_data,
            created_at=r.created_at
        ) for r in reports
    ]
