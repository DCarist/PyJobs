from __future__ import annotations

import datetime
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from pyjobs.dependencies import get_db, get_upload_dir, templates
from pyjobs.models import Resume, ResumeVersion, UserPreference
from pyjobs.services.resume_parser import (
    convert_docx_to_pdf,
    extract_text,
    generate_download_filename,
)

router = APIRouter()


def validate_resume_file(filename: str | None, content: bytes) -> str | None:
    """Validates uploaded resume filename extension and content. Returns error message or None."""
    if not filename:
        return "No file selected."
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "docx"):
        return "Unsupported file format. Please upload a .pdf or .docx document."
    if not content:
        return "Uploaded file is empty."
    return None


def process_and_store_resume_file(
    upload_dir: Path,
    filename: str,
    content: bytes,
) -> tuple[Path, Path, str, str]:
    """Persists uploaded file, compiles DOCX to PDF if needed, and extracts plain text.

    Returns (file_path, pdf_path, ext, extracted_text).
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    file_id = uuid.uuid4().hex
    file_path = upload_dir / f"{file_id}.{ext}"
    file_path.write_bytes(content)

    if ext in ("docx", "doc"):
        pdf_path = upload_dir / f"{file_id}.pdf"
        converted = convert_docx_to_pdf(file_path, pdf_path)
        if not converted or not pdf_path.exists():
            pdf_path = file_path
    else:
        pdf_path = file_path

    extracted_text = extract_text(file_path, ext)
    return file_path, pdf_path, ext, extracted_text


@router.get("/resumes", response_class=HTMLResponse)
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


@router.post("/resumes")
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
    content = await file.read()
    err = validate_resume_file(file.filename, content)
    if err:
        return HTMLResponse(err, status_code=400)

    upload_dir = get_upload_dir(request.app)
    file_path, pdf_path, ext, extracted_text = process_and_store_resume_file(
        upload_dir, file.filename or "resume.pdf", content
    )

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
        original_filename=file.filename or "resume.pdf",
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


@router.post("/resumes/{id}/versions")
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

    content = await file.read()
    err = validate_resume_file(file.filename, content)
    if err:
        return HTMLResponse(err, status_code=400)

    upload_dir = get_upload_dir(request.app)
    file_path, pdf_path, ext, extracted_text = process_and_store_resume_file(
        upload_dir, file.filename or "resume.pdf", content
    )

    next_version = max([v.version_number for v in resume.versions], default=0) + 1

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=next_version,
        original_filename=file.filename or "resume.pdf",
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


@router.post("/resumes/{id}/edit")
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


@router.get("/resumes/versions/{version_id}/view")
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


@router.get("/resumes/versions/{version_id}/download")
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


@router.get("/resumes/versions/{version_id}/preview", response_class=HTMLResponse)
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


@router.delete("/resumes/versions/{version_id}", response_class=HTMLResponse)
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


@router.delete("/resumes/{id}", response_class=HTMLResponse)
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


@router.post("/resumes/settings")
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
