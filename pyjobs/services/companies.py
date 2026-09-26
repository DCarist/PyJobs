from __future__ import annotations

import re

from sqlalchemy.orm import Session

from pyjobs.models import Company, CompanySite, JobApplication, SavedJob
from pyjobs.services.locations import canonicalize_location

_REMOTE_ONLY_PREFIX = re.compile(
    r"^(?:(?:100\s*%\s*)?(?:fully\s+)?remote|wfh|work[\s-]+from[\s-]+home)\b",
    re.IGNORECASE,
)
_REMOTE_ONLY_TAG = re.compile(
    r"\([^)]*\b(?:remote|wfh|work[\s-]+from[\s-]+home)\b[^)]*\)",
    re.IGNORECASE,
)
_PLACEHOLDER_COMPANIES = {"unknown", "unknown company"}


def _collapsed(value: str) -> str:
    return " ".join(value.split())


def _company_identity(company_name: str | None) -> tuple[str | None, str | None]:
    name = _collapsed(company_name or "")
    key = name.casefold()
    if not name or key in _PLACEHOLDER_COMPANIES:
        return None, None
    return name, key


def _physical_location(job_location: str | None) -> str | None:
    raw = _collapsed(job_location or "")
    if not raw:
        return None

    canonical = canonicalize_location(raw)
    folded = canonical.casefold()
    if folded in {"remote", "work from home", "wfh", "unknown", "unknown location"}:
        return None
    if _REMOTE_ONLY_PREFIX.search(raw) or _REMOTE_ONLY_TAG.search(raw):
        return None
    return canonical


def get_or_create_company_site(
    db: Session, company_name: str, job_location: str
) -> tuple[Company | None, CompanySite | None]:
    """Find or add a company and its observed physical site without flushing or committing."""
    name, name_key = _company_identity(company_name)
    if name is None or name_key is None:
        return None, None

    with db.no_autoflush:
        company = next(
            (
                pending
                for pending in db.new
                if isinstance(pending, Company) and pending.name_key == name_key
            ),
            None,
        )
        if company is None:
            company = db.query(Company).filter(Company.name_key == name_key).one_or_none()
        if company is None:
            company = Company(name=name, name_key=name_key)
            db.add(company)

        location = _physical_location(job_location)
        if location is None:
            return company, None
        location_key = _collapsed(location).casefold()

        for pending in db.new:
            if not isinstance(pending, CompanySite) or pending.location_key != location_key:
                continue
            same_company = pending.company is company or (
                company.id is not None and pending.company_id == company.id
            )
            if same_company:
                return company, pending

        if company.id is not None:
            site = (
                db.query(CompanySite)
                .filter(
                    CompanySite.company_id == company.id,
                    CompanySite.location_key == location_key,
                )
                .one_or_none()
            )
            if site is not None:
                return company, site

        site = CompanySite(
            location=location,
            location_key=location_key,
            address="",
            company=company,
        )
        db.add(site)
        return company, site


def sync_company_profiles(session: Session) -> None:
    """Link historical jobs and applications to normalized company/site identities."""
    try:
        jobs = session.query(SavedJob).filter(SavedJob.company_id.is_(None)).all()
        applications = (
            session.query(JobApplication).filter(JobApplication.company_id.is_(None)).all()
        )

        for record in (*jobs, *applications):
            company, _ = get_or_create_company_site(session, record.company, record.location)
            if company is not None:
                record.company_profile = company

        session.commit()
    except Exception:
        session.rollback()
        raise
