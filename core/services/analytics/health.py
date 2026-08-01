"""
Executive Health Engine
=======================
Pure domain rules engine for calculating company Executive Health Scores,
Traffic Light indicators, and Financial Health Ratings (AAA to D).

Scoring Weight Distribution:
  - Profitability (ROE, ROA, Margins): 35%
  - Liquidity (Current Ratio, Quick Ratio): 25%
  - Leverage (Debt-to-Equity, Interest Coverage): 25%
  - Cash Flow (Free Cash Flow): 15%

Overall Health Rating Thresholds:
  - 90 - 100 : AAA (Green)
  - 80 - 89  : AA  (Green)
  - 70 - 79  : A   (Green)
  - 60 - 69  : BBB (Yellow)
  - 50 - 59  : BB  (Yellow)
  - 40 - 49  : B   (Yellow)
  - 30 - 39  : CCC (Red)
  - 20 - 29  : CC  (Red)
  - 10 - 19  : C   (Red)
  - < 10     : D   (Red)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.domain.value_objects import (
    CompanyHealthSummary,
    HealthRating,
    MetricHealth,
    TrafficLight,
)
from core.services.calculation.registry import metric_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threshold Rules for Metric Health Scoring
# ---------------------------------------------------------------------------

def _score_metric_value(key: str, val: float) -> tuple[float, TrafficLight]:
    """
    Evaluates a single metric value against enterprise financial standards.
    Returns (score 0-100, TrafficLight).
    """
    score = 50.0
    light = TrafficLight.YELLOW

    if key == "gross_profit_margin":
        # val is decimal ratio (0.40 = 40%)
        if val >= 0.45:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.30:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 0.15:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 25.0, TrafficLight.RED

    elif key == "operating_margin":
        if val >= 0.20:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.10:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 0.05:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 20.0, TrafficLight.RED

    elif key == "net_profit_margin":
        if val >= 0.15:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.08:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 0.03:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 20.0, TrafficLight.RED

    elif key == "return_on_equity":
        if val >= 0.20:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.12:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 0.05:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 20.0, TrafficLight.RED

    elif key == "return_on_assets":
        if val >= 0.10:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.05:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 0.02:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 20.0, TrafficLight.RED

    elif key == "current_ratio":
        # ideal 1.5 - 3.0
        if 1.5 <= val <= 3.5:
            score, light = 95.0, TrafficLight.GREEN
        elif 1.0 <= val < 1.5:
            score, light = 70.0, TrafficLight.YELLOW
        elif val > 3.5:
            score, light = 75.0, TrafficLight.YELLOW  # excess cash / inefficient
        else:
            score, light = 25.0, TrafficLight.RED

    elif key == "quick_ratio":
        if val >= 1.0:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 0.8:
            score, light = 70.0, TrafficLight.YELLOW
        else:
            score, light = 25.0, TrafficLight.RED

    elif key == "debt_to_equity":
        # lower is safer
        if val <= 0.5:
            score, light = 95.0, TrafficLight.GREEN
        elif val <= 1.5:
            score, light = 75.0, TrafficLight.GREEN
        elif val <= 2.5:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 20.0, TrafficLight.RED

    elif key == "liabilities_to_equity":
        if val <= 1.0:
            score, light = 95.0, TrafficLight.GREEN
        elif val <= 2.0:
            score, light = 70.0, TrafficLight.YELLOW
        else:
            score, light = 25.0, TrafficLight.RED

    elif key == "interest_coverage":
        if val >= 5.0:
            score, light = 95.0, TrafficLight.GREEN
        elif val >= 2.5:
            score, light = 75.0, TrafficLight.GREEN
        elif val >= 1.5:
            score, light = 50.0, TrafficLight.YELLOW
        else:
            score, light = 15.0, TrafficLight.RED

    elif key == "free_cash_flow":
        if val > 0:
            score, light = 85.0, TrafficLight.GREEN
        else:
            score, light = 25.0, TrafficLight.RED

    return (score, light)


def _map_score_to_rating(score: float) -> tuple[HealthRating, TrafficLight]:
    if score >= 90.0:
        return (HealthRating.AAA, TrafficLight.GREEN)
    elif score >= 80.0:
        return (HealthRating.AA, TrafficLight.GREEN)
    elif score >= 70.0:
        return (HealthRating.A, TrafficLight.GREEN)
    elif score >= 60.0:
        return (HealthRating.BBB, TrafficLight.YELLOW)
    elif score >= 50.0:
        return (HealthRating.BB, TrafficLight.YELLOW)
    elif score >= 40.0:
        return (HealthRating.B, TrafficLight.YELLOW)
    elif score >= 30.0:
        return (HealthRating.CCC, TrafficLight.RED)
    elif score >= 20.0:
        return (HealthRating.CC, TrafficLight.RED)
    elif score >= 10.0:
        return (HealthRating.C, TrafficLight.RED)
    else:
        return (HealthRating.D, TrafficLight.RED)


# ---------------------------------------------------------------------------
# Executive Health Engine
# ---------------------------------------------------------------------------

class ExecutiveHealthEngine:
    """
    Computes Executive Health Scores, Traffic Light indicators, and Credit-style Ratings.
    Supports both standalone company evaluations and cohort-relative percentiles.
    """

    CATEGORY_WEIGHTS = {
        "profitability": 0.35,
        "liquidity": 0.25,
        "leverage": 0.25,
        "cash_flow": 0.15,
        "other": 0.05,
    }

    def evaluate_company(
        self,
        company_id: str,
        ticker: str,
        company_name: str,
        metrics: dict[str, float],
        cohort_z_scores: dict[str, float] | None = None,
        cohort_percentiles: dict[str, float] | None = None,
    ) -> CompanyHealthSummary:
        metric_health_list: list[MetricHealth] = []
        category_scores: dict[str, list[float]] = {
            "profitability": [],
            "liquidity": [],
            "leverage": [],
            "cash_flow": [],
            "other": [],
        }

        for key, val in metrics.items():
            if val is None:
                continue
            metric_def = metric_registry.get_metric(key)
            name = metric_def.name if metric_def else key.replace("_", " ").title()
            category = metric_def.category if metric_def else "other"
            unit = metric_def.unit if metric_def else "absolute"

            # Compute score and traffic light
            base_score, light = _score_metric_value(key, val)
            rating, _ = _map_score_to_rating(base_score)

            z_sc = cohort_z_scores.get(key, 0.0) if cohort_z_scores else 0.0
            perc = cohort_percentiles.get(key, 50.0) if cohort_percentiles else 50.0

            mh = MetricHealth(
                metric_key=key,
                name=name,
                category=category,
                value=round(val, 6),
                unit=unit,
                score=round(base_score, 1),
                traffic_light=light,
                rating=rating,
                percentile=round(perc, 1),
                z_score=round(z_sc, 2),
            )
            metric_health_list.append(mh)
            category_scores.setdefault(category, []).append(base_score)

        # Calculate weighted overall score
        total_weight = 0.0
        weighted_score_sum = 0.0

        for cat, scores in category_scores.items():
            if scores:
                cat_avg = sum(scores) / len(scores)
                weight = self.CATEGORY_WEIGHTS.get(cat, 0.05)
                weighted_score_sum += cat_avg * weight
                total_weight += weight

        if total_weight > 0.0:
            overall_score = round(weighted_score_sum / total_weight, 1)
        else:
            overall_score = 50.0

        overall_rating, overall_light = _map_score_to_rating(overall_score)

        # Identify strengths (top 3 highest scores) and vulnerabilities (lowest 3 scores)
        sorted_by_score = sorted(metric_health_list, key=lambda x: x.score, reverse=True)
        strengths = [
            f"{m.name} ({m.rating.value}): {m.score:.0f}/100"
            for m in sorted_by_score[:3]
            if m.score >= 60.0
        ]
        vulnerabilities = [
            f"{m.name} ({m.rating.value}): {m.score:.0f}/100"
            for m in sorted_by_score[-3:]
            if m.score < 60.0
        ]

        return CompanyHealthSummary(
            company_id=company_id,
            ticker=ticker,
            company_name=company_name,
            overall_score=overall_score,
            rating=overall_rating,
            traffic_light=overall_light,
            metric_healths=metric_health_list,
            strengths=strengths,
            vulnerabilities=vulnerabilities,
        )
