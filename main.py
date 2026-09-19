from __future__ import annotations

import datetime
import io
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypedDict

import markdown
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import SessionLocal, init_db
from models import (
    ApplicationActivity,
    ApplicationContact,
    JobApplication,
    Resume,
    ResumeVersion,
    SavedJob,
    SearchProfile,
    UserPreference,
)
from resume_parser import (
    convert_docx_to_pdf,
    extract_text,
    generate_download_filename,
    score_resume_match,
)
from scheduler import start_scheduler, stop_scheduler
from scraper import check_job_url_liveness, evaluate_job_staleness, fetch_jobs
from task_manager import get_task, launch_scrape_task


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


# Create DB tables and apply column additions
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("PYJOBS_TESTING"):
        start_scheduler(SessionLocal)
    yield
    if not os.environ.get("PYJOBS_TESTING"):
        stop_scheduler()


app = FastAPI(title="PyJobs", version="0.1.0", lifespan=lifespan)

# Ensure directories exist
os.makedirs("templates/partials", exist_ok=True)
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["render_markdown"] = render_markdown


def get_upload_dir(app_instance: FastAPI | None = None) -> Path:
    """Returns the storage path for resume uploads, supporting test overrides."""
    if app_instance and hasattr(app_instance.state, "upload_dir") and app_instance.state.upload_dir:
        p = Path(app_instance.state.upload_dir)
    else:
        p = Path(os.environ.get("PYJOBS_UPLOAD_DIR", "uploads/resumes"))
    p.mkdir(parents=True, exist_ok=True)
    return p


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


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tracked_applications_map(db: Session) -> dict[int, JobApplication]:
    """Returns a mapping of saved_job_id -> JobApplication for quickly checking track status."""
    apps = db.query(JobApplication).filter(JobApplication.saved_job_id.isnot(None)).all()
    return {app.saved_job_id: app for app in apps if app.saved_job_id is not None}


def get_week_ending(d: datetime.date) -> datetime.date:
    """Calculates the Saturday week-ending date for unemployment reporting."""
    days_ahead = (5 - d.weekday()) % 7
    return d + datetime.timedelta(days=days_ahead)


def query_filtered_jobs(
    db: Session,
    q: str = "",
    sort: str = "newest",
    seniority: str = "all",
    salary_bracket: str = "all",
    include_unspecified: bool = True,
    site: str = "all",
    date_range: str = "all",
    show_hidden: bool = False,
    profile_id: str | int = "all",
    staleness: str = "all",
) -> list[SavedJob]:
    """Queries saved jobs applying active text, seniority, salary, site, and profile filters."""
    query = db.query(SavedJob)

    if not show_hidden:
        query = query.filter(SavedJob.is_hidden.is_(False))
    else:
        query = query.filter(SavedJob.is_hidden.is_(True))

    if profile_id and str(profile_id) != "all":
        try:
            pid = int(profile_id)
            query = query.filter(SavedJob.search_profiles.any(SearchProfile.id == pid))
        except ValueError:
            pass

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

    if seniority and seniority != "all":
        query = query.filter(SavedJob.seniority_level == seniority)

    if salary_bracket and salary_bracket != "all":
        if include_unspecified:
            query = query.filter(
                or_(
                    SavedJob.salary_bracket == salary_bracket,
                    SavedJob.salary_bracket == "Unspecified",
                )
            )
        else:
            query = query.filter(SavedJob.salary_bracket == salary_bracket)

    if site and site != "all":
        query = query.filter(SavedJob.site == site)

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
            key = job.location.strip() if job.location else "Unknown Location"
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    if not profiles:
        pref = db.query(UserPreference).first()
        now_utc = datetime.datetime.now(datetime.UTC)
        default_profile = SearchProfile(
            name="Primary Search",
            positions=pref.positions if pref else "",
            fields=pref.fields if pref else "",
            location=pref.location if pref else "",
            sites=pref.sites if pref else "linkedin,indeed,google",
            is_remote=pref.is_remote if pref else False,
            distance_miles=50,
            results_wanted=25,
            created_at=now_utc,
        )
        db.add(default_profile)
        db.commit()
        db.refresh(default_profile)
        profiles = [default_profile]

    active_profile = profiles[0]

    # Immediately load existing saved jobs on launch so the user is in curation mode
    jobs = (
        db.query(SavedJob)
        .filter(SavedJob.is_hidden.is_(False))
        .order_by(SavedJob.date_posted.desc().nullslast(), SavedJob.id.desc())
        .all()
    )
    tracked_map = get_tracked_applications_map(db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "profiles": profiles,
            "active_profile": active_profile,
            "jobs": jobs,
            "total_jobs_count": len(jobs),
            "group_by": "none",
            "active_page": "curation",
            "tracked_map": tracked_map,
        },
    )


@app.get("/jobs/filter", response_class=HTMLResponse)
async def filter_jobs(
    request: Request,
    q: str = "",
    sort: str = "newest",
    seniority: str = "all",
    salary_bracket: str = "all",
    include_unspecified: bool = True,
    site: str = "all",
    date_range: str = "all",
    show_hidden: bool = False,
    group_by: str = "none",
    profile_id: str = "all",
    staleness: str = "all",
    db: Session = Depends(get_db),
):
    jobs = query_filtered_jobs(
        db=db,
        q=q,
        sort=sort,
        seniority=seniority,
        salary_bracket=salary_bracket,
        include_unspecified=include_unspecified,
        site=site,
        date_range=date_range,
        show_hidden=show_hidden,
        profile_id=profile_id,
        staleness=staleness,
    )
    grouped = group_jobs(jobs, group_by=group_by)
    tracked_map = get_tracked_applications_map(db)
    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": jobs,
            "grouped_jobs": grouped,
            "group_by": group_by,
            "show_hidden": show_hidden,
            "tracked_map": tracked_map,
        },
    )


@app.get("/jobs/export")
async def export_jobs(
    format: str = "csv",
    q: str = "",
    sort: str = "newest",
    seniority: str = "all",
    salary_bracket: str = "all",
    include_unspecified: bool = True,
    site: str = "all",
    date_range: str = "all",
    show_hidden: bool = False,
    profile_id: str = "all",
    staleness: str = "all",
    db: Session = Depends(get_db),
):
    jobs = query_filtered_jobs(
        db=db,
        q=q,
        sort=sort,
        seniority=seniority,
        salary_bracket=salary_bracket,
        include_unspecified=include_unspecified,
        site=site,
        date_range=date_range,
        show_hidden=show_hidden,
        profile_id=profile_id,
        staleness=staleness,
    )

    data = [
        {
            "Title": j.title,
            "Company": j.company,
            "Location": j.location,
            "Seniority": j.seniority_level,
            "Salary Bracket": j.salary_bracket,
            "Salary Stated": j.salary_source or "Not specified",
            "Min Annual Salary": j.min_salary,
            "Max Annual Salary": j.max_salary,
            "Site": j.site.capitalize() if j.site else "",
            "Date Posted": j.date_posted.strftime("%Y-%m-%d") if j.date_posted else "",
            "URL": j.job_url,
        }
        for j in jobs
    ]
    df = pd.DataFrame(data)

    if format == "json":
        return Response(
            content=df.to_json(orient="records", indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="curated_jobs.json"'},
        )
    elif format == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")  # ty: ignore[invalid-argument-type]
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="curated_jobs.xlsx"'},
        )
    else:  # default csv
        return Response(
            content=df.to_csv(index=False),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="curated_jobs.csv"'},
        )


