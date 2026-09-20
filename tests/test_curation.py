import datetime
import io
import json

import openpyxl
from sqlalchemy.orm import Session

from pyjobs.database import sync_job_classifications
from pyjobs.models import JobApplication, SavedJob
from pyjobs.services.scraper import _parse_valid_float, categorize_salary, classify_seniority


def test_classify_seniority():
    assert classify_seniority("VP of Engineering") == "Executive / VP"
    assert classify_seniority("Chief Technology Officer") == "Executive / VP"
    assert classify_seniority("Head of Quality") == "Executive / VP"
    assert classify_seniority("SVP, Finance") == "Executive / VP"
    assert classify_seniority("EVP of Operations") == "Executive / VP"
    assert classify_seniority("AVP, Clinical Operations") == "Executive / VP"
    assert classify_seniority("President and CEO") == "Executive / VP"
    assert classify_seniority("Executive Director, Quality Systems") == "Executive / VP"

    assert classify_seniority("Director of Quality Assurance") == "Director"
    assert classify_seniority("Dir. Manufacturing") == "Director"
    assert classify_seniority("Sr Director, Global Operations Leader") == "Director"

    assert classify_seniority("Engineering Manager") == "Manager"
    assert classify_seniority("QA Manager") == "Manager"
    assert classify_seniority("Manager, Quality Systems and Risk Management") == "Manager"
    assert classify_seniority("Manager, Corrective Action & Continuous Improvement") == "Manager"
    assert classify_seniority("Senior Manager, Clinical Product Quality") == "Manager"

    assert classify_seniority("QA Team Lead") == "Supervisor / Lead"
    assert classify_seniority("Tech Lead - Python") == "Supervisor / Lead"
    assert classify_seniority("Senior Software Engineer") == "Senior / Principal"
    assert classify_seniority("Sr. Automation Engineer") == "Senior / Principal"
    assert classify_seniority("Staff System Architect") == "Senior / Principal"

    assert classify_seniority("Quality Assurance Specialist") == "Specialist / Contributor"
    assert classify_seniority("Software Engineer") == "Specialist / Contributor"
    assert classify_seniority("") == "Specialist / Contributor"


def test_categorize_salary():
    # Unspecified
    min_sal, max_sal, intv, bracket = categorize_salary(None, None, "yearly")
    assert min_sal is None
    assert max_sal is None
    assert bracket == "Unspecified"

    # Hourly rate annualization (2080 hours)
    min_sal, max_sal, intv, bracket = categorize_salary(50.0, 60.0, "hourly")
    assert min_sal == 50.0 * 2080
    assert max_sal == 60.0 * 2080
    # $124,800 is in $120k - $160k
    assert bracket == "$120k - $160k"

    # Monthly rate annualization (12 months)
    min_sal, max_sal, intv, bracket = categorize_salary(5000.0, 6000.0, "monthly")
    assert min_sal == 60000.0
    assert max_sal == 72000.0
    assert bracket == "< $80k"

    # Brackets
    assert categorize_salary(70000, 75000, "yearly")[3] == "< $80k"
    assert categorize_salary(90000, 110000, "yearly")[3] == "$80k - $120k"
    assert categorize_salary(130000, 150000, "yearly")[3] == "$120k - $160k"
    assert categorize_salary(170000, 190000, "yearly")[3] == "$160k - $200k"
    assert categorize_salary(210000, 250000, "yearly")[3] == "$200k+"


