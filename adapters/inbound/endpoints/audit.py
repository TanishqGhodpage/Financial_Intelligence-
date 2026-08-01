"""
Audit Logs API Endpoints
========================
Provides read access to the system's immutable audit log records.
Supports filtering by entity_type, action, and entity_id.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import AuditLogORM

router = APIRouter()


class AuditLogResponse(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str
    description: Optional[str]
    old_state: Optional[dict]
    new_state: Optional[dict]
    timestamp: str


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    entity_type: Optional[str] = Query(None, description="Filter by entity type (document, metric, company)"),
    action: Optional[str] = Query(None, description="Filter by audit action (INGESTION, NORMALIZATION, CORRECTION)"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogResponse]:
    """
    Retrieve system audit logs ordered by timestamp descending.
    """
    stmt = select(AuditLogORM).order_by(AuditLogORM.timestamp.desc()).limit(limit)

    if entity_type:
        stmt = stmt.where(AuditLogORM.entity_type == entity_type)
    if action:
        stmt = stmt.where(AuditLogORM.action == action.upper())

    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        AuditLogResponse(
            id=log.id,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            description=log.description,
            old_state=log.old_state,
            new_state=log.new_state,
            timestamp=log.timestamp.isoformat() if log.timestamp else "",
        )
        for log in logs
    ]
