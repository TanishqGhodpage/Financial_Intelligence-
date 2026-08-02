"""
Variance Analysis Engine
========================
Pure domain service for variance and contribution analysis.

Compares Actuals against Benchmarks:
  - Actual vs Forecast
  - Actual vs Budget
  - Actual vs Previous Year (YoY)
  - Actual vs Industry Benchmark

Calculates:
  - Absolute Variance (Actual - Benchmark)
  - Relative Variance % ((Actual - Benchmark) / Benchmark * 100)
  - Directional Badge: Favorable (F) or Unfavorable (U)
  - Contribution Analysis (% contribution of line item to category variance)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from core.services.calculation.registry import metric_registry

logger = logging.getLogger(__name__)


class VarianceType(str, Enum):
    FAVORABLE = "Favorable"
    UNFAVORABLE = "Unfavorable"
    NEUTRAL = "Neutral"


# Higher is better for revenue, margins, ROE, FCF, quick ratio
# Lower is better for liabilities, debt, interest expense, COGS
METRIC_DIRECTION_PREFERENCE = {
    "revenue": "higher",
    "gross_profit_margin": "higher",
    "operating_margin": "higher",
    "net_profit_margin": "higher",
    "return_on_equity": "higher",
    "return_on_assets": "higher",
    "current_ratio": "higher",
    "quick_ratio": "higher",
    "interest_coverage": "higher",
    "free_cash_flow": "higher",
    "cost_of_goods_sold": "lower",
    "total_liabilities": "lower",
    "total_debt": "lower",
    "short_term_debt": "lower",
    "long_term_debt": "lower",
    "debt_to_equity": "lower",
    "liabilities_to_equity": "lower",
    "interest_expense": "lower",
}


@dataclass(frozen=True)
class MetricVarianceDetail:
    metric_key: str
    name: str
    category: str
    unit: str
    actual_value: float
    benchmark_value: float
    absolute_variance: float
    relative_variance_pct: float
    variance_type: VarianceType
    contribution_pct: float


@dataclass(frozen=True)
class VarianceAnalysisResult:
    company_id: str
    benchmark_name: str                     # "Budget", "Forecast", "Prior Year", "Industry"
    fiscal_period_label: str
    metrics_variance: list[MetricVarianceDetail]
    favorable_count: int
    unfavorable_count: int
    net_variance_summary: str
    top_positive_drivers: list[dict[str, Any]] = field(default_factory=list)
    top_negative_drivers: list[dict[str, Any]] = field(default_factory=list)
    business_change_summary: str = ""


class VarianceAnalysisEngine:
    """
    Engine for actual vs benchmark variance analysis.
    Computes absolute/relative variance, F/U classification, and contribution percentages.
    """

    def analyze_variance(
        self,
        company_id: str,
        actual_metrics: dict[str, float],
        benchmark_metrics: dict[str, float],
        benchmark_name: str = "Forecast",
        fiscal_period_label: str = "FY2024",
    ) -> VarianceAnalysisResult:
        all_keys = set(actual_metrics.keys()).union(benchmark_metrics.keys())
        details: list[MetricVarianceDetail] = []

        f_count = 0
        u_count = 0

        # Calculate absolute variances to determine sum for contribution analysis
        raw_abs_vars: dict[str, float] = {}
        total_abs_var_sum = 0.0

        for key in sorted(all_keys):
            actual_val = actual_metrics.get(key, 0.0)
            bench_val = benchmark_metrics.get(key, 0.0)
            diff = actual_val - bench_val
            raw_abs_vars[key] = diff
            total_abs_var_sum += abs(diff)

        for key in sorted(all_keys):
            actual_val = actual_metrics.get(key, 0.0)
            bench_val = benchmark_metrics.get(key, 0.0)
            abs_var = raw_abs_vars[key]

            if bench_val == 0.0:
                rel_var_pct = 0.0
            else:
                rel_var_pct = (abs_var / abs(bench_val)) * 100.0

            # Direction preference
            pref = METRIC_DIRECTION_PREFERENCE.get(key, "higher")
            if abs_var == 0.0:
                v_type = VarianceType.NEUTRAL
            elif pref == "higher":
                v_type = VarianceType.FAVORABLE if abs_var > 0 else VarianceType.UNFAVORABLE
            else:
                v_type = VarianceType.FAVORABLE if abs_var < 0 else VarianceType.UNFAVORABLE

            if v_type == VarianceType.FAVORABLE:
                f_count += 1
            elif v_type == VarianceType.UNFAVORABLE:
                u_count += 1

            contrib_pct = (abs(abs_var) / total_abs_var_sum * 100.0) if total_abs_var_sum > 0 else 0.0

            m_def = metric_registry.get_metric(key)
            name = m_def.name if m_def else key.replace("_", " ").title()
            category = m_def.category if m_def else "other"
            unit = m_def.unit if m_def else "absolute"

            details.append(MetricVarianceDetail(
                metric_key=key,
                name=name,
                category=category,
                unit=unit,
                actual_value=round(actual_val, 6),
                benchmark_value=round(bench_val, 6),
                absolute_variance=round(abs_var, 6),
                relative_variance_pct=round(rel_var_pct, 4),
                variance_type=v_type,
                contribution_pct=round(contrib_pct, 2),
            ))

        # Extract top positive & negative drivers by contribution %
        fav_details = sorted([m for m in details if m.variance_type == VarianceType.FAVORABLE], key=lambda x: x.contribution_pct, reverse=True)
        unfav_details = sorted([m for m in details if m.variance_type == VarianceType.UNFAVORABLE], key=lambda x: x.contribution_pct, reverse=True)

        top_pos = [
            {"name": m.name, "metric_key": m.metric_key, "abs_var": m.absolute_variance, "rel_var_pct": m.relative_variance_pct, "contrib_pct": m.contribution_pct}
            for m in fav_details[:3]
        ]
        top_neg = [
            {"name": m.name, "metric_key": m.metric_key, "abs_var": m.absolute_variance, "rel_var_pct": m.relative_variance_pct, "contrib_pct": m.contribution_pct}
            for m in unfav_details[:3]
        ]

        net_summary = f"{f_count} Favorable, {u_count} Unfavorable variances vs {benchmark_name}."

        pos_name = top_pos[0]['name'] if top_pos else "None"
        neg_name = top_neg[0]['name'] if top_neg else "None"

        bus_summary = (
            f"Performance vs {benchmark_name} is primarily driven positively by {pos_name} "
            f"and constrained by {neg_name}. Overall, {f_count} metrics met or exceeded target benchmarks."
        )

        return VarianceAnalysisResult(
            company_id=company_id,
            benchmark_name=benchmark_name,
            fiscal_period_label=fiscal_period_label,
            metrics_variance=details,
            favorable_count=f_count,
            unfavorable_count=u_count,
            net_variance_summary=net_summary,
            top_positive_drivers=top_pos,
            top_negative_drivers=top_neg,
            business_change_summary=bus_summary,
        )
