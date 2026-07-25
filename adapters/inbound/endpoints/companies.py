"""
Companies Endpoints
===================
CRUD API for tracked financial entities (companies).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import yfinance as yf
import logging

logger = logging.getLogger(__name__)

from adapters.outbound.postgres.connection import get_db
from adapters.outbound.postgres.schema import CompanyORM
from core.domain.entities import Company
from core.domain.value_objects import Currency

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas (Pydantic I/O)
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12, examples=["AAPL"])


class CompanyResponse(BaseModel):
    id: str
    ticker: str
    name: str
    sector: Optional[str]
    industry: Optional[str]
    currency: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _orm_to_response(orm: CompanyORM) -> CompanyResponse:
    return CompanyResponse(
        id=orm.id,
        ticker=orm.ticker,
        name=orm.name,
        sector=orm.sector,
        industry=orm.industry,
        currency=orm.currency,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Register a new company for financial tracking."""

    # Check for duplicate ticker
    ticker_upper = payload.ticker.upper().strip()
    result = await db.execute(
        select(CompanyORM).where(CompanyORM.ticker == ticker_upper)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Company with ticker '{ticker_upper}' already exists.",
        )

    # Fetch data from yfinance
    try:
        stock = yf.Ticker(ticker_upper)
        info = stock.info
        name = info.get("longName") or info.get("shortName") or ticker_upper
        sector = info.get("sector") or "Unknown"
        industry = info.get("industry") or "Unknown"
        currency = info.get("financialCurrency") or info.get("currency") or "USD"
        currency = currency.upper()
    except Exception as e:
        logger.warning(f"Failed to fetch yfinance data for {ticker_upper}: {e}")
        name = ticker_upper
        sector = "Unknown"
        industry = "Unknown"
        currency = "USD"

    # Build domain entity (validates invariants)
    entity = Company(
        ticker=ticker_upper,
        name=name,
        sector=sector,
        industry=industry,
        currency=Currency(currency),
    )

    orm = CompanyORM(
        id=entity.id,
        ticker=entity.ticker,
        name=entity.name,
        sector=entity.sector or None,
        industry=entity.industry or None,
        currency=entity.currency.code,
    )
    db.add(orm)
    await db.flush()
    return _orm_to_response(orm)


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
) -> list[CompanyResponse]:
    """List all registered companies."""
    result = await db.execute(select(CompanyORM).order_by(CompanyORM.ticker))
    return [_orm_to_response(c) for c in result.scalars().all()]


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    """Retrieve a company by ID."""
    result = await db.execute(
        select(CompanyORM).where(CompanyORM.id == company_id)
    )
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    return _orm_to_response(company)
