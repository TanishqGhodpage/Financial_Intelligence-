"""
Business Rules Engine
=====================
Declares an AbstractRule interface and a RuleValidator that runs all registered
rules against a dataset. Rules are pure Python — no database or API calls.

Business rules capture domain invariants that must hold for any set of
extracted financial metrics. Violations are returned as structured results
(never exceptions) so callers can decide how to handle them.

Adding a new rule:
  1. Create a class inheriting AbstractRule.
  2. Implement rule_key, description, and validate().
  3. Register it in the RULE_REGISTRY list at the bottom of this file.

No other files need to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Rule Severity
# ---------------------------------------------------------------------------

class RuleSeverity(str, Enum):
    ERROR = "ERROR"       # Data cannot be trusted; block processing
    WARNING = "WARNING"   # Flag for analyst review; continue processing
    INFO = "INFO"         # Informational note only


# ---------------------------------------------------------------------------
# Violation & Validation Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleViolation:
    rule_key: str
    severity: RuleSeverity
    message: str
    context: dict[str, Any]


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    violations: list[RuleViolation]

    @property
    def has_errors(self) -> bool:
        return any(v.severity == RuleSeverity.ERROR for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return any(v.severity == RuleSeverity.WARNING for v in self.violations)

    def summary(self) -> str:
        if self.passed:
            return "Validation passed with no violations."
        errors = sum(1 for v in self.violations if v.severity == RuleSeverity.ERROR)
        warnings = sum(1 for v in self.violations if v.severity == RuleSeverity.WARNING)
        return f"Validation found {errors} error(s) and {warnings} warning(s)."


# ---------------------------------------------------------------------------
# Abstract Rule
# ---------------------------------------------------------------------------

class AbstractRule(ABC):
    """
    Every validation rule implements this interface.
    validate() receives a flat dict of { metric_key: metric_value }
    and returns a list of RuleViolation objects (empty = passed).
    """

    @property
    @abstractmethod
    def rule_key(self) -> str:
        """Unique identifier for this rule, e.g. 'non_negative_revenue'."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description shown in audit logs."""
        ...

    @abstractmethod
    def validate(self, metrics: dict[str, float]) -> list[RuleViolation]:
        ...


# ---------------------------------------------------------------------------
# Built-in Rules
# ---------------------------------------------------------------------------

class NonNegativeRevenueRule(AbstractRule):
    """Revenue must not be negative. Negative revenue indicates a data error."""

    @property
    def rule_key(self) -> str:
        return "non_negative_revenue"

    @property
    def description(self) -> str:
        return "Revenue must be a non-negative number."

    def validate(self, metrics: dict[str, float]) -> list[RuleViolation]:
        revenue = metrics.get("revenue")
        if revenue is not None and revenue < 0:
            return [
                RuleViolation(
                    rule_key=self.rule_key,
                    severity=RuleSeverity.ERROR,
                    message=f"Revenue is negative ({revenue:.2f}), which is invalid.",
                    context={"revenue": revenue},
                )
            ]
        return []


class AssetLiabilityBalanceRule(AbstractRule):
    """
    Basic accounting equation: Total Assets ≈ Total Liabilities + Total Equity.
    Allows a 1% tolerance to account for rounding across data sources.
    """

    TOLERANCE = 0.01  # 1%

    @property
    def rule_key(self) -> str:
        return "asset_liability_balance"

    @property
    def description(self) -> str:
        return "Assets must approximately equal Liabilities + Equity (±1% tolerance)."

    def validate(self, metrics: dict[str, float]) -> list[RuleViolation]:
        assets = metrics.get("total_assets")
        liabilities = metrics.get("total_liabilities")
        equity = metrics.get("total_equity")

        if any(v is None for v in [assets, liabilities, equity]):
            return []  # Cannot validate without all three values

        expected = liabilities + equity  # type: ignore[operator]
        if abs(assets - expected) / max(abs(expected), 1) > self.TOLERANCE:  # type: ignore[operator]
            return [
                RuleViolation(
                    rule_key=self.rule_key,
                    severity=RuleSeverity.WARNING,
                    message=(
                        f"Accounting equation imbalance: Assets={assets:.2f}, "
                        f"Liabilities+Equity={expected:.2f}. "
                        "Possible data extraction error or multiple reporting periods mixed."
                    ),
                    context={"assets": assets, "liabilities": liabilities, "equity": equity},
                )
            ]
        return []


class CurrencyConsistencyRule(AbstractRule):
    """
    All monetary metrics in a single ingestion batch must use the same currency.
    If currencies differ, the data cannot be safely aggregated.
    """

    @property
    def rule_key(self) -> str:
        return "currency_consistency"

    @property
    def description(self) -> str:
        return "All metrics in a batch must share the same currency."

    def validate(self, metrics: dict[str, float]) -> list[RuleViolation]:
        # This rule is currency-aware and validated separately at ingestion;
        # here we leave a placeholder returning no violations (currency
        # is stored on NormalizedMetric, not in the flat dict).
        return []


class PositiveEBITDARule(AbstractRule):
    """Warn when EBITDA is negative — a potential sign of operating distress."""

    @property
    def rule_key(self) -> str:
        return "positive_ebitda"

    @property
    def description(self) -> str:
        return "EBITDA should be positive for a financially healthy company."

    def validate(self, metrics: dict[str, float]) -> list[RuleViolation]:
        ebitda = metrics.get("ebitda")
        if ebitda is not None and ebitda < 0:
            return [
                RuleViolation(
                    rule_key=self.rule_key,
                    severity=RuleSeverity.WARNING,
                    message=f"EBITDA is negative ({ebitda:.2f}). Possible financial distress.",
                    context={"ebitda": ebitda},
                )
            ]
        return []


# ---------------------------------------------------------------------------
# Rule Validator (Aggregate Runner)
# ---------------------------------------------------------------------------

RULE_REGISTRY: list[AbstractRule] = [
    NonNegativeRevenueRule(),
    AssetLiabilityBalanceRule(),
    CurrencyConsistencyRule(),
    PositiveEBITDARule(),
]


class RuleValidator:
    """
    Runs all registered rules against a metric dict and returns a
    consolidated ValidationResult.

    Usage:
        result = RuleValidator().validate({"revenue": 100.0, "total_assets": 500.0, ...})
        if result.has_errors:
            block_processing()
    """

    def __init__(self, rules: list[AbstractRule] | None = None) -> None:
        self._rules = rules if rules is not None else RULE_REGISTRY

    def validate(self, metrics: dict[str, float]) -> ValidationResult:
        all_violations: list[RuleViolation] = []
        for rule in self._rules:
            violations = rule.validate(metrics)
            all_violations.extend(violations)

        has_errors = any(v.severity == RuleSeverity.ERROR for v in all_violations)
        return ValidationResult(
            passed=not has_errors,
            violations=all_violations,
        )
