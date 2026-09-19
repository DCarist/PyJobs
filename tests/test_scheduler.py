from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from pyjobs.models import SearchProfile
from pyjobs.services.scheduler import (
    VALID_REFRESH_INTERVALS,
    _check_and_run_scheduled_profiles,
    _run_startup_profiles,
    format_interval_description,
)


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


@pytest.mark.anyio
async def test_scheduler_multi_day_intervals(db_session):
    now = datetime.datetime.now(datetime.UTC)

    # 3 days = 72h; scraped 4 days ago -> due
    p_3d_due = SearchProfile(
        name="3-Day Due",
        refresh_interval_hours=72,
        last_scraped_at=now - datetime.timedelta(days=4),
    )
    # 3 days = 72h; scraped 2 days ago -> not due
    p_3d_fresh = SearchProfile(
        name="3-Day Fresh",
        refresh_interval_hours=72,
        last_scraped_at=now - datetime.timedelta(days=2),
    )
    # 5 days = 120h; scraped 6 days ago -> due
    p_5d_due = SearchProfile(
        name="5-Day Due",
        refresh_interval_hours=120,
        last_scraped_at=now - datetime.timedelta(days=6),
    )
    # 7 days = 168h; scraped 8 days ago -> due
    p_7d_due = SearchProfile(
        name="7-Day Due",
        refresh_interval_hours=168,
        last_scraped_at=now - datetime.timedelta(days=8),
    )
    # 7 days = 168h; scraped 5 days ago -> not due
    p_7d_fresh = SearchProfile(
        name="7-Day Fresh",
        refresh_interval_hours=168,
        last_scraped_at=now - datetime.timedelta(days=5),
    )

    db_session.add_all([p_3d_due, p_3d_fresh, p_5d_due, p_7d_due, p_7d_fresh])
    db_session.commit()

    with patch(
        "pyjobs.services.scheduler.launch_scrape_task", new_callable=AsyncMock
    ) as mock_launch:
        await _check_and_run_scheduled_profiles(lambda: db_session)
        # Should trigger p_3d_due, p_5d_due, and p_7d_due
        assert mock_launch.call_count == 3
        launched_ids = {call[0][0] for call in mock_launch.call_args_list}
        assert launched_ids == {p_3d_due.id, p_5d_due.id, p_7d_due.id}


def test_format_interval_description():
    assert format_interval_description(0) == "manual only"
    assert format_interval_description(-1) == "manual only"
    assert format_interval_description(6) == "every 6h"
    assert format_interval_description(12) == "every 12h"
    assert format_interval_description(24) == "every 1 day (24h)"
    assert format_interval_description(72) == "every 3 days (72h)"
    assert format_interval_description(120) == "every 5 days (120h)"
    assert format_interval_description(168) == "every 7 days (168h)"
    assert VALID_REFRESH_INTERVALS == (0, 6, 12, 24, 72, 120, 168)
