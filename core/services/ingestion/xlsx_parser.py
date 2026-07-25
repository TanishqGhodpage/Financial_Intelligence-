"""
Excel Parser Plugin
===================
Handles ingestion of structured Excel financial statements (.xlsx / .xls).

Registered MIME types:
  application/vnd.openxmlformats-officedocument.spreadsheetml.sheet (.xlsx)
  application/vnd.ms-excel (.xls)

Behaviour:
  - Reads the first sheet by default.
  - Applies the same column validation and deduplication logic as CSV Parser.
  - Detects currency symbols in value cells and records as currency_hint.
  - Parentheses-negative format, e.g. (1,234) → -1234, is handled.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd

from core.services.ingestion.registry import (
    AbstractParser,
    ParsedRow,
    ParserResult,
    parser_registry,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"metric_key", "value", "fiscal_year", "fiscal_period"}
_CURRENCY_SYMBOLS: dict[str, str] = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def _clean_numeric_string(raw: str) -> str:
    """
    Cleans common financial formatting from value strings:
      - Removes currency symbols and thousands separators
      - Converts parentheses negatives: (1,234) → -1234
    """
    raw = raw.strip()
    # Parentheses negative
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    # Remove currency symbols and commas
    raw = re.sub(r"[$€£¥,]", "", raw)
    return raw.strip()


@parser_registry.register(
    mime_types=[
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ]
)
class ExcelParser(AbstractParser):
    """
    Excel parser for financial statements.
    Reads the first sheet; multi-sheet support can be added as a configuration option.
    """

    @property
    def parser_name(self) -> str:
        return "Excel Parser"

    @property
    def supported_mime_types(self) -> list[str]:
        return [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ]

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        fiscal_year: int | None = None,
        fiscal_period: str | None = None,
    ) -> ParserResult:
        warnings: list[str] = []

        try:
            df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
        except Exception as exc:
            raise ValueError(f"Could not read Excel file '{filename}': {exc}") from exc

        df.columns = [str(c).strip().lower() for c in df.columns]

        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"Excel file '{filename}' is missing required columns: {missing}."
            )

        rows: list[ParsedRow] = []
        seen: set[tuple] = set()
        duplicates = 0

        for idx, row in df.iterrows():
            raw_key = str(row["metric_key"]).strip()
            raw_value_str = str(row["value"]).strip()
            row_year = int(row["fiscal_year"]) if pd.notna(row.get("fiscal_year")) else fiscal_year
            row_period = str(row["fiscal_period"]).strip().upper() if pd.notna(row.get("fiscal_period")) else fiscal_period

            # Detect currency from value cell
            currency_hint = "USD"
            for symbol, code in _CURRENCY_SYMBOLS.items():
                if symbol in raw_value_str:
                    currency_hint = code
                    break
            if "currency" in df.columns and pd.notna(row.get("currency")):
                currency_hint = str(row["currency"]).strip().upper()

            section_hint = str(row.get("section", "")).strip() if "section" in df.columns else None
            cleaned_value = _clean_numeric_string(raw_value_str)

            if not raw_key or not cleaned_value:
                warnings.append(f"Row {idx}: empty metric_key or value — skipped.")
                continue

            identity = (raw_key.lower(), row_year, row_period)
            if identity in seen:
                duplicates += 1
                warnings.append(f"Row {idx}: duplicate ({raw_key}, {row_year}, {row_period}) — removed.")
                continue
            seen.add(identity)

            rows.append(
                ParsedRow(
                    raw_key=raw_key,
                    raw_value=cleaned_value,
                    fiscal_year=row_year,
                    fiscal_period=row_period,
                    currency_hint=currency_hint,
                    section_hint=section_hint or None,
                    confidence=1.0,
                )
            )

        return ParserResult(
            rows=rows,
            parser_name=self.parser_name,
            source_filename=filename,
            duplicates_removed=duplicates,
            warnings=warnings,
        )
