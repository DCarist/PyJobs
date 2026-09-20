import datetime
from unittest.mock import patch

from pyjobs.models import JobSearchProfile, SavedJob, SearchProfile
from pyjobs.services.scraper import evaluate_job_staleness
from pyjobs.services.task_manager import run_scrape_task_sync


def test_create_and_update_search_profile(client, db_session):
    # 1. Create a profile
    response = client.post(
        "/profiles",
        data={
            "name": "Python Lead",
            "positions": "Senior Python Developer",
            "fields": "FastAPI, PostgreSQL",
            "location": "Philadelphia, PA",
            "sites": ["linkedin", "indeed"],
            "is_remote": True,
            "distance_miles": 25,
            "results_wanted": 50,
            "refresh_interval_hours": 6,
            "refresh_on_launch": True,
        },
    )
    assert response.status_code == 200
    assert "Python Lead" in response.text
    assert "created successfully!" in response.text

    profile = db_session.query(SearchProfile).filter(SearchProfile.name == "Python Lead").first()
    assert profile is not None
    assert profile.distance_miles == 25
    assert profile.results_wanted == 50
    assert profile.refresh_interval_hours == 6
    assert profile.refresh_on_launch is True
    assert profile.is_remote is True

    # 2. Update the profile
    update_res = client.post(
        f"/profiles/{profile.id}",
        data={
            "name": "Python Principal",
            "positions": "Principal Python Engineer",
            "fields": "Cloud, Architecture",
            "location": "Remote",
            "sites": ["linkedin"],
            "is_remote": True,
            "distance_miles": 100,
            "results_wanted": 100,
            "refresh_interval_hours": 12,
            "refresh_on_launch": False,
        },
    )
    assert update_res.status_code == 200
    assert "Python Principal" in update_res.text
    assert "updated successfully!" in update_res.text

    db_session.refresh(profile)
    assert profile.name == "Python Principal"
    assert profile.distance_miles == 100
    assert profile.refresh_interval_hours == 12


def test_delete_search_profile(client, db_session):
    p1 = SearchProfile(name="Profile 1", positions="Dev")
    p2 = SearchProfile(name="Profile 2", positions="QA")
    db_session.add_all([p1, p2])
    db_session.commit()

    # Delete p2
    del_res = client.delete(f"/profiles/{p2.id}")
    assert del_res.status_code == 200
    assert "Profile deleted successfully." in del_res.text
    assert db_session.query(SearchProfile).filter(SearchProfile.id == p2.id).first() is None

    # Try deleting p1 (last remaining profile)
    del_last = client.delete(f"/profiles/{p1.id}")
    assert del_last.status_code == 200
    assert "Cannot delete the only remaining profile." in del_last.text
    assert db_session.query(SearchProfile).filter(SearchProfile.id == p1.id).first() is not None


def test_async_scrape_flow_and_metrics(client, db_session):
    profile = SearchProfile(
        name="Backend Core",
        positions="Backend Engineer",
        location="Remote",
        sites="linkedin",
        distance_miles=50,
        results_wanted=15,
    )
    db_session.add(profile)
    db_session.commit()

    mock_jobs = [
        {
            "job_id": "test-job-101",
            "site": "linkedin",
            "title": "Backend Engineer",
            "company": "Tech Corp",
            "location": "Remote",
            "salary_source": "USD 120000 / yearly",
            "min_salary": 120000.0,
            "max_salary": 140000.0,
            "salary_interval": "yearly",
            "salary_bracket": "$120k - $160k",
            "seniority_level": "Specialist / Contributor",
            "job_url": "https://example.com/job101",
            "date_posted": datetime.datetime.now(datetime.UTC),
        }
    ]

    with patch("pyjobs.services.task_manager.fetch_jobs", return_value=mock_jobs):
        # Trigger async scrape start
        response = client.post(f"/scrape/start?profile_id={profile.id}")
        assert response.status_code == 200
        assert "Scraping in progress" in response.text

        # Extract task_id from markup
        import re

        m = re.search(r"/scrape/status/([a-zA-Z0-9_-]+)", response.text)
        assert m is not None
        task_id = m.group(1)
        prof_id = profile.id
        session_factory = client.app.state.session_factory
        run_scrape_task_sync(task_id, prof_id, session_factory)

        # Check completed status response
        status_res = client.get(f"/scrape/status/{task_id}")
        assert status_res.status_code == 200
        assert "Scrape Completed" in status_res.text
        assert "Newly Added" in status_res.text
        assert "Metadata Refreshed" in status_res.text

        # Verify job was inserted and linked to profile
        saved_job = db_session.query(SavedJob).filter(SavedJob.job_id == "test-job-101").first()
        assert saved_job is not None
        assoc = (
            db_session.query(JobSearchProfile)
            .filter(
                JobSearchProfile.saved_job_id == saved_job.id,
                JobSearchProfile.search_profile_id == prof_id,
            )
            .first()
        )
        assert assoc is not None


