"""
FastAPI Application Entry Point
================================
Initializes the FastAPI app, registers routers, and configures
startup events (e.g., database table creation).
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from adapters.outbound.postgres.connection import create_tables
from adapters.inbound.endpoints import companies, documents, analytics, jobs, audit, comparison, workspace, modeling
from configs.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Enterprise-grade Financial Intelligence Platform. "
        "Transforms fragmented financial data into trusted, explainable, "
        "decision-ready intelligence."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in Phase 8 with RBAC
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(companies.router, prefix="/api/v1/companies", tags=["Companies"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit Logs"])
app.include_router(comparison.router, prefix="/api/v1/comparison", tags=["Comparative Analytics"])
app.include_router(workspace.router, prefix="/api/v1/workspace", tags=["Decision Workspace"])
app.include_router(modeling.router, prefix="/api/v1/modeling", tags=["Financial Modeling Suite"])

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup() -> None:
    logging.getLogger(__name__).info("Starting %s v%s...", settings.app_name, settings.app_version)
    await create_tables()
    logging.getLogger(__name__).info("Database tables ready.")


@app.get("/api/health", tags=["System"])
async def health_check() -> dict:
    return {"status": "ok", "version": settings.app_version}


# ---------------------------------------------------------------------------
# Static frontend — mounted last so API routes take priority
# ---------------------------------------------------------------------------
_frontend_dir = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)

try:
    if os.path.isdir(_frontend_dir):
        app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
        logging.getLogger(__name__).info("Serving frontend from: %s", _frontend_dir)
    else:
        logging.getLogger(__name__).warning(
            "Frontend directory not found at %s — visit /api/docs for the API.", _frontend_dir
        )
except Exception as e:
    logging.getLogger(__name__).error("Could not mount frontend: %s", e)
