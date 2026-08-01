"""
PDF Filing Parser Plugin
========================
Extracts text and financial tables from PDF files (e.g. SEC 10-K, 10-Q filings,
annual reports) and passes excerpts to the OpenRouter AI extraction provider.

Model Fallback Strategy:
  1. nvidia/nemotron-3-ultra-550b-a55b:free (Primary)
  2. poolside/laguna-m.1:free (Fallback)

Self-registers with parser_registry for application/pdf.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import pypdf

from core.domain.entities import NormalizedMetric
from core.domain.value_objects import ConfidenceScore, Currency, FiscalPeriod, FiscalPeriodType, SourceAuthority
from core.services.ingestion.registry import AbstractParser, ParsedRow, ParserResult, parser_registry
from adapters.outbound.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


@parser_registry.register(mime_types=["application/pdf"])
class PDFParserPlugin(AbstractParser):
    """
    Parses PDF financial documents using pypdf for text extraction
    and OpenRouter AI for structured metric extraction.
    """

    @property
    def parser_name(self) -> str:
        return "PDF Filing Parser (OpenRouter AI)"

    @property
    def supported_mime_types(self) -> list[str]:
        return ["application/pdf"]

    def __init__(self) -> None:
        self.ai_provider = OpenRouterProvider()

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[str] = None,
    ) -> ParseResult:
        """
        Extract text from PDF pages and run AI metric extraction.
        """
        logger.info("Extracting text from PDF filing: %s", filename)
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        num_pages = len(reader.pages)

        # Extract text from pages
        text_content = ""
        for idx in range(min(num_pages, 20)):  # Extract up to first 20 pages
            page = reader.pages[idx]
            extracted = page.extract_text() or ""
            text_content += f"\n--- PAGE {idx + 1} ---\n" + extracted

        if not text_content.strip():
            raise ValueError(f"Could not extract readable text from PDF '{filename}'. Is it a scanned image?")

        # Call OpenRouter fallback chain
        logger.info("Sending PDF text to OpenRouter AI model fallback chain...")
        ai_metrics, model_used = self.ai_provider.extract_from_text(text_content)

        # Convert AI JSON output to ParsedRow format
        rows: list[ParsedRow] = []
        for m in ai_metrics:
            raw_val = m.get("raw_value") or m.get("value")
            if raw_val is None:
                continue

            rows.append(
                ParsedRow(
                    raw_key=str(m.get("metric_key", "unknown")),
                    raw_value=str(raw_val),
                    fiscal_year=m.get("fiscal_year") or fiscal_year,
                    fiscal_period=m.get("fiscal_period") or fiscal_period,
                    currency_hint=m.get("currency") or "USD",
                    section_hint=m.get("section") or "PDF Table",
                    confidence=float(m.get("confidence", 0.85)),
                )
            )

        logger.info("PDF Parsing complete for %s. %d metrics extracted via %s.", filename, len(rows), model_used)

        return ParserResult(
            rows=rows,
            parser_name="pdf_parser",
            source_filename=filename,
            duplicates_removed=0,
            warnings=[f"Extracted via OpenRouter AI model ({model_used})"],
        )



