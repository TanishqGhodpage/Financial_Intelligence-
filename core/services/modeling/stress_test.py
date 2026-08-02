"""
Stress Test Engine
==================
Pure domain service for simulating financial shocks and evaluating enterprise stress risk.

Market Shocks:
  - Revenue Shock (% drop in revenue)
  - Margin Compression (bps drop in operating margin)
  - Debt Shock (% increase in total debt)
  - Interest Rate Shock (bps increase in interest rates)
  - Liquidity Drain (% drop in cash & equivalents)

Stress Level Classification:
  - SAFE: Current Ratio >= 1.2 AND Interest Coverage >= 2.5
  - MODERATE_STRESS: Current Ratio 0.9 - 1.2 OR Interest Coverage 1.5 - 2.5
  - SEVERE_STRESS: Current Ratio 0.6 - 0.9 OR Interest Coverage 1.0 - 1.5
  - DISTRESS: Current Ratio < 0.6 OR Interest Coverage < 1.0 (Insolvency Warning)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from core.domain.value_objects import CalculationContext, Currency, FiscalPeriod, FiscalPeriodType, ConfidenceScore
from core.services.calculation.engine import CalculationEngine
from core.services.calculation.registry import metric_registry
from core.services.calculation.valuation import DCFValuationStrategy

logger = logging.getLogger(__name__)


class StressLevel(str, Enum):
    SAFE = "safe"
    MODERATE_STRESS = "moderate_stress"
    SEVERE_STRESS = "severe_stress"
    DISTRESS = "distress"


@dataclass(frozen=True)
class StressShockParams:
    revenue_shock_pct: float = -0.20           # -20% revenue drop
    margin_compression_bps: float = 500.0      # -500 bps operating margin compression
    debt_shock_pct: float = 0.30              # +30% debt increase
    interest_rate_shock_bps: float = 300.0    # +300 bps interest rate increase
    liquidity_drain_pct: float = -0.40         # -40% cash drain


@dataclass(frozen=True)
class StressTestResult:
    company_id: str
    stress_level: StressLevel
    insolvency_warning: bool
    baseline_metrics: dict[str, float]
    post_shock_metrics: dict[str, float]
    metric_deltas: dict[str, float]            # post_shock - baseline
    post_shock_dcf_equity_value: float
    risk_summary: list[str]
    business_outcome_summary: str = ""
    operating_margin_impact: str = ""
    liquidity_status: str = ""
    debt_coverage_status: str = ""
    analyst_next_steps: list[str] = field(default_factory=list)


class StressTestEngine:
    """
    Engine for multi-shock financial stress testing.
    Calculates post-shock ratios, valuations, and risk levels.
    """

    def run_stress_test(
        self,
        company_id: str,
        base_inputs: dict[str, float],
        shocks: StressShockParams | None = None,
        fiscal_year: int = 2024,
    ) -> StressTestResult:
        if shocks is None:
            shocks = StressShockParams()

        calc_engine = CalculationEngine(metric_registry)
        dcf_strategy = DCFValuationStrategy()

        fp = FiscalPeriod(year=fiscal_year, period_type=FiscalPeriodType.ANNUAL)
        context = CalculationContext(
            company_id=company_id,
            fiscal_period=fp,
            currency=Currency.usd(),
            engine_version="v2.0",
        )

        # 1. Baseline Calculation
        base_conf = {k: ConfidenceScore(1.0) for k in base_inputs}
        base_results = calc_engine.calculate_all(context=context, inputs=base_inputs, confidences=base_conf)
        baseline_metrics = {r.key: r.value for r in base_results if r.status.value == "success"}

        # 2. Apply Shock Perturbations
        post_shock_inputs = dict(base_inputs)

        # Revenue Shock
        base_rev = post_shock_inputs.get("revenue", 1000.0)
        shocked_rev = max(1.0, base_rev * (1.0 + shocks.revenue_shock_pct))
        post_shock_inputs["revenue"] = shocked_rev

        # Margin Compression
        base_op_inc = post_shock_inputs.get("operating_income", 200.0)
        base_op_margin = base_op_inc / base_rev if base_rev else 0.20
        shocked_op_margin = max(0.01, base_op_margin - (shocks.margin_compression_bps / 10000.0))
        shocked_op_inc = shocked_rev * shocked_op_margin
        post_shock_inputs["operating_income"] = shocked_op_inc

        # Debt & Interest Rate Shock
        base_st_debt = post_shock_inputs.get("short_term_debt", 50.0)
        base_lt_debt = post_shock_inputs.get("long_term_debt", 200.0)
        shocked_st_debt = base_st_debt * (1.0 + shocks.debt_shock_pct)
        shocked_lt_debt = base_lt_debt * (1.0 + shocks.debt_shock_pct)
        post_shock_inputs["short_term_debt"] = shocked_st_debt
        post_shock_inputs["long_term_debt"] = shocked_lt_debt
        post_shock_inputs["total_liabilities"] = post_shock_inputs.get("total_liabilities", 300.0) * (1.0 + shocks.debt_shock_pct)

        base_interest = post_shock_inputs.get("interest_expense", 15.0)
        rate_increase_factor = 1.0 + (shocks.interest_rate_shock_bps / 10000.0)
        shocked_interest = max(1.0, base_interest * rate_increase_factor)
        post_shock_inputs["interest_expense"] = shocked_interest

        # Liquidity Drain
        base_cash = post_shock_inputs.get("cash", 100.0)
        shocked_cash = max(0.0, base_cash * (1.0 + shocks.liquidity_drain_pct))
        post_shock_inputs["cash"] = shocked_cash
        base_curr_assets = post_shock_inputs.get("current_assets", 300.0)
        post_shock_inputs["current_assets"] = max(0.0, base_curr_assets + (shocked_cash - base_cash))

        # Net Income Post-Shock
        pretax = shocked_op_inc - shocked_interest
        shocked_net_inc = max(0.0, pretax * 0.79)
        post_shock_inputs["net_income"] = shocked_net_inc

        # 3. Post-Shock Metric Recalculation
        shock_conf = {k: ConfidenceScore(1.0) for k in post_shock_inputs}
        shock_results = calc_engine.calculate_all(context=context, inputs=post_shock_inputs, confidences=shock_conf)
        post_shock_metrics = {r.key: r.value for r in shock_results if r.status.value == "success"}

        # Deltas
        metric_deltas = {}
        for k in set(baseline_metrics.keys()).union(post_shock_metrics.keys()):
            base_v = baseline_metrics.get(k, 0.0)
            shock_v = post_shock_metrics.get(k, 0.0)
            metric_deltas[k] = round(shock_v - base_v, 4)

        # 4. Post-Shock Valuation
        dcf_inputs = {
            "wacc": 0.12,  # elevated WACC during stress
            "terminal_growth_rate": 0.015,
            "free_cash_flow": post_shock_metrics.get("free_cash_flow", post_shock_inputs.get("free_cash_flow", 50.0)),
            "total_liabilities": post_shock_inputs["total_liabilities"],
            "cash_and_equivalents": shocked_cash,
        }
        dcf_res = dcf_strategy.calculate(inputs=dcf_inputs, confidences={"free_cash_flow": ConfidenceScore(1.0)}, context=context)
        post_shock_eq = next((r.value for r in dcf_res if r.key == "equity_value"), 0.0)

        # 5. Stress Level & Insolvency Warning Classification
        post_curr_ratio = post_shock_metrics.get("current_ratio", 1.5)
        post_interest_cov = post_shock_metrics.get("interest_coverage", 3.0)

        insolvency_warning = False
        risk_summary = []
        next_steps = []

        if post_curr_ratio < 0.6 or post_interest_cov < 1.0:
            level = StressLevel.DISTRESS
            insolvency_warning = True
            risk_summary.append("CRITICAL: Insolvency Risk! Interest coverage < 1.0 or Current Ratio < 0.6 under stress.")
            next_steps = [
                "Audit debt refinancing schedules and debt maturity walls over next 12-24 months.",
                "Model immediate cost rationalization and non-core asset disposition scenarios.",
                "Assess revolving credit line drawdowns and debt covenant breach conditions."
            ]
        elif post_curr_ratio < 0.9 or post_interest_cov < 1.5:
            level = StressLevel.SEVERE_STRESS
            risk_summary.append("HIGH RISK: Severe liquidity and debt service pressure.")
            next_steps = [
                "Evaluate working capital optimization (inventory reduction & receivable acceleration).",
                "Stress test interest expense sensitivity against benchmark rate hikes."
            ]
        elif post_curr_ratio < 1.2 or post_interest_cov < 2.5:
            level = StressLevel.MODERATE_STRESS
            risk_summary.append("MODERATE RISK: Liquidity buffer is tight under market shocks.")
            next_steps = ["Monitor working capital buffer and discretionary CapEx spending."]
        else:
            level = StressLevel.SAFE
            risk_summary.append("SAFE: Balance sheet withstands all applied stress shocks.")
            next_steps = ["Continue routine peer benchmarking and leverage monitoring."]

        base_op_m = baseline_metrics.get("operating_margin", 0.20) * 100.0
        shock_op_m = post_shock_metrics.get("operating_margin", 0.15) * 100.0
        margin_imp = f"Operating Margin shifts from {base_op_m:.1f}% to {shock_op_m:.1f}% ({shock_op_m - base_op_m:+.1f}%)."

        liq_stat = f"Current Ratio {post_curr_ratio:.2f}x ({'Healthy' if post_curr_ratio >= 1.2 else 'Tight' if post_curr_ratio >= 0.9 else 'Vulnerable'})."
        debt_stat = f"Interest Coverage {post_interest_cov:.2f}x ({'Safe' if post_interest_cov >= 2.5 else 'Constrained' if post_interest_cov >= 1.5 else 'High Risk'})."

        bus_outcome = (
            f"Under applied shocks ({shocks.revenue_shock_pct*100:.0f}% Revenue, -{shocks.margin_compression_bps:.0f} bps Margin, +{shocks.debt_shock_pct*100:.0f}% Debt), "
            f"DCF Equity Valuation drops to ${post_shock_eq:,.1f}M. Operating solvency remains {level.value.upper().replace('_', ' ')}."
        )

        return StressTestResult(
            company_id=company_id,
            stress_level=level,
            insolvency_warning=insolvency_warning,
            baseline_metrics=baseline_metrics,
            post_shock_metrics=post_shock_metrics,
            metric_deltas=metric_deltas,
            post_shock_dcf_equity_value=post_shock_eq,
            risk_summary=risk_summary,
            business_outcome_summary=bus_outcome,
            operating_margin_impact=margin_imp,
            liquidity_status=liq_stat,
            debt_coverage_status=debt_stat,
            analyst_next_steps=next_steps,
        )
