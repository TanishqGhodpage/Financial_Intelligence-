"""
Parser Plugin Registry
======================
Implements the Plugin Architecture for document ingestion.

Each file format (CSV, Excel, PDF, OCR image) has its own isolated parser
class conforming to AbstractParser. Parsers self-register via the
@parser_registry.register decorator, keyed to the MIME types they handle.

Adding a new parser (e.g. Word documents):
  1. Create a WordParser class inheriting AbstractParser.
  2. Decorate with @parser_registry.register(mime_types=["application/msword"]).
  No other files need to change.

Design:
  - Parsers return raw ParsedRow objects (not NormalizedMetric).
  - Normalisation is a separate stage (normalizer.py).
  - Parsers are stateless; all context is passed in parameters.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parsed Row (raw output from any parser)
# ---------------------------------------------------------------------------

@dataclass
class ParsedRow:
    """
    A single raw data point extracted from a document.
    Keys and values are unprocessed (raw strings from the source).
    The normalizer converts these into canonical NormalizedMetric entities.
    """

    raw_key: str                    # e.g. "Net Sales", "Total Revenue (USD)"
    raw_value: str                  # e.g. "98,456", "$1.2B"
    fiscal_year: int | None = None
    fiscal_period: str | None = None  # "FY", "Q1", "Q2", etc.
    currency_hint: str | None = None  # e.g. "USD", detected by parser
    page_number: int | None = None    # for PDF/image parsers
    section_hint: str | None = None   # e.g. "Income Statement"
    confidence: float = 1.0           # 0.0–1.0; lower for OCR-extracted values
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parser Result (collection of rows + metadata)
# ---------------------------------------------------------------------------

@dataclass
class ParserResult:
    """Aggregated output of a single parse operation."""

    rows: list[ParsedRow]
    parser_name: str
    source_filename: str
    duplicates_removed: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def avg_confidence(self) -> float:
        if not self.rows:
            return 0.0
        return round(sum(r.confidence for r in self.rows) / len(self.rows), 4)


# ---------------------------------------------------------------------------
# Abstract Parser
# ---------------------------------------------------------------------------

class AbstractParser(ABC):
    """
    Interface every document parser must implement.
    Parsers are stateless; instantiate once and call parse() many times.
    """

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Human-readable identifier, e.g. 'CSV Parser'."""
        ...

    @property
    @abstractmethod
    def supported_mime_types(self) -> list[str]:
        """List of MIME types this parser handles."""
        ...

    @abstractmethod
    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        fiscal_year: int | None = None,
        fiscal_period: str | None = None,
    ) -> ParserResult:
        """
        Parse raw file bytes and return a ParserResult.

        Parameters
        ----------
        file_bytes:
            Raw bytes of the uploaded file.
        filename:
            Original filename (used for type hints and logging).
        fiscal_year:
            Optional override for the fiscal year (if not embedded in the file).
        fiscal_period:
            Optional override for the fiscal period (e.g. "FY", "Q1").
        """
        ...


# ---------------------------------------------------------------------------
# Parser Registry
# ---------------------------------------------------------------------------

class _ParserRegistry:
    """
    Central registry mapping MIME types to parser instances.
    Parsers self-register via the @register decorator.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, AbstractParser] = {}

    def register(
        self,
        mime_types: list[str],
    ):
        """
        Decorator factory. Example usage:
            @parser_registry.register(mime_types=["text/csv"])
            class CSVParser(AbstractParser):
                ...
        """
        def decorator(cls: type[AbstractParser]) -> type[AbstractParser]:
            instance = cls()
            for mime in mime_types:
                if mime in self._parsers:
                    logger.warning(
                        "Parser registry: overwriting existing parser for MIME '%s' with %s.",
                        mime, cls.__name__,
                    )
                self._parsers[mime] = instance
                logger.debug("Registered parser %s for MIME '%s'.", cls.__name__, mime)
            return cls
        return decorator

    def get_parser(self, mime_type: str) -> AbstractParser:
        """
        Retrieve the registered parser for a given MIME type.
        Raises KeyError if no parser is registered for that type.
        """
        parser = self._parsers.get(mime_type)
        if parser is None:
            supported = list(self._parsers.keys())
            raise KeyError(
                f"No parser registered for MIME type '{mime_type}'. "
                f"Supported types: {supported}"
            )
        return parser

    def supported_types(self) -> list[str]:
        return list(self._parsers.keys())


# Global singleton
parser_registry = _ParserRegistry()
