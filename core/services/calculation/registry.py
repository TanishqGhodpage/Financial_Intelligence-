"""
Financial Metric Registry
=========================
Central registry holding declarative MetricDefinition objects.

Each MetricDefinition carries full metadata (business description,
formula display, structured references) so the CalculationEngine can
produce self-documenting CalculationResults without per-metric UI code.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque

from core.services.calculation.engine import MetricDefinition

logger = logging.getLogger(__name__)


def safe_divide(num: float, den: float, error_msg: str) -> float:
    if not den:
        raise ZeroDivisionError(error_msg)
    return num / den


class MetricRegistry:
    def __init__(self) -> None:
        self._metrics: dict[str, MetricDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        defaults = [
            # ---------------------------------------------------------------
            # PROFITABILITY
            # ---------------------------------------------------------------
            MetricDefinition(
                key="gross_profit_margin",
                name="Gross Profit Margin",
                category="profitability",
                dependencies=["revenue", "cost_of_goods_sold"],
                unit="percentage",
                description=(
                    "Measures the percentage of revenue retained after deducting "
                    "direct production costs (COGS). Indicates core pricing power "
                    "and production efficiency."
                ),
                formula_display="(Revenue - Cost of Goods Sold) / Revenue",
                formula=lambda i, ctx: safe_divide(
                    i["revenue"] - i["cost_of_goods_sold"],
                    i["revenue"],
                    "Revenue is zero",
                ),
                references=[
                    {"source": "GAAP", "title": "Income Statement Analysis", "section": "Gross Profit"},
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Profitability Ratios"},
                ],
            ),
            MetricDefinition(
                key="operating_margin",
                name="Operating Margin",
                category="profitability",
                dependencies=["revenue", "operating_income"],
                unit="percentage",
                description=(
                    "Measures the proportion of revenue remaining after covering "
                    "operating expenses (COGS + SG&A + R&D). Reflects operational "
                    "efficiency independent of capital structure and tax regime."
                ),
                formula_display="Operating Income / Revenue",
                formula=lambda i, ctx: safe_divide(
                    i["operating_income"], i["revenue"], "Revenue is zero"
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Operating Efficiency"},
                ],
            ),
            MetricDefinition(
                key="net_profit_margin",
                name="Net Profit Margin",
                category="profitability",
                dependencies=["revenue", "net_income"],
                unit="percentage",
                description=(
                    "Measures the percentage of revenue that becomes net income "
                    "after all expenses, interest, and taxes. The bottom-line "
                    "profitability indicator."
                ),
                formula_display="Net Income / Revenue",
                formula=lambda i, ctx: safe_divide(
                    i["net_income"], i["revenue"], "Revenue is zero"
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Bottom-Line Profitability"},
                ],
            ),
            MetricDefinition(
                key="return_on_equity",
                name="Return on Equity (ROE)",
                category="profitability",
                dependencies=["net_income", "total_equity"],
                unit="percentage",
                description=(
                    "Measures management's ability to generate returns on "
                    "shareholders' invested capital. A key metric for comparing "
                    "profitability across companies with different capital structures."
                ),
                formula_display="Net Income / Total Shareholders' Equity",
                formula=lambda i, ctx: safe_divide(
                    i["net_income"], i["total_equity"], "Total Equity is zero"
                ),
                references=[
                    {"source": "CFA Institute", "title": "Equity Analysis", "section": "Return on Equity"},
                    {"source": "Damodaran", "title": "Investment Valuation", "section": "ROE Decomposition"},
                ],
            ),
            MetricDefinition(
                key="return_on_assets",
                name="Return on Assets (ROA)",
                category="profitability",
                dependencies=["net_income", "total_assets"],
                unit="percentage",
                description=(
                    "Measures how efficiently a company uses its total asset base "
                    "to generate profit. Useful for capital-intensive industries."
                ),
                formula_display="Net Income / Total Assets",
                formula=lambda i, ctx: safe_divide(
                    i["net_income"], i["total_assets"], "Total Assets is zero"
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Asset Utilization"},
                ],
            ),

            # ---------------------------------------------------------------
            # LIQUIDITY
            # ---------------------------------------------------------------
            MetricDefinition(
                key="current_ratio",
                name="Current Ratio",
                category="liquidity",
                dependencies=["current_assets", "current_liabilities"],
                unit="ratio",
                description=(
                    "Measures short-term solvency by comparing current assets to "
                    "current liabilities. A ratio above 1.0 indicates the company "
                    "can cover near-term obligations."
                ),
                formula_display="Current Assets / Current Liabilities",
                formula=lambda i, ctx: safe_divide(
                    i["current_assets"],
                    i["current_liabilities"],
                    "Current Liabilities is zero",
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Liquidity Ratios"},
                ],
            ),
            MetricDefinition(
                key="quick_ratio",
                name="Quick Ratio",
                category="liquidity",
                dependencies=["current_assets", "current_liabilities", "inventory"],
                unit="ratio",
                description=(
                    "A stricter liquidity measure that excludes inventory from "
                    "current assets, since inventory may not be quickly convertible "
                    "to cash. Also known as the Acid-Test Ratio."
                ),
                formula_display="(Current Assets - Inventory) / Current Liabilities",
                formula=lambda i, ctx: safe_divide(
                    i["current_assets"] - i["inventory"],
                    i["current_liabilities"],
                    "Current Liabilities is zero",
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Acid-Test Ratio"},
                    {"source": "Corporate Finance Institute", "title": "Quick Ratio Guide"},
                ],
            ),

            # ---------------------------------------------------------------
            # LEVERAGE
            # ---------------------------------------------------------------
            MetricDefinition(
                key="debt_to_equity",
                name="Debt-to-Equity Ratio",
                category="leverage",
                dependencies=["short_term_debt", "long_term_debt", "total_equity"],
                unit="ratio",
                description=(
                    "Measures financial leverage using ONLY interest-bearing debt "
                    "(short-term + long-term). Excludes trade payables, deferred "
                    "revenue, and other non-debt liabilities. The conventional "
                    "leverage metric used by CFA, Damodaran, and enterprise "
                    "financial systems."
                ),
                formula_display="(Short-Term Debt + Long-Term Debt) / Total Shareholders' Equity",
                formula=lambda i, ctx: safe_divide(
                    i["short_term_debt"] + i["long_term_debt"],
                    i["total_equity"],
                    "Total Equity is zero",
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Leverage Ratios"},
                    {"source": "Damodaran", "title": "Investment Valuation", "section": "Debt-to-Equity"},
                    {"source": "Corporate Finance Institute", "title": "Debt-to-Equity Ratio"},
                    {"source": "Investopedia", "title": "Debt-to-Equity Ratio Definition"},
                ],
            ),
            MetricDefinition(
                key="liabilities_to_equity",
                name="Liabilities-to-Equity Ratio",
                category="leverage",
                dependencies=["total_liabilities", "total_equity"],
                unit="ratio",
                description=(
                    "Measures total liabilities (including trade payables, deferred "
                    "revenue, and all other obligations) relative to shareholders' "
                    "equity. A broader leverage measure than Debt-to-Equity."
                ),
                formula_display="Total Liabilities / Total Shareholders' Equity",
                formula=lambda i, ctx: safe_divide(
                    i["total_liabilities"],
                    i["total_equity"],
                    "Total Equity is zero",
                ),
                references=[
                    {"source": "CFA Institute", "title": "Financial Statement Analysis", "section": "Total Leverage"},
                    {"source": "Corporate Finance Institute", "title": "Liabilities-to-Equity Ratio"},
                    {"source": "IFRS", "title": "Financial Statement Analysis"},
                ],
            ),
            MetricDefinition(
                key="interest_coverage",
                name="Interest Coverage Ratio",
                category="leverage",
                dependencies=["operating_income", "interest_expense"],
                unit="ratio",
                description=(
                    "Measures how easily a company can pay interest on outstanding "
                    "debt from operating earnings. A ratio below 1.5 is generally "
                    "considered a warning signal."
                ),
                formula_display="Operating Income / Interest Expense",
                formula=lambda i, ctx: safe_divide(
                    i["operating_income"],
                    i["interest_expense"],
                    "Interest Expense is zero",
                ),
                references=[
                    {"source": "CFA Institute", "title": "Fixed Income Analysis", "section": "Coverage Ratios"},
                    {"source": "Corporate Finance Institute", "title": "Interest Coverage Ratio"},
                ],
            ),

            # ---------------------------------------------------------------
            # CASH FLOW
            # ---------------------------------------------------------------
            MetricDefinition(
                key="free_cash_flow",
                name="Free Cash Flow",
                category="cash_flow",
                dependencies=["operating_cf", "capex"],
                unit="absolute",
                description=(
                    "Cash generated by operations minus capital expenditures. "
                    "Represents cash available for debt repayment, dividends, "
                    "buybacks, and reinvestment."
                ),
                formula_display="Operating Cash Flow - Capital Expenditures",
                formula=lambda i, ctx: i["operating_cf"] - abs(i["capex"]),
                references=[
                    {"source": "CFA Institute", "title": "Equity Valuation", "section": "Free Cash Flow"},
                    {"source": "Damodaran", "title": "Investment Valuation", "section": "FCFF & FCFE"},
                ],
            ),
            # Note: DCF metrics are generated by the Valuation Strategy directly, not here.
        ]
        for metric in defaults:
            self.register(metric)

    def register(self, metric: MetricDefinition) -> None:
        if metric.key in self._metrics:
            logger.warning("Overwriting existing metric for key '%s'.", metric.key)
        self._metrics[metric.key] = metric

    def get_metric(self, key: str) -> MetricDefinition | None:
        return self._metrics.get(key)

    def list_metrics(self) -> list[dict]:
        """Returns metadata about all registered metrics for API consumption."""
        return [
            {
                "key": m.key,
                "name": m.name,
                "category": m.category,
                "unit": m.unit,
                "description": m.description,
                "formula_display": m.formula_display,
                "dependencies": m.dependencies,
                "references": m.references,
                "version": m.version_number,
            }
            for m in self._metrics.values()
        ]

    def topological_order(self) -> list[str]:
        in_degree: dict[str, int] = defaultdict(int)
        graph: dict[str, list[str]] = defaultdict(list)

        for key, metric in self._metrics.items():
            in_degree.setdefault(key, 0)
            for dep in metric.dependencies:
                if dep in self._metrics:
                    graph[dep].append(key)
                    in_degree[key] += 1

        queue = deque(k for k, d in in_degree.items() if d == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbour in graph[node]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        return order


metric_registry = MetricRegistry()
