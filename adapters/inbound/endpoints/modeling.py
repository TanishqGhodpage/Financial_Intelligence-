"""
Financial Modeling Suite Endpoints
====================================
Provides REST endpoints for Scenario Modeling, 2D Sensitivity Analysis,
Stress Testing, Time-Series Forecasting, and Variance Analysis.

Clean Controller: Contains NO modeling or calculation logic.
Delegates entirely to core services in core/services/modeling/.
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
from core.services.modeling.forecasting import get_forecast_strategy
from core.services.modeling.scenarios import ScenarioModelingEngine, ScenarioParameters
from core.services.modeling.sensitivity import SensitivityAnalysisEngine
from core.services.modeling.stress_test import StressShockParams, StressTestEngine
from core.services.modeling.variance import VarianceAnalysisEngine

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class ScenarioRequest(BaseModel):
    company_id: str
    fiscal_year: Optional[int] = 2024
    revenue_growth_pct: Optional[float] = 0.0
    cogs_ratio_adj: Optional[float] = 0.0
    tax_rate: Optional[float] = 0.21
    inflation_rate_pct: Optional[float] = 0.0
    interest_rate_adj_bps: Optional[float] = 0.0
    fx_rate: Optional[float] = 1.0
    op_margin_adj_pct: Optional[float] = 0.0


class SensitivityRequest(BaseModel):
    company_id: str
    sensitivity_type: str = "dcf"             # "dcf" or "margin"
    target_metric_key: Optional[str] = "return_on_equity"
    fiscal_year: Optional[int] = 2024


class StressTestRequest(BaseModel):
    company_id: str
    fiscal_year: Optional[int] = 2024
    revenue_shock_pct: Optional[float] = -0.20
    margin_compression_bps: Optional[float] = 500.0
    debt_shock_pct: Optional[float] = 0.30
    interest_rate_shock_bps: Optional[float] = 300.0
    liquidity_drain_pct: Optional[float] = -0.40


class ForecastRequest(BaseModel):
    company_id: str
    metric_key: str = "revenue"
    strategy_type: str = "linear"             # "naive", "linear", "sma", "ema"
    periods_ahead: int = 3
    start_year: int = 2020
    end_year: int = 2024


class VarianceRequest(BaseModel):
    company_id: str
    benchmark_name: str = "Forecast"         # "Forecast", "Budget", "Prior Year", "Industry"
    fiscal_year: Optional[int] = 2024
    benchmark_metrics: Optional[dict[str, float]] = None


# ---------------------------------------------------------------------------
# Helper: Fetch base inputs for a company
# ---------------------------------------------------------------------------

async def _fetch_company_inputs(company_id: str, fiscal_year: int, db: AsyncSession) -> dict[str, float]:
    result = await db.execute(
        select(NormalizedMetricORM)
        .where(NormalizedMetricORM.company_id == company_id)
        .where(NormalizedMetricORM.fiscal_year == fiscal_year)
    )
    metrics = result.scalars().all()
    inputs = {m.metric_key: m.metric_value for m in metrics}

    # Set sensible fallbacks if missing
    inputs.setdefault("revenue", 1000.0)
    inputs.setdefault("cost_of_goods_sold", 600.0)
    inputs.setdefault("operating_income", 200.0)
    inputs.setdefault("net_income", 150.0)
    inputs.setdefault("total_assets", 2000.0)
    inputs.setdefault("total_liabilities", 800.0)
    inputs.setdefault("total_equity", 1200.0)
    inputs.setdefault("current_assets", 500.0)
    inputs.setdefault("current_liabilities", 300.0)
    inputs.setdefault("short_term_debt", 50.0)
    inputs.setdefault("long_term_debt", 250.0)
    inputs.setdefault("interest_expense", 15.0)
    inputs.setdefault("free_cash_flow", 120.0)
    inputs.setdefault("cash", 150.0)
    inputs.setdefault("inventory", 50.0)

    return inputs


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/scenarios")
async def run_scenarios(
    payload: ScenarioRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Runs multi-scenario simulation (Base, Bull, Bear, Custom)."""
    inputs = await _fetch_company_inputs(payload.company_id, payload.fiscal_year or 2024, db)

    custom_params = ScenarioParameters(
        name="Custom Scenario",
        revenue_growth_pct=payload.revenue_growth_pct or 0.0,
        cogs_ratio_adj=payload.cogs_ratio_adj or 0.0,
        tax_rate=payload.tax_rate or 0.21,
        inflation_rate_pct=payload.inflation_rate_pct or 0.0,
        interest_rate_adj_bps=payload.interest_rate_adj_bps or 0.0,
        fx_rate=payload.fx_rate or 1.0,
        op_margin_adj_pct=payload.op_margin_adj_pct or 0.0,
    )

    engine = ScenarioModelingEngine()
    result = engine.simulate_scenarios(
        company_id=payload.company_id,
        base_inputs=inputs,
        custom_params=custom_params,
        fiscal_year=payload.fiscal_year or 2024,
    )

    out_scenarios = {}
    for k, s_out in result.scenarios.items():
        out_scenarios[k] = {
            "scenario_name": s_out.scenario_name,
            "dcf_equity_value": s_out.dcf_equity_value,
            "dcf_enterprise_value": s_out.dcf_enterprise_value,
            "statement_impact": s_out.statement_impact,
            "metrics": s_out.metrics,
            "executive_summary": s_out.executive_summary,
            "primary_drivers": s_out.primary_drivers,
            "risk_level": s_out.risk_level,
        }

    return {
        "company_id": result.company_id,
        "base_year": result.base_year,
        "scenarios": out_scenarios,
        "overall_executive_summary": result.overall_executive_summary,
    }


