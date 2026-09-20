from __future__ import annotations

import asyncio
import datetime
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pyjobs.models import JobSearchProfile, SavedJob, SearchProfile
from pyjobs.services.scraper import evaluate_job_staleness, fetch_jobs

logger = logging.getLogger("pyjobs.task_manager")


@dataclass
class ScrapeTaskState:
    task_id: str
    profile_id: int | None
    profile_name: str
    status: str = "pending"  # pending, running, completed, failed
    progress_message: str = "Task queued"
    progress_percent: int = 0
    jobs_added: int = 0
    jobs_updated: int = 0
    jobs_aging: int = 0
    jobs_hidden: int = 0
    error_message: str | None = None
    started_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    completed_at: datetime.datetime | None = None


# In-memory storage for scrape tasks
TASKS: dict[str, ScrapeTaskState] = {}


def get_task(task_id: str) -> ScrapeTaskState | None:
    return TASKS.get(task_id)


def create_task(profile_name: str, profile_id: int | None = None) -> ScrapeTaskState:
    task_id = str(uuid.uuid4())[:8]
    state = ScrapeTaskState(
        task_id=task_id,
        profile_id=profile_id,
        profile_name=profile_name,
        status="pending",
        progress_message="Starting search task...",
        progress_percent=5,
    )
    TASKS[task_id] = state
    return state


def _ingest_jobs_for_profile(
    db: Session,
    profile: SearchProfile,
    fetched_jobs: list[dict[str, Any]],
    task: ScrapeTaskState,
) -> None:
    """Inserts or updates jobs in SQLite and associates them with the search profile."""
    for j in fetched_jobs:
        job_id = j.get("job_id")
        if not job_id:
            continue

        existing_job = db.query(SavedJob).filter(SavedJob.job_id == str(job_id)).first()
        if not existing_job:
            date_posted = j.get("date_posted")
            if isinstance(date_posted, str):
                try:
                    date_posted = datetime.datetime.fromisoformat(date_posted)
                except ValueError:
                    date_posted = None

            now_utc = datetime.datetime.now(datetime.UTC)
            is_stale = evaluate_job_staleness(date_posted, now_utc)

            new_job = SavedJob(
                job_id=str(job_id),
                site=j.get("site", ""),
                title=j.get("title", ""),
                company=j.get("company", ""),
                location=j.get("location", ""),
                salary_source=j.get("salary_source"),
                min_salary=j.get("min_salary"),
                max_salary=j.get("max_salary"),
                salary_interval=j.get("salary_interval", "yearly"),
                seniority_level=j.get("seniority_level", "Specialist / Contributor"),
                salary_bracket=j.get("salary_bracket", "Unspecified"),
                job_url=j.get("job_url", ""),
                description=j.get("description", ""),
                date_posted=date_posted,
                is_hidden=False,
                is_stale=is_stale,
                last_verified_at=now_utc,
            )
            db.add(new_job)
            try:
                db.flush()
                # Create association
                assoc = JobSearchProfile(
                    saved_job_id=new_job.id,
                    search_profile_id=profile.id,
                    discovered_at=now_utc,
                )
                db.add(assoc)
                db.commit()
                task.jobs_added += 1
            except IntegrityError:
                db.rollback()
        else:
            # Refresh existing job metadata
            modified = False
            if j.get("seniority_level") and existing_job.seniority_level != j["seniority_level"]:
                existing_job.seniority_level = j["seniority_level"]
                modified = True
            if j.get("salary_bracket") and j["salary_bracket"] != "Unspecified":
                existing_job.salary_bracket = j["salary_bracket"]
                existing_job.min_salary = j.get("min_salary")
                existing_job.max_salary = j.get("max_salary")
                existing_job.salary_interval = j.get("salary_interval")
                existing_job.salary_source = j.get("salary_source")
                modified = True

            # Update staleness check
            now_utc = datetime.datetime.now(datetime.UTC)
            is_stale = evaluate_job_staleness(existing_job.date_posted, existing_job.saved_at)
            if existing_job.is_stale != is_stale:
                existing_job.is_stale = is_stale
                modified = True

            # Ensure profile association exists
            existing_assoc = (
                db.query(JobSearchProfile)
                .filter(
                    JobSearchProfile.saved_job_id == existing_job.id,
                    JobSearchProfile.search_profile_id == profile.id,
                )
                .first()
            )
            if not existing_assoc:
                new_assoc = JobSearchProfile(
                    saved_job_id=existing_job.id,
                    search_profile_id=profile.id,
                    discovered_at=now_utc,
                )
                db.add(new_assoc)
                modified = True

            if modified:
                try:
                    db.commit()
                    task.jobs_updated += 1
                except IntegrityError:
                    db.rollback()


