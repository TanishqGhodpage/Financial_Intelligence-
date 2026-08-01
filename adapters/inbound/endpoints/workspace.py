"""
Decision Workspace Endpoints
============================
Provides REST endpoints for persisting workspace session state,
saving comparison cohorts, and managing analyst decision notes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import (
    AnalystNoteORM,
    SavedComparisonORM,
    WorkspaceStateORM,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class WorkspaceStatePayload(BaseModel):
    selected_company_ids: list[str] = Field(default_factory=list)
    active_filters: dict = Field(default_factory=dict)
    bookmarks: list[str] = Field(default_factory=list)
    layout_config: dict = Field(default_factory=dict)


class SavedComparisonCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company_ids: list[str] = Field(..., min_items=1)
    fiscal_year: Optional[int] = 2024
    fiscal_period: str = "FY"


class AnalystNoteCreate(BaseModel):
    company_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspace State Endpoints
# ---------------------------------------------------------------------------

@router.get("/state")
async def get_workspace_state(
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retrieves the persisted workspace session state."""
    result = await db.execute(
        select(WorkspaceStateORM).where(WorkspaceStateORM.user_id == user_id)
    )
    state = result.scalar_one_or_none()
    if not state:
        return {
            "user_id": user_id,
            "selected_company_ids": [],
            "active_filters": {},
            "bookmarks": [],
            "layout_config": {},
        }
    return {
        "id": state.id,
        "user_id": state.user_id,
        "selected_company_ids": state.selected_company_ids,
        "active_filters": state.active_filters,
        "bookmarks": state.bookmarks,
        "layout_config": state.layout_config,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


@router.post("/state")
async def save_workspace_state(
    payload: WorkspaceStatePayload,
    user_id: str = "default_user",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Saves or updates workspace session state."""
    result = await db.execute(
        select(WorkspaceStateORM).where(WorkspaceStateORM.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.selected_company_ids = payload.selected_company_ids
        existing.active_filters = payload.active_filters
        existing.bookmarks = payload.bookmarks
        existing.layout_config = payload.layout_config
        existing.updated_at = datetime.now(timezone.utc)
        target = existing
    else:
        target = WorkspaceStateORM(
            id=str(uuid.uuid4()),
            user_id=user_id,
            selected_company_ids=payload.selected_company_ids,
            active_filters=payload.active_filters,
            bookmarks=payload.bookmarks,
            layout_config=payload.layout_config,
        )
        db.add(target)

    await db.flush()
    return {
        "status": "saved",
        "user_id": user_id,
        "selected_company_ids": target.selected_company_ids,
    }


# ---------------------------------------------------------------------------
# Saved Comparisons Endpoints
# ---------------------------------------------------------------------------

@router.get("/comparisons")
async def list_saved_comparisons(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Lists all saved comparison cohorts."""
    result = await db.execute(
        select(SavedComparisonORM).order_by(SavedComparisonORM.created_at.desc())
    )
    comparisons = result.scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "company_ids": c.company_ids,
            "fiscal_year": c.fiscal_year,
            "fiscal_period": c.fiscal_period,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in comparisons
    ]


@router.post("/comparisons", status_code=status.HTTP_201_CREATED)
async def create_saved_comparison(
    payload: SavedComparisonCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Saves a comparison cohort."""
    orm = SavedComparisonORM(
        id=str(uuid.uuid4()),
        name=payload.name,
        company_ids=payload.company_ids,
        fiscal_year=payload.fiscal_year,
        fiscal_period=payload.fiscal_period,
    )
    db.add(orm)
    await db.flush()
    return {
        "id": orm.id,
        "name": orm.name,
        "company_ids": orm.company_ids,
        "created_at": orm.created_at.isoformat() if orm.created_at else None,
    }


@router.delete("/comparisons/{comparison_id}")
async def delete_saved_comparison(
    comparison_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deletes a saved comparison cohort."""
    result = await db.execute(
        select(SavedComparisonORM).where(SavedComparisonORM.id == comparison_id)
    )
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="Saved comparison not found.")
    await db.delete(comp)
    await db.flush()
    return {"status": "deleted", "id": comparison_id}


# ---------------------------------------------------------------------------
# Analyst Notes Endpoints
# ---------------------------------------------------------------------------

@router.get("/notes")
async def list_analyst_notes(
    company_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Lists analyst decision notes."""
    query = select(AnalystNoteORM).order_by(AnalystNoteORM.created_at.desc())
    if company_id:
        query = query.where(AnalystNoteORM.company_id == company_id)

    result = await db.execute(query)
    notes = result.scalars().all()
    return [
        {
            "id": n.id,
            "company_id": n.company_id,
            "author": n.author,
            "title": n.title,
            "content": n.content,
            "tags": n.tags,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None,
        }
        for n in notes
    ]


@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def create_analyst_note(
    payload: AnalystNoteCreate,
    author: str = "analyst",
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Creates a new analyst decision note."""
    orm = AnalystNoteORM(
        id=str(uuid.uuid4()),
        company_id=payload.company_id,
        author=author,
        title=payload.title,
        content=payload.content,
        tags=payload.tags,
    )
    db.add(orm)
    await db.flush()
    return {
        "id": orm.id,
        "company_id": orm.company_id,
        "title": orm.title,
        "content": orm.content,
        "created_at": orm.created_at.isoformat() if orm.created_at else None,
    }


@router.delete("/notes/{note_id}")
async def delete_analyst_note(
    note_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deletes an analyst note."""
    result = await db.execute(
        select(AnalystNoteORM).where(AnalystNoteORM.id == note_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Analyst note not found.")
    await db.delete(note)
    await db.flush()
    return {"status": "deleted", "id": note_id}
