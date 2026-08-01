"""
Enterprise Comparative Intelligence Engine
===========================================
Pure domain service for multi-company financial benchmarking and cohort statistics.

Supports 2 to 10 companies simultaneously.

Calculates:
  - Rankings (1st .. Nth)
  - Mean, Median, Min, Max
  - Standard Deviation & Variance
  - Percentiles (P25, P50, P75, P90)
  - Z-Scores (Standardized Distance from Mean)
  - Relative Performance (% deviation from cohort mean)
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from core.services.calculation.registry import metric_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Statistical Utility Functions
# ---------------------------------------------------------------------------

def calculate_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_median(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.median(values)


def calculate_min_max(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    return (min(values), max(values))


def calculate_std_dev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        return statistics.stdev(values)
    except Exception:
        return 0.0


def calculate_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        return statistics.variance(values)
    except Exception:
        return 0.0


def calculate_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _perc(p: float) -> float:
        idx = p * (n - 1)
        lower = math.floor(idx)
        upper = math.ceil(idx)
        weight = idx - lower
        return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight

    return {
        "p25": round(_perc(0.25), 6),
        "p50": round(_perc(0.50), 6),
        "p75": round(_perc(0.75), 6),
        "p90": round(_perc(0.90), 6),
    }


def calculate_z_scores(values: dict[str, float]) -> dict[str, float]:
    """Computes Z-Score = (x - mean) / std_dev for each company."""
    if not values:
        return {}
    val_list = list(values.values())
    mean_val = calculate_mean(val_list)
    std_val = calculate_std_dev(val_list)

    z_scores = {}
    for cid, val in values.items():
        if std_val == 0.0:
            z_scores[cid] = 0.0
        else:
            z_scores[cid] = round((val - mean_val) / std_val, 4)
    return z_scores


def calculate_rankings(values: dict[str, float], reverse: bool = True) -> dict[str, int]:
    """
    Ranks companies based on metric values.
    By default reverse=True (higher value = 1st place).
    """
    if not values:
        return {}
    sorted_pairs = sorted(values.items(), key=lambda x: x[1], reverse=reverse)
    rankings = {}
    for rank, (cid, _) in enumerate(sorted_pairs, start=1):
        rankings[cid] = rank
    return rankings


def calculate_relative_performance(
    values: dict[str, float], benchmark_avg: float
) -> dict[str, float]:
    """Percentage deviation from cohort average."""
    result = {}
    for cid, val in values.items():
        if benchmark_avg == 0.0:
            result[cid] = 0.0
        else:
            result[cid] = round(((val - benchmark_avg) / abs(benchmark_avg)) * 100.0, 2)
    return result


# ---------------------------------------------------------------------------
# Data Models for Comparative Intelligence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricBenchmarkStats:
    metric_key: str
    name: str
    category: str
    unit: str
    mean: float
    median: float
    min_value: float
    max_value: float
    std_dev: float
    variance: float
    percentiles: dict[str, float]
    company_values: dict[str, float]
    z_scores: dict[str, float]
    rankings: dict[str, int]
    relative_performance: dict[str, float]


@dataclass(frozen=True)
class CohortComparisonResult:
    company_ids: list[str]
    company_tickers: dict[str, str]           # company_id -> ticker
    fiscal_period_label: str
    metric_stats: dict[str, MetricBenchmarkStats]


# ---------------------------------------------------------------------------
# Comparative Analytics Engine
# ---------------------------------------------------------------------------

class ComparativeAnalyticsEngine:
    """
    Engine for multi-company comparative analytics (2–10 companies).
    Calculates rankings, statistics, Z-scores, and percentiles for every metric.
    """

    def compare_cohort(
        self,
        cohort_metrics: dict[str, dict[str, float]],   # company_id -> {metric_key -> float}
        company_tickers: dict[str, str],               # company_id -> ticker
        fiscal_period_label: str = "FY2024",
    ) -> CohortComparisonResult:
        company_ids = list(cohort_metrics.keys())
        if len(company_ids) < 2:
            logger.warning("Cohort has fewer than 2 companies (%d). Statistics calculated on small cohort.", len(company_ids))

        # Collect all metric keys present across the cohort
        all_metric_keys = set()
        for c_metrics in cohort_metrics.values():
            all_metric_keys.update(c_metrics.keys())

        metric_stats_map: dict[str, MetricBenchmarkStats] = {}

        for key in sorted(all_metric_keys):
            metric_def = metric_registry.get_metric(key)
            name = metric_def.name if metric_def else key.replace("_", " ").title()
            category = metric_def.category if metric_def else "other"
            unit = metric_def.unit if metric_def else "absolute"

            # Extract values for companies that have this metric
            comp_vals = {
                cid: c_metrics[key]
                for cid, c_metrics in cohort_metrics.items()
                if key in c_metrics and c_metrics[key] is not None
            }

            if not comp_vals:
                continue

            val_list = list(comp_vals.values())
            mean_val = calculate_mean(val_list)
            median_val = calculate_median(val_list)
            min_v, max_v = calculate_min_max(val_list)
            std_v = calculate_std_dev(val_list)
            var_v = calculate_variance(val_list)
            perc = calculate_percentiles(val_list)
            z_sc = calculate_z_scores(comp_vals)
            rank = calculate_rankings(comp_vals, reverse=True)
            rel_perf = calculate_relative_performance(comp_vals, mean_val)

            metric_stats_map[key] = MetricBenchmarkStats(
                metric_key=key,
                name=name,
                category=category,
                unit=unit,
                mean=round(mean_val, 6),
                median=round(median_val, 6),
                min_value=round(min_v, 6),
                max_value=round(max_v, 6),
                std_dev=round(std_v, 6),
                variance=round(var_v, 6),
                percentiles=perc,
                company_values=comp_vals,
                z_scores=z_sc,
                rankings=rank,
                relative_performance=rel_perf,
            )

        return CohortComparisonResult(
            company_ids=company_ids,
            company_tickers=company_tickers,
            fiscal_period_label=fiscal_period_label,
            metric_stats=metric_stats_map,
        )
