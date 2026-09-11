from unittest.mock import patch

from models import SavedJob, UserPreference


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "PyJobs" in response.text
    assert "Search Profile" in response.text


def test_save_preferences(client, db_session):
    response = client.post(
        "/preferences",
        data={
            "location": "New York, NY",
            "positions": "Backend Engineer",
            "fields": "Python, FastAPI",
        },
    )
    assert response.status_code == 200
    assert "Preferences saved successfully!" in response.text

    pref = db_session.query(UserPreference).first()
    assert pref is not None
    assert pref.location == "New York, NY"
    assert pref.positions == "Backend Engineer"


def test_save_preferences_with_sites_and_remote(client, db_session):
    response = client.post(
        "/preferences",
        data={
            "location": "Philadelphia, PA, Remote",
            "positions": "Quality Assurance",
            "fields": "Six Sigma",
            "sites": ["linkedin", "indeed"],
            "is_remote": "true",
        },
    )
    assert response.status_code == 200
    assert "Preferences saved successfully!" in response.text

    pref = db_session.query(UserPreference).first()
    assert pref is not None
    assert pref.location == "Philadelphia, PA, Remote"
    assert pref.is_remote is True
    assert "linkedin" in pref.sites


def test_search_jobs_missing_preferences(client):
    response = client.post("/search")
    assert response.status_code == 200
    assert "Please set and save your position and location preferences first" in response.text


def test_search_jobs_with_mock(client, db_session):
    pref = UserPreference(location="Remote", positions="Python Developer", fields="Backend")
    db_session.add(pref)
    db_session.commit()

    mock_jobs = [
        {
            "job_id": "test-job-1",
            "site": "linkedin",
            "title": "Senior Python Engineer",
            "company": "Acme Corp",
            "location": "Remote",
            "salary_source": "USD 120000 - 150000 / yearly",
            "job_url": "https://example.com/job/1",
            "description": "Awesome role.",
            "date_posted": "2026-09-01",
        }
    ]

    with patch("main.fetch_jobs", return_value=mock_jobs):
        response = client.post("/search")
        assert response.status_code == 200
        assert "Senior Python Engineer" in response.text
        assert "Acme Corp" in response.text

    saved = db_session.query(SavedJob).filter(SavedJob.job_id == "test-job-1").first()
    assert saved is not None
    assert saved.title == "Senior Python Engineer"


def test_get_job_detail(client, db_session):
    job = SavedJob(
        job_id="detail-1",
        site="indeed",
        title="Data Engineer",
        company="Data Corp",
        location="Austin, TX",
        job_url="https://example.com/job/2",
        description="Detailed job description here.",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    response = client.get(f"/job/{job.id}")
    assert response.status_code == 200
    assert "Detailed job description here." in response.text


def test_get_job_detail_markdown_rendering(client, db_session):
    markdown_text = (
        "**Why join us:**\n\n"
        "**Culture:** Flexible work\\-life balance \\& perks.\n\n"
        "* Develop strategies\n"
        "* Lead cross-functional teams"
    )
    job = SavedJob(
        job_id="md-1",
        site="indeed",
        title="Category Manager",
        company="Superior Plus",
        location="Wayne, PA",
        job_url="https://example.com/job/md",
        description=markdown_text,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    response = client.get(f"/job/{job.id}")
    assert response.status_code == 200
    assert "<strong>Why join us:</strong>" in response.text
    assert "work-life balance &amp; perks" in response.text
    assert "<li>Develop strategies</li>" in response.text
    assert "<li>Lead cross-functional teams</li>" in response.text


def test_get_job_detail_not_found(client):
    response = client.get("/job/999999")
    assert response.status_code == 200
    assert "Job not found." in response.text


def test_hide_job(client):
    response = client.delete("/job/1")
    assert response.status_code == 200
    assert response.text == ""
