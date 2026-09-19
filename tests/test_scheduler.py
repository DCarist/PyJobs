from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from pyjobs.models import SearchProfile
from pyjobs.services.scheduler import _check_and_run_scheduled_profiles, _run_startup_profiles


@pytest.mark.anyio
async def test_scheduler_startup_profiles(db_session):
    p1 = SearchProfile(name="Auto Launch", refresh_on_launch=True)
    p2 = SearchProfile(name="Manual", refresh_on_launch=False)
    db_session.add_all([p1, p2])
    db_session.commit()

    with patch(
        "pyjobs.services.scheduler.launch_scrape_task", new_callable=AsyncMock
    ) as mock_launch:
        await _run_startup_profiles(lambda: db_session)
        assert mock_launch.call_count == 1
        call_args = mock_launch.call_args[0]
        assert call_args[0] == p1.id


@pytest.mark.anyio
async def test_scheduler_interval_profiles(db_session):
    now = datetime.datetime.now(datetime.UTC)
    due_time = now - datetime.timedelta(hours=8)
    recent_time = now - datetime.timedelta(hours=2)

    p_due = SearchProfile(
        name="Due Profile",
        refresh_interval_hours=6,
        last_scraped_at=due_time,
    )
    p_recent = SearchProfile(
        name="Recent Profile",
        refresh_interval_hours=6,
        last_scraped_at=recent_time,
    )
    p_manual = SearchProfile(
        name="Manual Only",
        refresh_interval_hours=0,
    )
    db_session.add_all([p_due, p_recent, p_manual])
    db_session.commit()

    with patch(
        "pyjobs.services.scheduler.launch_scrape_task", new_callable=AsyncMock
    ) as mock_launch:
        await _check_and_run_scheduled_profiles(lambda: db_session)
        assert mock_launch.call_count == 1
        call_args = mock_launch.call_args[0]
        assert call_args[0] == p_due.id
