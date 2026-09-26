from __future__ import annotations

import re
from html.parser import HTMLParser

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
_PLACEHOLDER_COMPANIES = {
    "-",
    "n/a",
    "na",
    "nan",
    "none",
    "not available",
    "not provided",
    "not specified",
    "null",
    "unknown",
    "unknown company",
}


def _collapsed(value: str) -> str:
    return " ".join(value.split())


def normalize_company_name(company_name: str | None) -> str | None:
    """Return a cleaned employer name, rejecting common scraper placeholders."""
    name = _collapsed(company_name or "")
    key = name.casefold().strip(" .,:;-")
    if not key or key in _PLACEHOLDER_COMPANIES:
        return None
    return name


def is_valid_company_name(company_name: str | None) -> bool:
    """Whether a company name is a usable employer identity rather than a placeholder."""
    return normalize_company_name(company_name) is not None


def _company_identity(company_name: str | None) -> tuple[str | None, str | None]:
    name = normalize_company_name(company_name)
    if name is None:
        return None, None
    return name, name.casefold()


class _DescriptionTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_EMPHASIS = re.compile(r"(?<!\w)(\*\*|__|\*|_)(.+?)\1(?!\w)")
_COMPANY_LABEL = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:#{1,6}\s*)?(?:company|employer)\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)


def _strip_markdown(value: str) -> str:
    value = _MARKDOWN_LINK.sub(r"\1", value)
    value = _MARKDOWN_EMPHASIS.sub(r"\2", value)
    return value.strip().strip("`*_ ")


def infer_company_from_description(description: str | None) -> str | None:
    """Infer an employer only from a line explicitly labeled Company or Employer."""
    if not description:
        return None

    parser = _DescriptionTextParser()
    parser.feed(description)
    parser.close()

    names: dict[str, str] = {}
    for line in "".join(parser.parts).splitlines():
        # Strip emphasis before checking the label, allowing **Company:** Acme.
        plain_line = _strip_markdown(line)
        match = _COMPANY_LABEL.match(plain_line)
        if not match:
            continue
        name = normalize_company_name(_strip_markdown(match.group(1)))
        if name:
            names.setdefault(name.casefold(), name)

    if len(names) != 1:
        return None
    return next(iter(names.values()))


def company_name_from_scrape(company_name: str | None, description: str | None) -> str | None:
    """Use a valid scraper name, falling back only to explicit description attribution."""
    return normalize_company_name(company_name) or infer_company_from_description(description)


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
        invalid_company_ids = [
            company.id
            for company in session.query(Company).all()
            if normalize_company_name(company.name) is None
        ]
        for company_id in invalid_company_ids:
            for job in session.query(SavedJob).filter(SavedJob.company_id == company_id):
                job.company_id = None
            for application in session.query(JobApplication).filter(
                JobApplication.company_id == company_id
            ):
                application.company_id = None

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
