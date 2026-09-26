from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pyjobs.database import SessionLocal
from pyjobs.dependencies import (
    CurationFilters,
    get_curation_filters,
    get_db,
    get_tracked_applications_map,
    group_jobs,
    query_filtered_jobs,
    templates,
)
from pyjobs.models import (
    SavedJob,
    SearchProfile,
    UserPreference,
)
from pyjobs.services.companies import (
    company_name_from_scrape,
    get_or_create_company_site,
    normalize_company_name,
)
from pyjobs.services.scraper import fetch_jobs
from pyjobs.services.task_manager import get_task, launch_scrape_task

router = APIRouter()


def render_index(request: Request, db: Session, filters: CurationFilters):
    """Render the full curation page using the same filters as partials and exports."""
    is_exclude_tracked = filters.exclude_tracked
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

    jobs = filters.jobs(db)
    tracked_map = get_tracked_applications_map(db)
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "filters": filters,
            "profiles": profiles,
            "active_profile": active_profile,
            "jobs": jobs,
            "total_jobs_count": len(jobs),
            "group_by": filters.group_by,
            "grouped_jobs": group_jobs(jobs, filters.group_by),
            "active_page": "curation",
            "tracked_map": tracked_map,
            "exclude_tracked": is_exclude_tracked,
        },
    )
    response.set_cookie(
        key="pyjobs_exclude_tracked",
        value="true" if is_exclude_tracked else "false",
        max_age=31536000,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    filters: CurationFilters = Depends(get_curation_filters),
    db: Session = Depends(get_db),
):
    return render_index(request, db, filters)


@router.post("/scrape/start", response_class=HTMLResponse)
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


@router.get("/scrape/status/{task_id}", response_class=HTMLResponse)
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


@router.post("/preferences", response_class=HTMLResponse)
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


@router.post("/search", response_class=HTMLResponse)
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
        scraped_company = company_name_from_scrape(j.get("company"), j.get("description"))
        observed_company = (
            normalize_company_name(existing_job.company) if existing_job else None
        ) or scraped_company
        observed_location = j.get("location") or (existing_job.location if existing_job else "")
        try:
            company_record, _ = get_or_create_company_site(
                db, observed_company or "", observed_location
            )
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
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
                company=observed_company or "",
                location=j.get("location", ""),
                company_id=company_record.id if company_record else None,
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
            existing_job.company_id = company_record.id if company_record else None
            existing_job.company = observed_company or ""
            if j.get("location"):
                existing_job.location = j["location"]
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
