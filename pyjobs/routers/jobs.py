from __future__ import annotations

import datetime
import io

import pandas as pd
from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from pyjobs.dependencies import (
    CurationFilters,
    find_matching_resumes,
    get_curation_filters,
    get_db,
    get_tracked_applications_map,
    group_jobs,
    query_filtered_jobs,
    templates,
)
from pyjobs.models import (
    ApplicationActivity,
    JobApplication,
    SavedJob,
)
from pyjobs.routers.discovery import render_index
from pyjobs.services.companies import get_or_create_company_site
from pyjobs.services.scraper import check_job_url_liveness, evaluate_job_staleness

router = APIRouter()


@router.get("/jobs/filter", response_class=HTMLResponse)
async def filter_jobs(
    request: Request,
    filters: CurationFilters = Depends(get_curation_filters),
    db: Session = Depends(get_db),
):
    if request.headers.get("HX-Request") != "true":
        return render_index(request, db, filters)
    jobs = filters.jobs(db)
    response = templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": jobs,
            "grouped_jobs": group_jobs(jobs, group_by=filters.group_by),
            "group_by": filters.group_by,
            "show_hidden": filters.show_hidden,
            "tracked_map": get_tracked_applications_map(db),
            "exclude_tracked": filters.exclude_tracked,
        },
    )
    response.set_cookie(
        key="pyjobs_exclude_tracked",
        value="true" if filters.exclude_tracked else "false",
        max_age=31536000,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/jobs/export")
async def export_jobs(
    format: str = "csv",
    filters: CurationFilters = Depends(get_curation_filters),
    db: Session = Depends(get_db),
):
    jobs = filters.jobs(db)

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


@router.post("/jobs/staleness/check", response_class=HTMLResponse)
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


@router.post("/jobs/staleness/auto-hide", response_class=HTMLResponse)
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


@router.get("/job/{id}", response_class=HTMLResponse)
async def get_job_detail(request: Request, id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if not job:
        return HTMLResponse("Job not found.")
    return templates.TemplateResponse(
        request=request, name="partials/job_detail.html", context={"job": job}
    )


@router.post("/job/{id}/company", response_class=HTMLResponse)
async def update_job_company(
    request: Request,
    id: int,
    company: str = Form(...),
    db: Session = Depends(get_db),
):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if job is None:
        return HTMLResponse("Job not found.", status_code=404)

    company_record, _ = get_or_create_company_site(db, company, job.location)
    if company_record is None:
        if request.headers.get("HX-Request") != "true":
            return HTMLResponse("Enter a valid company name.", status_code=422)
        return templates.TemplateResponse(
            request=request,
            name="partials/job_detail.html",
            context={"job": job, "company_error": "Enter a valid company name."},
        )

    db.flush()
    job.company = company_record.name
    job.company_id = company_record.id
    for application in job.applications:
        application.company = job.company
        application.company_id = job.company_id
    db.commit()

    if request.headers.get("HX-Request") == "true":
        response = templates.TemplateResponse(
            request=request,
            name="partials/job_detail.html",
            context={"job": job},
        )
        response.headers["HX-Trigger-After-Swap"] = "companyUpdated"
        return response
    return RedirectResponse(url=f"/#job-{id}", status_code=303)


@router.post("/job/{id}/hide", response_class=HTMLResponse)
@router.delete("/job/{id}", response_class=HTMLResponse)
async def hide_job(id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if job:
        job.is_hidden = True
        db.commit()
    return HTMLResponse("")


@router.post("/job/{id}/unhide", response_class=HTMLResponse)
async def unhide_job(id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if job:
        job.is_hidden = False
        db.commit()
    return HTMLResponse("")


@router.post("/job/{id}/track", response_class=HTMLResponse)
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

    company_record, _ = get_or_create_company_site(db, job.company, job.location)
    db.flush()
    job.company_id = company_record.id if company_record else None
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
            company_id=job.company_id,
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
        app_record.company_id = job.company_id
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

    if db.new or db.dirty:
        db.commit()

    tracked_map = {job.id: app_record}
    return templates.TemplateResponse(
        request=request,
        name="partials/job_actions.html",
        context={"job": job, "tracked_map": tracked_map},
    )
