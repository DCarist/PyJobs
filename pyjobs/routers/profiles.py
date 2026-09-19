from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from pyjobs.dependencies import get_db, templates
from pyjobs.models import SearchProfile

router = APIRouter()


@router.get("/profiles/sidebar", response_class=HTMLResponse)
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


@router.post("/profiles", response_class=HTMLResponse)
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


@router.post("/profiles/{id}", response_class=HTMLResponse)
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


@router.delete("/profiles/{id}", response_class=HTMLResponse)
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
