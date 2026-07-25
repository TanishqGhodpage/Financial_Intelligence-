"""
Valuation Engine
================
Defines valuation strategies and implements a bottom-up DCF.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from core.domain.value_objects import (
    CalculationContext,
    CalculationStatus,
    CalculationTrace,
    ConfidenceScore,
    ConfidenceStrategy,
)
from core.services.calculation.engine import CalculationResult

logger = logging.getLogger(__name__)


class ValuationStrategy(ABC):
    """
    Interface for valuation strategies (DCF, Comparable Companies, etc.)
    """
    @abstractmethod
    def calculate(
        self,
        inputs: dict[str, float],
        confidences: dict[str, ConfidenceScore],
        context: CalculationContext
    ) -> list[CalculationResult]:
        """Calculates valuation and returns a list of CalculationResults."""
        pass


class DCFValuationStrategy(ValuationStrategy):
    """
    Bottom-up DCF valuation.
    Derives WACC from CAPM and Cost of Debt.
    Expects projected Free Cash Flows to be available in inputs or generated via DAG.
    """
    def calculate(
        self,
        inputs: dict[str, float],
        confidences: dict[str, ConfidenceScore],
        context: CalculationContext
    ) -> list[CalculationResult]:
        
        results = []
        try:
            # 1. WACC Calculation (Bottom-Up)
            # CAPM = Risk Free Rate + (Beta * Market Premium)
            risk_free_rate = inputs.get("risk_free_rate", 0.04)
            beta = inputs.get("beta", 1.0)
            market_premium = inputs.get("market_premium", 0.06)
            cost_of_equity = risk_free_rate + (beta * market_premium)

            # Cost of Debt = Interest Expense / Total Debt
            interest_expense = inputs.get("interest_expense", 0.0)
            total_debt = inputs.get("total_debt", 1.0) # avoid div by zero
            cost_of_debt = interest_expense / total_debt if total_debt else 0.0

            tax_rate = inputs.get("tax_rate", 0.21)
            
            # WACC
            equity_weight = 0.6 # Placeholder for E/V
            debt_weight = 0.4   # Placeholder for D/V
            wacc = (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt * (1 - tax_rate))
            
            terminal_growth_rate = inputs.get("terminal_growth_rate", 0.02)
            n = context.forecast_horizon_years

            # 2. Extract or project FCFs
            # For MVP, assume a flat base FCF projected out with terminal growth
            base_fcf = inputs.get("free_cash_flow", 0.0)
            if base_fcf <= 0:
                raise ValueError("Base Free Cash Flow must be positive for DCF")

            discounted_fcfs = []
            for t in range(1, n + 1):
                fcf_t = base_fcf * ((1 + terminal_growth_rate) ** t)
                discounted_fcf = fcf_t / ((1 + wacc) ** t)
                discounted_fcfs.append(discounted_fcf)

            fcf_n = base_fcf * ((1 + terminal_growth_rate) ** n)
            terminal_value = (fcf_n * (1 + terminal_growth_rate)) / (wacc - terminal_growth_rate)
            discounted_terminal_value = terminal_value / ((1 + wacc) ** n)

            enterprise_value = sum(discounted_fcfs) + discounted_terminal_value
            net_debt = inputs.get("total_liabilities", 0) - inputs.get("cash_and_equivalents", 0)
            equity_value = enterprise_value - net_debt

            base_trace = CalculationTrace(
                formula_version="v2.0",
                effective_date="2024-01-01",
                author="system",
                inputs_used={"wacc": wacc, "base_fcf": base_fcf, "terminal_growth_rate": terminal_growth_rate},
                engine_version=context.engine_version
            )

            results.append(CalculationResult(
                key="enterprise_value",
                value=round(enterprise_value, 2),
                unit="absolute",
                currency=context.currency,
                fiscal_period=context.fiscal_period,
                confidence=ConfidenceScore(0.5), # estimated
                status=CalculationStatus.SUCCESS,
                trace=base_trace
            ))

            results.append(CalculationResult(
                key="equity_value",
                value=round(equity_value, 2),
                unit="absolute",
                currency=context.currency,
                fiscal_period=context.fiscal_period,
                confidence=ConfidenceScore(0.5),
                status=CalculationStatus.SUCCESS,
                trace=base_trace
            ))

        except Exception as e:
            logger.error("DCF Valuation Failed: %s", e)

        return results
