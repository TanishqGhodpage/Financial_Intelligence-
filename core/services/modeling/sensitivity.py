"""
Sensitivity Analysis Engine
===========================
Pure domain service for generating N x M 2D Sensitivity Matrices.

Supports:
  - DCF Sensitivity: WACC vs Terminal Growth Rate -> Equity Value Matrix
  - Margin Sensitivity: Revenue Growth vs Operating Margin -> Net Income / ROE Matrix
  - Leverage Sensitivity: Debt vs Equity -> Debt-to-Equity Matrix
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.domain.value_objects import CalculationContext, Currency, FiscalPeriod, FiscalPeriodType, ConfidenceScore
from core.services.calculation.engine import CalculationEngine
from core.services.calculation.registry import metric_registry
from core.services.calculation.valuation import DCFValuationStrategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensitivityMatrixResult:
    target_metric_key: str
    target_metric_name: str
    row_parameter_name: str
    row_values: list[float]                # N values
    col_parameter_name: str
    col_values: list[float]                # M values
    grid_matrix: list[list[float]]         # N x M matrix
    min_value: float
    max_value: float
    baseline_row_idx: int
    baseline_col_idx: int
    executive_summary: str = ""
    optimal_region_summary: str = ""
    risk_region_summary: str = ""


class SensitivityAnalysisEngine:
    """
    Generates N x M 2D sensitivity matrices by varying two input parameters simultaneously.
    """

    def generate_dcf_sensitivity(
        self,
        base_fcf: float,
        wacc_range: list[float],                # e.g. [0.06, 0.08, 0.10, 0.12, 0.14]
        terminal_growth_range: list[float],     # e.g. [0.01, 0.02, 0.03, 0.04, 0.05]
        net_debt: float = 0.0,
        baseline_wacc: float = 0.10,
        baseline_tgr: float = 0.03,
    ) -> SensitivityMatrixResult:
        dcf_strategy = DCFValuationStrategy()
        context = CalculationContext(
            company_id="sens_dcf",
            fiscal_period=FiscalPeriod(year=2024, period_type=FiscalPeriodType.ANNUAL),
            currency=Currency.usd(),
        )

        matrix: list[list[float]] = []
        min_v = float("inf")
        max_v = float("-inf")

        for wacc in wacc_range:
            row: list[float] = []
            for tgr in terminal_growth_range:
                if wacc <= tgr:
                    # Invalid DCF condition (WACC <= Terminal Growth)
                    row.append(0.0)
                    continue

                dcf_inputs = {
                    "wacc": wacc,
                    "terminal_growth_rate": tgr,
                    "free_cash_flow": base_fcf,
                    "total_liabilities": net_debt,
                    "cash_and_equivalents": 0.0,
                }

                results = dcf_strategy.calculate(
                    inputs=dcf_inputs,
                    confidences={"free_cash_flow": ConfidenceScore(1.0)},
                    context=context,
                )
                eq_val = next((r.value for r in results if r.key == "equity_value"), 0.0)
                row.append(round(eq_val, 2))

                if eq_val > 0:
                    min_v = min(min_v, eq_val)
                    max_v = max(max_v, eq_val)

            matrix.append(row)

        b_row = min(range(len(wacc_range)), key=lambda i: abs(wacc_range[i] - baseline_wacc))
        b_col = min(range(len(terminal_growth_range)), key=lambda j: abs(terminal_growth_range[j] - baseline_tgr))
        base_val = matrix[b_row][b_col] if matrix and b_row < len(matrix) and b_col < len(matrix[0]) else 0.0

        exec_summary = (
            f"DCF Equity Value is highly sensitive to WACC assumptions and moderately sensitive to Terminal Growth. "
            f"Baseline valuation of ${base_val:,.1f}M (WACC {wacc_range[b_row]*100:.1f}%, TGR {terminal_growth_range[b_col]*100:.1f}%) "
            f"ranges from ${min_v:,.1f}M under conservative conditions to ${max_v:,.1f}M under optimal conditions."
        )

        return SensitivityMatrixResult(
            target_metric_key="equity_value",
            target_metric_name="DCF Equity Value ($M)",
            row_parameter_name="WACC (%)",
            row_values=[round(w * 100.0, 2) for w in wacc_range],
            col_parameter_name="Terminal Growth Rate (%)",
            col_values=[round(t * 100.0, 2) for t in terminal_growth_range],
            grid_matrix=matrix,
            min_value=round(min_v if min_v != float("inf") else 0.0, 2),
            max_value=round(max_v if max_v != float("-inf") else 0.0, 2),
            baseline_row_idx=b_row,
            baseline_col_idx=b_col,
            executive_summary=exec_summary,
            optimal_region_summary="Optimal Region (Top-Right): Lower WACC combined with higher Terminal Growth maximizes valuation.",
            risk_region_summary="Risk Region (Bottom-Left): Elevated WACC combined with lower Terminal Growth severely compresses valuation.",
        )

    def generate_margin_sensitivity(
        self,
        base_inputs: dict[str, float],
        rev_growth_range: list[float],          # e.g. [-0.10, 0.0, 0.10, 0.20]
        op_margin_range: list[float],           # e.g. [0.10, 0.15, 0.20, 0.25]
        target_metric_key: str = "return_on_equity",
    ) -> SensitivityMatrixResult:
        calc_engine = CalculationEngine(metric_registry)
        context = CalculationContext(
            company_id="sens_margin",
            fiscal_period=FiscalPeriod(year=2024, period_type=FiscalPeriodType.ANNUAL),
            currency=Currency.usd(),
        )

        matrix: list[list[float]] = []
        min_v = float("inf")
        max_v = float("-inf")

        base_rev = base_inputs.get("revenue", 1000.0)

        for rev_g in rev_growth_range:
            row: list[float] = []
            for op_m in op_margin_range:
                inputs = dict(base_inputs)
                p_rev = base_rev * (1.0 + rev_g)
                p_op_inc = p_rev * op_m
                inputs["revenue"] = p_rev
                inputs["operating_income"] = p_op_inc
                inputs["net_income"] = max(0.0, p_op_inc * 0.79)  # approx net income after 21% tax

                confidences = {k: ConfidenceScore(1.0) for k in inputs}
                results = calc_engine.calculate_all(context=context, inputs=inputs, confidences=confidences)
                res_val = next((r.value for r in results if r.key == target_metric_key), 0.0)

                row.append(round(res_val, 6))
                min_v = min(min_v, res_val)
                max_v = max(max_v, res_val)

            matrix.append(row)

        m_def = metric_registry.get_metric(target_metric_key)
        name = m_def.name if m_def else target_metric_key.replace("_", " ").title()

        exec_summary = (
            f"{name} sensitivity analysis demonstrates how profitability shifts across combinations of Revenue Growth and Operating Margin. "
            f"Values range from a low of {min_v*100:.1f}% to a high of {max_v*100:.1f}%."
        )

        return SensitivityMatrixResult(
            target_metric_key=target_metric_key,
            target_metric_name=name,
            row_parameter_name="Revenue Growth (%)",
            row_values=[round(rg * 100.0, 1) for rg in rev_growth_range],
            col_parameter_name="Operating Margin (%)",
            col_values=[round(om * 100.0, 1) for om in op_margin_range],
            grid_matrix=matrix,
            min_value=round(min_v, 6),
            max_value=round(max_v, 6),
            baseline_row_idx=0,
            baseline_col_idx=0,
            executive_summary=exec_summary,
            optimal_region_summary="Optimal Region (Top-Right): Double leverage from positive revenue growth and operating margin expansion.",
            risk_region_summary="Risk Region (Bottom-Left): Revenue contraction compounded by margin compression.",
        )