def _seed_jobs(db: Session) -> list[SavedJob]:
    now = datetime.datetime.now(datetime.UTC)
    jobs = [
        SavedJob(
            job_id="job-1",
            title="Director of QA",
            company="Acme Corp",
            location="Philadelphia, PA",
            site="linkedin",
            seniority_level="Director",
            salary_bracket="$160k - $200k",
            min_salary=160000.0,
            max_salary=180000.0,
            salary_interval="yearly",
            salary_source="$160k - $180k/yr",
            date_posted=now - datetime.timedelta(hours=5),
            is_hidden=False,
        ),
        SavedJob(
            job_id="job-2",
            title="Senior QA Engineer",
            company="Beta Labs",
            location="New York, NY",
            site="indeed",
            seniority_level="Senior / Principal",
            salary_bracket="$120k - $160k",
            min_salary=130000.0,
            max_salary=145000.0,
            salary_interval="yearly",
            salary_source="$130k - $145k/yr",
            date_posted=now - datetime.timedelta(days=2),
            is_hidden=False,
        ),
        SavedJob(
            job_id="job-3",
            title="QA Specialist",
            company="Gamma Health",
            location="Remote",
            site="google",
            seniority_level="Specialist / Contributor",
            salary_bracket="Unspecified",
            min_salary=None,
            max_salary=None,
            salary_interval="yearly",
            salary_source=None,
            date_posted=now - datetime.timedelta(days=10),
            is_hidden=False,
        ),
        SavedJob(
            job_id="job-4",
            title="Hidden Manager",
            company="Delta Inc",
            location="Philadelphia, PA",
            site="linkedin",
            seniority_level="Manager",
            salary_bracket="$120k - $160k",
            min_salary=125000.0,
            max_salary=135000.0,
            salary_interval="yearly",
            salary_source="$125k - $135k/yr",
            date_posted=now - datetime.timedelta(days=1),
            is_hidden=True,
        ),
    ]
    for j in jobs:
        db.add(j)
    db.commit()
    return jobs


def test_index_loads_saved_jobs_immediately(client, db_session):
    _seed_jobs(db_session)
    response = client.get("/")
    assert response.status_code == 200
    assert "Director of QA" in response.text
    assert "Senior QA Engineer" in response.text
    assert "QA Specialist" in response.text
    # Hidden job should NOT appear by default
    assert "Hidden Manager" not in response.text


def test_jobs_filter_endpoint(client, db_session):
    _seed_jobs(db_session)

    # Filter by text search q
    res = client.get("/jobs/filter?q=Director")
    assert res.status_code == 200
    assert "Director of QA" in res.text
    assert "Senior QA Engineer" not in res.text

    # Filter by Seniority
    res = client.get("/jobs/filter?seniority=Senior / Principal")
    assert res.status_code == 200
    assert "Senior QA Engineer" in res.text
    assert "Director of QA" not in res.text

    # Filter by Salary Bracket
    res = client.get("/jobs/filter?salary_bracket=$160k - $200k")
    assert res.status_code == 200
    assert "Director of QA" in res.text
    assert "Senior QA Engineer" not in res.text

    # Filter by Job Board
    res = client.get("/jobs/filter?site=indeed")
    assert res.status_code == 200
    assert "Senior QA Engineer" in res.text
    assert "Director of QA" not in res.text

    # Filter by Date Range (past 24h should only include job-1)
    res = client.get("/jobs/filter?date_range=24h")
    assert res.status_code == 200
    assert "Director of QA" in res.text
    assert "Senior QA Engineer" not in res.text

    # Show hidden jobs
    res = client.get("/jobs/filter?show_hidden=true")
    assert res.status_code == 200
    assert "Hidden Manager" in res.text
    assert "Director of QA" not in res.text


def test_jobs_filter_grouping(client, db_session):
    _seed_jobs(db_session)

    # Group by Company
    res = client.get("/jobs/filter?group_by=company")
    assert res.status_code == 200
    assert 'details class="group-section' in res.text
    assert "Acme Corp" in res.text
    assert "Beta Labs" in res.text

    # Group by Seniority
    res = client.get("/jobs/filter?group_by=seniority")
    assert res.status_code == 200
    assert "Director" in res.text
    assert "Senior / Principal" in res.text


def test_soft_delete_hide_and_unhide(client, db_session):
    _seed_jobs(db_session)

    # Hide job 1
    res = client.post("/job/1/hide")
    assert res.status_code == 200
    job1 = db_session.query(SavedJob).filter(SavedJob.id == 1).first()
    assert job1 is not None
    assert job1.is_hidden is True

    # Unhide job 1
    res = client.post("/job/1/unhide")
    assert res.status_code == 200
    db_session.refresh(job1)
    assert job1.is_hidden is False