def test_staleness_detection_and_auto_hide(client, db_session):
    now = datetime.datetime.now(datetime.UTC)
    old_date = now - datetime.timedelta(days=40)
    fresh_date = now - datetime.timedelta(days=5)

    # Unit test evaluate_job_staleness
    assert evaluate_job_staleness(old_date, max_age_days=30) is True
    assert evaluate_job_staleness(fresh_date, max_age_days=30) is False

    # Seed an aging job and a fresh job
    old_job = SavedJob(
        job_id="old-job-1",
        title="Legacy Role",
        company="Old Co",
        date_posted=old_date,
        is_stale=False,
        is_hidden=False,
    )
    fresh_job = SavedJob(
        job_id="fresh-job-1",
        title="Modern Role",
        company="New Co",
        date_posted=fresh_date,
        is_stale=False,
        is_hidden=False,
    )
    db_session.add_all([old_job, fresh_job])
    db_session.commit()

    # Trigger staleness check endpoint
    check_res = client.post("/jobs/staleness/check")
    assert check_res.status_code == 200
    db_session.refresh(old_job)
    db_session.refresh(fresh_job)
    assert old_job.is_stale is True
    assert fresh_job.is_stale is False

    # Trigger auto-hide stale endpoint
    hide_res = client.post("/jobs/staleness/auto-hide")
    assert hide_res.status_code == 200
    db_session.refresh(old_job)
    db_session.refresh(fresh_job)
    assert old_job.is_hidden is True
    assert fresh_job.is_hidden is False


def test_filter_by_profile_and_staleness(client, db_session):
    p1 = SearchProfile(name="Profile Alpha", positions="Alpha")
    p2 = SearchProfile(name="Profile Beta", positions="Beta")
    db_session.add_all([p1, p2])
    db_session.commit()

    job1 = SavedJob(job_id="j1", title="Job Alpha", company="Co 1", is_stale=False, is_hidden=False)
    job2 = SavedJob(job_id="j2", title="Job Beta", company="Co 2", is_stale=True, is_hidden=False)
    db_session.add_all([job1, job2])
    db_session.commit()

    # Link job1 to p1, job2 to p2
    assoc1 = JobSearchProfile(saved_job_id=job1.id, search_profile_id=p1.id)
    assoc2 = JobSearchProfile(saved_job_id=job2.id, search_profile_id=p2.id)
    db_session.add_all([assoc1, assoc2])
    db_session.commit()

    # Filter by profile p1
    res_p1 = client.get(f"/jobs/filter?profile_id={p1.id}")
    assert res_p1.status_code == 200
    assert "Job Alpha" in res_p1.text
    assert "Job Beta" not in res_p1.text

    # Filter by active_only staleness
    res_active = client.get("/jobs/filter?staleness=active_only")
    assert res_active.status_code == 200
    assert "Job Alpha" in res_active.text
    assert "Job Beta" not in res_active.text

    # Filter by stale_only staleness
    res_stale = client.get("/jobs/filter?staleness=stale_only")
    assert res_stale.status_code == 200
    assert "Job Alpha" not in res_stale.text
    assert "Job Beta" in res_stale.text


def test_profile_sidebar_unsaved_modal_markup(client, db_session):
    p = SearchProfile(name="Fullstack Dev", positions="Fullstack Developer")
    db_session.add(p)
    db_session.commit()

    res = client.get(f"/profiles/sidebar?profile_id={p.id}")
    assert res.status_code == 200
    assert 'id="scrape-profile-btn"' in res.text
    assert f"window.handleProfileScrape('{p.id}')" in res.text
    assert 'id="unsaved-profile-modal"' in res.text
    assert "Unsaved Profile Changes" in res.text
    assert 'id="modal-save-and-scrape"' in res.text
    assert f"window.saveAndScrapeProfile('{p.id}')" in res.text
    assert 'id="modal-scrape-without-saving"' in res.text
    assert f"window.scrapeWithoutSaving('{p.id}')" in res.text
    assert 'id="modal-cancel-scrape"' in res.text


