from __future__ import annotations

import datetime

import pandas as pd
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from pyjobs.dependencies import (
    WorkSearchLogEntry,
    find_matching_resumes,
    get_db,
    get_week_ending,
    templates,
)
from pyjobs.models import (
    ApplicationActivity,
    ApplicationContact,
    JobApplication,
    Resume,
)

router = APIRouter()


@router.get("/applications", response_class=HTMLResponse)
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


@router.post("/applications")
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


@router.post("/applications/{id}/status")
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


@router.get("/applications/unemployment-report", response_class=HTMLResponse)
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


@router.get("/applications/unemployment-report/export")
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


@router.get("/applications/{id}", response_class=HTMLResponse)
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


@router.post("/applications/{id}")
async def update_application_detail(
    id: int,
    request: Request,
    applied_date: str = Form(""),
    follow_up_date: str = Form(""),
    method: str = Form("Company Website"),
    account_created: bool = Form(False),
    portal_username: str = Form(""),
    confirmation_number: str = Form(""),
    resume_version_id: str | None = Form(None),
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

    if resume_version_id is not None:
        clean_rv = resume_version_id.strip()
        if clean_rv.isdigit():
            app_record.resume_version_id = int(clean_rv)
        elif clean_rv == "":
            app_record.resume_version_id = None

    db.commit()

    if request.headers.get("HX-Request"):
        return HTMLResponse('<div class="save-status-badge">✓ Changes Saved</div>')
    return RedirectResponse(url=f"/applications/{id}?saved=Changes+Saved", status_code=303)


@router.post("/applications/{id}/job-info")
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
    return RedirectResponse(url=f"/applications/{id}?saved=Job+Info+Saved", status_code=303)


@router.post("/applications/{id}/follow-up", response_class=HTMLResponse)
async def update_application_follow_up(
    id: int,
    follow_up_date: str = Form(""),
    db: Session = Depends(get_db),
):
    """Updates follow-up reminder date without logging activity."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if not app_record:
        return HTMLResponse("Application not found.", status_code=404)

    if follow_up_date:
        try:
            app_record.follow_up_date = datetime.date.fromisoformat(follow_up_date)
        except ValueError:
            pass
    else:
        app_record.follow_up_date = None

    db.commit()
    return HTMLResponse('<div class="save-status-badge">✓ Reminder Date Saved</div>')


@router.post("/applications/{id}/description")
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
    return RedirectResponse(url=f"/applications/{id}?saved=Description+Saved", status_code=303)


@router.post("/applications/{id}/delete")
async def delete_application_form(id: int, db: Session = Depends(get_db)):
    """Deletes tracked application via standard form post."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if app_record:
        db.delete(app_record)
        db.commit()
    return RedirectResponse(url="/applications", status_code=303)


@router.delete("/applications/{id}", response_class=HTMLResponse)
async def delete_application_htmx(id: int, db: Session = Depends(get_db)):
    """Deletes tracked application via HTMX table action."""
    app_record = db.query(JobApplication).filter(JobApplication.id == id).first()
    if app_record:
        db.delete(app_record)
        db.commit()
    return HTMLResponse("")


@router.post("/applications/{id}/contacts", response_class=HTMLResponse)
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


@router.delete("/applications/{id}/contacts/{contact_id}", response_class=HTMLResponse)
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


@router.post("/applications/{id}/contacts/{contact_id}", response_class=HTMLResponse)
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


@router.post("/applications/{id}/activities", response_class=HTMLResponse)
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
