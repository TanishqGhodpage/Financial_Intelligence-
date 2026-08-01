"""
Comparative Analytics Endpoints
===============================
Provides REST endpoints for multi-company financial benchmarking,
cohort statistics, trends, and executive health scores.

Clean Controller: Contains NO calculation or business logic.
Delegates entirely to ComparativeAnalyticsEngine, TrendAnalyticsEngine,
and ExecutiveHealthEngine.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import CompanyORM, NormalizedMetricORM
from core.domain.value_objects import CalculationContext, Currency, FiscalPeriod, FiscalPeriodType, ConfidenceScore
from core.services.analytics.comparison import ComparativeAnalyticsEngine
from core.services.analytics.health import ExecutiveHealthEngine
from core.services.analytics.trend import TrendAnalyticsEngine
from core.services.calculation.engine import CalculationEngine
from core.services.calculation.registry import metric_registry

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------

class CohortAnalyzeRequest(BaseModel):
    company_ids: list[str] = Field(..., min_items=1, max_items=10)
    fiscal_year: Optional[int] = 2024
    fiscal_period: str = "FY"


class TrendAnalyzeRequest(BaseModel):
    company_ids: list[str] = Field(..., min_items=1, max_items=10)
    metric_keys: Optional[list[str]] = None
    start_year: int = 2020
    end_year: int = 2024


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_cohort(
    payload: CohortAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Runs multi-company comparative analytics (2–10 companies).
    Calculates statistics, rankings, percentiles, Z-scores, and Executive Health Scores.
    """
    if len(payload.company_ids) < 1:
        raise HTTPException(status_code=400, detail="At least 1 company ID is required.")

    # 1. Fetch company details
    result = await db.execute(
        select(CompanyORM).where(CompanyORM.id.in_(payload.company_ids))
    )
    companies = result.scalars().all()
    company_map = {c.id: c for c in companies}
    company_tickers = {c.id: c.ticker for c in companies}

    if not companies:
        raise HTTPException(status_code=404, detail="No matching companies found.")

    # 2. For each company, fetch normalized metrics & calculate metric values
    calc_engine = CalculationEngine(metric_registry)
    cohort_calculated_metrics: dict[str, dict[str, float]] = {}

    for cid in payload.company_ids:
        if cid not in company_map:
            continue

        query = select(NormalizedMetricORM).where(NormalizedMetricORM.company_id == cid)
        if payload.fiscal_year:
            query = query.where(NormalizedMetricORM.fiscal_year == payload.fiscal_year)
        if payload.fiscal_period:
            query = query.where(NormalizedMetricORM.fiscal_period == payload.fiscal_period.upper())

        norm_raw = await db.execute(query)
        norm_metrics = norm_raw.scalars().all()

        inputs: dict[str, float] = {}
        confidences: dict[str, ConfidenceScore] = {}
        for m in norm_metrics:
            if m.metric_key not in inputs or m.confidence_score > confidences[m.metric_key].value:
                inputs[m.metric_key] = m.metric_value
                confidences[m.metric_key] = ConfidenceScore(value=m.confidence_score)

        fp = FiscalPeriod(
            year=payload.fiscal_year or 2024,
            period_type=FiscalPeriodType(payload.fiscal_period.upper()) if payload.fiscal_period.upper() in FiscalPeriodType.__members__ else FiscalPeriodType.ANNUAL
        )

        context = CalculationContext(
            company_id=cid,
            fiscal_period=fp,
            currency=Currency.usd(),
            engine_version="v2.0"
        )

        results = calc_engine.calculate_all(context=context, inputs=inputs, confidences=confidences)
        comp_metrics = {res.key: res.value for res in results if res.status.value == "success"}
        cohort_calculated_metrics[cid] = comp_metrics

    # 3. Run Comparative Engine
    comp_engine = ComparativeAnalyticsEngine()
    period_label = f"{payload.fiscal_period.upper()}{payload.fiscal_year or 2024}"
    cohort_result = comp_engine.compare_cohort(
        cohort_metrics=cohort_calculated_metrics,
        company_tickers=company_tickers,
        fiscal_period_label=period_label,
    )

    # 4. Run Executive Health Engine for each company in cohort
    health_engine = ExecutiveHealthEngine()
    executive_healths: dict[str, dict] = {}

    for cid, metrics in cohort_calculated_metrics.items():
        comp_info = company_map.get(cid)
        ticker = comp_info.ticker if comp_info else "N/A"
        name = comp_info.name if comp_info else "Unknown"

        # Compute cohort-relative z-scores and percentiles
        z_scores = {
            m_key: m_stats.z_scores.get(cid, 0.0)
            for m_key, m_stats in cohort_result.metric_stats.items()
        }
        percentiles = {
            m_key: m_stats.percentiles.get("p50", 50.0)
            for m_key, m_stats in cohort_result.metric_stats.items()
        }

        health_summary = health_engine.evaluate_company(
            company_id=cid,
            ticker=ticker,
            company_name=name,
            metrics=metrics,
            cohort_z_scores=z_scores,
            cohort_percentiles=percentiles,
        )

        executive_healths[cid] = {
            "company_id": health_summary.company_id,
            "ticker": health_summary.ticker,
            "company_name": health_summary.company_name,
            "overall_score": health_summary.overall_score,
            "rating": health_summary.rating.value,
            "traffic_light": health_summary.traffic_light.value,
            "strengths": health_summary.strengths,
            "vulnerabilities": health_summary.vulnerabilities,
            "metric_healths": [
                {
                    "metric_key": mh.metric_key,
                    "name": mh.name,
                    "category": mh.category,
                    "value": mh.value,
                    "unit": mh.unit,
                    "score": mh.score,
                    "traffic_light": mh.traffic_light.value,
                    "rating": mh.rating.value,
                    "z_score": mh.z_score,
                }
                for mh in health_summary.metric_healths
            ],
        }

    # 5. Format response
    metric_stats_out = {}
    for k, stats in cohort_result.metric_stats.items():
        metric_stats_out[k] = {
            "metric_key": stats.metric_key,
            "name": stats.name,
            "category": stats.category,
            "unit": stats.unit,
            "mean": stats.mean,
            "median": stats.median,
            "min_value": stats.min_value,
            "max_value": stats.max_value,
            "std_dev": stats.std_dev,
            "variance": stats.variance,
            "percentiles": stats.percentiles,
            "company_values": stats.company_values,
            "z_scores": stats.z_scores,
            "rankings": stats.rankings,
            "relative_performance": stats.relative_performance,
        }

    return {
        "fiscal_period_label": period_label,
        "company_tickers": company_tickers,
        "metric_stats": metric_stats_out,
        "executive_healths": executive_healths,
    }


