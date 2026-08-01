"""
Conflict Resolution Engine
==========================
Detects and resolves financial data conflicts when multiple documents
or data sources provide metrics for the same company, metric key,
and fiscal period.

Conflict Resolution Strategy:
1. Authority Ranking: Higher SourceAuthority weight takes precedence
   (SEC_FILING=1.0 > PRESS_RELEASE=0.85 > THIRD_PARTY_API=0.70 > NEWS=0.50).
2. Equal Authority: If source authorities are equal, higher confidence score wins.
3. Discrepancy Logging: Whenever values differ by > 0.1%, an audit warning is generated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.domain.entities import AuditAction, AuditLog, NormalizedMetric
from core.domain.value_objects import SourceAuthority

logger = logging.getLogger(__name__)


@dataclass
class ConflictResolutionResult:
    """Encapsulates the result of conflict resolution for a batch of metrics."""
    resolved_metrics: list[NormalizedMetric]
    conflicts_detected: int
    conflicts_resolved: int
    audit_logs: list[AuditLog]
    warnings: list[str]


class ConflictResolver:
    """
    Evaluates new incoming metrics against existing stored metrics for a company,
    resolving discrepancies based on source authority and confidence weighting.
    """

    AUTHORITY_WEIGHTS: dict[str, float] = {
        SourceAuthority.SEC_FILING.name: 1.00,
        SourceAuthority.EARNINGS_CALL.name: 0.90,
        SourceAuthority.PRESS_RELEASE.name: 0.85,
        SourceAuthority.THIRD_PARTY_API.name: 0.70,
        SourceAuthority.NEWS.name: 0.50,
        SourceAuthority.UNKNOWN.name: 0.40,
    }

    def resolve_conflicts(
        self,
        new_metrics: list[NormalizedMetric],
        existing_metrics: list[NormalizedMetric],
    ) -> ConflictResolutionResult:
        """
        Compare new_metrics with existing_metrics.
        Returns resolved list of metrics and audit logs.
        """
        conflicts_count = 0
        resolved_count = 0
        audit_logs: list[AuditLog] = []
        warnings: list[str] = []

        def _get_fp_type(fp: FiscalPeriod | None) -> str | None:
            if not fp or not fp.period_type:
                return None
            pt = fp.period_type
            return pt.value if isinstance(pt, Enum) else (pt.value if hasattr(pt, "value") else str(pt))

        # Index existing metrics by composite key: (metric_key, fiscal_year, fiscal_period)
        existing_map: dict[tuple[str, int | None, str | None], NormalizedMetric] = {}
        for em in existing_metrics:
            fp_year = em.fiscal_period.year if em.fiscal_period else None
            fp_type = _get_fp_type(em.fiscal_period)
            existing_map[(em.metric_key, fp_year, fp_type)] = em

        final_metrics: list[NormalizedMetric] = []

        for new_m in new_metrics:
            fp_year = new_m.fiscal_period.year if new_m.fiscal_period else None
            fp_type = _get_fp_type(new_m.fiscal_period)
            key = (new_m.metric_key, fp_year, fp_type)

            existing_m = existing_map.get(key)

            if existing_m is None:
                # No conflict — store directly
                final_metrics.append(new_m)
            else:
                # Conflict candidate — check if values differ meaningfully (> 0.1%)
                val_diff = abs(new_m.metric_value - existing_m.metric_value)
                rel_diff = val_diff / abs(existing_m.metric_value) if existing_m.metric_value != 0 else val_diff

                if rel_diff > 0.001:
                    conflicts_count += 1
                    # Conflict detected! Resolve based on Authority Weight & Confidence
                    new_weight = self.AUTHORITY_WEIGHTS.get(new_m.source_citation.get("source_authority", "UNKNOWN"), 0.40) * new_m.confidence.value
                    existing_weight = self.AUTHORITY_WEIGHTS.get(existing_m.source_citation.get("source_authority", "UNKNOWN"), 0.40) * existing_m.confidence.value

                    if new_weight >= existing_weight:
                        winner = new_m
                        loser = existing_m
                        winner_label = "NEW metric"
                    else:
                        winner = existing_m
                        loser = new_m
                        winner_label = "EXISTING metric"

                    resolved_count += 1
                    warn_msg = (
                        f"Conflict detected for '{new_m.metric_key}' ({fp_year} {fp_type}): "
                        f"New value {new_m.metric_value} vs Existing value {existing_m.metric_value}. "
                        f"Resolved to {winner_label} (Value: {winner.metric_value}) based on SourceAuthority."
                    )
                    logger.warning(warn_msg)
                    warnings.append(warn_msg)

                    audit = AuditLog(
                        action=AuditAction.CORRECTION,
                        entity_type="metric",
                        entity_id=winner.id,
                        description=warn_msg,
                        old_state={"value": loser.metric_value, "authority": loser.source_citation.get("source_authority")},
                        new_state={"value": winner.metric_value, "authority": winner.source_citation.get("source_authority")},
                    )
                    audit_logs.append(audit)
                    final_metrics.append(winner)
                else:
                    # Values are effectively identical
                    final_metrics.append(new_m)

        return ConflictResolutionResult(
            resolved_metrics=final_metrics,
            conflicts_detected=conflicts_count,
            conflicts_resolved=resolved_count,
            audit_logs=audit_logs,
            warnings=warnings,
        )
