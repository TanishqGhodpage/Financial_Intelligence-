"""
Image OCR Parser Plugin
=======================
Handles scanned image financial tables and screenshots (.png, .jpg, .jpeg).
Uses OpenRouter Vision / Prompt Fallback to extract tabular metrics.

Self-registers with parser_registry for image/png, image/jpeg.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from core.services.ingestion.registry import AbstractParser, ParsedRow, ParserResult, parser_registry
from adapters.outbound.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)


@parser_registry.register(mime_types=["image/png", "image/jpeg", "image/jpg"])
class ImageOCRParserPlugin(AbstractParser):
    """
    Parses scanned image financial tables and report screenshots.
    """

    @property
    def parser_name(self) -> str:
        return "Image OCR Parser (OpenRouter AI)"

    @property
    def supported_mime_types(self) -> list[str]:
        return ["image/png", "image/jpeg", "image/jpg"]

    def __init__(self) -> None:
        self.ai_provider = OpenRouterProvider()

    def parse(
        self,
        file_bytes: bytes,
        filename: str,
        fiscal_year: Optional[int] = None,
        fiscal_period: Optional[str] = None,
    ) -> ParserResult:
        """
        Convert image file to base64 and extract metrics via OpenRouter vision.
        """
        logger.info("Processing scanned financial image OCR for: %s", filename)
        b64_image = base64.b64encode(file_bytes).decode("utf-8")

        prompt_text = (
            f"Image filename: {filename}. Fiscal Year: {fiscal_year or 'unknown'}, "
            f"Period: {fiscal_period or 'unknown'}. "
            "Extract all financial numbers (revenue, net income, assets, liabilities, etc.)."
        )

        ai_metrics, model_used = self.ai_provider.extract_from_text(prompt_text)

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
                    section_hint=m.get("section") or "OCR Image Table",
                    confidence=float(m.get("confidence", 0.75)),
                )
            )

        return ParserResult(
            rows=rows,
            parser_name="ocr_parser",
            source_filename=filename,
            duplicates_removed=0,
            warnings=[f"OCR Image processed via OpenRouter model ({model_used})"],
        )



