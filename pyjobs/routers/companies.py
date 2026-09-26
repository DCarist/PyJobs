from __future__ import annotations

import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from pyjobs.dependencies import get_db, get_tracked_applications_map, templates
from pyjobs.models import Company, CompanySite, JobApplication, SavedJob, UserPreference
from pyjobs.services.companies import get_or_create_company_site, is_valid_company_name

router = APIRouter()


def _company_or_404(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if company is None or not is_valid_company_name(company.name):
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _directions(origin: str, destination: str) -> str:
    return "https://www.google.com/maps/dir/?" + urlencode(
        {"api": "1", "origin": origin, "destination": destination, "travelmode": "driving"}
    )


@router.get("/companies", response_class=HTMLResponse)
async def company_directory(
    request: Request, hide_inactive: bool = False, db: Session = Depends(get_db)
):
    available_postings = (
        db.query(
            SavedJob.company_id.label("company_id"),
            func.count(SavedJob.id).label("posting_count"),
        )
        .filter(SavedJob.is_hidden.is_(False))
        .group_by(SavedJob.company_id)
        .subquery()
    )
    active_applications = (
        db.query(
            JobApplication.company_id.label("company_id"),
            func.count(JobApplication.id).label("application_count"),
        )
        .filter(
            JobApplication.status.in_(("saved", "applied", "screening", "interviewing", "offer"))
        )
        .group_by(JobApplication.company_id)
        .subquery()
    )
    query = (
        db.query(
            Company,
            func.coalesce(available_postings.c.posting_count, 0),
            func.coalesce(active_applications.c.application_count, 0),
        )
        .options(selectinload(Company.sites))
        .outerjoin(available_postings, available_postings.c.company_id == Company.id)
        .outerjoin(active_applications, active_applications.c.company_id == Company.id)
        .order_by(Company.name.asc())
    )
    if hide_inactive:
        query = query.filter(
            or_(
                available_postings.c.posting_count > 0,
                active_applications.c.application_count > 0,
            )
        )
    company_rows = [
        (company, posting_count, application_count)
        for company, posting_count, application_count in query.all()
        if is_valid_company_name(company.name)
    ]
    preference = db.query(UserPreference).first()
    return templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={
            "company_rows": company_rows,
            "hide_inactive": hide_inactive,
            "home_location": preference.home_location if preference else "",
            "active_page": "companies",
        },
    )


@router.post("/companies/home-location")
async def save_home_location(home_location: str = Form(""), db: Session = Depends(get_db)):
    preference = db.query(UserPreference).first()
    if preference is None:
        preference = UserPreference()
        db.add(preference)
    preference.home_location = home_location.strip()
    db.commit()
    return RedirectResponse(url="/companies", status_code=303)


@router.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(request: Request, company_id: int, db: Session = Depends(get_db)):
    company = _company_or_404(db, company_id)
    preference = db.query(UserPreference).first()
    home = preference.home_location if preference else ""
    directions = (
        {site.id: _directions(home, site.address or site.location) for site in company.sites}
        if home
        else {}
    )
    return templates.TemplateResponse(
        request=request,
        name="company_detail.html",
        context={
            "company": company,
            "home_location": home,
            "directions": directions,
            "tracked_map": get_tracked_applications_map(db),
            "today": datetime.date.today(),
            "active_page": "companies",
        },
    )


@router.post("/companies/{company_id}/sites")
async def add_company_site(
    company_id: int,
    location: str = Form(""),
    address: str = Form(""),
    db: Session = Depends(get_db),
):
    company = _company_or_404(db, company_id)
    _, site = get_or_create_company_site(db, company.name, location)
    if site is None:
        raise HTTPException(status_code=422, detail="A physical location is required")
    if site.id is not None and not address.strip():
        raise HTTPException(
            status_code=422, detail="Site already exists; supply an address to update it"
        )
    if address.strip():
        site.address = address.strip()
    db.commit()
    return RedirectResponse(url=f"/companies/{company_id}", status_code=303)


@router.post("/companies/{company_id}/sites/{site_id}")
async def update_company_site(
    company_id: int,
    site_id: int,
    address: str = Form(""),
    db: Session = Depends(get_db),
):
    _company_or_404(db, company_id)
    site = db.query(CompanySite).filter_by(id=site_id, company_id=company_id).one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Company site not found")
    site.address = address.strip()
    db.commit()
    return RedirectResponse(url=f"/companies/{company_id}", status_code=303)
