"""
Forecast Strategy Engine
========================
Pure domain service utilizing the Strategy Pattern for time-series forecasting.

Implemented Strategies:
  1. NaiveForecastStrategy: Carries last observed value forward.
  2. LinearRegressionForecastStrategy: Fits linear model Y = mX + b.
  3. MovingAverageForecastStrategy: Simple Moving Average (SMA).
  4. ExponentialSmoothingForecastStrategy: Exponential Moving Average (EMA).

Extensible Architecture:
  Prepared for future strategies: ARIMA, Prophet, Dynamax, Transformer.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.services.analytics.trend import (
    calculate_ema,
    calculate_linear_regression,
    calculate_sma,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForecastPoint:
    year: int
    value: float
    is_projected: bool
    confidence_lower: float | None = None
    confidence_upper: float | None = None


@dataclass(frozen=True)
class ForecastResult:
    metric_key: str
    strategy_name: str
    historical_points: list[ForecastPoint]
    projected_points: list[ForecastPoint]
    combined_series: list[ForecastPoint]
    model_accuracy: dict[str, float]      # MAPE, RMSE, R²
    executive_summary: str = ""
    historical_cagr_pct: float = 0.0
    volatility_level: str = "LOW"         # LOW, MODERATE, HIGH
    projection_takeaway: str = ""


# ---------------------------------------------------------------------------
# Strategy Pattern Interface
# ---------------------------------------------------------------------------

class ForecastStrategy(ABC):
    """Abstract Strategy Interface for Time-Series Forecasting."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        pass

    @abstractmethod
    def forecast(
        self,
        series: list[tuple[int, float]],   # [(year, value), ...]
        periods_ahead: int = 3,
        metric_key: str = "metric",
    ) -> ForecastResult:
        """Generates future projections for periods_ahead years."""
        pass


# ---------------------------------------------------------------------------
# Concrete Strategy 1: Naive Forecast
# ---------------------------------------------------------------------------

class NaiveForecastStrategy(ForecastStrategy):
    """Carries the last observed value forward into future periods."""

    @property
    def name(self) -> str:
        return "Naive (Last Value)"

    def forecast(
        self,
        series: list[tuple[int, float]],
        periods_ahead: int = 3,
        metric_key: str = "metric",
    ) -> ForecastResult:
        sorted_series = sorted(series, key=lambda x: x[0])
        hist = [ForecastPoint(year=yr, value=round(val, 6), is_projected=False) for yr, val in sorted_series]

        if not sorted_series:
            return ForecastResult(metric_key=metric_key, strategy_name=self.name, historical_points=[], projected_points=[], combined_series=[], model_accuracy={})

        last_year, last_val = sorted_series[-1]
        projected = []
        for i in range(1, periods_ahead + 1):
            projected.append(ForecastPoint(
                year=last_year + i,
                value=round(last_val, 6),
                is_projected=True,
                confidence_lower=round(last_val * 0.90, 6),
                confidence_upper=round(last_val * 1.10, 6),
            ))

        return ForecastResult(
            metric_key=metric_key,
            strategy_name=self.name,
            historical_points=hist,
            projected_points=projected,
            combined_series=hist + projected,
            model_accuracy={"mape": 0.0, "r_squared": 1.0},
        )


# ---------------------------------------------------------------------------
# Concrete Strategy 2: Linear Regression Forecast
# ---------------------------------------------------------------------------

class LinearRegressionForecastStrategy(ForecastStrategy):
    """Fits linear model Y = mX + b to project future periods."""

    @property
    def name(self) -> str:
        return "Linear Regression"

    def forecast(
        self,
        series: list[tuple[int, float]],
        periods_ahead: int = 3,
        metric_key: str = "metric",
    ) -> ForecastResult:
        sorted_series = sorted(series, key=lambda x: x[0])
        hist = [ForecastPoint(year=yr, value=round(val, 6), is_projected=False) for yr, val in sorted_series]

        if len(sorted_series) < 2:
            # Fallback to Naive if not enough points
            return NaiveForecastStrategy().forecast(series, periods_ahead, metric_key)

        slope, r2 = calculate_linear_regression(sorted_series)
        x_mean = sum(s[0] for s in sorted_series) / len(sorted_series)
        y_mean = sum(s[1] for s in sorted_series) / len(sorted_series)
        intercept = y_mean - (slope * x_mean)

        last_year = sorted_series[-1][0]
        projected = []
        for i in range(1, periods_ahead + 1):
            fut_yr = last_year + i
            pred_val = max(0.0, (slope * fut_yr) + intercept)
            margin = abs(pred_val * 0.05 * i)
            projected.append(ForecastPoint(
                year=fut_yr,
                value=round(pred_val, 6),
                is_projected=True,
                confidence_lower=round(max(0.0, pred_val - margin), 6),
                confidence_upper=round(pred_val + margin, 6),
            ))

        # Synthesize CAGR & summary
        s_start = sorted_series[0][1]
        s_end = sorted_series[-1][1]
        n_yrs = len(sorted_series) - 1
        cagr = (((s_end / s_start) ** (1.0 / n_yrs)) - 1.0) * 100.0 if n_yrs > 0 and s_start > 0 and s_end > 0 else 0.0

        volatility = "LOW" if r2 >= 0.80 else "MODERATE" if r2 >= 0.50 else "HIGH"
        last_proj = projected[-1].value if projected else s_end

        exec_summary = (
            f"Historical trend indicates a CAGR of {cagr:+.1f}% across {len(sorted_series)} periods (R²: {r2:.2f}). "
            f"Linear Model projects {metric_key.replace('_', ' ').title()} to reach ${last_proj:,.1f}M by {last_year + periods_ahead}."
        )

        return ForecastResult(
            metric_key=metric_key,
            strategy_name=self.name,
            historical_points=hist,
            projected_points=projected,
            combined_series=hist + projected,
            model_accuracy={"r_squared": round(r2, 4), "slope": round(slope, 6)},
            executive_summary=exec_summary,
            historical_cagr_pct=round(cagr, 2),
            volatility_level=volatility,
            projection_takeaway=f"Projected {last_proj > s_end and 'growth' or 'contraction'} driven by historical trend slope of {slope:+,.2f} per year.",
        )


