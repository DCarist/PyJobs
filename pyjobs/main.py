from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pyjobs.database import SessionLocal, init_db
from pyjobs.dependencies import (
    PROJECT_ROOT,
    STATIC_DIR,
    TEMPLATES_DIR,
    get_db,
    templates,
)
from pyjobs.routers import applications, companies, discovery, jobs, profiles, resumes
from pyjobs.services.scheduler import start_scheduler, stop_scheduler
from pyjobs.services.scraper import fetch_jobs

# Initialize database tables and schema migrations
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("PYJOBS_TESTING"):
        start_scheduler(SessionLocal)
    yield
    if not os.environ.get("PYJOBS_TESTING"):
        stop_scheduler()


app = FastAPI(title="PyJobs", version="0.2.2", lifespan=lifespan)

# Ensure required directories exist
(TEMPLATES_DIR / "partials").mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount static asset delivery
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register domain router controllers
app.include_router(discovery.router)
app.include_router(jobs.router)
app.include_router(profiles.router)
app.include_router(applications.router)
app.include_router(resumes.router)
app.include_router(companies.router)

# Re-exports for backward compatibility
__all__ = ["app", "get_db", "fetch_jobs", "templates", "PROJECT_ROOT"]
