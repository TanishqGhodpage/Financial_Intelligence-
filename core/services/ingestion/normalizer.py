"""
Financial Metric Normalizer
============================
Converts raw ParsedRow objects (from parsers) into canonical NormalizedMetric
entities using:

  1. Terminology Map (deterministic): maps synonyms to standard metric keys.
  2. Value Cleaner: converts string values to floats (handles B/M/K suffixes).
  3. Source Confidence Assignment: based on SourceAuthority enum.
  4. Conflict Detection: flags when two sources report different values for
     the same (company, metric, period) combination.

The normalizer is a pure domain service — no database calls inside.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.domain.entities import NormalizedMetric
from core.domain.value_objects import (
    ConfidenceScore,
    Currency,
    FiscalPeriod,
    FiscalPeriodType,
    SourceAuthority,
)
from core.services.ingestion.registry import ParsedRow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load Terminology Mappings
# ---------------------------------------------------------------------------

_MAPPINGS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "mappings.json"

def _load_mappings() -> dict[str, str]:
    """
    Load synonym→canonical mappings from configs/mappings.json.
    Falls back to hard-coded defaults if the file is not found.
    """
    if _MAPPINGS_PATH.exists():
        with _MAPPINGS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    logger.warning("mappings.json not found at %s — using built-in defaults.", _MAPPINGS_PATH)
    return _BUILTIN_MAPPINGS

_BUILTIN_MAPPINGS: dict[str, str] = {
    # Revenue
    "revenue": "revenue",
    "sales": "revenue",
    "net sales": "revenue",
    "total revenues": "revenue",
    "operating revenues": "revenue",
    "net revenues": "revenue",
    # COGS
    "cost of goods sold": "cost_of_goods_sold",
    "cost of sales": "cost_of_goods_sold",
    "cost of revenue": "cost_of_goods_sold",
    "cogs": "cost_of_goods_sold",
    # Operating Income
    "operating income": "operating_income",
    "operating profit": "operating_income",
    "ebit": "operating_income",
    "income from operations": "operating_income",
    # Net Income
    "net income": "net_income",
    "net profit": "net_income",
    "earnings": "net_income",
    "net earnings": "net_income",
    "profit for the year": "net_income",
    # EBITDA
    "ebitda": "ebitda",
    # Assets / Liabilities / Equity
    "total assets": "total_assets",
    "assets": "total_assets",
    "total liabilities": "total_liabilities",
    "liabilities": "total_liabilities",
    "total equity": "total_equity",
    "shareholders equity": "total_equity",
    "stockholders equity": "total_equity",
    "total stockholders equity": "total_equity",
    "current assets": "current_assets",
    "current liabilities": "current_liabilities",
    # Cash Flow
    "operating cash flow": "operating_cf",
    "net cash provided by operating activities": "operating_cf",
    "cash from operations": "operating_cf",
    "capital expenditures": "capex",
    "capex": "capex",
    "free cash flow": "free_cash_flow",
}

# Load mappings at module import time
_TERMINOLOGY_MAP: dict[str, str] = _load_mappings()


# ---------------------------------------------------------------------------
# Value Cleaner
# ---------------------------------------------------------------------------

_SCALE_SUFFIXES: dict[str, float] = {
    "t": 1e12,   # Trillion
    "b": 1e9,    # Billion
    "m": 1e6,    # Million
    "k": 1e3,    # Thousand
}

def _parse_numeric_value(raw_value: str) -> float:
    """
    Converts a raw string value to a float.
    Handles: commas, currency symbols, B/M/K/T suffixes, parentheses negatives.

    Examples:
      "98,456"   → 98456.0
      "$1.2B"    → 1_200_000_000.0
      "(500M)"   → -500_000_000.0
      "2.4T"     → 2_400_000_000_000.0
    """
    s = raw_value.strip()
    if not s:
        raise ValueError("Empty value string cannot be converted to float.")

    # Parentheses → negative
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True

    # Remove currency symbols and commas
    s = re.sub(r"[$€£¥,]", "", s)

    # Scale suffix
    scale = 1.0
    if s and s[-1].lower() in _SCALE_SUFFIXES:
        scale = _SCALE_SUFFIXES[s[-1].lower()]
        s = s[:-1]

    try:
        value = float(s) * scale
    except ValueError:
        raise ValueError(f"Cannot parse '{raw_value}' as a numeric financial value.") from None

    return -value if negative else value


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

class FinancialNormalizer:
    """
    Converts ParsedRow objects into NormalizedMetric entities.

    Workflow per row:
      1. Normalise metric_key via terminology map.
      2. Parse raw_value → float.
      3. Assign ConfidenceScore based on source authority.
      4. Detect conflicts against an existing metrics dict.
      5. Return a NormalizedMetric entity ready for persistence.
    """

    def __init__(
        self,
        terminology_map: dict[str, str] | None = None,
    ) -> None:
        self._map = terminology_map or _TERMINOLOGY_MAP

    def _normalize_key(self, raw_key: str) -> tuple[str, float]:
        """
        Returns (canonical_key, mapping_confidence).
        Falls back to a slug of the raw key with reduced confidence if unmapped.
        """
        lookup = raw_key.strip().lower()
        if lookup in self._map:
            return self._map[lookup], 1.0

        # Partial match attempt
        for synonym, canonical in self._map.items():
            if synonym in lookup:
                logger.debug("Partial match: '%s' → '%s' (via '%s').", raw_key, canonical, synonym)
                return canonical, 0.80

        # Unmapped: use slugified raw key
        slug = re.sub(r"\W+", "_", lookup).strip("_")
        logger.warning("Unmapped metric key '%s' → stored as '%s' with low confidence.", raw_key, slug)
        return slug, 0.50

    def normalize_row(
        self,
        row: ParsedRow,
        company_id: str,
        document_id: str,
        source_authority: SourceAuthority = SourceAuthority.UNKNOWN,
    ) -> NormalizedMetric | None:
        """
        Convert a single ParsedRow to a NormalizedMetric.
        Returns None if the value cannot be parsed (logged as a warning).
        """
        canonical_key, mapping_confidence = self._normalize_key(row.raw_key)

        try:
            float_value = _parse_numeric_value(row.raw_value)
        except ValueError as exc:
            logger.warning(
                "Could not parse value for key '%s' (raw: '%s'): %s",
                row.raw_key, row.raw_value, exc,
            )
            return None

        # Confidence = parser_confidence × source_authority × mapping_confidence
        parser_conf = ConfidenceScore(value=row.confidence)
        source_conf = ConfidenceScore.from_source_authority(source_authority)
        mapping_conf = ConfidenceScore(value=mapping_confidence)
        final_confidence = parser_conf.propagate(source_conf, mapping_conf)

        # Build FiscalPeriod value object
        fiscal_period: FiscalPeriod | None = None
        if row.fiscal_year and row.fiscal_period:
            try:
                period_type = FiscalPeriodType(row.fiscal_period.upper())
                fiscal_period = FiscalPeriod(year=row.fiscal_year, period_type=period_type)
            except ValueError:
                logger.warning("Unknown fiscal period type '%s' — storing without period.", row.fiscal_period)

        citation: dict[str, Any] = {
            "raw_key": row.raw_key,
            "raw_value": row.raw_value,
            "canonical_key": canonical_key,
            "mapping_confidence": mapping_confidence,
            "source_authority": source_authority.name,
        }
        if row.page_number is not None:
            citation["page"] = row.page_number
        if row.section_hint:
            citation["section"] = row.section_hint

        return NormalizedMetric(
            company_id=company_id,
            document_id=document_id,
            metric_key=canonical_key,
            metric_value=float_value,
            currency=Currency(row.currency_hint or "USD"),
            fiscal_period=fiscal_period,
            confidence=final_confidence,
            source_citation=citation,
        )

    def normalize_batch(
        self,
        rows: list[ParsedRow],
        company_id: str,
        document_id: str,
        source_authority: SourceAuthority = SourceAuthority.UNKNOWN,
    ) -> tuple[list[NormalizedMetric], list[str]]:
        """
        Normalise a list of ParsedRows.
        Returns (normalised_metrics, list_of_warning_messages).
        """
        metrics: list[NormalizedMetric] = []
        warnings: list[str] = []
        seen: dict[tuple, NormalizedMetric] = {}

        for row in rows:
            metric = self.normalize_row(row, company_id, document_id, source_authority)
            if metric is None:
                warnings.append(f"Could not normalise row: raw_key='{row.raw_key}', raw_value='{row.raw_value}'")
                continue

            key = (metric.metric_key, metric.fiscal_period)
            if key in seen:
                # Conflict detection: same metric, same period, different value
                existing = seen[key]
                if abs(existing.metric_value - metric.metric_value) / max(abs(existing.metric_value), 1) > 0.01:
                    msg = (
                        f"Conflict detected for '{metric.metric_key}' "
                        f"({metric.fiscal_period}): "
                        f"{existing.metric_value} vs {metric.metric_value}. "
                        f"Higher-confidence value retained."
                    )
                    warnings.append(msg)
                    logger.warning(msg)
                    # Retain the higher-confidence value
                    if metric.confidence.value > existing.confidence.value:
                        seen[key] = metric
                continue

            seen[key] = metric

        metrics = list(seen.values())
        return metrics, warnings