# ==============================================================================
# Search Profiles Endpoints
# ==============================================================================


@app.get("/profiles/sidebar", response_class=HTMLResponse)
async def get_profiles_sidebar(
    request: Request,
    profile_selector: str | None = None,
    new: bool = False,
    db: Session = Depends(get_db),
):
    profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    if not profiles:
        default_p = SearchProfile(name="Primary Search")
        db.add(default_p)
        db.commit()
        db.refresh(default_p)
        profiles = [default_p]

    is_new = new or (profile_selector == "new")
    active_profile = None
    if not is_new:
        if profile_selector and profile_selector.isdigit():
            active_profile = (
                db.query(SearchProfile).filter(SearchProfile.id == int(profile_selector)).first()
            )
        if not active_profile and profiles:
            active_profile = profiles[0]

    return templates.TemplateResponse(
        request=request,
        name="partials/profile_sidebar.html",
        context={
            "profiles": profiles,
            "active_profile": active_profile,
            "is_new": is_new,
        },
    )


@app.post("/profiles", response_class=HTMLResponse)
async def create_search_profile(
    request: Request,
    name: str = Form("New Profile"),
    positions: str = Form(""),
    fields: str = Form(""),
    location: str = Form(""),
    sites: list[str] = Form(default=[]),
    is_remote: bool = Form(default=False),
    distance_miles: int = Form(default=50),
    results_wanted: int = Form(default=25),
    refresh_interval_hours: int = Form(default=0),
    refresh_on_launch: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    sites_str = ",".join(sites) if sites else "linkedin,indeed,google"
    new_profile = SearchProfile(
        name=name.strip() or "Untitled Profile",
        positions=positions.strip(),
        fields=fields.strip(),
        location=location.strip(),
        sites=sites_str,
        is_remote=is_remote,
        distance_miles=distance_miles,
        results_wanted=results_wanted,
        refresh_interval_hours=refresh_interval_hours,
        refresh_on_launch=refresh_on_launch,
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="partials/profile_sidebar.html",
        context={
            "profiles": profiles,
            "active_profile": new_profile,
            "is_new": False,
            "message": f"Profile '{new_profile.name}' created successfully!",
        },
    )


@app.post("/profiles/{id}", response_class=HTMLResponse)
async def update_search_profile(
    request: Request,
    id: int,
    name: str = Form(""),
    positions: str = Form(""),
    fields: str = Form(""),
    location: str = Form(""),
    sites: list[str] = Form(default=[]),
    is_remote: bool = Form(default=False),
    distance_miles: int = Form(default=50),
    results_wanted: int = Form(default=25),
    refresh_interval_hours: int = Form(default=0),
    refresh_on_launch: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    profile = db.query(SearchProfile).filter(SearchProfile.id == id).first()
    if not profile:
        return HTMLResponse("<div class='error-msg'>Profile not found.</div>", status_code=404)

    sites_str = ",".join(sites) if sites else "linkedin,indeed,google"
    profile.name = name.strip() or profile.name
    profile.positions = positions.strip()
    profile.fields = fields.strip()
    profile.location = location.strip()
    profile.sites = sites_str
    profile.is_remote = is_remote
    profile.distance_miles = distance_miles
    profile.results_wanted = results_wanted
    profile.refresh_interval_hours = refresh_interval_hours
    profile.refresh_on_launch = refresh_on_launch
    db.commit()

    profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="partials/profile_sidebar.html",
        context={
            "profiles": profiles,
            "active_profile": profile,
            "is_new": False,
            "message": f"Profile '{profile.name}' updated successfully!",
        },
    )


@app.delete("/profiles/{id}", response_class=HTMLResponse)
async def delete_search_profile(request: Request, id: int, db: Session = Depends(get_db)):
    profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    if len(profiles) <= 1:
        return templates.TemplateResponse(
            request=request,
            name="partials/profile_sidebar.html",
            context={
                "profiles": profiles,
                "active_profile": profiles[0],
                "is_new": False,
                "message": "Cannot delete the only remaining profile.",
            },
        )

    profile = db.query(SearchProfile).filter(SearchProfile.id == id).first()
    if profile:
        db.delete(profile)
        db.commit()

    updated_profiles = db.query(SearchProfile).order_by(SearchProfile.id.asc()).all()
    return templates.TemplateResponse(
        request=request,
        name="partials/profile_sidebar.html",
        context={
            "profiles": updated_profiles,
            "active_profile": updated_profiles[0] if updated_profiles else None,
            "is_new": False,
            "message": "Profile deleted successfully.",
        },
    )


# ==============================================================================
# Asynchronous Scraping & Progress Tracking Endpoints
# ==============================================================================


@app.post("/scrape/start", response_class=HTMLResponse)
async def start_scrape(
    request: Request,
    profile_id: str = "all",
    db: Session = Depends(get_db),
):
    pid: int | None = None
    profile_name = "All Profiles"
    if profile_id != "all":
        try:
            pid = int(profile_id)
            prof = db.query(SearchProfile).filter(SearchProfile.id == pid).first()
            if prof:
                profile_name = prof.name
        except ValueError:
            pass

    session_factory = getattr(request.app.state, "session_factory", SessionLocal)
    task = await launch_scrape_task(pid, session_factory, profile_name)
    return templates.TemplateResponse(
        request=request,
        name="partials/scrape_progress.html",
        context={"task": task},
    )


@app.get("/scrape/status/{task_id}", response_class=HTMLResponse)
async def get_scrape_status(request: Request, task_id: str, db: Session = Depends(get_db)):
    task = get_task(task_id)
    if not task:
        return HTMLResponse("")

    context: dict[str, Any] = {"task": task}
    if task.status == "completed":
        jobs = query_filtered_jobs(db)
        tracked_map = get_tracked_applications_map(db)
        context["jobs"] = jobs
        context["group_by"] = "none"
        context["show_hidden"] = False
        context["tracked_map"] = tracked_map

    return templates.TemplateResponse(
        request=request,
        name="partials/scrape_progress.html",
        context=context,
    )


# ==============================================================================
# Staleness & Expiration Management Endpoints
# ==============================================================================


@app.post("/jobs/staleness/check", response_class=HTMLResponse)
async def check_jobs_staleness(request: Request, db: Session = Depends(get_db)):
    """Re-evaluates posting age and verifies live HTTP status on a batch of postings."""
    jobs = db.query(SavedJob).filter(SavedJob.is_hidden.is_(False)).all()
    now_utc = datetime.datetime.now(datetime.UTC)

    checked_links = 0
    for job in jobs:
        job.is_stale = evaluate_job_staleness(job.date_posted, job.saved_at)

        # Check up to 8 unverified job links per run
        if checked_links < 8 and (
            job.last_verified_at is None
            or (
                now_utc
                - (
                    job.last_verified_at.replace(tzinfo=datetime.UTC)
                    if job.last_verified_at.tzinfo is None
                    else job.last_verified_at
                )
            ).total_seconds()
            > 86400 * 7
        ):
            if job.job_url:
                is_alive = check_job_url_liveness(job.job_url)
                job.is_link_dead = not is_alive
                job.last_verified_at = now_utc
                checked_links += 1

    db.commit()
    updated_jobs = query_filtered_jobs(db)
    tracked_map = get_tracked_applications_map(db)
    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": updated_jobs,
            "group_by": "none",
            "show_hidden": False,
            "tracked_map": tracked_map,
        },
    )


