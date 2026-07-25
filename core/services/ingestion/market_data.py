"""
Market Data Fetch Service
=========================
Fetches historical stock price data from Yahoo Finance via yfinance,
converts it into our normalized CSV format, saves to the data/ directory,
and returns metadata for the ingestion pipeline.

Supports: daily OHLCV (Open, High, Low, Close, Volume)
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


class MarketDataFetchResult:
    """Encapsulates the result of a market data fetch operation."""

    def __init__(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        csv_bytes: bytes,
        csv_filename: str,
        rows_fetched: int,
        saved_path: str,
        warnings: list[str],
    ):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date
        self.csv_bytes = csv_bytes
        self.csv_filename = csv_filename
        self.rows_fetched = rows_fetched
        self.saved_path = saved_path
        self.warnings = warnings


def fetch_market_data(
    ticker: str,
    start_date: date,
    end_date: date,
    storage_base: str = "./data",
) -> MarketDataFetchResult:
    """
    Fetch historical daily stock data from Yahoo Finance.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "AAPL", "MSFT").
    start_date : date
        Start of date range (inclusive).
    end_date : date
        End of date range (inclusive).
    storage_base : str
        Base path where CSVs are stored.

    Returns
    -------
    MarketDataFetchResult
        Contains the CSV bytes, saved path, and metadata.

    Raises
    ------
    ValueError
        If no data is returned by yfinance.
    """
    warnings: list[str] = []
    ticker_upper = ticker.upper().strip()

    logger.info(
        "Fetching market data for %s from %s to %s...",
        ticker_upper, start_date.isoformat(), end_date.isoformat(),
    )

    stock = yf.Ticker(ticker_upper)
    df = stock.history(
        start=start_date.isoformat(),
        end=end_date.isoformat(),
        auto_adjust=True,
    )

    if df.empty:
        raise ValueError(
            f"No market data returned for ticker '{ticker_upper}' "
            f"between {start_date} and {end_date}. "
            "Check that the ticker is valid and the date range contains trading days."
        )

    # Drop any rows with NaN close price
    df = df.dropna(subset=["Close"])

    if len(df) == 0:
        raise ValueError(f"All rows had NaN close prices for '{ticker_upper}'.")

    # Build our normalized CSV format:
    # metric_key, value, fiscal_year, fiscal_period, currency, section, date
    rows: list[dict] = []
    metrics_to_extract = [
        ("open_price", "Open"),
        ("high_price", "High"),
        ("low_price", "Low"),
        ("close_price", "Close"),
        ("trading_volume", "Volume"),
    ]

    for idx, row in df.iterrows():
        trade_date = idx.date() if hasattr(idx, "date") else idx
        trade_year = trade_date.year if hasattr(trade_date, "year") else 2024

        for metric_key, col_name in metrics_to_extract:
            if col_name in df.columns:
                val = row[col_name]
                if val is not None:
                    rows.append({
                        "metric_key": metric_key,
                        "value": str(round(float(val), 4) if metric_key != "trading_volume" else int(val)),
                        "fiscal_year": trade_year,
                        "fiscal_period": "FY",
                        "currency": "USD",
                        "section": "Market Data",
                        "date": str(trade_date),
                    })

    if not rows:
        raise ValueError(f"Could not extract any metrics from market data for '{ticker_upper}'.")

    # Write CSV bytes
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["metric_key", "value", "fiscal_year", "fiscal_period", "currency", "section", "date"])
    writer.writeheader()
    writer.writerows(rows)
    csv_content = output.getvalue()
    csv_bytes = csv_content.encode("utf-8")

    # Save to disk
    filename = f"{ticker_upper}_market_{start_date.isoformat()}_to_{end_date.isoformat()}.csv"
    save_dir = Path(storage_base) / "companies" / ticker_upper / "financials"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / filename
    save_path.write_bytes(csv_bytes)

    logger.info(
        "Market data for %s: %d rows fetched, %d trading days, saved to %s",
        ticker_upper, len(rows), len(df), save_path,
    )

    return MarketDataFetchResult(
        ticker=ticker_upper,
        start_date=start_date,
        end_date=end_date,
        csv_bytes=csv_bytes,
        csv_filename=filename,
        rows_fetched=len(rows),
        saved_path=str(save_path),
        warnings=warnings,
    )
