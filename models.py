import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    location: Mapped[str] = mapped_column(String, default="")
    positions: Mapped[str] = mapped_column(String, default="")  # comma separated
    fields: Mapped[str] = mapped_column(String, default="")  # comma separated


class SavedJob(Base):
    __tablename__ = "saved_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_id: Mapped[str] = mapped_column(String, unique=True, index=True)  # from scraper
    site: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    company: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(String, default="")
    salary_source: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    job_url: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    date_posted: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    saved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.UTC)
    )