def test_search_profile_multi_day_schedule_options(client, db_session):
    # 1. Create profile with 3-day (72h) refresh schedule
    create_res = client.post(
        "/profiles",
        data={
            "name": "3-Day Refresh Profile",
            "positions": "Data Scientist",
            "refresh_interval_hours": 72,
        },
    )
    assert create_res.status_code == 200
    p = (
        db_session.query(SearchProfile)
        .filter(SearchProfile.name == "3-Day Refresh Profile")
        .first()
    )
    assert p is not None
    assert p.refresh_interval_hours == 72

    # 2. Update profile to 5-day (120h) refresh schedule
    update_res = client.post(
        f"/profiles/{p.id}",
        data={
            "name": "5-Day Refresh Profile",
            "refresh_interval_hours": 120,
        },
    )
    assert update_res.status_code == 200
    db_session.refresh(p)
    assert p.refresh_interval_hours == 120

    # 3. Update profile to 7-day / weekly (168h) refresh schedule
    update_res_7d = client.post(
        f"/profiles/{p.id}",
        data={
            "name": "Weekly Refresh Profile",
            "refresh_interval_hours": 168,
        },
    )
    assert update_res_7d.status_code == 200
    db_session.refresh(p)
    assert p.refresh_interval_hours == 168

    # 4. Verify negative interval is clamped to 0 (manual only)
    clamp_res = client.post(
        f"/profiles/{p.id}",
        data={
            "name": "Clamped Profile",
            "refresh_interval_hours": -5,
        },
    )
    assert clamp_res.status_code == 200
    db_session.refresh(p)
    assert p.refresh_interval_hours == 0


def test_profile_sidebar_schedule_dropdown_markup(client, db_session):
    p = SearchProfile(
        name="Scheduled Profile",
        positions="ML Engineer",
        refresh_interval_hours=72,
    )
    db_session.add(p)
    db_session.commit()

    res = client.get(f"/profiles/sidebar?profile_id={p.id}")
    assert res.status_code == 200

    # Verify all schedule interval options are rendered
    assert '<option value="0"' in res.text
    assert "Manual Only" in res.text
    assert '<option value="6"' in res.text
    assert "Every 6 Hours" in res.text
    assert '<option value="12"' in res.text
    assert "Every 12 Hours" in res.text
    assert '<option value="24"' in res.text
    assert "Daily (Every 24h)" in res.text
    assert '<option value="72" selected>Every 3 Days (72h)</option>' in res.text
    assert '<option value="120">Every 5 Days (120h)</option>' in res.text
    assert '<option value="168">Every 7 Days (Weekly)</option>' in res.text


def test_profile_sidebar_equal_action_buttons_and_toast_notification(client, db_session):
    p1 = SearchProfile(name="Profile One", positions="Dev")
    p2 = SearchProfile(name="Profile Two", positions="QA")
    db_session.add_all([p1, p2])
    db_session.commit()

    # 1. Verify equal sized buttons (flex: 1 1 0) on both Save and Delete
    sidebar_res = client.get(f"/profiles/sidebar?profile_id={p1.id}")
    assert sidebar_res.status_code == 200
    assert "flex: 1 1 0;" in sidebar_res.text
    assert "white-space: nowrap;" in sidebar_res.text
    assert "Save Profile" in sidebar_res.text
    assert "Delete" in sidebar_res.text
    # Ensure inline success-msg is not present
    assert "success-msg" not in sidebar_res.text

    # 2. Verify update triggers top-right out-of-band toast notification
    update_res = client.post(
        f"/profiles/{p1.id}",
        data={
            "name": "Profile One Updated",
            "positions": "Senior Dev",
        },
    )
    assert update_res.status_code == 200
    assert 'id="save-status-toast"' in update_res.text
    assert 'hx-swap-oob="true"' in update_res.text
    assert "save-status-badge" in update_res.text
    assert "updated successfully!" in update_res.text
    assert "success-msg" not in update_res.text

    # 3. Verify delete triggers top-right out-of-band toast notification
    del_res = client.delete(f"/profiles/{p2.id}")
    assert del_res.status_code == 200
    assert 'id="save-status-toast"' in del_res.text
    assert 'hx-swap-oob="true"' in del_res.text
    assert "save-status-badge" in del_res.text
    assert "Profile deleted successfully." in del_res.text

    # 4. Verify deleting last remaining profile shows error toast badge
    del_last = client.delete(f"/profiles/{p1.id}")
    assert del_last.status_code == 200
    assert 'id="save-status-toast"' in del_last.text
    assert 'hx-swap-oob="true"' in del_last.text
    assert "save-status-badge error" in del_last.text
    assert "Cannot delete the only remaining profile." in del_last.text
