import datetime

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    location: Mapped[str] = mapped_column(String, default="")
    positions: Mapped[str] = mapped_column(String, default="")  # comma separated
    fields: Mapped[str] = mapped_column(String, default="")  # comma separated
    sites: Mapped[str] = mapped_column(String, default="linkedin,indeed,google")
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)


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
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
