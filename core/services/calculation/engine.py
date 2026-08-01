"""
Calculation Engine
==================
Executes metric calculations within a specific context and produces rich CalculationResults.

Every CalculationResult carries full explainability metadata (description,
formula display, references, trace) populated automatically from its
MetricDefinition — no per-metric custom code needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from core.domain.value_objects import (
    CalculationContext,
    CalculationStatus,
    CalculationTrace,
    ConfidenceScore,
    ConfidenceStrategy,
    Currency,
    FiscalPeriod,
)

if TYPE_CHECKING:
    from core.services.calculation.registry import MetricRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalculationResult:
    """
    Immutable result of a single metric calculation.
    Carries full explainability metadata for the UI "View Calculation" panel.
    """
    key: str
    value: float
    unit: str
    currency: Currency
    fiscal_period: FiscalPeriod
    confidence: ConfidenceScore
    status: CalculationStatus
    trace: CalculationTrace

    # --- Explainability fields (populated from MetricDefinition) ---
    name: str = ""
    category: str = ""
    description: str = ""
    formula_display: str = ""
    references: list[dict[str, str]] = field(default_factory=list)
    validation_messages: list[str] = field(default_factory=list)


@dataclass
class MetricDefinition:
    """
    Declarative definition of a financial metric.
    All metadata fields are used by the CalculationEngine to produce
    self-documenting CalculationResults.
    """
    key: str
    name: str
    category: str
    dependencies: list[str]
    formula: Callable[[dict[str, float], CalculationContext], float]
    unit: str = "absolute"
    description: str = ""
    formula_display: str = ""
    references: list[dict[str, str]] = field(default_factory=list)
    version_number: str = "v1"
    effective_date: str = "2024-01-01"
    author: str = "system"


class CalculationEngine:
    def __init__(self, registry: MetricRegistry):
        self.registry = registry

    def _build_trace(
        self,
        metric_def: MetricDefinition,
        context: CalculationContext,
        inputs_used: dict[str, float],
    ) -> CalculationTrace:
        """Build a CalculationTrace from the MetricDefinition and context."""
        return CalculationTrace(
            formula_version=metric_def.version_number,
            effective_date=metric_def.effective_date,
            author=metric_def.author,
            inputs_used=inputs_used,
            engine_version=context.engine_version,
            calculation_strategy="deterministic",
            configuration_version=context.configuration_version,
        )

    def _build_result(
        self,
        metric_def: MetricDefinition,
        value: float,
        context: CalculationContext,
        confidence: ConfidenceScore,
        status: CalculationStatus,
        trace: CalculationTrace,
        validation_messages: list[str] | None = None,
    ) -> CalculationResult:
        """
        Build a CalculationResult, automatically populating all explainability
        fields from the MetricDefinition.
        """
        return CalculationResult(
            key=metric_def.key,
            value=value,
            unit=metric_def.unit,
            currency=context.currency,
            fiscal_period=context.fiscal_period,
            confidence=confidence,
            status=status,
            trace=trace,
            name=metric_def.name,
            category=metric_def.category,
            description=metric_def.description,
            formula_display=metric_def.formula_display,
            references=list(metric_def.references),
            validation_messages=validation_messages or [],
        )

    def calculate_all(
        self,
        context: CalculationContext,
        inputs: dict[str, float],
        confidences: dict[str, ConfidenceScore],
    ) -> list[CalculationResult]:
        resolved_values = dict(inputs)
        resolved_confidences = dict(confidences)
        results = []

        for key in self.registry.topological_order():
            metric_def = self.registry.get_metric(key)
            if not metric_def:
                continue

            missing_deps = [d for d in metric_def.dependencies if d not in resolved_values]
            if missing_deps:
                logger.debug("Skipping metric '%s': missing %s", key, missing_deps)
                trace = self._build_trace(metric_def, context, {})
                results.append(self._build_result(
                    metric_def, 0.0, context,
                    ConfidenceScore(0.0),
                    CalculationStatus.MISSING_DEPENDENCY,
                    trace,
                    [f"Missing dependencies: {missing_deps}"],
                ))
                continue

            # Extract inputs
            metric_inputs = {d: resolved_values[d] for d in metric_def.dependencies}
            dep_confidences = [resolved_confidences[d] for d in metric_def.dependencies]

            try:
                # Propagate confidence
                final_confidence = ConfidenceScore.certain().propagate(
                    dep_confidences, strategy=ConfidenceStrategy.MULTIPLICATIVE
                )

                # Execute formula
                value = metric_def.formula(metric_inputs, context)

                trace = self._build_trace(metric_def, context, metric_inputs)
                result = self._build_result(
                    metric_def, round(value, 6), context,
                    final_confidence,
                    CalculationStatus.SUCCESS,
                    trace,
                )

                results.append(result)
                resolved_values[key] = result.value
                resolved_confidences[key] = final_confidence

            except ZeroDivisionError as e:
                # Handle gracefully
                logger.warning("Validation Error for %s: %s", key, e)
                trace = self._build_trace(metric_def, context, metric_inputs)
                results.append(self._build_result(
                    metric_def, 0.0, context,
                    ConfidenceScore(0.0),
                    CalculationStatus.INVALID_INPUT,
                    trace,
                    [str(e)],
                ))
            except Exception as e:
                logger.error("Error calculating %s: %s", key, e, exc_info=True)

        return results
