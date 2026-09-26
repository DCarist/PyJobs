from __future__ import annotations

import datetime
import os
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import markdown
from fastapi import FastAPI, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from pyjobs.database import SessionLocal
from pyjobs.models import (
    JobApplication,
    Resume,
    SavedJob,
    SearchProfile,
)
from pyjobs.services.locations import canonicalize_location
from pyjobs.services.resume_parser import score_resume_match

# Workspace directory paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


def render_markdown(text: str | None) -> str:
    """Renders job description markdown/plain-text into formatted HTML."""
    if not text:
        return ""
    # Strip backslash escapes before markdown punctuation and symbols (e.g. \-, \&, \*, \_)
    cleaned = re.sub(r"\\([-_*#&`~\[\]()])", r"\1", text)
    return markdown.markdown(
        cleaned,
        extensions=["extra", "nl2br", "sane_lists"],
    )


class WorkSearchLogEntry(TypedDict):
    date: datetime.date
    activity_type: str
    company: str
    title: str
    method: str
    portal_account: bool
    portal_username: str | None
    confirmation: str | None
    status: str
    notes: str


# Pre-configured Jinja2 templates instance
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["render_markdown"] = render_markdown


def get_upload_dir(app_instance: FastAPI | None = None) -> Path:
    """Returns the storage path for resume uploads, supporting test overrides."""
    if app_instance and hasattr(app_instance.state, "upload_dir") and app_instance.state.upload_dir:
        p = Path(app_instance.state.upload_dir)
    else:
        custom_dir = os.environ.get("PYJOBS_UPLOAD_DIR")
        if custom_dir:
            p = Path(custom_dir)
        else:
            p = PROJECT_ROOT / "uploads" / "resumes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db() -> Generator[Session]:
    """Yields a database session guaranteed to close on completion."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def find_matching_resumes(
    db: Session, job_title: str, job_description: str | None = None
) -> list[tuple[Resume, float]]:
    """Returns resumes scored and ordered by match relevance to the given job."""
    resumes = db.query(Resume).all()
    scored: list[tuple[Resume, float]] = []
    for r in resumes:
        if not r.versions:
            continue
        score = score_resume_match(r.title, r.tags, job_title, job_description)
        if score > 0.0:
            scored.append((r, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


def get_tracked_applications_map(db: Session) -> dict[int, JobApplication]:
    """Returns a mapping of saved_job_id -> JobApplication for quickly checking track status."""
    apps = db.query(JobApplication).filter(JobApplication.saved_job_id.isnot(None)).all()
    return {app.saved_job_id: app for app in apps if app.saved_job_id is not None}


def get_week_ending(d: datetime.date) -> datetime.date:
    """Calculates the Saturday week-ending date for unemployment reporting."""
    days_ahead = (5 - d.weekday()) % 7
    return d + datetime.timedelta(days=days_ahead)


@dataclass
class CurationFilters:
    q: str
    sort: str
    seniority: list[str]
    salary_bracket: list[str]
    include_unspecified: bool
    site: list[str]
    date_range: str
    show_hidden: bool
    group_by: str
    profile_id: list[int]
    staleness: str
    exclude_tracked: bool

    def jobs(self, db: Session) -> list[SavedJob]:
        return query_filtered_jobs(
            db,
            q=self.q,
            sort=self.sort,
            seniority=self.seniority,
            salary_bracket=self.salary_bracket,
            include_unspecified=self.include_unspecified,
            site=self.site,
            date_range=self.date_range,
            show_hidden=self.show_hidden,
            profile_id=self.profile_id,
            staleness=self.staleness,
            exclude_tracked=self.exclude_tracked,
        )


def get_curation_filters(
    request: Request,
    q: str = "",
    sort: str = "newest",
    seniority: list[str] = Query(default=[]),
    salary_bracket: list[str] = Query(default=[]),
    include_unspecified: bool = True,
    site: list[str] = Query(default=[]),
    date_range: str = "all",
    show_hidden: bool = False,
    group_by: str = "none",
    profile_id: list[int] = Query(default=[]),
    staleness: str = "all",
    exclude_tracked: bool | None = None,
) -> CurationFilters:
    if exclude_tracked is None:
        cookie = request.cookies.get("pyjobs_exclude_tracked", "")
        exclude_tracked = cookie.lower() in ("true", "1")
    return CurationFilters(
        q,
        sort,
        seniority,
        salary_bracket,
        include_unspecified,
        site,
        date_range,
        show_hidden,
        group_by,
        profile_id,
        staleness,
        exclude_tracked,
    )


def query_filtered_jobs(
    db: Session,
    q: str = "",
    sort: str = "newest",
    seniority: list[str] | None = None,
    salary_bracket: list[str] | None = None,
    include_unspecified: bool = True,
    site: list[str] | None = None,
    date_range: str = "all",
    show_hidden: bool = False,
    profile_id: list[int] | None = None,
    staleness: str = "all",
    exclude_tracked: bool = False,
) -> list[SavedJob]:
    """Queries saved jobs applying active text, seniority, salary, site, and profile filters."""
    query = db.query(SavedJob)

    if not show_hidden:
        query = query.filter(SavedJob.is_hidden.is_(False))
    else:
        query = query.filter(SavedJob.is_hidden.is_(True))

    if exclude_tracked:
        tracked_urls = db.query(JobApplication.job_url).filter(
            JobApplication.job_url.isnot(None),
            JobApplication.job_url != "",
        )
        query = query.filter(
            ~SavedJob.applications.any(),
            or_(
                SavedJob.job_url.is_(None),
                SavedJob.job_url == "",
                ~SavedJob.job_url.in_(tracked_urls),
            ),
        )

    if profile_id:
        query = query.filter(SavedJob.search_profiles.any(SearchProfile.id.in_(profile_id)))

    if staleness == "active_only":
        query = query.filter(SavedJob.is_stale.is_(False))
    elif staleness == "stale_only":
        query = query.filter(SavedJob.is_stale.is_(True))

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SavedJob.title.ilike(term),
                SavedJob.company.ilike(term),
                SavedJob.description.ilike(term),
                SavedJob.location.ilike(term),
            )
        )

    if seniority:
        query = query.filter(SavedJob.seniority_level.in_(seniority))

    if salary_bracket:
        selected = set(salary_bracket)
        if include_unspecified:
            selected.add("Unspecified")
        query = query.filter(SavedJob.salary_bracket.in_(selected))

    if site:
        query = query.filter(SavedJob.site.in_(site))

    if date_range and date_range != "all":
        now = datetime.datetime.now(datetime.UTC)
        cutoff = None
        if date_range == "24h":
            cutoff = now - datetime.timedelta(days=1)
        elif date_range == "3d":
            cutoff = now - datetime.timedelta(days=3)
        elif date_range == "7d":
            cutoff = now - datetime.timedelta(days=7)
        elif date_range == "14d":
            cutoff = now - datetime.timedelta(days=14)
        elif date_range == "30d":
            cutoff = now - datetime.timedelta(days=30)
        if cutoff:
            query = query.filter(SavedJob.date_posted >= cutoff)

    # Apply sorting
    if sort == "oldest":
        query = query.order_by(SavedJob.date_posted.asc().nullslast(), SavedJob.id.asc())
    elif sort == "salary_desc":
        query = query.order_by(
            SavedJob.max_salary.desc().nullslast(), SavedJob.min_salary.desc().nullslast()
        )
    elif sort == "salary_asc":
        query = query.order_by(
            SavedJob.min_salary.asc().nullslast(), SavedJob.max_salary.asc().nullslast()
        )
    elif sort == "company":
        query = query.order_by(SavedJob.company.asc())
    elif sort == "title":
        query = query.order_by(SavedJob.title.asc())
    else:  # newest default
        query = query.order_by(SavedJob.date_posted.desc().nullslast(), SavedJob.id.desc())

    return query.all()


def group_jobs(jobs: list[SavedJob], group_by: str) -> dict[str, list[SavedJob]]:
    """Organizes jobs into categorized groups for collapsible accordion display."""
    if not group_by or group_by == "none":
        return {}

    groups: dict[str, list[SavedJob]] = {}
    for job in jobs:
        if group_by == "company":
            key = job.company.strip() if job.company else "Unknown Company"
        elif group_by == "location":
            key = canonicalize_location(job.location or "") or "Unknown Location"
        elif group_by == "seniority":
            key = job.seniority_level or "Specialist / Contributor"
        elif group_by == "salary_bracket":
            key = job.salary_bracket or "Unspecified"
        elif group_by == "date_posted":
            key = job.date_posted.strftime("%B %d, %Y") if job.date_posted else "Undated Postings"
        else:
            key = "All Jobs"

        groups.setdefault(key, []).append(job)

    # Sort groups alphabetically, placing 'Unspecified' or 'Unknown' at the end
    def sort_key(item: tuple[str, list[SavedJob]]) -> tuple[bool, str]:
        name = item[0]
        is_unknown = any(w in name.lower() for w in ["unknown", "unspecified", "undated"])
        return (is_unknown, name.lower())

    return dict(sorted(groups.items(), key=sort_key))