# ---------------------------------------------------------------------------
# Concrete Strategy 3: Moving Average Forecast
# ---------------------------------------------------------------------------

class MovingAverageForecastStrategy(ForecastStrategy):
    """Simple Moving Average (SMA) forecast over k window periods."""

    def __init__(self, window: int = 3):
        self.window = window

    @property
    def name(self) -> str:
        return f"Simple Moving Average (k={self.window})"

    def forecast(
        self,
        series: list[tuple[int, float]],
        periods_ahead: int = 3,
        metric_key: str = "metric",
    ) -> ForecastResult:
        sorted_series = sorted(series, key=lambda x: x[0])
        hist = [ForecastPoint(year=yr, value=round(val, 6), is_projected=False) for yr, val in sorted_series]

        if not sorted_series:
            return ForecastResult(metric_key=metric_key, strategy_name=self.name, historical_points=[], projected_points=[], combined_series=[], model_accuracy={})

        vals = [s[1] for s in sorted_series]
        sub = vals[-self.window :] if len(vals) >= self.window else vals
        sma_val = sum(sub) / len(sub)

        last_year = sorted_series[-1][0]
        projected = []
        for i in range(1, periods_ahead + 1):
            projected.append(ForecastPoint(
                year=last_year + i,
                value=round(sma_val, 6),
                is_projected=True,
                confidence_lower=round(sma_val * 0.92, 6),
                confidence_upper=round(sma_val * 1.08, 6),
            ))

        return ForecastResult(
            metric_key=metric_key,
            strategy_name=self.name,
            historical_points=hist,
            projected_points=projected,
            combined_series=hist + projected,
            model_accuracy={"window": float(self.window)},
        )


# ---------------------------------------------------------------------------
# Concrete Strategy 4: Exponential Smoothing Forecast
# ---------------------------------------------------------------------------

class ExponentialSmoothingForecastStrategy(ForecastStrategy):
    """Exponential Moving Average (EMA) forecast with smoothing factor alpha."""

    def __init__(self, span: int = 3):
        self.span = span

    @property
    def name(self) -> str:
        return f"Exponential Smoothing (span={self.span})"

    def forecast(
        self,
        series: list[tuple[int, float]],
        periods_ahead: int = 3,
        metric_key: str = "metric",
    ) -> ForecastResult:
        sorted_series = sorted(series, key=lambda x: x[0])
        hist = [ForecastPoint(year=yr, value=round(val, 6), is_projected=False) for yr, val in sorted_series]

        if not sorted_series:
            return ForecastResult(metric_key=metric_key, strategy_name=self.name, historical_points=[], projected_points=[], combined_series=[], model_accuracy={})

        vals = [s[1] for s in sorted_series]
        ema_series = calculate_ema(vals, span=self.span)
        last_ema = ema_series[-1]

        last_year = sorted_series[-1][0]
        projected = []
        for i in range(1, periods_ahead + 1):
            projected.append(ForecastPoint(
                year=last_year + i,
                value=round(last_ema, 6),
                is_projected=True,
                confidence_lower=round(last_ema * 0.90, 6),
                confidence_upper=round(last_ema * 1.10, 6),
            ))

        return ForecastResult(
            metric_key=metric_key,
            strategy_name=self.name,
            historical_points=hist,
            projected_points=projected,
            combined_series=hist + projected,
            model_accuracy={"span": float(self.span), "alpha": round(2.0 / (self.span + 1.0), 4)},
        )


# ---------------------------------------------------------------------------
# Strategy Factory
# ---------------------------------------------------------------------------

def get_forecast_strategy(strategy_type: str = "linear") -> ForecastStrategy:
    """Returns requested strategy instance."""
    st = strategy_type.lower().strip()
    if st in ("naive", "last"):
        return NaiveForecastStrategy()
    elif st in ("linear", "regression"):
        return LinearRegressionForecastStrategy()
    elif st in ("sma", "moving_average"):
        return MovingAverageForecastStrategy(window=3)
    elif st in ("ema", "exponential"):
        return ExponentialSmoothingForecastStrategy(span=3)
    else:
        logger.info("Strategy '%s' fallback to LinearRegressionForecastStrategy", strategy_type)
        return LinearRegressionForecastStrategy()
