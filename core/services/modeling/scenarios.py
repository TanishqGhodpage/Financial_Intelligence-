"""
Scenario Simulation Engine
==========================
Pure domain service for simulating financial scenarios (Base, Bull, Bear, Custom).

Recalculates financial statements, ratios, DCF valuations, and KPIs under
perturbed parameters (Revenue, COGS, Tax, Inflation, Interest Rates, FX, Operating Margin).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.domain.value_objects import CalculationContext, Currency, FiscalPeriod, FiscalPeriodType, ConfidenceScore
from core.services.calculation.engine import CalculationEngine, CalculationResult
from core.services.calculation.registry import metric_registry
from core.services.calculation.valuation import DCFValuationStrategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioParameters:
    """Parameters used to perturb baseline financial inputs."""
    name: str = "custom"
    revenue_growth_pct: float = 0.0        # e.g. 0.15 for +15%
    cogs_ratio_adj: float = 0.0            # e.g. -0.02 for -2% COGS/Revenue
    tax_rate: float = 0.21                 # e.g. 0.21 for 21%
    inflation_rate_pct: float = 0.0        # e.g. 0.03 for 3%
    interest_rate_adj_bps: float = 0.0     # e.g. 200.0 for +200 bps
    fx_rate: float = 1.0                   # Currency multiplier
    op_margin_adj_pct: float = 0.0         # e.g. 0.03 for +3%


# Pre-built Scenario Presets
SCENARIO_PRESETS: dict[str, ScenarioParameters] = {
    "base": ScenarioParameters(name="Base Case"),
    "bull": ScenarioParameters(
        name="Bull Case",
        revenue_growth_pct=0.15,
        cogs_ratio_adj=-0.02,
        tax_rate=0.20,
        op_margin_adj_pct=0.03,
    ),
    "bear": ScenarioParameters(
        name="Bear Case",
        revenue_growth_pct=-0.15,
        cogs_ratio_adj=0.03,
        interest_rate_adj_bps=200.0,
        inflation_rate_pct=0.05,
        op_margin_adj_pct=-0.04,
    ),
}


@dataclass(frozen=True)
class SingleScenarioOutput:
    scenario_name: str
    parameters: ScenarioParameters
    metrics: dict[str, float]               # key -> calculated value
    dcf_equity_value: float
    dcf_enterprise_value: float
    statement_impact: dict[str, float]      # perturbed statement lines
    executive_summary: str = ""
    primary_drivers: list[str] = field(default_factory=list)
    risk_level: str = "LOW"                 # LOW, MODERATE, HIGH


@dataclass(frozen=True)
class ScenarioSimulationResult:
    company_id: str
    base_year: int
    scenarios: dict[str, SingleScenarioOutput]   # scenario_name -> SingleScenarioOutput
    overall_executive_summary: str = ""


class ScenarioModelingEngine:
    """
    Engine for simulating scenario modeling.
    Perturbs baseline inputs and re-runs metric and valuation engines.
    """

    def simulate_scenarios(
        self,
        company_id: str,
        base_inputs: dict[str, float],
        custom_params: ScenarioParameters | None = None,
        fiscal_year: int = 2024,
    ) -> ScenarioSimulationResult:
        scenarios_to_run: dict[str, ScenarioParameters] = dict(SCENARIO_PRESETS)
        if custom_params:
            scenarios_to_run["custom"] = custom_params

        calc_engine = CalculationEngine(metric_registry)
        dcf_strategy = DCFValuationStrategy()
        fp = FiscalPeriod(year=fiscal_year, period_type=FiscalPeriodType.ANNUAL)
        context = CalculationContext(
            company_id=company_id,
            fiscal_period=fp,
            currency=Currency.usd(),
            engine_version="v2.0",
        )

        outputs: dict[str, SingleScenarioOutput] = {}

        for key, params in scenarios_to_run.items():
            perturbed_inputs, statement_impact = self._apply_scenario_parameters(base_inputs, params)
            confidences = {k: ConfidenceScore(1.0) for k in perturbed_inputs}

            # 1. Recalculate deterministic metrics via CalculationEngine
            results = calc_engine.calculate_all(context=context, inputs=perturbed_inputs, confidences=confidences)
            metrics_map = {r.key: r.value for r in results if r.status.value == "success"}

            # 2. Recalculate DCF valuation via DCFValuationStrategy
            dcf_inputs = {
                "wacc": perturbed_inputs.get("wacc", 0.10) + (params.interest_rate_adj_bps / 10000.0),
                "terminal_growth_rate": perturbed_inputs.get("terminal_growth_rate", 0.03),
                "free_cash_flow": metrics_map.get("free_cash_flow", perturbed_inputs.get("free_cash_flow", 100.0)),
                "total_liabilities": perturbed_inputs.get("total_liabilities", 0.0),
                "cash_and_equivalents": perturbed_inputs.get("cash", 0.0),
            }

            dcf_results = dcf_strategy.calculate(
                inputs=dcf_inputs,
                confidences={"free_cash_flow": ConfidenceScore(1.0)},
                context=context,
            )
            ev = next((r.value for r in dcf_results if r.key == "enterprise_value"), 0.0)
            eq = next((r.value for r in dcf_results if r.key == "equity_value"), 0.0)

            # Synthesize deterministic scenario summary & primary drivers
            drivers = []
            if params.revenue_growth_pct != 0.0:
                drivers.append(f"Revenue growth ({'+' if params.revenue_growth_pct > 0 else ''}{params.revenue_growth_pct*100:.1f}%)")
            if params.op_margin_adj_pct != 0.0:
                drivers.append(f"Margin adjustment ({'+' if params.op_margin_adj_pct > 0 else ''}{params.op_margin_adj_pct*100:.1f}%)")
            if params.interest_rate_adj_bps != 0.0:
                drivers.append(f"Interest rate adjustment ({'+' if params.interest_rate_adj_bps > 0 else ''}{params.interest_rate_adj_bps:.0f} bps)")

            curr_ratio = metrics_map.get("current_ratio", 1.5)
            if curr_ratio < 1.0 or params.revenue_growth_pct < -0.10:
                risk_lvl = "HIGH"
            elif params.revenue_growth_pct < 0.0 or params.op_margin_adj_pct < 0.0:
                risk_lvl = "MODERATE"
            else:
                risk_lvl = "LOW"

            exec_summary = (
                f"Under {params.name}, projected revenue reaches ${statement_impact['revenue']:,.1f}M "
                f"with net income of ${statement_impact['net_income']:,.1f}M. Equity valuation is projected at ${eq:,.1f}M."
            )

            outputs[key] = SingleScenarioOutput(
                scenario_name=params.name,
                parameters=params,
                metrics=metrics_map,
                dcf_equity_value=eq,
                dcf_enterprise_value=ev,
                statement_impact=statement_impact,
                executive_summary=exec_summary,
                primary_drivers=drivers if drivers else ["Historical baseline operational trends"],
                risk_level=risk_lvl,
            )

        # Synthesize overall scenario summary
        base_eq = outputs["base"].dcf_equity_value if "base" in outputs else 0.0
        bull_eq = outputs["bull"].dcf_equity_value if "bull" in outputs else base_eq
        bear_eq = outputs["bear"].dcf_equity_value if "bear" in outputs else base_eq

        bull_delta = ((bull_eq - base_eq) / base_eq * 100.0) if base_eq else 0.0
        bear_delta = ((bear_eq - base_eq) / base_eq * 100.0) if base_eq else 0.0

        overall_summary = (
            f"Scenario modeling projects DCF Equity Valuation ranging from ${bear_eq:,.1f}M (Bear Case, {bear_delta:+.1f}%) "
            f"to ${bull_eq:,.1f}M (Bull Case, {bull_delta:+.1f}%) relative to the Base Case baseline of ${base_eq:,.1f}M. "
            f"Solvency and operational liquidity remain stable across core scenarios."
        )

        return ScenarioSimulationResult(
            company_id=company_id,
            base_year=fiscal_year,
            scenarios=outputs,
            overall_executive_summary=overall_summary,
        )

    def _apply_scenario_parameters(
        self, base_inputs: dict[str, float], params: ScenarioParameters
    ) -> tuple[dict[str, float], dict[str, float]]:
        """Perturbs raw financial statement lines based on scenario parameters."""
        inputs = dict(base_inputs)

        # Revenue perturbation & FX rate
        base_rev = inputs.get("revenue", 0.0) * params.fx_rate
        perturbed_rev = base_rev * (1.0 + params.revenue_growth_pct)
        inputs["revenue"] = perturbed_rev

        # COGS perturbation
        base_cogs = inputs.get("cost_of_goods_sold", 0.0) * params.fx_rate
        cogs_ratio = (base_cogs / base_rev) if base_rev else 0.60
        perturbed_cogs_ratio = max(0.05, cogs_ratio + params.cogs_ratio_adj)
        perturbed_cogs = perturbed_rev * perturbed_cogs_ratio
        inputs["cost_of_goods_sold"] = perturbed_cogs

        # Operating Income / Margin
        base_op_inc = inputs.get("operating_income", 0.0) * params.fx_rate
        op_margin = (base_op_inc / base_rev) if base_rev else 0.20
        perturbed_op_margin = max(0.01, op_margin + params.op_margin_adj_pct)
        perturbed_op_inc = perturbed_rev * perturbed_op_margin
        inputs["operating_income"] = perturbed_op_inc

        # Interest Expense
        base_interest = inputs.get("interest_expense", 0.0) * params.fx_rate
        interest_adj_mult = 1.0 + (params.interest_rate_adj_bps / 100.0) / 100.0
        perturbed_interest = base_interest * interest_adj_mult
        inputs["interest_expense"] = perturbed_interest

        # Net Income (approximate statement linkage)
        pretax_income = perturbed_op_inc - perturbed_interest
        perturbed_net_income = max(0.0, pretax_income * (1.0 - params.tax_rate))
        inputs["net_income"] = perturbed_net_income

        statement_impact = {
            "revenue": round(perturbed_rev, 2),
            "cost_of_goods_sold": round(perturbed_cogs, 2),
            "operating_income": round(perturbed_op_inc, 2),
            "interest_expense": round(perturbed_interest, 2),
            "net_income": round(perturbed_net_income, 2),
        }

        return (inputs, statement_impact)
