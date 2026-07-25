"""
OpenRouter AI Provider Adapter
================================
Implements ExtractionProviderPort for Phase 3 AI-powered document extraction.

Model Fallback Strategy:
  Models are tried in the order defined in settings.OPENROUTER_MODELS.
  If a model hits its rate limit (429), quota (402), or is unavailable (503),
  the next model in the list is tried automatically.

  Current fallback chain (configured in .env):
    1. nvidia/nemotron-3-ultra-550b-a55b:free   ← Primary
    2. poolside/laguna-m.1:free                  ← Fallback

OpenRouter is fully OpenAI-compatible, so we use the openai library
pointed at the OpenRouter base URL.

Phase 1: This adapter is NOT called for CSV/Excel (parsers handle those).
Phase 3: Called for PDF text extraction and image OCR tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy import — openai is only needed for Phase 3 PDF/image extraction
try:
    from openai import OpenAI, RateLimitError, APIStatusError
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    logger.warning(
        "openai package not installed — OpenRouter extraction unavailable. "
        "Install with: pip install openai"
    )


RETRYABLE_STATUS_CODES = {
    429,  # Rate limit
    402,  # Quota exceeded
    503,  # Service unavailable
    502,  # Bad gateway (model loading)
}

_EXTRACTION_SYSTEM_PROMPT = """
You are a precise financial data extraction assistant.
Given a financial document excerpt, extract all financial metrics you find.
Return ONLY a JSON array in this exact format:
[
  {
    "metric_key": "<canonical_name>",
    "raw_value": "<numeric_string>",
    "fiscal_year": <int_or_null>,
    "fiscal_period": "<FY|Q1|Q2|Q3|Q4|null>",
    "currency": "<USD|EUR|GBP|etc>",
    "section": "<Income Statement|Balance Sheet|Cash Flow|Other>",
    "confidence": <0.0_to_1.0>
  }
]
Use canonical metric keys: revenue, net_income, operating_income, ebitda,
total_assets, total_liabilities, total_equity, operating_cf, capex, free_cash_flow, etc.
Return ONLY the JSON array, no other text.
""".strip()


class OpenRouterProvider:
    """
    OpenRouter AI extraction provider with automatic model fallback.
    
    Usage:
        provider = OpenRouterProvider()
        metrics = provider.extract_from_text("Revenue: $394.3B, Net Income: $93.7B...")
    """

    def __init__(self) -> None:
        from configs.settings import get_settings
        self.settings = get_settings()
        self._models: list[str] = self.settings.openrouter_model_list
        self._client: Optional["OpenAI"] = None

        if not self._models:
            raise ValueError("No OpenRouter models configured. Check OPENROUTER_MODELS in .env")

        logger.info(
            "OpenRouter provider initialized. Fallback chain: %s",
            " → ".join(self._models),
        )

    def _get_client(self) -> "OpenAI":
        if not _OPENAI_AVAILABLE:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )
        if self._client is None:
            self._client = OpenAI(
                api_key=self.settings.openrouter_api_key,
                base_url=self.settings.openrouter_base_url,
                default_headers={
                    "HTTP-Referer": "https://financial-intelligence-platform.local",
                    "X-Title": "Financial Intelligence Platform",
                },
            )
        return self._client

    def _call_model(self, model: str, text: str) -> str:
        """
        Makes a single completion request to a specific model.
        Returns the raw response text.
        Raises:
            RateLimitError / APIStatusError for retryable failures.
        """
        client = self._get_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract financial metrics from this text:\n\n{text[:8000]}"},
            ],
            temperature=0.0,       # Deterministic extraction
            max_tokens=2048,
            response_format={"type": "text"},
        )
        return response.choices[0].message.content or ""

    def extract_from_text(self, text: str) -> tuple[list[dict], str]:
        """
        Extract financial metrics from raw text using the model fallback chain.

        Returns:
            (list_of_metric_dicts, model_used)
            
        Each dict has keys: metric_key, raw_value, fiscal_year, fiscal_period,
        currency, section, confidence.

        Raises:
            RuntimeError if all models in the fallback chain are exhausted.
        """
        last_error: Optional[Exception] = None

        for idx, model in enumerate(self._models):
            try:
                logger.info(
                    "Attempting extraction with model [%d/%d]: %s",
                    idx + 1, len(self._models), model,
                )
                raw_response = self._call_model(model, text)

                # Parse JSON response
                # Strip any markdown code fences the model might add
                raw_response = raw_response.strip()
                if raw_response.startswith("```"):
                    raw_response = "\n".join(
                        line for line in raw_response.split("\n")
                        if not line.startswith("```")
                    )

                metrics = json.loads(raw_response)
                if not isinstance(metrics, list):
                    raise ValueError(f"Expected JSON array, got {type(metrics)}")

                logger.info(
                    "Extraction successful with model '%s': %d metrics found.",
                    model, len(metrics),
                )
                return metrics, model

            except Exception as exc:
                # Determine if this is a retryable error (quota/rate limit)
                is_retryable = False
                if _OPENAI_AVAILABLE:
                    if isinstance(exc, RateLimitError):
                        is_retryable = True
                    elif isinstance(exc, APIStatusError):
                        is_retryable = exc.status_code in RETRYABLE_STATUS_CODES

                if is_retryable and idx < len(self._models) - 1:
                    next_model = self._models[idx + 1]
                    logger.warning(
                        "Model '%s' hit limit (%s). Falling back to '%s'.",
                        model, type(exc).__name__, next_model,
                    )
                    last_error = exc
                    continue
                elif isinstance(exc, (json.JSONDecodeError, ValueError)):
                    # Parse error — log but try next model
                    logger.warning(
                        "Model '%s' returned unparseable response: %s. Trying next model.",
                        model, exc,
                    )
                    last_error = exc
                    if idx < len(self._models) - 1:
                        continue
                else:
                    # Non-retryable (bad input, auth error, etc.)
                    logger.error("Non-retryable error from model '%s': %s", model, exc)
                    raise

        raise RuntimeError(
            f"All {len(self._models)} models in the fallback chain were exhausted. "
            f"Last error: {last_error}"
        )

    def health_check(self) -> dict:
        """
        Lightweight check: verifies OpenRouter connectivity with a tiny prompt.
        Returns status dict with model, latency, and reachability.
        """
        import time
        results = []
        for model in self._models:
            start = time.monotonic()
            try:
                self._call_model(model, "Return the JSON array: []")
                latency_ms = round((time.monotonic() - start) * 1000)
                results.append({"model": model, "status": "ok", "latency_ms": latency_ms})
            except Exception as exc:
                results.append({"model": model, "status": "error", "error": str(exc)})
        return {
            "provider": "openrouter",
            "fallback_chain": self._models,
            "models": results,
        }
