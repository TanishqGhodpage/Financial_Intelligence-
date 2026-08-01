"""
Domain Value Objects
====================
Pure, immutable value types with no external dependencies.
These model concepts central to financial intelligence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any


# ---------------------------------------------------------------------------
# Confidence Score
# ---------------------------------------------------------------------------

class ConfidenceStrategy(str, Enum):
    MULTIPLICATIVE = "multiplicative"
    MINIMUM = "minimum"
    WEIGHTED_AVERAGE = "weighted_average"


@dataclass(frozen=True)
class ConfidenceScore:
    """
    Represents a confidence percentage (0.0 - 1.0) for any extracted
    or calculated financial value.
    """

    value: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(
                f"ConfidenceScore must be between 0.0 and 1.0, got {self.value}"
            )

    @classmethod
    def certain(cls) -> "ConfidenceScore":
        """Returns a fully certain (deterministic) confidence score."""
        return cls(value=1.0)

    @classmethod
    def from_source_authority(cls, authority: "SourceAuthority") -> "ConfidenceScore":
        return cls(value=authority.score)

    def propagate(self, others: list["ConfidenceScore"], strategy: ConfidenceStrategy = ConfidenceStrategy.MULTIPLICATIVE) -> "ConfidenceScore":
        """
        Combine this confidence with others using the specified strategy.
        """
        if not others:
            return self

        if strategy == ConfidenceStrategy.MULTIPLICATIVE:
            result = self.value
            for other in others:
                result *= other.value
            return ConfidenceScore(value=round(result, 4))
        
        elif strategy == ConfidenceStrategy.MINIMUM:
            result = min([self.value] + [o.value for o in others])
            return ConfidenceScore(value=round(result, 4))
            
        elif strategy == ConfidenceStrategy.WEIGHTED_AVERAGE:
            # Simple average for MVP
            result = sum([self.value] + [o.value for o in others]) / (len(others) + 1)
            return ConfidenceScore(value=round(result, 4))
            
        return self

    def __mul__(self, other: "ConfidenceScore") -> "ConfidenceScore":
        return self.propagate([other])

    def __repr__(self) -> str:  # pragma: no cover
        return f"ConfidenceScore({self.value:.2%})"

    @property
    def is_reliable(self) -> bool:
        """True if confidence is above 80%."""
        return self.value >= 0.80

    @property
    def is_acceptable(self) -> bool:
        """True if confidence is above 60%."""
        return self.value >= 0.60


# ---------------------------------------------------------------------------
# Source Authority
# ---------------------------------------------------------------------------

class SourceAuthority(float, Enum):
    """
    Authority weights for data sources, used to initialise ConfidenceScore
    and resolve conflicts between competing data sources.
    """

    SEC_FILING = 1.00       # 10-K / 10-Q – highest authority
    EARNINGS_CALL = 0.90    # Official earnings transcript
    PRESS_RELEASE = 0.85    # Company IR press releases
    THIRD_PARTY_API = 0.70  # Yahoo Finance, FMP, etc.
    NEWS = 0.50             # News articles
    UNKNOWN = 0.40          # Unrecognised source

    @property
    def score(self) -> float:
        return self.value


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Currency:
    """ISO-4217 currency code, e.g. 'USD', 'EUR', 'GBP'."""

    code: str

    def __post_init__(self) -> None:
        if len(self.code) != 3 or not self.code.isalpha():
            raise ValueError(f"Currency code must be ISO-4217 (3 letters), got '{self.code}'")
        # Store as uppercase internally
        object.__setattr__(self, "code", self.code.upper())

    def __repr__(self) -> str:  # pragma: no cover
        return f"Currency({self.code})"

    @classmethod
    def usd(cls) -> "Currency":
        return cls("USD")


# ---------------------------------------------------------------------------
# Fiscal Period
# ---------------------------------------------------------------------------

class FiscalPeriodType(str, Enum):
    ANNUAL = "FY"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    LTM = "LTM"  # Last Twelve Months


@dataclass(frozen=True)
class FiscalPeriod:
    """
    Represents a fiscal reporting period, e.g. FY2024, Q3-2025.
    Provides comparison helpers so metrics can be sorted chronologically.
    """

    year: int
    period_type: FiscalPeriodType

    def __post_init__(self) -> None:
        if self.year < 1900 or self.year > 2100:
            raise ValueError(f"Fiscal year {self.year} is out of expected range.")

    @property
    def label(self) -> str:
        return f"{self.period_type.value}-{self.year}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"FiscalPeriod({self.label})"

    def __lt__(self, other: "FiscalPeriod") -> bool:
        _order = {
            FiscalPeriodType.Q1: 1,
            FiscalPeriodType.Q2: 2,
            FiscalPeriodType.Q3: 3,
            FiscalPeriodType.Q4: 4,
            FiscalPeriodType.ANNUAL: 5,
            FiscalPeriodType.LTM: 6,
        }
        if self.year != other.year:
            return self.year < other.year
        return _order[self.period_type] < _order[other.period_type]


# ---------------------------------------------------------------------------
# Calculation Context & Tracking
# ---------------------------------------------------------------------------

class CalculationStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    MISSING_DEPENDENCY = "missing_dependency"
    INVALID_INPUT = "invalid_input"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class CalculationContext:
    """
    Injected into every calculation to provide state and context.
    """
    company_id: str
    fiscal_period: FiscalPeriod
    currency: Currency
    accounting_standard: str = "GAAP"
    scenario: str = "base"
    forecast_horizon_years: int = 5
    engine_version: str = "v1.0"
    configuration_version: str = "2026.08"


@dataclass(frozen=True)
class CalculationTrace:
    """
    Full audit lineage for a calculation result.
    """
    formula_version: str
    effective_date: str
    author: str
    inputs_used: dict[str, float]
    engine_version: str
    calculation_strategy: str = "deterministic"
    configuration_version: str = "2026.08"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Executive Dashboard & Comparative Analytics Value Objects (Phase 4A)
# ---------------------------------------------------------------------------

class TrafficLight(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class HealthRating(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"
    CC = "CC"
    C = "C"
    D = "D"


class TrendDirection(str, Enum):
    UPWARD = "upward"
    DOWNWARD = "downward"
    FLAT = "flat"
    VOLATILE = "volatile"


@dataclass(frozen=True)
class MetricHealth:
    metric_key: str
    name: str
    category: str
    value: float
    unit: str
    score: float                      # 0.0 to 100.0
    traffic_light: TrafficLight
    rating: HealthRating
    percentile: float                 # 0.0 to 100.0
    z_score: float


@dataclass(frozen=True)
class CompanyHealthSummary:
    company_id: str
    ticker: str
    company_name: str
    overall_score: float              # 0.0 to 100.0
    rating: HealthRating
    traffic_light: TrafficLight
    metric_healths: list[MetricHealth]
    strengths: list[str]              # Top 3 strong metrics
    vulnerabilities: list[str]        # Top 3 vulnerable metrics

