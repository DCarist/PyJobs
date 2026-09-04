import datetime
import os

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine
from models import SavedJob, UserPreference
from scraper import fetch_jobs

# Create DB tables
Base.metadata.create_all(bind=engine)

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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    # Get the first preference if it exists
    pref = db.query(UserPreference).first()
    return templates.TemplateResponse(request=request, name="index.html", context={"pref": pref})


@app.post("/preferences", response_class=HTMLResponse)
async def save_preferences(
    request: Request,
    location: str = Form(""),
    positions: str = Form(""),
    fields: str = Form(""),
    db: Session = Depends(get_db),
):
    pref = db.query(UserPreference).first()
    if not pref:
        pref = UserPreference(location=location, positions=positions, fields=fields)
        db.add(pref)
    else:
        pref.location = location
        pref.positions = positions
        pref.fields = fields
    db.commit()

    # Return just the form to update it without full reload
    return templates.TemplateResponse(
        request=request,
        name="partials/preferences_form.html",
        context={"pref": pref, "message": "Preferences saved successfully!"},
    )


@app.post("/search", response_class=HTMLResponse)
async def search_jobs(request: Request, db: Session = Depends(get_db)):
    pref = db.query(UserPreference).first()
    if not pref or not pref.positions or not pref.location:
        return HTMLResponse(
            "<div class='error-msg'>"
            "Please set and save your position and location preferences first."
            "</div>"
        )

    search_term = pref.positions
    if pref.fields:
        search_term += f" {pref.fields}"

    fetched_jobs = fetch_jobs(
        search_term=search_term, location=pref.location, distance_miles=50, results_wanted=20
    )

    saved_jobs_list = []

    for j in fetched_jobs:
        if not j.get("job_id"):
            continue
        # Check if job exists
        existing_job = db.query(SavedJob).filter(SavedJob.job_id == j["job_id"]).first()
        if not existing_job:
            date_posted = j["date_posted"]
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
                job_url=j.get("job_url", ""),
                description=j.get("description", ""),
                date_posted=date_posted,
            )
            db.add(new_job)
            try:
                db.commit()
                db.refresh(new_job)
                saved_jobs_list.append(new_job)
            except IntegrityError:
                db.rollback()
                existing_job = (
                    db.query(SavedJob).filter(SavedJob.job_id == str(j["job_id"])).first()
                )
                if existing_job:
                    saved_jobs_list.append(existing_job)
        else:
            saved_jobs_list.append(existing_job)

    return templates.TemplateResponse(
        request=request,
        name="partials/job_results.html",
        context={"jobs": saved_jobs_list, "pref": pref},
    )


@app.get("/job/{id}", response_class=HTMLResponse)
async def get_job_detail(request: Request, id: int, db: Session = Depends(get_db)):
    job = db.query(SavedJob).filter(SavedJob.id == id).first()
    if not job:
        return HTMLResponse("Job not found.")
    return templates.TemplateResponse(
        request=request, name="partials/job_detail.html", context={"job": job}
    )


@app.delete("/job/{id}", response_class=HTMLResponse)
async def hide_job(request: Request, id: int):
    # Endpoint to remove from UI via HTMX
    return HTMLResponse("")
