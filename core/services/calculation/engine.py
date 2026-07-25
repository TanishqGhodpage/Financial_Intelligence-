"""
Calculation Engine
==================
Executes metric calculations within a specific context and produces rich CalculationResults.
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
    key: str
    value: float
    unit: str
    currency: Currency
    fiscal_period: FiscalPeriod
    confidence: ConfidenceScore
    status: CalculationStatus
    trace: CalculationTrace
    validation_messages: list[str] = field(default_factory=list)


@dataclass
class MetricDefinition:
    key: str
    name: str
    category: str
    dependencies: list[str]
    formula: Callable[[dict[str, float], CalculationContext], float]
    unit: str = "absolute"
    references: list[dict[str, str]] = field(default_factory=list)
    version_number: str = "v1"
    effective_date: str = "2024-01-01"
    author: str = "system"


class CalculationEngine:
    def __init__(self, registry: MetricRegistry):
        self.registry = registry

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
                results.append(CalculationResult(
                    key=key,
                    value=0.0,
                    unit=metric_def.unit,
                    currency=context.currency,
                    fiscal_period=context.fiscal_period,
                    confidence=ConfidenceScore(0.0),
                    status=CalculationStatus.MISSING_DEPENDENCY,
                    trace=CalculationTrace(
                        formula_version=metric_def.version_number,
                        effective_date=metric_def.effective_date,
                        author=metric_def.author,
                        inputs_used={},
                        engine_version=context.engine_version
                    ),
                    validation_messages=[f"Missing dependencies: {missing_deps}"]
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

                result = CalculationResult(
                    key=key,
                    value=round(value, 6),
                    unit=metric_def.unit,
                    currency=context.currency,
                    fiscal_period=context.fiscal_period,
                    confidence=final_confidence,
                    status=CalculationStatus.SUCCESS,
                    trace=CalculationTrace(
                        formula_version=metric_def.version_number,
                        effective_date=metric_def.effective_date,
                        author=metric_def.author,
                        inputs_used=metric_inputs,
                        engine_version=context.engine_version
                    )
                )

                results.append(result)
                resolved_values[key] = result.value
                resolved_confidences[key] = final_confidence

            except ZeroDivisionError as e:
                # Handle gracefully
                logger.warning("Validation Error for %s: %s", key, e)
                results.append(CalculationResult(
                    key=key,
                    value=0.0,
                    unit=metric_def.unit,
                    currency=context.currency,
                    fiscal_period=context.fiscal_period,
                    confidence=ConfidenceScore(0.0),
                    status=CalculationStatus.INVALID_INPUT,
                    trace=CalculationTrace(
                        formula_version=metric_def.version_number,
                        effective_date=metric_def.effective_date,
                        author=metric_def.author,
                        inputs_used=metric_inputs,
                        engine_version=context.engine_version
                    ),
                    validation_messages=[str(e)]
                ))
            except Exception as e:
                logger.error("Error calculating %s: %s", key, e, exc_info=True)

        return results
