import asyncio
import datetime
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from models import SearchProfile
from task_manager import TASKS, launch_scrape_task

logger = logging.getLogger("pyjobs.scheduler")

_scheduler_task: asyncio.Task | None = None
_running: bool = False


async def _check_and_run_scheduled_profiles(session_factory: Callable[[], Session]) -> None:
    """Checks for profiles due for refresh or configured to run on startup."""
    db = session_factory()
    try:
        now = datetime.datetime.now(datetime.UTC)
        profiles = db.query(SearchProfile).all()

        for profile in profiles:
            if profile.refresh_interval_hours <= 0:
                continue

            interval_seconds = profile.refresh_interval_hours * 3600
            should_run = False

            if not profile.last_scraped_at:
                should_run = True
            else:
                last_time = profile.last_scraped_at
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=datetime.UTC)
                if (now - last_time).total_seconds() >= interval_seconds:
                    should_run = True

            if should_run:
                # Check if already running
                is_active = any(
                    t.profile_id == profile.id and t.status in ("pending", "running")
                    for t in TASKS.values()
                )
                if not is_active:
                    logger.info(
                        "Triggering scheduled refresh for profile '%s' (every %dh)",
                        profile.name,
                        profile.refresh_interval_hours,
                    )
                    await launch_scrape_task(profile.id, session_factory, profile.name)

    except Exception as e:
        logger.error("Error in scheduler cycle: %s", e)
    finally:
        db.close()


async def _run_startup_profiles(session_factory: Callable[[], Session]) -> None:
    """Runs profiles configured with refresh_on_launch=True."""
    db = session_factory()
    try:
        startup_profiles = (
            db.query(SearchProfile).filter(SearchProfile.refresh_on_launch.is_(True)).all()
        )
        for profile in startup_profiles:
            logger.info("Triggering on-launch scrape for profile '%s'", profile.name)
            await launch_scrape_task(profile.id, session_factory, profile.name)
    except Exception as e:
        logger.error("Error running startup profiles: %s", e)
    finally:
        db.close()


async def scheduler_loop(session_factory: Callable[[], Session]) -> None:
    """Recurring async loop that polls for scheduled profiles."""
    global _running
    _running = True
    logger.info("SearchProfile background scheduler loop started.")

    # Run on-launch scrapes first
    await _run_startup_profiles(session_factory)

    while _running:
        try:
            await asyncio.sleep(60)
            if not _running:
                break
            await _check_and_run_scheduled_profiles(session_factory)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Unexpected error in scheduler loop: %s", e)
            await asyncio.sleep(10)


def start_scheduler(session_factory: Callable[[], Session]) -> None:
    """Starts the background scheduler loop as an asyncio Task."""
    global _scheduler_task, _running
    if _scheduler_task is None or _scheduler_task.done():
        _running = True
        _scheduler_task = asyncio.create_task(scheduler_loop(session_factory))


def stop_scheduler() -> None:
    """Stops the background scheduler loop."""
    global _scheduler_task, _running
    _running = False
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        _scheduler_task = None
    logger.info("SearchProfile background scheduler stopped.")