@app.post("/jobs/staleness/auto-hide", response_class=HTMLResponse)
async def auto_hide_stale_jobs(request: Request, db: Session = Depends(get_db)):
    """Automatically marks all stale postings (30d+) as hidden."""
    stale_jobs = (
        db.query(SavedJob).filter(SavedJob.is_stale.is_(True), SavedJob.is_hidden.is_(False)).all()
    )
    for job in stale_jobs:
        job.is_hidden = True
    db.commit()

    updated_jobs = query_filtered_jobs(db)
    tracked_map = get_tracked_applications_map(db)
    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": updated_jobs,
            "group_by": "none",
            "show_hidden": False,
            "tracked_map": tracked_map,
        },
    )


# Legacy preferences endpoint maintained for backward compatibility
@app.post("/preferences", response_class=HTMLResponse)
async def save_preferences(
    request: Request,
    location: str = Form(""),
    positions: str = Form(""),
    fields: str = Form(""),
    sites: list[str] = Form(default=[]),
    is_remote: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    pref = db.query(UserPreference).first()
    sites_str = ",".join(sites) if sites else "linkedin,indeed,google"
    if not pref:
        pref = UserPreference(
            location=location,
            positions=positions,
            fields=fields,
            sites=sites_str,
            is_remote=is_remote,
        )
        db.add(pref)
    else:
        pref.location = location
        pref.positions = positions
        pref.fields = fields
        pref.sites = sites_str
        pref.is_remote = is_remote
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/preferences_form.html",
        context={"pref": pref, "message": "Preferences saved successfully!"},
    )


@app.post("/search", response_class=HTMLResponse)
async def search_jobs(request: Request, db: Session = Depends(get_db)):
    """Runs a live web scrape across selected job boards and saves new postings."""
    pref = db.query(UserPreference).first()
    if not pref or not pref.positions or (not pref.location and not pref.is_remote):
        return HTMLResponse(
            "<div class='error-msg'>"
            "Please set and save your position and location preferences first."
            "</div>"
        )

    search_term = pref.positions
    if pref.fields:
        search_term += f" {pref.fields}"

    sites_list = (
        [s.strip() for s in pref.sites.split(",") if s.strip()]
        if pref.sites
        else ["linkedin", "indeed", "google"]
    )

    fetched_jobs = fetch_jobs(
        search_term=search_term,
        location=pref.location,
        distance_miles=50,
        results_wanted=25,
        sites=sites_list,
        is_remote=pref.is_remote,
    )

    for j in fetched_jobs:
        if not j.get("job_id"):
            continue

        existing_job = db.query(SavedJob).filter(SavedJob.job_id == j["job_id"]).first()
        if not existing_job:
            date_posted = j.get("date_posted")
            if isinstance(date_posted, str):
                try:
                    date_posted = datetime.datetime.fromisoformat(date_posted)
                except ValueError:
                    date_posted = None

            new_job = SavedJob(
                job_id=str(j["job_id"]),
                site=j.get("site", ""),
                title=j.get("title", ""),
                company=j.get("company", ""),
                location=j.get("location", ""),
                salary_source=j.get("salary_source"),
                min_salary=j.get("min_salary"),
                max_salary=j.get("max_salary"),
                salary_interval=j.get("salary_interval", "yearly"),
                seniority_level=j.get("seniority_level", "Specialist / Contributor"),
                salary_bracket=j.get("salary_bracket", "Unspecified"),
                job_url=j.get("job_url", ""),
                description=j.get("description", ""),
                date_posted=date_posted,
                is_hidden=False,
            )
            db.add(new_job)
        else:
            # Refresh classification and salary metadata on existing job
            if j.get("seniority_level"):
                existing_job.seniority_level = j["seniority_level"]
            if j.get("salary_bracket") and j["salary_bracket"] != "Unspecified":
                existing_job.salary_bracket = j["salary_bracket"]
                existing_job.min_salary = j.get("min_salary")
                existing_job.max_salary = j.get("max_salary")
                existing_job.salary_interval = j.get("salary_interval")
                existing_job.salary_source = j.get("salary_source")

        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    # Re-query filtered active jobs
    jobs = (
        db.query(SavedJob)
        .filter(SavedJob.is_hidden.is_(False))
        .order_by(SavedJob.date_posted.desc().nullslast(), SavedJob.id.desc())
        .all()
    )
    tracked_map = get_tracked_applications_map(db)

    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": jobs,
            "group_by": "none",
            "show_hidden": False,
            "tracked_map": tracked_map,
        },
    )


