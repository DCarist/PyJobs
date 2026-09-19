from unittest.mock import patch

import pandas as pd

from pyjobs.services.scraper import fetch_jobs, parse_locations


def test_parse_locations_single():
    locs, is_remote = parse_locations("Philadelphia")
    assert locs == ["Philadelphia"]
    assert is_remote is False


def test_parse_locations_city_state():
    locs, is_remote = parse_locations("Philadelphia, PA")
    assert locs == ["Philadelphia, PA"]
    assert is_remote is False


def test_parse_locations_city_state_with_remote():
    locs, is_remote = parse_locations("Philadelphia, PA, Remote")
    assert locs == ["Philadelphia, PA"]
    assert is_remote is True


def test_parse_locations_multiple_city_states():
    locs, is_remote = parse_locations("Philadelphia, PA, New York, NY")
    assert locs == ["Philadelphia, PA", "New York, NY"]
    assert is_remote is False


def test_parse_locations_semicolon_delimited():
    locs, is_remote = parse_locations("Dallas, TX; Austin, TX; Remote")
    assert locs == ["Dallas, TX", "Austin, TX"]
    assert is_remote is True


def test_parse_locations_remote_only():
    locs, is_remote = parse_locations("Remote")
    assert locs == []
    assert is_remote is True


def test_parse_locations_empty():
    locs, is_remote = parse_locations("")
    assert locs == []
    assert is_remote is False


def test_fetch_jobs_multi_location_and_deduplication():
    df_philly = pd.DataFrame(
        [
            {
                "id": "job-1",
                "site": "linkedin",
                "title": "QA Engineer",
                "company": "Comcast",
                "location": "Philadelphia, PA",
                "min_amount": 90000,
                "max_amount": 120000,
                "interval": "yearly",
                "currency": "USD",
                "job_url": "https://linkedin.com/job/1",
                "description": "QA role in Philly",
                "date_posted": "2026-09-01",
            },
            {
                "id": "job-duplicate",
                "site": "linkedin",
                "title": "SDET",
                "company": "Cross-City Tech",
                "location": "Remote",
                "min_amount": None,
                "max_amount": None,
                "job_url": "https://linkedin.com/job/dup",
                "description": "Duplicate SDET",
                "date_posted": "2026-09-01",
            },
        ]
    )

    df_ny = pd.DataFrame(
        [
            {
                "id": "job-2",
                "site": "indeed",
                "title": "Senior QA Lead",
                "company": "NY Media",
                "location": "New York, NY",
                "min_amount": 130000,
                "max_amount": None,
                "interval": "yearly",
                "currency": "USD",
                "job_url": "https://indeed.com/job/2",
                "description": "QA role in NY",
                "date_posted": "2026-09-02",
            },
            {
                "id": "job-duplicate",  # Same ID as from philly batch
                "site": "indeed",
                "title": "SDET",
                "company": "Cross-City Tech",
                "location": "Remote",
                "min_amount": None,
                "max_amount": None,
                "job_url": "https://indeed.com/job/dup",
                "description": "Duplicate SDET",
                "date_posted": "2026-09-01",
            },
        ]
    )

    call_count = 0

    def mock_scrape(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        loc = kwargs.get("location")
        if loc == "Philadelphia, PA":
            return df_philly
        return df_ny

    with patch("pyjobs.services.scraper.scrape_jobs", side_effect=mock_scrape):
        results = fetch_jobs(
            search_term="QA",
            location="Philadelphia, PA, New York, NY",
            sites=["linkedin", "indeed"],
        )

    # Scraped both locations
    assert call_count == 2
    # Total 3 unique jobs returned (job-duplicate was deduplicated)
    assert len(results) == 3
    job_ids = [j["job_id"] for j in results]
    assert "job-1" in job_ids
    assert "job-2" in job_ids
    assert "job-duplicate" in job_ids


def test_fetch_jobs_handles_scraper_exception():
    with patch(
        "pyjobs.services.scraper.scrape_jobs", side_effect=RuntimeError("Cloudflare blocked")
    ):
        results = fetch_jobs(
            search_term="QA",
            location="Philadelphia, PA",
            sites=["glassdoor"],
        )
        assert results == []
