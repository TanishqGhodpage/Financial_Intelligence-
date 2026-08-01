import logging
from typing import Optional
import yfinance as yf
from datetime import datetime

from core.domain.entities import NormalizedMetric
from core.domain.value_objects import ConfidenceScore, Currency, FiscalPeriod, FiscalPeriodType

logger = logging.getLogger(__name__)

async def auto_ingest_financials(company_id: str, ticker: str, start_year: int, end_year: int, fiscal_period: str = "FY") -> list[NormalizedMetric]:
    """
    Fetches the latest financial statements from yfinance, maps them to internal metrics,
    and stores them as NormalizedMetricORM.
    """
    logger.info(f"Auto-ingesting financials for {ticker}")
    stock = yf.Ticker(ticker)
    
    if fiscal_period == "FY":
        financials = stock.financials
        balance_sheet = stock.balance_sheet
        valid_fin_dates = [d for d in financials.columns if start_year <= d.year <= end_year]
        valid_bs_dates = [d for d in balance_sheet.columns if start_year <= d.year <= end_year]
    else:
        financials = stock.quarterly_financials
        balance_sheet = stock.quarterly_balance_sheet
        # Map Q1=March, Q2=June, Q3=Sept, Q4=Dec
        target_month = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}.get(fiscal_period)
        if target_month:
            valid_fin_dates = [d for d in financials.columns if start_year <= d.year <= end_year and d.month == target_month]
            valid_bs_dates = [d for d in balance_sheet.columns if start_year <= d.year <= end_year and d.month == target_month]
        else:
            valid_fin_dates = [d for d in financials.columns if start_year <= d.year <= end_year]
            valid_bs_dates = [d for d in balance_sheet.columns if start_year <= d.year <= end_year]

    if financials.empty or balance_sheet.empty:
        raise ValueError(f"No {fiscal_period} financial data available on Yahoo Finance for {ticker}.")
    
    if not valid_fin_dates:
        raise ValueError(f"No income statement data available for {ticker} between {start_year} and {end_year}.")
    if not valid_bs_dates:
        raise ValueError(f"No balance sheet data available for {ticker} between {start_year} and {end_year}.")
    
    # Simple mapping from yfinance keys to internal keys
    fin_mapping = {
        "Total Revenue": "revenue",
        "Cost Of Revenue": "cost_of_goods_sold",
        "Operating Income": "operating_income",
        "Net Income": "net_income",
        "Interest Expense": "interest_expense",
    }
    
    bs_mapping = {
        "Total Assets": "total_assets",
        "Total Liabilities Net Minority Interest": "total_liabilities",
        "Stockholders Equity": "total_equity",
        "Current Assets": "current_assets",
        "Current Liabilities": "current_liabilities",
        "Current Debt": "short_term_debt",
        "Long Term Debt": "long_term_debt",
        "Inventory": "inventory",
    }

    cf_mapping = {
        "Operating Cash Flow": "operating_cf",
        "Capital Expenditure": "capex",
        "Free Cash Flow": "free_cash_flow",
    }

    metrics_to_add = []
    
    def _add_metric(key: str, value: float, year: int):
        if value is not None and not (isinstance(value, float) and value != value): # skip NaN
            fp = FiscalPeriod(year=year, period_type=FiscalPeriodType(fiscal_period))
            metric = NormalizedMetric(
                company_id=company_id,
                metric_key=key,
                metric_value=float(value),
                currency=Currency.usd(),
                fiscal_period=fp,
                confidence=ConfidenceScore.certain(),
                source_citation={"source": "yfinance", "ticker": ticker, "date": str(year)}
            )
            metrics_to_add.append(metric)

    # Process Income Statement for each valid year
    for fin_date in valid_fin_dates:
        year = fin_date.year
        for yf_key, internal_key in fin_mapping.items():
            if yf_key in financials.index:
                val = financials.loc[yf_key, fin_date]
                _add_metric(internal_key, val, year)

    # Process Balance Sheet for each valid year
    for bs_date in valid_bs_dates:
        bs_year = bs_date.year
        for yf_key, internal_key in bs_mapping.items():
            if yf_key in balance_sheet.index:
                val = balance_sheet.loc[yf_key, bs_date]
                _add_metric(internal_key, val, bs_year)

    # Process Cash Flow Statement for each valid year
    try:
        if fiscal_period == "FY":
            cashflow = stock.cashflow
        else:
            cashflow = stock.quarterly_cashflow
        if not cashflow.empty:
            valid_cf_dates = [d for d in cashflow.columns if start_year <= d.year <= end_year]
            for cf_date in valid_cf_dates:
                cf_year = cf_date.year
                for yf_key, internal_key in cf_mapping.items():
                    if yf_key in cashflow.index:
                        val = cashflow.loc[yf_key, cf_date]
                        _add_metric(internal_key, val, cf_year)
    except Exception as e:
        logger.warning(f"Cash flow data not available for {ticker}: {e}")

    if not metrics_to_add:
        raise ValueError("Could not extract any mapped financial metrics.")

    logger.info(f"Auto-ingested {len(metrics_to_add)} metrics for {ticker}")
    return metrics_to_add