def run_scrape_task_sync(
    task_id: str,
    profile_id: int | None,
    session_factory: Callable[[], Session],
) -> None:
    """Synchronous scrape execution designed to run inside a worker thread."""
    task = get_task(task_id)
    if not task:
        return

    db = session_factory()
    try:
        task.status = "running"
        task.progress_percent = 15

        if profile_id is not None:
            profiles_to_scrape = (
                db.query(SearchProfile).filter(SearchProfile.id == profile_id).all()
            )
        else:
            profiles_to_scrape = db.query(SearchProfile).all()

        if not profiles_to_scrape:
            task.status = "failed"
            task.error_message = "No search profiles found to execute."
            task.completed_at = datetime.datetime.now(datetime.UTC)
            return

        total_profiles = len(profiles_to_scrape)
        for idx, profile in enumerate(profiles_to_scrape, 1):
            task.progress_message = (
                f"Scraping boards for profile '{profile.name}' ({idx}/{total_profiles})..."
            )
            task.progress_percent = 15 + int((idx - 1) / total_profiles * 70)

            search_term = profile.positions
            if profile.fields:
                search_term += f" {profile.fields}"

            sites_list = (
                [s.strip() for s in profile.sites.split(",") if s.strip()]
                if profile.sites
                else ["linkedin", "indeed", "google"]
            )

            hours_old = (
                profile.date_range_days * 24 if profile.date_range_days is not None else None
            )

            fetched_jobs = fetch_jobs(
                search_term=search_term,
                location=profile.location,
                distance_miles=profile.distance_miles,
                results_wanted=profile.results_wanted,
                sites=sites_list,
                is_remote=profile.is_remote,
                hours_old=hours_old,
            )

            task.progress_message = f"Processing {len(fetched_jobs)} jobs for '{profile.name}'..."
            _ingest_jobs_for_profile(db, profile, fetched_jobs, task)

            profile.last_scraped_at = datetime.datetime.now(datetime.UTC)
            db.commit()

        # Compute global feed stats for aging and hidden
        task.jobs_aging = (
            db.query(SavedJob)
            .filter(SavedJob.is_stale.is_(True), SavedJob.is_hidden.is_(False))
            .count()
        )
        task.jobs_hidden = db.query(SavedJob).filter(SavedJob.is_hidden.is_(True)).count()

        task.status = "completed"
        task.progress_percent = 100
        task.progress_message = (
            f"Done! {task.jobs_added} new jobs added, {task.jobs_updated} updated."
        )
        task.completed_at = datetime.datetime.now(datetime.UTC)

    except Exception as e:
        logger.exception("Error executing scrape task %s: %s", task_id, e)
        task.status = "failed"
        task.error_message = str(e)
        task.progress_percent = 100
        task.completed_at = datetime.datetime.now(datetime.UTC)
    finally:
        db.close()


async def launch_scrape_task(
    profile_id: int | None,
    session_factory: Callable[[], Session],
    profile_name: str | None = None,
) -> ScrapeTaskState:
    """Launches an asynchronous scrape in a background thread."""
    name = profile_name or ("All Profiles" if profile_id is None else f"Profile #{profile_id}")
    task = create_task(profile_name=name, profile_id=profile_id)
    # Run in background executor thread without blocking event loop
    if not os.environ.get("PYJOBS_TESTING"):
        asyncio.create_task(
            asyncio.to_thread(run_scrape_task_sync, task.task_id, profile_id, session_factory)
        )
    return task