@app.get("/job/{id}", response_class=HTMLResponse)
async def get_job_detail(request: Request, id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if not job:
        return HTMLResponse("Job not found.")
    return templates.TemplateResponse(
        request=request, name="partials/job_detail.html", context={"job": job}
    )


@app.post("/job/{id}/hide", response_class=HTMLResponse)
@app.delete("/job/{id}", response_class=HTMLResponse)
async def hide_job(id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if job:
        job.is_hidden = True
        db.commit()
    return HTMLResponse("")


@app.post("/job/{id}/unhide", response_class=HTMLResponse)
async def unhide_job(id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if job:
        job.is_hidden = False
        db.commit()
    return HTMLResponse("")


# ==============================================================================
# Job Application Tracking & Unemployment Compliance Routes
# ==============================================================================


@app.post("/job/{id}/track", response_class=HTMLResponse)
async def track_job(
    request: Request,
    id: int,
    status: str = Query("applied"),
    db: Session = Depends(get_db),
):
    """1-Click tracking from curated feed with smart defaults (applied or saved)."""
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if not job:
        return HTMLResponse("Job not found.", status_code=404)

    target_status = status.lower().strip() if status else "applied"
    if target_status not in ["saved", "applied"]:
        target_status = "applied"

    app_record = db.query(JobApplication).filter(JobApplication.saved_job_id == job.id).first()
    if not app_record:
        today = datetime.date.today()
        follow_up = today + datetime.timedelta(days=14)
        method = job.site.capitalize() if job.site else "Company Website"
        salary = job.salary_bracket if job.salary_bracket != "Unspecified" else job.salary_source

        # Check for matching resume to pre-attach
        matched = find_matching_resumes(db, job.title, job.description)
        suggested_rv_id = None
        if matched and matched[0][1] >= 0.2 and matched[0][0].versions:
            suggested_rv_id = matched[0][0].versions[0].id

        applied_dt = today if target_status == "applied" else None

        app_record = JobApplication(
            saved_job_id=job.id,
            title=job.title,
            company=job.company,
            location=job.location,
            salary_stated=salary,
            job_url=job.job_url,
            description=job.description,
            status=target_status,
            applied_date=applied_dt,
            method=method,
            follow_up_date=follow_up if target_status == "applied" else None,
            resume_version_id=suggested_rv_id,
        )
        db.add(app_record)
        db.flush()

        act_note = (
            f"Tracked application from feed ({method})"
            if target_status == "applied"
            else f"Saved job from feed ({method})"
        )
        activity = ApplicationActivity(
            application_id=app_record.id,
            activity_type="status_change",
            old_status=None,
            new_status=target_status,
            note=act_note,
            activity_date=today,
        )
        db.add(activity)
        db.commit()
        db.refresh(app_record)
    else:
        # If already tracked as 'saved' and user clicks 'Track Application', upgrade to 'applied'
        if app_record.status == "saved" and target_status == "applied":
            today = datetime.date.today()
            app_record.status = "applied"
            app_record.applied_date = today
            app_record.follow_up_date = today + datetime.timedelta(days=14)
            activity = ApplicationActivity(
                application_id=app_record.id,
                activity_type="status_change",
                old_status="saved",
                new_status="applied",
                note="Marked as applied from feed",
                activity_date=today,
            )
            db.add(activity)
            db.commit()
            db.refresh(app_record)

    tracked_map = {job.id: app_record}
    return templates.TemplateResponse(
        request=request,
        name="partials/job_actions.html",
        context={"job": job, "tracked_map": tracked_map},
    )


@app.get("/applications", response_class=HTMLResponse)
async def applications_dashboard(
    request: Request,
    view: str = "kanban",
    q: str = "",
    status: str = "all",
    db: Session = Depends(get_db),
):
    """Main Application Tracker view supporting interactive Kanban board and Table view."""
    query = db.query(JobApplication)

    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                JobApplication.title.ilike(term),
                JobApplication.company.ilike(term),
                JobApplication.location.ilike(term),
            )
        )

    if status and status != "all":
        if status == "closed":
            query = query.filter(JobApplication.status.in_(["rejected", "withdrawn", "cancelled"]))
        else:
            query = query.filter(JobApplication.status == status)

    applications = query.order_by(JobApplication.updated_at.desc(), JobApplication.id.desc()).all()

    all_apps = db.query(JobApplication).all()
    today = datetime.date.today()
    default_follow_up = today + datetime.timedelta(days=14)

    due_soon_count = sum(
        1
        for a in all_apps
        if a.follow_up_date
        and a.status not in ["offer", "rejected", "withdrawn", "cancelled"]
        and a.follow_up_date <= (today + datetime.timedelta(days=7))
    )

    metrics = {
        "total": len(all_apps),
        "saved": sum(1 for a in all_apps if a.status == "saved"),
        "applied": sum(1 for a in all_apps if a.status == "applied"),
        "screening": sum(1 for a in all_apps if a.status == "screening"),
        "interviewing": sum(1 for a in all_apps if a.status == "interviewing"),
        "offer": sum(1 for a in all_apps if a.status == "offer"),
        "closed": sum(1 for a in all_apps if a.status in ["rejected", "withdrawn", "cancelled"]),
        "due_soon": due_soon_count,
    }

    kanban_columns = [
        {
            "id": "saved",
            "title": "Saved / To Apply",
            "icon": "📌",
            "badge_class": "stage-saved",
            "cards": [a for a in applications if a.status == "saved"],
        },
        {
            "id": "applied",
            "title": "Applied",
            "icon": "✉️",
            "badge_class": "stage-applied",
            "cards": [a for a in applications if a.status == "applied"],
        },
        {
            "id": "screening",
            "title": "Phone Screen",
            "icon": "📞",
            "badge_class": "stage-screening",
            "cards": [a for a in applications if a.status == "screening"],
        },
        {
            "id": "interviewing",
            "title": "Interviewing",
            "icon": "💼",
            "badge_class": "stage-interviewing",
            "cards": [a for a in applications if a.status == "interviewing"],
        },
        {
            "id": "offer",
            "title": "Offer Received",
            "icon": "🎉",
            "badge_class": "stage-offer",
            "cards": [a for a in applications if a.status == "offer"],
        },
        {
            "id": "closed",
            "title": "Closed / Archived",
            "icon": "📁",
            "badge_class": "stage-closed",
            "cards": [
                a for a in applications if a.status in ["rejected", "withdrawn", "cancelled"]
            ],
        },
    ]

    all_resumes = db.query(Resume).order_by(Resume.title.asc()).all()

    context = {
        "request": request,
        "applications": applications,
        "kanban_columns": kanban_columns,
        "metrics": metrics,
        "current_view": view,
        "status_filter": status,
        "q": q,
        "today": today,
        "default_follow_up": default_follow_up,
        "active_page": "applications",
        "resumes": all_resumes,
    }

    if request.headers.get("HX-Target") == "applications-content":
        template_name = (
            "partials/applications_table.html"
            if view == "table"
            else "partials/applications_kanban.html"
        )
        return templates.TemplateResponse(request=request, name=template_name, context=context)

    return templates.TemplateResponse(request=request, name="applications.html", context=context)


@app.post("/applications")
async def create_manual_application(
    company: str = Form(...),
    title: str = Form(...),
    location: str = Form(""),
    salary_stated: str = Form(""),
    method: str = Form("Company Website"),
    status: str = Form("applied"),
    applied_date: str = Form(""),
    follow_up_date: str = Form(""),
    job_url: str = Form(""),
    account_created: bool = Form(False),
    portal_username: str = Form(""),
    confirmation_number: str = Form(""),
    description: str = Form(""),
    resume_version_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Manually logs an external application for complete tracking and unemployment audits."""
    today = datetime.date.today()
    parsed_applied_date = None
    if applied_date:
        try:
            parsed_applied_date = datetime.date.fromisoformat(applied_date)
        except ValueError:
            parsed_applied_date = today

    parsed_follow_up_date = None
    if follow_up_date:
        try:
            parsed_follow_up_date = datetime.date.fromisoformat(follow_up_date)
        except ValueError:
            parsed_follow_up_date = None

    if not parsed_follow_up_date and status == "applied":
        base_date = parsed_applied_date or today
        parsed_follow_up_date = base_date + datetime.timedelta(days=14)

    app_record = JobApplication(
        company=company.strip(),
        title=title.strip(),
        location=location.strip(),
        salary_stated=salary_stated.strip() or None,
        method=method.strip(),
        status=status.strip(),
        applied_date=parsed_applied_date,
        follow_up_date=parsed_follow_up_date,
        job_url=job_url.strip() or None,
        account_created=account_created,
        portal_username=portal_username.strip() or None,
        confirmation_number=confirmation_number.strip() or None,
        description=description.strip() or None,
        resume_version_id=resume_version_id,
    )
    db.add(app_record)
    db.flush()

    activity = ApplicationActivity(
        application_id=app_record.id,
        activity_type="status_change",
        old_status=None,
        new_status=status,
        note=f"Manually logged application ({method})",
        activity_date=parsed_applied_date or today,
    )
    db.add(activity)
    db.commit()

    return RedirectResponse(url="/applications", status_code=303)


@app.post("/applications/{id}/status")
async def update_application_status(
    request: Request,
    id: int,
    new_status: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    """Updates status and automatically logs activity for timeline tracking."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    old_status = app_record.status
    if old_status != new_status:
        app_record.status = new_status
        today = datetime.date.today()
        if new_status == "applied" and not app_record.applied_date:
            app_record.applied_date = today
            if not app_record.follow_up_date:
                app_record.follow_up_date = today + datetime.timedelta(days=14)

        activity_note = note.strip() or f"Updated status to {new_status.capitalize()}"
        activity = ApplicationActivity(
            application_id=app_record.id,
            activity_type="status_change",
            old_status=old_status,
            new_status=new_status,
            note=activity_note,
            activity_date=today,
        )
        db.add(activity)
        db.commit()

    if request.headers.get("HX-Target") == "applications-content":
        view = request.query_params.get("view", "kanban")
        q = request.query_params.get("q", "")
        status = request.query_params.get("status", "all")
        return await applications_dashboard(request=request, view=view, q=q, status=status, db=db)

    return RedirectResponse(url=f"/applications/{id}", status_code=303)


@app.get("/applications/unemployment-report", response_class=HTMLResponse)
async def unemployment_report(request: Request, db: Session = Depends(get_db)):
    """Groups work-search activities into weekly certification claim periods."""
    apps = db.query(JobApplication).order_by(JobApplication.applied_date.desc().nullslast()).all()
    activities = (
        db.query(ApplicationActivity)
        .order_by(ApplicationActivity.activity_date.desc(), ApplicationActivity.id.desc())
        .all()
    )

    entries: list[WorkSearchLogEntry] = []
    seen_keys = set()

    for a in apps:
        if a.status and a.status.lower() in ("saved", "cancelled", "canceled"):
            continue
        if a.applied_date:
            key = (a.id, a.applied_date, "Submitted Application")
            seen_keys.add(key)
            entries.append(
                {
                    "date": a.applied_date,
                    "activity_type": "Submitted Application",
                    "company": a.company,
                    "title": a.title,
                    "method": a.method,
                    "portal_account": a.account_created,
                    "portal_username": a.portal_username,
                    "confirmation": a.confirmation_number,
                    "status": a.status,
                    "notes": a.notes or "",
                }
            )

    for act in activities:
        app_obj = act.application
        if not app_obj:
            continue
        if app_obj.status and app_obj.status.lower() in ("saved", "cancelled", "canceled"):
            continue
        if act.new_status and act.new_status.lower() in ("saved", "cancelled", "canceled"):
            continue
        if act.activity_type and act.activity_type.lower() in ("saved", "cancelled", "canceled"):
            continue

        type_label = "Logged Activity"
        if act.activity_type == "interview":
            type_label = "Attended Interview / Screen"
        elif act.activity_type == "contact":
            type_label = "Employer / Recruiter Contact"
        elif act.activity_type == "follow_up":
            type_label = "Follow-up Sent"
        elif act.activity_type == "status_change":
            if act.new_status in ["screening", "interviewing"]:
                type_label = f"Advanced to {act.new_status.capitalize()}"
            elif act.new_status == "offer":
                type_label = "Offer Extended"
            else:
                continue

        key = (app_obj.id, act.activity_date, type_label)
        if key not in seen_keys:
            seen_keys.add(key)
            entries.append(
                {
                    "date": act.activity_date,
                    "activity_type": type_label,
                    "company": app_obj.company,
                    "title": app_obj.title,
                    "method": app_obj.method,
                    "portal_account": app_obj.account_created,
                    "portal_username": app_obj.portal_username,
                    "confirmation": app_obj.confirmation_number,
                    "status": app_obj.status,
                    "notes": act.note,
                }
            )

    entries.sort(key=lambda x: x["date"], reverse=True)

    weeks_map: dict[datetime.date, list[WorkSearchLogEntry]] = {}
    for entry in entries:
        we = get_week_ending(entry["date"])
        weeks_map.setdefault(we, []).append(entry)

    weekly_logs = []
    for we in sorted(weeks_map.keys(), reverse=True):
        ws = we - datetime.timedelta(days=6)
        weekly_logs.append(
            {
                "week_ending": we,
                "week_start": ws,
                "records": weeks_map[we],
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="unemployment_report.html",
        context={
            "weekly_logs": weekly_logs,
            "total_activities_count": len(entries),
            "active_page": "unemployment",
        },
    )


@app.get("/applications/unemployment-report/export")
async def export_unemployment_report(db: Session = Depends(get_db)):
    """Exports certified weekly work-search records to CSV."""
    apps = db.query(JobApplication).order_by(JobApplication.applied_date.desc().nullslast()).all()
    activities = (
        db.query(ApplicationActivity)
        .order_by(ApplicationActivity.activity_date.desc(), ApplicationActivity.id.desc())
        .all()
    )

    rows = []
    seen_keys = set()

    for a in apps:
        if a.status and a.status.lower() in ("saved", "cancelled", "canceled"):
            continue
        if a.applied_date:
            key = (a.id, a.applied_date, "Submitted Application")
            seen_keys.add(key)
            we = get_week_ending(a.applied_date)
            rows.append(
                {
                    "Claim Week Ending": we.strftime("%Y-%m-%d"),
                    "Activity Date": a.applied_date.strftime("%Y-%m-%d"),
                    "Activity Type": "Submitted Application",
                    "Employer": a.company,
                    "Job Title": a.title,
                    "Contact Method": a.method,
                    "Portal Account": "Yes" if a.account_created else "No",
                    "Portal Username": a.portal_username or "",
                    "Confirmation #": a.confirmation_number or "",
                    "Current Status": a.status.capitalize(),
                    "Notes": a.notes or "",
                }
            )

    for act in activities:
        app_obj = act.application
        if (
            not app_obj
            or (app_obj.status and app_obj.status.lower() in ("saved", "cancelled", "canceled"))
            or (act.new_status and act.new_status.lower() in ("saved", "cancelled", "canceled"))
            or (
                act.activity_type
                and act.activity_type.lower() in ("saved", "cancelled", "canceled")
            )
        ):
            continue

        type_label = "Logged Activity"
        if act.activity_type == "interview":
            type_label = "Attended Interview / Screen"
        elif act.activity_type == "contact":
            type_label = "Employer / Recruiter Contact"
        elif act.activity_type == "follow_up":
            type_label = "Follow-up Sent"
        elif act.activity_type == "status_change":
            if act.new_status in ["screening", "interviewing"]:
                type_label = f"Advanced to {act.new_status.capitalize()}"
            elif act.new_status == "offer":
                type_label = "Offer Extended"
            else:
                continue

        key = (app_obj.id, act.activity_date, type_label)
        if key not in seen_keys:
            seen_keys.add(key)
            we = get_week_ending(act.activity_date)
            rows.append(
                {
                    "Claim Week Ending": we.strftime("%Y-%m-%d"),
                    "Activity Date": act.activity_date.strftime("%Y-%m-%d"),
                    "Activity Type": type_label,
                    "Employer": app_obj.company,
                    "Job Title": app_obj.title,
                    "Contact Method": app_obj.method,
                    "Portal Account": "Yes" if app_obj.account_created else "No",
                    "Portal Username": app_obj.portal_username or "",
                    "Confirmation #": app_obj.confirmation_number or "",
                    "Current Status": app_obj.status.capitalize(),
                    "Notes": act.note or "",
                }
            )

    df = pd.DataFrame(rows)
    return Response(
        content=df.to_csv(index=False),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="unemployment_work_search_log.csv"'},
    )


@app.get("/applications/{id}", response_class=HTMLResponse)
async def get_application_detail(request: Request, id: int, db: Session = Depends(get_db)):
    """Follow-up command center for a specific job application."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    today = datetime.date.today()
    all_resumes = db.query(Resume).order_by(Resume.title.asc()).all()
    matching_resumes = find_matching_resumes(db, app_record.title, app_record.description)

    return templates.TemplateResponse(
        request=request,
        name="application_detail.html",
        context={
            "application": app_record,
            "contacts": app_record.contacts,
            "activities": app_record.activities,
            "today": today,
            "active_page": "applications",
            "resumes": all_resumes,
            "matching_resumes": matching_resumes,
        },
    )


@app.post("/applications/{id}")
async def update_application_detail(
    id: int,
    applied_date: str = Form(""),
    follow_up_date: str = Form(""),
    method: str = Form("Company Website"),
    account_created: bool = Form(False),
    portal_username: str = Form(""),
    confirmation_number: str = Form(""),
    resume_version_id: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Saves follow-up and compliance settings on the detail page."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    if applied_date:
        try:
            app_record.applied_date = datetime.date.fromisoformat(applied_date)
        except ValueError:
            pass
    else:
        app_record.applied_date = None

    if follow_up_date:
        try:
            app_record.follow_up_date = datetime.date.fromisoformat(follow_up_date)
        except ValueError:
            pass
    else:
        app_record.follow_up_date = None

    app_record.method = method.strip()
    app_record.account_created = account_created
    app_record.portal_username = portal_username.strip() or None
    app_record.confirmation_number = confirmation_number.strip() or None
    app_record.resume_version_id = resume_version_id

    db.commit()
    return RedirectResponse(url=f"/applications/{id}", status_code=303)


@app.post("/applications/{id}/job-info")
async def update_application_job_info(
    id: int,
    company: str = Form(...),
    title: str = Form(...),
    location: str = Form(""),
    salary_stated: str = Form(""),
    job_url: str = Form(""),
    db: Session = Depends(get_db),
):
    """Updates core job posting information (company, title, location, salary, job_url)."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    app_record.company = company.strip()
    app_record.title = title.strip()
    app_record.location = location.strip()
    app_record.salary_stated = salary_stated.strip() or None
    app_record.job_url = job_url.strip() or None

    if app_record.saved_job:
        app_record.saved_job.company = app_record.company
        app_record.saved_job.title = app_record.title
        app_record.saved_job.location = app_record.location
        if app_record.job_url:
            app_record.saved_job.job_url = app_record.job_url
        if app_record.salary_stated:
            app_record.saved_job.salary_bracket = app_record.salary_stated

    db.commit()
    return RedirectResponse(url=f"/applications/{id}", status_code=303)


@app.post("/applications/{id}/description")
async def update_application_description(
    id: int,
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    """Allows manual editing/updating of cached job description."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    app_record.description = description.strip() or None
    db.commit()
    return RedirectResponse(url=f"/applications/{id}", status_code=303)


@app.post("/applications/{id}/delete")
async def delete_application_form(id: int, db: Session = Depends(get_db)):
    """Deletes tracked application via standard form post."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if app_record:
        db.delete(app_record)
        db.commit()
    return RedirectResponse(url="/applications", status_code=303)


@app.delete("/applications/{id}", response_class=HTMLResponse)
async def delete_application_htmx(id: int, db: Session = Depends(get_db)):
    """Deletes tracked application via HTMX table action."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if app_record:
        db.delete(app_record)
        db.commit()
    return HTMLResponse("")


@app.post("/applications/{id}/contacts", response_class=HTMLResponse)
async def add_application_contact(
    request: Request,
    id: int,
    name: str = Form(...),
    role: str = Form("Hiring Manager"),
    email: str = Form(""),
    phone: str = Form(""),
    linkedin_url: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Adds a new contact (Hiring Manager, Recruiter, Referral) to an application."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    contact = ApplicationContact(
        application_id=app_record.id,
        name=name.strip(),
        role=role.strip(),
        email=email.strip() or None,
        phone=phone.strip() or None,
        linkedin_url=linkedin_url.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(contact)

    activity = ApplicationActivity(
        application_id=app_record.id,
        activity_type="contact",
        note=f"Added contact: {contact.name} ({contact.role})",
        activity_date=datetime.date.today(),
    )
    db.add(activity)
    db.commit()
    db.refresh(app_record)

    return templates.TemplateResponse(
        request=request,
        name="partials/application_contacts.html",
        context={"application": app_record, "contacts": app_record.contacts},
    )


@app.delete("/applications/{id}/contacts/{contact_id}", response_class=HTMLResponse)
async def delete_application_contact(
    request: Request,
    id: int,
    contact_id: int,
    db: Session = Depends(get_db),
):
    """Removes a contact from an application."""
    contact = (
        db.query(ApplicationContact)
        .filter(
            ApplicationContact.id == contact_id,
            ApplicationContact.application_id == id,
        )
        .first()
    )
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if contact:
        db.delete(contact)
        db.commit()
    if app_record:
        db.refresh(app_record)

    return templates.TemplateResponse(
        request=request,
        name="partials/application_contacts.html",
        context={
            "application": app_record,
            "contacts": app_record.contacts if app_record else [],
        },
    )


@app.post("/applications/{id}/contacts/{contact_id}", response_class=HTMLResponse)
async def update_application_contact(
    request: Request,
    id: int,
    contact_id: int,
    name: str = Form(...),
    role: str = Form("Hiring Manager"),
    email: str = Form(""),
    phone: str = Form(""),
    linkedin_url: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Updates an existing contact on an application."""
    contact = (
        db.query(ApplicationContact)
        .filter(
            ApplicationContact.id == contact_id,
            ApplicationContact.application_id == id,
        )
        .first()
    )
    if not contact:
        return HTMLResponse("Contact not found.", status_code=404)

    contact.name = name.strip()
    contact.role = role.strip()
    contact.email = email.strip() or None
    contact.phone = phone.strip() or None
    contact.linkedin_url = linkedin_url.strip() or None
    contact.notes = notes.strip() or None

    activity = ApplicationActivity(
        application_id=id,
        activity_type="contact",
        note=f"Updated contact: {contact.name} ({contact.role})",
        activity_date=datetime.date.today(),
    )
    db.add(activity)
    db.commit()

    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if app_record:
        db.refresh(app_record)

    return templates.TemplateResponse(
        request=request,
        name="partials/application_contacts.html",
        context={
            "application": app_record,
            "contacts": app_record.contacts if app_record else [],
        },
    )


@app.post("/applications/{id}/activities", response_class=HTMLResponse)
async def add_application_activity(
    request: Request,
    id: int,
    activity_type: str = Form("note"),
    activity_date: str = Form(""),
    note: str = Form(...),
    db: Session = Depends(get_db),
):
    """Adds a note, interview update, or interaction to the reverse-chronological timeline."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    parsed_date = datetime.date.today()
    if activity_date:
        try:
            parsed_date = datetime.date.fromisoformat(activity_date)
        except ValueError:
            parsed_date = datetime.date.today()

    activity = ApplicationActivity(
        application_id=app_record.id,
        activity_type=activity_type,
        note=note.strip(),
        activity_date=parsed_date,
    )
    db.add(activity)
    db.commit()
    db.refresh(app_record)

    return templates.TemplateResponse(
        request=request,
        name="partials/activity_timeline.html",
        context={"activities": app_record.activities},
    )


# ==============================================================================
# Resume Management & Versioning System
# ==============================================================================


@app.get("/resumes", response_class=HTMLResponse)
async def list_resumes(
    request: Request,
    tag: str = "all",
    person: str = "all",
    q: str = "",
    db: Session = Depends(get_db),
):
    """Resume Management Dashboard with tag/person filtering and version history."""
    query = db.query(Resume)
    if tag and tag != "all":
        query = query.filter(Resume.tags.ilike(f"%{tag}%"))
    if person and person != "all":
        query = query.filter(func.lower(Resume.person) == person.strip().lower())
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Resume.title.ilike(term),
                Resume.person.ilike(term),
                Resume.description.ilike(term),
                Resume.tags.ilike(term),
            )
        )
    resumes = query.order_by(Resume.updated_at.desc(), Resume.id.desc()).all()

    # Collect distinct tags and distinct people
    all_resumes = db.query(Resume).all()
    unique_tags: set[str] = set()
    unique_people: set[str] = set()
    for r in all_resumes:
        if r.tags:
            for t in r.tags.split(","):
                clean = t.strip()
                if clean:
                    unique_tags.add(clean)
        if r.person and r.person.strip():
            unique_people.add(r.person.strip())
    sorted_tags = sorted(unique_tags, key=str.lower)
    sorted_people = sorted(unique_people, key=str.lower)

    pref = db.query(UserPreference).first()

    return templates.TemplateResponse(
        request=request,
        name="resumes.html",
        context={
            "resumes": resumes,
            "all_resumes_count": len(all_resumes),
            "active_page": "resumes",
            "active_tag": tag,
            "active_person": person,
            "q": q,
            "tags": sorted_tags,
            "people": sorted_people,
            "pref": pref,
            "today": datetime.date.today(),
        },
    )


@app.post("/resumes")
async def create_resume(
    request: Request,
    title: str = Form(...),
    person: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    change_notes: str = Form("Initial upload"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Uploads and registers a new resume with its initial version (v1)."""
    if not file.filename:
        return HTMLResponse("No file selected.", status_code=400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "docx"):
        return HTMLResponse(
            "Unsupported file format. Please upload a .pdf or .docx document.",
            status_code=400,
        )

    content = await file.read()
    if not content:
        return HTMLResponse("Uploaded file is empty.", status_code=400)

    upload_dir = get_upload_dir(request.app)
    file_id = uuid.uuid4().hex
    stored_original = f"{file_id}.{ext}"
    file_path = upload_dir / stored_original
    file_path.write_bytes(content)

    # If DOCX, compile to PDF
    if ext in ("docx", "doc"):
        pdf_stored = f"{file_id}.pdf"
        pdf_path = upload_dir / pdf_stored
        converted = convert_docx_to_pdf(file_path, pdf_path)
        if not converted or not pdf_path.exists():
            pdf_path = file_path
    else:
        pdf_path = file_path

    extracted_text = extract_text(file_path, ext)

    resume = Resume(
        title=title.strip(),
        person=person.strip(),
        description=description.strip() or None,
        tags=tags.strip(),
    )
    db.add(resume)
    db.flush()

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=1,
        original_filename=file.filename,
        file_path=str(file_path),
        pdf_path=str(pdf_path),
        file_size=len(content),
        file_type=ext,
        extracted_text=extracted_text,
        change_notes=change_notes.strip() or "Initial upload",
    )
    db.add(version)
    db.commit()

    return RedirectResponse(url="/resumes", status_code=303)


@app.post("/resumes/{id}/versions")
async def upload_resume_version(
    request: Request,
    id: int,
    change_notes: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Uploads a subsequent version (v2, v3, etc.) for an existing resume."""
    resume = db.query(Resume).filter(Resume.id == id).first()
    if not resume:
        return HTMLResponse("Resume not found.", status_code=404)

    if not file.filename:
        return HTMLResponse("No file selected.", status_code=400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("pdf", "docx"):
        return HTMLResponse(
            "Unsupported file format. Please upload a .pdf or .docx document.",
            status_code=400,
        )

    content = await file.read()
    if not content:
        return HTMLResponse("Uploaded file is empty.", status_code=400)

    upload_dir = get_upload_dir(request.app)
    file_id = uuid.uuid4().hex
    stored_original = f"{file_id}.{ext}"
    file_path = upload_dir / stored_original
    file_path.write_bytes(content)

    if ext in ("docx", "doc"):
        pdf_stored = f"{file_id}.pdf"
        pdf_path = upload_dir / pdf_stored
        converted = convert_docx_to_pdf(file_path, pdf_path)
        if not converted or not pdf_path.exists():
            pdf_path = file_path
    else:
        pdf_path = file_path

    extracted_text = extract_text(file_path, ext)
    next_version = max([v.version_number for v in resume.versions], default=0) + 1

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=next_version,
        original_filename=file.filename,
        file_path=str(file_path),
        pdf_path=str(pdf_path),
        file_size=len(content),
        file_type=ext,
        extracted_text=extracted_text,
        change_notes=change_notes.strip() or f"Version {next_version}",
    )
    db.add(version)
    resume.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()

    return RedirectResponse(url="/resumes", status_code=303)


@app.post("/resumes/{id}/edit")
async def edit_resume(
    id: int,
    title: str = Form(...),
    person: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    """Updates resume title, person, description, and tags."""
    resume = db.query(Resume).filter(Resume.id == id).first()
    if not resume:
        return HTMLResponse("Resume not found.", status_code=404)

    resume.title = title.strip()
    resume.person = person.strip()
    resume.description = description.strip() or None
    resume.tags = tags.strip()
    resume.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()

    return RedirectResponse(url="/resumes", status_code=303)


@app.get("/resumes/versions/{version_id}/view")
async def view_resume_pdf(
    version_id: int,
    db: Session = Depends(get_db),
):
    """Streams the PDF version inline for in-browser viewing."""
    version = db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()
    if not version or not os.path.exists(version.pdf_path):
        return HTMLResponse("PDF document not found.", status_code=404)

    return FileResponse(
        path=version.pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{Path(version.pdf_path).name}"'},
    )


@app.get("/resumes/versions/{version_id}/download")
async def download_resume(
    version_id: int,
    format: str = "original",
    custom_filename: str = "",
    db: Session = Depends(get_db),
):
    """Downloads resume with customizable, dated retrieval naming."""
    version = db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()
    if not version:
        return HTMLResponse("Resume version not found.", status_code=404)

    use_pdf = format.lower() == "pdf" or (
        format.lower() != "original" and version.file_type == "pdf"
    )
    target_path = version.pdf_path if use_pdf else version.file_path
    target_ext = "pdf" if use_pdf else version.file_type

    if not os.path.exists(target_path):
        return HTMLResponse("File not found on disk.", status_code=404)

    pref = db.query(UserPreference).first()
    pattern = pref.resume_filename_pattern if pref else "{name} {date}.{ext}"
    date_format = pref.resume_date_format if pref else "%m-%d-%Y"
    # Resolve candidate name: resume.person takes precedence, then pref.candidate_name,
    # then fallback to resume.title
    cand_name = (
        (version.resume.person or "").strip()
        or (pref.candidate_name if pref else "").strip()
        or version.resume.title
    )

    if custom_filename and custom_filename.strip():
        download_name = custom_filename.strip()
        if not download_name.lower().endswith(f".{target_ext}"):
            download_name = f"{download_name}.{target_ext}"
    else:
        download_name = generate_download_filename(
            pattern=pattern,
            date_format=date_format,
            candidate_name=cand_name,
            resume_title=version.resume.title,
            version_number=version.version_number,
            file_ext=target_ext,
        )

    media_type = (
        "application/pdf"
        if use_pdf
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path=target_path,
        media_type=media_type,
        filename=download_name,
    )


@app.get("/resumes/versions/{version_id}/preview", response_class=HTMLResponse)
async def preview_resume_modal(
    request: Request,
    version_id: int,
    db: Session = Depends(get_db),
):
    """HTMX partial returning the embedded PDF viewer and extracted text viewer tabs."""
    version = db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()
    if not version:
        return HTMLResponse("Version not found.", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="partials/resume_preview_modal.html",
        context={
            "version": version,
            "resume": version.resume,
        },
    )


@app.delete("/resumes/versions/{version_id}", response_class=HTMLResponse)
async def delete_resume_version(
    version_id: int,
    db: Session = Depends(get_db),
):
    """Deletes a specific version and purges its physical files."""
    version = db.query(ResumeVersion).filter(ResumeVersion.id == version_id).first()
    if not version:
        return HTMLResponse("Version not found.", status_code=404)

    resume = version.resume
    if version.file_path and os.path.exists(version.file_path):
        try:
            os.remove(version.file_path)
        except OSError:
            pass
    if (
        version.pdf_path
        and version.pdf_path != version.file_path
        and os.path.exists(version.pdf_path)
    ):
        try:
            os.remove(version.pdf_path)
        except OSError:
            pass

    db.delete(version)
    resume.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()

    return HTMLResponse("", status_code=200)


@app.delete("/resumes/{id}", response_class=HTMLResponse)
async def delete_resume(
    id: int,
    db: Session = Depends(get_db),
):
    """Deletes an entire resume profile, all historical versions, and physical files."""
    resume = db.query(Resume).filter(Resume.id == id).first()
    if not resume:
        return HTMLResponse("Resume not found.", status_code=404)

    for version in resume.versions:
        if version.file_path and os.path.exists(version.file_path):
            try:
                os.remove(version.file_path)
            except OSError:
                pass
        if (
            version.pdf_path
            and version.pdf_path != version.file_path
            and os.path.exists(version.pdf_path)
        ):
            try:
                os.remove(version.pdf_path)
            except OSError:
                pass

    db.delete(resume)
    db.commit()
    return HTMLResponse("", status_code=200)


@app.post("/resumes/settings")
async def update_resume_settings(
    candidate_name: str = Form(""),
    resume_filename_pattern: str = Form("{name} {date}.{ext}"),
    resume_date_format: str = Form("%m-%d-%Y"),
    db: Session = Depends(get_db),
):
    """Updates candidate export naming preferences."""
    pref = db.query(UserPreference).first()
    if not pref:
        pref = UserPreference()
        db.add(pref)

    pref.candidate_name = candidate_name.strip()
    pref.resume_filename_pattern = resume_filename_pattern.strip() or "{name} {date}.{ext}"
    pref.resume_date_format = resume_date_format.strip() or "%m-%d-%Y"
    db.commit()

    return RedirectResponse(url="/resumes", status_code=303)
