import datetime
import io
import json

import openpyxl
from sqlalchemy.orm import Session

from models import SavedJob
from scraper import categorize_salary, classify_seniority


def test_classify_seniority():
    assert classify_seniority("VP of Engineering") == "Executive / VP"
    assert classify_seniority("Chief Technology Officer") == "Executive / VP"
    assert classify_seniority("Head of Quality") == "Executive / VP"
    assert classify_seniority("Director of Quality Assurance") == "Director"
    assert classify_seniority("Dir. Manufacturing") == "Director"
    assert classify_seniority("Engineering Manager") == "Manager"
    assert classify_seniority("QA Manager") == "Manager"
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
