from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base
import datetime

class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    location = Column(String, default="")
    positions = Column(String, default="") # comma separated
    fields = Column(String, default="") # comma separated

class SavedJob(Base):
    __tablename__ = "saved_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True) # from scraper
    site = Column(String)
    title = Column(String)
    company = Column(String)
    location = Column(String)
    salary_source = Column(String, nullable=True)
    job_url = Column(String)
    description = Column(String, nullable=True)
    date_posted = Column(DateTime, nullable=True)
    saved_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
