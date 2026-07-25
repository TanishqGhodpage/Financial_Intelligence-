"""
CSV Parser Plugin
=================
Handles ingestion of structured CSV financial statements.

Registered MIME types: text/csv, application/csv

Assumptions:
  - CSV file contains at minimum these columns (case-insensitive):
      metric_key | value | fiscal_year | fiscal_period
  - Additional optional columns: currency, section
  - Duplicate (metric_key, fiscal_year, fiscal_period) rows are removed
    and counted for audit purposes.
  - Numeric values may include commas, dollar signs, or parentheses for
    negatives — these are cleaned but not converted (normalizer handles that).
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from core.services.ingestion.registry import (
    AbstractParser,
    ParsedRow,
    ParserResult,
    parser_registry,
)

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"metric_key", "value", "fiscal_year", "fiscal_period"}


@parser_registry.register(mime_types=["text/csv", "application/csv"])
class CSVParser(AbstractParser):
    """
    Structured CSV parser for financial statements.
    Expects a normalized column layout from analysts or finance teams.
    """

    @property
    def parser_name(self) -> str:
        return "CSV Parser"

    @property
    def supported_mime_types(self) -> list[str]:
        return ["text/csv", "application/csv"]

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        fiscal_year: int | None = None,
        fiscal_period: str | None = None,
    ) -> ParserResult:
        warnings: list[str] = []

        try:
            df = pd.read_csv(io.BytesIO(file_bytes))
        except Exception as exc:
            raise ValueError(f"Could not read CSV file '{filename}': {exc}") from exc

        # Normalise column names (lowercase, strip whitespace)
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Validate required columns
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV file '{filename}' is missing required columns: {missing}. "
                f"Found columns: {list(df.columns)}"
            )

        rows: list[ParsedRow] = []
        seen: set[tuple] = set()
        duplicates = 0

        for idx, row in df.iterrows():
            raw_key = str(row["metric_key"]).strip()
            raw_value = str(row["value"]).strip()
            row_year = int(row["fiscal_year"]) if pd.notna(row["fiscal_year"]) else fiscal_year
            row_period = str(row["fiscal_period"]).strip().upper() if pd.notna(row["fiscal_period"]) else fiscal_period
            currency_hint = str(row.get("currency", "USD")).strip().upper() if "currency" in df.columns else "USD"
            section_hint = str(row.get("section", "")).strip() if "section" in df.columns else None

            if not raw_key or not raw_value:
                warnings.append(f"Row {idx}: empty metric_key or value — skipped.")
                continue

            # Deduplication check
            identity = (raw_key.lower(), row_year, row_period)
            if identity in seen:
                duplicates += 1
                warnings.append(f"Row {idx}: duplicate ({raw_key}, {row_year}, {row_period}) — removed.")
                continue
            seen.add(identity)

            rows.append(
                ParsedRow(
                    raw_key=raw_key,
                    raw_value=raw_value,
                    fiscal_year=row_year,
                    fiscal_period=row_period,
                    currency_hint=currency_hint,
                    section_hint=section_hint or None,
                    confidence=1.0,  # CSV is structured — fully reliable
                )
            )

        if warnings:
            for w in warnings:
                logger.warning("[CSVParser] %s", w)

        return ParserResult(
            rows=rows,
            parser_name=self.parser_name,
            source_filename=filename,
            duplicates_removed=duplicates,
            warnings=warnings,
        )
