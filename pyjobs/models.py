from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pyjobs.database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    location: Mapped[str] = mapped_column(String, default="")
    positions: Mapped[str] = mapped_column(String, default="")  # comma separated
    fields: Mapped[str] = mapped_column(String, default="")  # comma separated
    sites: Mapped[str] = mapped_column(String, default="linkedin,indeed,google")
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_name: Mapped[str] = mapped_column(String, default="")
    resume_filename_pattern: Mapped[str] = mapped_column(String, default="{name} {date}.{ext}")
    resume_date_format: Mapped[str] = mapped_column(String, default="%m-%d-%Y")
    home_location: Mapped[str] = mapped_column(String, default="")


class Company(Base):
    """A normalized company identity observed in saved postings or applications."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, default="")
    name_key: Mapped[str] = mapped_column(String, unique=True)

    sites: Mapped[list[CompanySite]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="CompanySite.location",
    )
    saved_jobs: Mapped[list[SavedJob]] = relationship(back_populates="company_profile")
    applications: Mapped[list[JobApplication]] = relationship(back_populates="company_profile")


class CompanySite(Base):
    """A physical work location observed for a company."""

    __tablename__ = "company_sites"
    __table_args__ = (
        UniqueConstraint("company_id", "location_key", name="uq_company_site_location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    location: Mapped[str] = mapped_column(String)
    location_key: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String, default="")

    company: Mapped[Company] = relationship(back_populates="sites")


class SearchProfile(Base):
    """Represents a named multi-query search profile with custom filters and schedules."""

    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, default="Default Search", index=True)
    positions: Mapped[str] = mapped_column(String, default="")  # comma separated
    fields: Mapped[str] = mapped_column(String, default="")  # comma separated
    location: Mapped[str] = mapped_column(String, default="")
    sites: Mapped[str] = mapped_column(String, default="linkedin,indeed,google")
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    distance_miles: Mapped[int] = mapped_column(Integer, default=50)
    results_wanted: Mapped[int] = mapped_column(Integer, default=25)
    date_range_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    # Automated Scheduling
    refresh_interval_hours: Mapped[int] = mapped_column(Integer, default=0)  # 0 = manual only
    refresh_on_launch: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scraped_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    jobs: Mapped[list[SavedJob]] = relationship(
        secondary="job_search_profiles",
        back_populates="search_profiles",
    )


class JobSearchProfile(Base):
    """Many-to-many relationship tracking which search profiles discovered a saved job."""

    __tablename__ = "job_search_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    saved_job_id: Mapped[int] = mapped_column(
        ForeignKey("saved_jobs.id", ondelete="CASCADE"), index=True
    )
    search_profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="CASCADE"), index=True
    )
    discovered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )


class SavedJob(Base):
    """Represents a curated job posting saved locally in SQLite.

    FUTURE TODO:
    Analyze data collected week-to-week for similar roles to compare offered salary data
    (min_salary, max_salary, seniority_level, date_posted) to benchmark market compensation
    and empower users during interview salary negotiations.
    """

    __tablename__ = "saved_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)  # from scraper
    site: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, default=None, index=True
    )
    location: Mapped[str] = mapped_column(String, default="")
    salary_source: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    min_salary: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    max_salary: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    salary_interval: Mapped[str | None] = mapped_column(String, nullable=True, default="yearly")
    seniority_level: Mapped[str] = mapped_column(String, default="Specialist / Contributor")
    salary_bracket: Mapped[str] = mapped_column(String, default="Unspecified")
    job_url: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    date_posted: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_link_dead: Mapped[bool] = mapped_column(Boolean, default=False)
    last_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    company_profile: Mapped[Company | None] = relationship(back_populates="saved_jobs")

    applications: Mapped[list[JobApplication]] = relationship(
        back_populates="saved_job", cascade="all, delete-orphan"
    )
    search_profiles: Mapped[list[SearchProfile]] = relationship(
        secondary="job_search_profiles",
        back_populates="jobs",
    )


class JobApplication(Base):
    """Tracks personal application progress, follow-ups, and unemployment compliance details."""

    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    saved_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True, default=None, index=True
    )
    title: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="", index=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, default=None, index=True
    )
    location: Mapped[str] = mapped_column(String, default="")
    salary_stated: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    job_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    # Status: saved, applied, screening, interviewing, offer, rejected, withdrawn, cancelled
    status: Mapped[str] = mapped_column(String, default="applied", index=True)
    applied_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True, default=None)
    method: Mapped[str] = mapped_column(String, default="Company Website")

    # Portal Account Tracking
    account_created: Mapped[bool] = mapped_column(Boolean, default=False)
    portal_username: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    # Unemployment proof & follow up
    confirmation_number: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    follow_up_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )

    # Resume version attachment
    resume_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        index=True,
    )

    company_profile: Mapped[Company | None] = relationship(back_populates="applications")
    saved_job: Mapped[SavedJob | None] = relationship(back_populates="applications")
    resume_version: Mapped[ResumeVersion | None] = relationship(back_populates="applications")
    contacts: Mapped[list[ApplicationContact]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationContact.id.asc()",
    )
    activities: Mapped[list[ApplicationActivity]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationActivity.created_at.desc()",
    )


class ApplicationContact(Base):
    """Tracks multiple contacts (e.g. Hiring Manager, Recruiter, Referral) for an application."""

    __tablename__ = "application_contacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="Hiring Manager")
    email: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    phone: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    linkedin_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    application: Mapped[JobApplication] = relationship(back_populates="contacts")


class ApplicationActivity(Base):
    """Audit timeline of status changes, notes, interviews, and follow-ups over time."""

    __tablename__ = "application_activities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"), index=True
    )
    activity_type: Mapped[str] = mapped_column(String, default="status_change")
    old_status: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    new_status: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    activity_date: Mapped[datetime.date] = mapped_column(
        Date, default=lambda: datetime.datetime.now(datetime.UTC).date()
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    application: Mapped[JobApplication] = relationship(back_populates="activities")


class Resume(Base):
    """Represents a resume profile/container holding tagged versions."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, index=True)
    person: Mapped[str] = mapped_column(String, default="", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    tags: Mapped[str] = mapped_column(String, default="")  # comma separated e.g. 'Python, FastAPI'
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
    )

    versions: Mapped[list[ResumeVersion]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        order_by="ResumeVersion.version_number.desc()",
    )


class ResumeVersion(Base):
    """Represents a specific chronological file version (v1, v2, etc.) of a resume."""

    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    original_filename: Mapped[str] = mapped_column(String, default="")
    file_path: Mapped[str] = mapped_column(String, default="")  # original uploaded (.pdf/.docx)
    pdf_path: Mapped[str] = mapped_column(String, default="")  # guaranteed rendered pdf
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_type: Mapped[str] = mapped_column(String, default="pdf")  # 'pdf' or 'docx'
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )

    resume: Mapped[Resume] = relationship(back_populates="versions")
    applications: Mapped[list[JobApplication]] = relationship(back_populates="resume_version")
