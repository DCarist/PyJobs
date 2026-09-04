import datetime
import io
import os

import pandas as pd
from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import SessionLocal, init_db
from models import SavedJob, UserPreference
from scraper import fetch_jobs

# Create DB tables and apply column additions
init_db()

app = FastAPI(title="PyJobs")

# Ensure directories exist
os.makedirs("templates/partials", exist_ok=True)
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
) -> list[SavedJob]:
    """Queries saved jobs applying all active text, seniority, salary, site, and date filters."""
    query = db.query(SavedJob)

    if not show_hidden:
        query = query.filter(SavedJob.is_hidden.is_(False))
    else:
        query = query.filter(SavedJob.is_hidden.is_(True))

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
    pref = db.query(UserPreference).first()
    # Immediately load existing saved jobs on launch so the user is in curation mode
    jobs = (
        db.query(SavedJob)
        .filter(SavedJob.is_hidden.is_(False))
        .order_by(SavedJob.date_posted.desc().nullslast(), SavedJob.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"pref": pref, "jobs": jobs, "total_jobs_count": len(jobs), "group_by": "none"},
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
    )
    grouped = group_jobs(jobs, group_by=group_by)
    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={
            "jobs": jobs,
            "grouped_jobs": grouped,
            "group_by": group_by,
            "show_hidden": show_hidden,
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

    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={"jobs": jobs, "group_by": "none", "show_hidden": False},
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