@router.post("/trends")
async def analyze_trends(
    payload: TrendAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Runs multi-year trend analysis (CAGR, YoY growth, slope, R², SMA, EMA).
    """
    result = await db.execute(
        select(CompanyORM).where(CompanyORM.id.in_(payload.company_ids))
    )
    companies = result.scalars().all()
    if not companies:
        raise HTTPException(status_code=404, detail="No matching companies found.")

    trend_engine = TrendAnalyticsEngine()
    calc_engine = CalculationEngine(metric_registry)
    trends_by_company: dict[str, dict] = {}

    for c in companies:
        # Fetch normalized metrics across years
        raw = await db.execute(
            select(NormalizedMetricORM)
            .where(NormalizedMetricORM.company_id == c.id)
            .where(NormalizedMetricORM.fiscal_year >= payload.start_year)
            .where(NormalizedMetricORM.fiscal_year <= payload.end_year)
        )
        norm_metrics = raw.scalars().all()

        # Group by year
        metrics_by_year: dict[int, dict[str, float]] = {}
        for m in norm_metrics:
            if m.fiscal_year is not None:
                metrics_by_year.setdefault(m.fiscal_year, {})[m.metric_key] = m.metric_value

        # Calculate metrics for each year
        year_calculated: dict[int, dict[str, float]] = {}
        for yr, inputs in metrics_by_year.items():
            context = CalculationContext(
                company_id=c.id,
                fiscal_period=FiscalPeriod(year=yr, period_type=FiscalPeriodType.ANNUAL),
                currency=Currency.usd(),
                engine_version="v2.0"
            )
            confidences = {k: ConfidenceScore(1.0) for k in inputs}
            res_list = calc_engine.calculate_all(context=context, inputs=inputs, confidences=confidences)
            year_calculated[yr] = {r.key: r.value for r in res_list if r.status.value == "success"}

        # Filter metric keys
        target_keys = payload.metric_keys or list(metric_registry._metrics.keys())

        company_trends = {}
        for m_key in target_keys:
            series = [
                (yr, vals[m_key])
                for yr, vals in sorted(year_calculated.items())
                if m_key in vals
            ]
            if not series:
                continue

            trend_res = trend_engine.analyze_trend(
                company_id=c.id,
                metric_key=m_key,
                time_series=series,
            )
            company_trends[m_key] = {
                "metric_key": trend_res.metric_key,
                "cagr": trend_res.cagr,
                "slope": trend_res.slope,
                "r_squared": trend_res.r_squared,
                "trend_direction": trend_res.trend_direction.value,
                "time_series": trend_res.time_series,
                "yoy_growth": trend_res.yoy_growth,
            }

        trends_by_company[c.id] = {
            "ticker": c.ticker,
            "name": c.name,
            "trends": company_trends,
        }

    return {"company_trends": trends_by_company}


@router.get("/health/{company_id}")
async def get_company_health(
    company_id: str,
    fiscal_year: int = 2024,
    fiscal_period: str = "FY",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Computes standalone Executive Health Score & ratings for a single company.
    """
    result = await db.execute(select(CompanyORM).where(CompanyORM.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    raw = await db.execute(
        select(NormalizedMetricORM)
        .where(NormalizedMetricORM.company_id == company_id)
        .where(NormalizedMetricORM.fiscal_year == fiscal_year)
    )
    norm_metrics = raw.scalars().all()
    inputs = {m.metric_key: m.metric_value for m in norm_metrics}

    context = CalculationContext(
        company_id=company_id,
        fiscal_period=FiscalPeriod(year=fiscal_year, period_type=FiscalPeriodType.ANNUAL),
        currency=Currency.usd(),
    )
    calc_engine = CalculationEngine(metric_registry)
    res_list = calc_engine.calculate_all(context=context, inputs=inputs, confidences={k: ConfidenceScore(1.0) for k in inputs})
    metrics = {r.key: r.value for r in res_list if r.status.value == "success"}

    health_engine = ExecutiveHealthEngine()
    summary = health_engine.evaluate_company(
        company_id=company_id,
        ticker=company.ticker,
        company_name=company.name,
        metrics=metrics,
    )

    return {
        "company_id": summary.company_id,
        "ticker": summary.ticker,
        "company_name": summary.company_name,
        "overall_score": summary.overall_score,
        "rating": summary.rating.value,
        "traffic_light": summary.traffic_light.value,
        "strengths": summary.strengths,
        "vulnerabilities": summary.vulnerabilities,
        "metric_healths": [
            {
                "metric_key": mh.metric_key,
                "name": mh.name,
                "category": mh.category,
                "value": mh.value,
                "score": mh.score,
                "traffic_light": mh.traffic_light.value,
                "rating": mh.rating.value,
            }
            for mh in summary.metric_healths
        ],
    }