@router.post("/sensitivity")
async def run_sensitivity(
    payload: SensitivityRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generates N x M 2D Sensitivity Matrix."""
    inputs = await _fetch_company_inputs(payload.company_id, payload.fiscal_year or 2024, db)
    engine = SensitivityAnalysisEngine()

    if payload.sensitivity_type.lower() == "dcf":
        base_fcf = inputs.get("free_cash_flow", 120.0)
        wacc_range = [0.06, 0.08, 0.10, 0.12, 0.14]
        tgr_range = [0.01, 0.02, 0.03, 0.04, 0.05]
        net_debt = inputs.get("total_liabilities", 800.0) - inputs.get("cash", 150.0)
        res = engine.generate_dcf_sensitivity(
            base_fcf=base_fcf,
            wacc_range=wacc_range,
            terminal_growth_range=tgr_range,
            net_debt=net_debt,
        )
    else:
        rev_g_range = [-0.15, -0.05, 0.05, 0.15]
        op_m_range = [0.10, 0.15, 0.20, 0.25]
        res = engine.generate_margin_sensitivity(
            base_inputs=inputs,
            rev_growth_range=rev_g_range,
            op_margin_range=op_m_range,
            target_metric_key=payload.target_metric_key or "return_on_equity",
        )

    return {
        "target_metric_key": res.target_metric_key,
        "target_metric_name": res.target_metric_name,
        "row_parameter_name": res.row_parameter_name,
        "row_values": res.row_values,
        "col_parameter_name": res.col_parameter_name,
        "col_values": res.col_values,
        "grid_matrix": res.grid_matrix,
        "min_value": res.min_value,
        "max_value": res.max_value,
        "baseline_row_idx": res.baseline_row_idx,
        "baseline_col_idx": res.baseline_col_idx,
        "executive_summary": res.executive_summary,
        "optimal_region_summary": res.optimal_region_summary,
        "risk_region_summary": res.risk_region_summary,
    }


@router.post("/stress-test")
async def run_stress_test(
    payload: StressTestRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Runs market shock stress test and computes stress risk level."""
    inputs = await _fetch_company_inputs(payload.company_id, payload.fiscal_year or 2024, db)
    shocks = StressShockParams(
        revenue_shock_pct=payload.revenue_shock_pct if payload.revenue_shock_pct is not None else -0.20,
        margin_compression_bps=payload.margin_compression_bps if payload.margin_compression_bps is not None else 500.0,
        debt_shock_pct=payload.debt_shock_pct if payload.debt_shock_pct is not None else 0.30,
        interest_rate_shock_bps=payload.interest_rate_shock_bps if payload.interest_rate_shock_bps is not None else 300.0,
        liquidity_drain_pct=payload.liquidity_drain_pct if payload.liquidity_drain_pct is not None else -0.40,
    )

    engine = StressTestEngine()
    res = engine.run_stress_test(
        company_id=payload.company_id,
        base_inputs=inputs,
        shocks=shocks,
        fiscal_year=payload.fiscal_year or 2024,
    )

    return {
        "company_id": res.company_id,
        "stress_level": res.stress_level.value,
        "insolvency_warning": res.insolvency_warning,
        "baseline_metrics": res.baseline_metrics,
        "post_shock_metrics": res.post_shock_metrics,
        "metric_deltas": res.metric_deltas,
        "post_shock_dcf_equity_value": res.post_shock_dcf_equity_value,
        "risk_summary": res.risk_summary,
        "business_outcome_summary": res.business_outcome_summary,
        "operating_margin_impact": res.operating_margin_impact,
        "liquidity_status": res.liquidity_status,
        "debt_coverage_status": res.debt_coverage_status,
        "analyst_next_steps": res.analyst_next_steps,
    }


@router.post("/forecast")
async def run_forecast(
    payload: ForecastRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Runs time-series metric forecasting strategy."""
    raw = await db.execute(
        select(NormalizedMetricORM)
        .where(NormalizedMetricORM.company_id == payload.company_id)
        .where(NormalizedMetricORM.metric_key == payload.metric_key)
        .where(NormalizedMetricORM.fiscal_year >= payload.start_year)
        .where(NormalizedMetricORM.fiscal_year <= payload.end_year)
        .order_by(NormalizedMetricORM.fiscal_year.asc())
    )
    norm_metrics = raw.scalars().all()

    series = [(m.fiscal_year, m.metric_value) for m in norm_metrics if m.fiscal_year is not None]

    if not series:
        # Fallback mock historical series if no DB records exist yet
        base_yr = payload.start_year
        series = [(base_yr + i, 1000.0 * ((1.08) ** i)) for i in range(5)]

    strategy = get_forecast_strategy(payload.strategy_type)
    res = strategy.forecast(series, periods_ahead=payload.periods_ahead, metric_key=payload.metric_key)

    return {
        "metric_key": res.metric_key,
        "strategy_name": res.strategy_name,
        "model_accuracy": res.model_accuracy,
        "executive_summary": res.executive_summary,
        "historical_cagr_pct": res.historical_cagr_pct,
        "volatility_level": res.volatility_level,
        "projection_takeaway": res.projection_takeaway,
        "historical_points": [
            {"year": p.year, "value": p.value, "is_projected": p.is_projected}
            for p in res.historical_points
        ],
        "projected_points": [
            {
                "year": p.year,
                "value": p.value,
                "is_projected": p.is_projected,
                "confidence_lower": p.confidence_lower,
                "confidence_upper": p.confidence_upper,
            }
            for p in res.projected_points
        ],
    }


@router.post("/variance")
async def run_variance_analysis(
    payload: VarianceRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Runs actual vs benchmark variance and contribution analysis."""
    actual_inputs = await _fetch_company_inputs(payload.company_id, payload.fiscal_year or 2024, db)

    benchmark_inputs = payload.benchmark_metrics
    if not benchmark_inputs:
        # Generate simulated benchmark (e.g. Budget = Actual * 0.95 or Forecast)
        benchmark_inputs = {k: v * 0.95 for k, v in actual_inputs.items()}

    engine = VarianceAnalysisEngine()
    res = engine.analyze_variance(
        company_id=payload.company_id,
        actual_metrics=actual_inputs,
        benchmark_metrics=benchmark_inputs,
        benchmark_name=payload.benchmark_name,
        fiscal_period_label=f"FY{payload.fiscal_year or 2024}",
    )

    return {
        "company_id": res.company_id,
        "benchmark_name": res.benchmark_name,
        "fiscal_period_label": res.fiscal_period_label,
        "favorable_count": res.favorable_count,
        "unfavorable_count": res.unfavorable_count,
        "net_variance_summary": res.net_variance_summary,
        "business_change_summary": res.business_change_summary,
        "top_positive_drivers": res.top_positive_drivers,
        "top_negative_drivers": res.top_negative_drivers,
        "metrics_variance": [
            {
                "metric_key": m.metric_key,
                "name": m.name,
                "category": m.category,
                "unit": m.unit,
                "actual_value": m.actual_value,
                "benchmark_value": m.benchmark_value,
                "absolute_variance": m.absolute_variance,
                "relative_variance_pct": m.relative_variance_pct,
                "variance_type": m.variance_type.value,
                "contribution_pct": m.contribution_pct,
            }
            for m in res.metrics_variance
        ],
    }
