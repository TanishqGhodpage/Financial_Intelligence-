"""
Trend Analytics Engine
======================
Pure domain service for multi-year time-series financial analytics.

Supports:
  - CAGR (Compound Annual Growth Rate)
  - YoY (Year-over-Year) percentage growth
  - Linear Regression Slope & R² (Goodness of Fit)
  - SMA (Simple Moving Average)
  - EMA (Exponential Moving Average)
  - Trend Direction classification (Upward, Downward, Flat, Volatile)
  - Time horizons: 1Y, 3Y, 5Y, 10Y
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from core.domain.value_objects import TrendDirection

# ---------------------------------------------------------------------------
# Trend Calculation Helpers
# ---------------------------------------------------------------------------

def calculate_cagr(start_val: float, end_val: float, num_years: int) -> float:
    """
    Computes Compound Annual Growth Rate.
    CAGR = (End Value / Start Value) ** (1 / n) - 1
    """
    if num_years <= 0 or start_val <= 0.0 or end_val <= 0.0:
        return 0.0
    try:
        cagr = ((end_val / start_val) ** (1.0 / num_years)) - 1.0
        return round(cagr, 6)
    except Exception:
        return 0.0


def calculate_yoy_growth(series: list[tuple[int, float]]) -> list[dict[str, Any]]:
    """
    Computes Year-over-Year growth percentage.
    series is sorted list of (year, value) tuples.
    """
    if len(series) < 2:
        return []

    sorted_series = sorted(series, key=lambda x: x[0])
    yoy_results = []

    for i in range(1, len(sorted_series)):
        prev_yr, prev_val = sorted_series[i - 1]
        curr_yr, curr_val = sorted_series[i]

        if prev_val == 0.0:
            growth_pct = 0.0
        else:
            growth_pct = ((curr_val - prev_val) / abs(prev_val)) * 100.0

        yoy_results.append({
            "year": curr_yr,
            "previous_year": prev_yr,
            "value": curr_val,
            "previous_value": prev_val,
            "growth_pct": round(growth_pct, 4),
        })

    return yoy_results


def calculate_linear_regression(series: list[tuple[int, float]]) -> tuple[float, float]:
    """
    Computes Linear Regression Slope (m) and Coefficient of Determination (R²).
    series: list of (year, value)
    """
    n = len(series)
    if n < 2:
        return (0.0, 0.0)

    x_vals = [float(item[0]) for item in series]
    y_vals = [float(item[1]) for item in series]

    x_mean = sum(x_vals) / n
    y_mean = sum(y_vals) / n

    numerator = sum((x_vals[i] - x_mean) * (y_vals[i] - y_mean) for i in range(n))
    denominator = sum((x_vals[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0.0:
        slope = 0.0
    else:
        slope = numerator / denominator

    # Calculate R² (Coefficient of Determination)
    ss_tot = sum((y_vals[i] - y_mean) ** 2 for i in range(n))
    if ss_tot == 0.0:
        r_squared = 1.0
    else:
        intercept = y_mean - (slope * x_mean)
        ss_res = sum((y_vals[i] - ((slope * x_vals[i]) + intercept)) ** 2 for i in range(n))
        r_squared = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot)))

    return (round(slope, 6), round(r_squared, 4))


def calculate_sma(values: list[float], window: int = 3) -> list[float]:
    """Computes Simple Moving Average with specified window size."""
    if not values:
        return []
    if window <= 1 or window > len(values):
        return [round(v, 6) for v in values]

    sma_list = []
    for i in range(len(values)):
        if i < window - 1:
            # Average available elements up to i
            sub = values[: i + 1]
        else:
            sub = values[i - window + 1 : i + 1]
        sma_list.append(round(sum(sub) / len(sub), 6))
    return sma_list


def calculate_ema(values: list[float], span: int = 3) -> list[float]:
    """Computes Exponential Moving Average with smoothing multiplier alpha = 2/(span+1)."""
    if not values:
        return []
    if len(values) == 1:
        return [round(values[0], 6)]

    alpha = 2.0 / (span + 1.0)
    ema_list = [values[0]]
    for i in range(1, len(values)):
        prev_ema = ema_list[-1]
        curr_ema = (values[i] * alpha) + (prev_ema * (1.0 - alpha))
        ema_list.append(curr_ema)

    return [round(v, 6) for v in ema_list]


def classify_trend_direction(slope: float, r_squared: float, values: list[float]) -> TrendDirection:
    """Classifies metric trend direction based on slope and R²."""
    if not values:
        return TrendDirection.FLAT

    val_mean = abs(sum(values) / len(values)) if values else 1.0
    rel_slope = slope / val_mean if val_mean != 0.0 else slope

    if r_squared < 0.35 and len(values) >= 3:
        return TrendDirection.VOLATILE
    elif rel_slope > 0.02:
        return TrendDirection.UPWARD
    elif rel_slope < -0.02:
        return TrendDirection.DOWNWARD
    else:
        return TrendDirection.FLAT


# ---------------------------------------------------------------------------
# Data Models for Trend Analytics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricTrendResult:
    metric_key: str
    company_id: str
    time_series: list[dict[str, Any]]         # [{"year": 2020, "value": 100.0}, ...]
    cagr: float
    yoy_growth: list[dict[str, Any]]
    slope: float
    r_squared: float
    sma_3y: list[float]
    ema_3y: list[float]
    trend_direction: TrendDirection


# ---------------------------------------------------------------------------
# Trend Analytics Engine
# ---------------------------------------------------------------------------

class TrendAnalyticsEngine:
    """
    Engine for multi-year financial trend analysis.
    Evaluates 1Y, 3Y, 5Y, and 10Y CAGR, YoY growth, linear regression, and moving averages.
    """

    def analyze_trend(
        self,
        company_id: str,
        metric_key: str,
        time_series: list[tuple[int, float]],   # [(year, value), ...]
    ) -> MetricTrendResult:
        sorted_series = sorted(time_series, key=lambda x: x[0])
        years = [item[0] for item in sorted_series]
        vals = [item[1] for item in sorted_series]

        num_years = len(sorted_series) - 1 if len(sorted_series) > 1 else 1
        start_val = sorted_series[0][1] if sorted_series else 0.0
        end_val = sorted_series[-1][1] if sorted_series else 0.0

        cagr = calculate_cagr(start_val, end_val, num_years)
        yoy = calculate_yoy_growth(sorted_series)
        slope, r2 = calculate_linear_regression(sorted_series)
        sma = calculate_sma(vals, window=3)
        ema = calculate_ema(vals, span=3)
        direction = classify_trend_direction(slope, r2, vals)

        formatted_series = [
            {"year": yr, "value": val, "sma_3": s, "ema_3": e}
            for (yr, val), s, e in zip(sorted_series, sma, ema)
        ]

        return MetricTrendResult(
            metric_key=metric_key,
            company_id=company_id,
            time_series=formatted_series,
            cagr=cagr,
            yoy_growth=yoy,
            slope=slope,
            r_squared=r2,
            sma_3y=sma,
            ema_3y=ema,
            trend_direction=direction,
        )