def test_export_jobs_csv(client, db_session):
    _seed_jobs(db_session)
    res = client.get("/jobs/export?format=csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="curated_jobs.csv"' in res.headers["content-disposition"]
    csv_text = res.text
    assert "Title,Company,Location,Seniority,Salary Bracket" in csv_text
    assert "Director of QA" in csv_text
    assert "Beta Labs" in csv_text


def test_export_jobs_xlsx(client, db_session):
    _seed_jobs(db_session)
    res = client.get("/jobs/export?format=xlsx")
    assert res.status_code == 200
    assert (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        in res.headers["content-type"]
    )
    assert 'attachment; filename="curated_jobs.xlsx"' in res.headers["content-disposition"]

    # Verify openpyxl can parse the binary output
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    sheet = wb.active
    assert sheet is not None
    rows = list(sheet.iter_rows(values_only=True))
    header = rows[0]
    assert "Title" in header
    assert "Company" in header
    assert "Salary Bracket" in header
    titles = [row[0] for row in rows[1:]]
    assert "Director of QA" in titles
    assert "Senior QA Engineer" in titles


def test_export_jobs_json(client, db_session):
    _seed_jobs(db_session)
    res = client.get("/jobs/export?format=json")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert 'attachment; filename="curated_jobs.json"' in res.headers["content-disposition"]

    parsed = json.loads(res.text)
    assert isinstance(parsed, list)
    assert len(parsed) == 3  # Non-hidden jobs
    titles = [item["Title"] for item in parsed]
    assert "Director of QA" in titles


def test_parse_valid_float():
    assert _parse_valid_float(None) is None
    assert _parse_valid_float(float("nan")) is None
    assert _parse_valid_float("nan") is None
    assert _parse_valid_float("NaN") is None
    assert _parse_valid_float("invalid") is None
    assert _parse_valid_float(120000) == 120000.0
    assert _parse_valid_float("55.5") == 55.5


def test_sync_job_classifications(db_session):
    # Seed outdated/unclassified job records
    job1 = SavedJob(
        job_id="sync-1",
        title="QA Manager",
        company="HealthCorp",
        location="Philadelphia, PA",
        site="linkedin",
        seniority_level="Specialist / Contributor",  # Stale/default
        salary_bracket="Unspecified",
        salary_source="USD 120000.0 - 150000.0 / yearly",
        min_salary=None,
        max_salary=None,
    )
    job2 = SavedJob(
        job_id="sync-2",
        title="Sr Director of Engineering",
        company="TechCorp",
        location="Remote",
        site="linkedin",
        seniority_level="Specialist / Contributor",  # Stale/default
        salary_bracket="Unspecified",
        salary_source="None nan - nan / None",  # Corrupted source
        min_salary=None,
        max_salary=None,
    )
    db_session.add_all([job1, job2])
    db_session.commit()

    # Run synchronization
    updated = sync_job_classifications(db_session)
    assert updated == 2

    db_session.refresh(job1)
    db_session.refresh(job2)

    # Verify job1 was reclassified and salary backfilled
    assert job1.seniority_level == "Manager"
    assert job1.min_salary == 120000.0
    assert job1.max_salary == 150000.0
    assert job1.salary_bracket == "$120k - $160k"

    # Verify job2 was reclassified and corrupt salary_source cleaned to None
    assert job2.seniority_level == "Director"
    assert job2.salary_source is None
    assert job2.salary_bracket == "Unspecified"


def test_filter_exclude_tracked_jobs(client, db_session):
    now = datetime.datetime.now(datetime.UTC)

    # Job 1: Untracked
    job1 = SavedJob(
        job_id="job-untracked-1",
        title="Untracked Python Engineer",
        company="Alpha Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/untracked-1",
        is_hidden=False,
    )
    # Job 2: Tracked with application in status 'saved'
    job2 = SavedJob(
        job_id="job-tracked-saved",
        title="Saved DevOps Lead",
        company="Beta Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/tracked-2",
        is_hidden=False,
    )
    # Job 3: Tracked with application in status 'applied'
    job3 = SavedJob(
        job_id="job-tracked-applied",
        title="Applied Tech Lead",
        company="Gamma Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/tracked-3",
        is_hidden=False,
    )
    # Job 4: Tracked with application in status 'interviewing'
    job4 = SavedJob(
        job_id="job-tracked-interview",
        title="Interviewing Architect",
        company="Delta Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/tracked-4",
        is_hidden=False,
    )
    # Job 5: Tracked with application in status 'cancelled'
    job5 = SavedJob(
        job_id="job-tracked-cancelled",
        title="Cancelled PM",
        company="Epsilon Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/tracked-5",
        is_hidden=False,
    )
    # Job 6: Manually logged application matching job_url (no direct FK)
    job6 = SavedJob(
        job_id="job-url-matched",
        title="URL Match Staff Eng",
        company="Zeta Systems",
        location="Remote",
        site="linkedin",
        date_posted=now,
        job_url="https://jobs.example.com/tracked-6",
        is_hidden=False,
    )

    db_session.add_all([job1, job2, job3, job4, job5, job6])
    db_session.commit()

    # Create associated JobApplications
    app2 = JobApplication(
        saved_job_id=job2.id,
        title=job2.title,
        company=job2.company,
        status="saved",
        job_url=job2.job_url,
    )
    app3 = JobApplication(
        saved_job_id=job3.id,
        title=job3.title,
        company=job3.company,
        status="applied",
        job_url=job3.job_url,
    )
    app4 = JobApplication(
        saved_job_id=job4.id,
        title=job4.title,
        company=job4.company,
        status="interviewing",
        job_url=job4.job_url,
    )
    app5 = JobApplication(
        saved_job_id=job5.id,
        title=job5.title,
        company=job5.company,
        status="cancelled",
        job_url=job5.job_url,
    )
    app6 = JobApplication(
        saved_job_id=None,
        title="External Role",
        company="Zeta Systems",
        status="applied",
        job_url=job6.job_url,
    )
    db_session.add_all([app2, app3, app4, app5, app6])
    db_session.commit()

    # Test 1: When exclude_tracked=false, all jobs appear
    res_all = client.get("/jobs/filter?exclude_tracked=false")
    assert res_all.status_code == 200
    assert "Untracked Python Engineer" in res_all.text
    assert "Saved DevOps Lead" in res_all.text
    assert "Applied Tech Lead" in res_all.text
    assert "Interviewing Architect" in res_all.text
    assert "Cancelled PM" in res_all.text
    assert "URL Match Staff Eng" in res_all.text

    # Test 2: When exclude_tracked=true, all tracked jobs (any status or url match) are hidden
    res_filtered = client.get("/jobs/filter?exclude_tracked=true")
    assert res_filtered.status_code == 200
    assert "Untracked Python Engineer" in res_filtered.text
    assert "Saved DevOps Lead" not in res_filtered.text
    assert "Applied Tech Lead" not in res_filtered.text
    assert "Interviewing Architect" not in res_filtered.text
    assert "Cancelled PM" not in res_filtered.text
    assert "URL Match Staff Eng" not in res_filtered.text

    # Test 3: Index endpoint respects exclude_tracked=true
    res_index = client.get("/?exclude_tracked=true")
    assert res_index.status_code == 200
    assert "Untracked Python Engineer" in res_index.text
    assert "Saved DevOps Lead" not in res_index.text
    assert "Applied Tech Lead" not in res_index.text

    # Test 4: Export endpoint respects exclude_tracked=true
    res_export = client.get("/jobs/export?format=json&exclude_tracked=true")
    assert res_export.status_code == 200
    export_data = json.loads(res_export.text)
    assert len(export_data) == 1
    assert export_data[0]["Title"] == "Untracked Python Engineer"

    # Test 5: Setting filter updates cookie
    res_filter_cookie = client.get("/jobs/filter?exclude_tracked=true")
    assert res_filter_cookie.cookies.get("pyjobs_exclude_tracked") == "true"

    # Test 6: Navigating away and back without query params preserves filter from cookie
    client.cookies.set("pyjobs_exclude_tracked", "true")
    res_nav_back = client.get("/")
    assert res_nav_back.status_code == 200
    assert "Untracked Python Engineer" in res_nav_back.text
    assert "Saved DevOps Lead" not in res_nav_back.text
    assert 'id="exclude_tracked"' in res_nav_back.text
    assert "checked" in res_nav_back.text

    # Test 7: Export endpoint without explicit param respects cookie
    res_export_cookie = client.get("/jobs/export?format=json")
    assert res_export_cookie.status_code == 200
    export_cookie_data = json.loads(res_export_cookie.text)
    assert len(export_cookie_data) == 1
    assert export_cookie_data[0]["Title"] == "Untracked Python Engineer"

    # Test 8: Toggling off updates cookie to 'false' and nav back loads unfiltered
    res_filter_off = client.get("/jobs/filter?exclude_tracked=false")
    assert res_filter_off.cookies.get("pyjobs_exclude_tracked") == "false"

    client.cookies.set("pyjobs_exclude_tracked", "false")
    res_nav_back_unfiltered = client.get("/")
    assert res_nav_back_unfiltered.status_code == 200
    assert "Untracked Python Engineer" in res_nav_back_unfiltered.text
    assert "Saved DevOps Lead" in res_nav_back_unfiltered.text
