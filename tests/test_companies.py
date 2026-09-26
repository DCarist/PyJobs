import html
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from pyjobs import database
from pyjobs.models import Company, CompanySite, JobApplication, SavedJob, UserPreference
from pyjobs.services.companies import get_or_create_company_site, sync_company_profiles
from pyjobs.services.task_manager import create_task, run_scrape_task_sync


@pytest.fixture
def migration_database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}")
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    yield engine, session_factory
    engine.dispose()


def test_fresh_database_creates_company_schema_and_home_location(migration_database):
    engine, session_factory = migration_database

    database.init_db()

    inspector = inspect(engine)
    assert {"companies", "company_sites"}.issubset(inspector.get_table_names())
    assert "home_location" in {
        column["name"] for column in inspector.get_columns("user_preferences")
    }
    for table in ("saved_jobs", "job_applications"):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert columns["company_id"]["nullable"] is True
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        assert f"ix_{table}_company_id" in indexes

    with session_factory() as session:
        preference = UserPreference(location="Search target")
        session.add(preference)
        session.commit()
        assert preference.location == "Search target"
        assert preference.home_location == ""


def test_legacy_database_migration_backfills_unlinked_records(migration_database):
    engine, session_factory = migration_database
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE user_preferences (
                id INTEGER PRIMARY KEY,
                location VARCHAR DEFAULT '',
                positions VARCHAR DEFAULT '',
                fields VARCHAR DEFAULT '',
                sites VARCHAR DEFAULT 'linkedin,indeed,google',
                is_remote BOOLEAN DEFAULT 0,
                candidate_name VARCHAR DEFAULT '',
                resume_filename_pattern VARCHAR DEFAULT '{name} {date}.{ext}',
                resume_date_format VARCHAR DEFAULT '%m-%d-%Y'
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE saved_jobs (
                id INTEGER PRIMARY KEY,
                job_id VARCHAR NOT NULL UNIQUE,
                site VARCHAR DEFAULT '',
                title VARCHAR DEFAULT '',
                company VARCHAR DEFAULT '',
                location VARCHAR DEFAULT '',
                salary_source VARCHAR,
                min_salary FLOAT,
                max_salary FLOAT,
                salary_interval VARCHAR DEFAULT 'yearly',
                seniority_level VARCHAR DEFAULT 'Specialist / Contributor',
                salary_bracket VARCHAR DEFAULT 'Unspecified',
                job_url VARCHAR DEFAULT '',
                description VARCHAR,
                date_posted DATETIME,
                is_hidden BOOLEAN DEFAULT 0,
                is_stale BOOLEAN DEFAULT 0,
                is_link_dead BOOLEAN DEFAULT 0,
                last_verified_at DATETIME,
                saved_at DATETIME DEFAULT '2026-09-25 00:00:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE job_applications (
                id INTEGER PRIMARY KEY,
                saved_job_id INTEGER REFERENCES saved_jobs(id) ON DELETE SET NULL,
                title VARCHAR DEFAULT '',
                company VARCHAR DEFAULT '',
                location VARCHAR DEFAULT '',
                salary_stated VARCHAR,
                job_url VARCHAR,
                description TEXT,
                status VARCHAR DEFAULT 'applied',
                applied_date DATE,
                method VARCHAR DEFAULT 'Company Website',
                account_created BOOLEAN DEFAULT 0,
                portal_username VARCHAR,
                confirmation_number VARCHAR,
                follow_up_date DATE,
                notes TEXT,
                created_at DATETIME DEFAULT '2026-09-25 00:00:00',
                updated_at DATETIME DEFAULT '2026-09-25 00:00:00',
                resume_version_id INTEGER
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO saved_jobs (id, job_id, title, company, location)
            VALUES
                (1, 'old-job-1', 'Engineer', '  Acme   Corp ', 'Allentown, PA'),
                (2, 'old-job-2', 'Analyst', 'ACME CORP', 'Allentown, PA, US'),
                (3, 'old-job-3', 'Designer', 'Acme Corp', 'Pittsburgh, PA'),
                (4, 'old-job-4', 'Remote Role', 'RemoteCo', 'Remote - US')
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO job_applications (id, saved_job_id, title, company, location)
            VALUES (1, 1, 'Manual role', 'Manual App Co', 'Portland, OR')
            """
        )

    database.init_db()

    inspector = inspect(engine)
    assert "home_location" in {
        column["name"] for column in inspector.get_columns("user_preferences")
    }
    for table in ("saved_jobs", "job_applications"):
        assert "company_id" in {column["name"] for column in inspector.get_columns(table)}

    with session_factory() as session:
        jobs = session.query(SavedJob).order_by(SavedJob.id).all()
        applications = session.query(JobApplication).all()
        companies = session.query(Company).all()
        sites = session.query(CompanySite).all()

        assert len(companies) == 3
        assert jobs[0].company_id == jobs[1].company_id == jobs[2].company_id
        acme_sites = [site for site in sites if site.company_id == jobs[0].company_id]
        assert {site.location for site in acme_sites} == {
            "Allentown, PA, US",
            "Pittsburgh, PA, US",
        }
        assert all(site.address == "" for site in acme_sites)
        assert jobs[3].company_id is not None
        assert not any(site.company_id == jobs[3].company_id for site in sites)
        assert applications[0].company_id != jobs[0].company_id
        assert applications[0].company_profile.name == "Manual App Co"
        assert [site.location for site in applications[0].company_profile.sites] == [
            "Portland, OR, US"
        ]

    database.init_db()
    with session_factory() as session:
        assert session.query(Company).count() == 3
        assert session.query(CompanySite).count() == 3


def test_company_site_helper_normalizes_and_preserves_manual_address(db_session):
    company, first_site = get_or_create_company_site(
        db_session, "  North   Star  ", "Allentown, PA"
    )
    equivalent_company, equivalent_site = get_or_create_company_site(
        db_session, "north star", "Allentown, PA, US"
    )
    _, second_site = get_or_create_company_site(db_session, "NORTH STAR", "Pittsburgh, PA")

    assert company is not None
    assert first_site is not None
    assert second_site is not None
    assert company is equivalent_company
    assert first_site is equivalent_site
    assert second_site is not first_site
    assert company.id is None
    assert first_site.id is None

    db_session.flush()
    first_site.address = "123 Main Street"
    db_session.commit()

    same_company, saved_site = get_or_create_company_site(
        db_session, "North Star", "ALLENTOWN, pa, us"
    )
    assert same_company is not None
    assert saved_site is not None
    assert same_company.id == company.id
    assert saved_site.id == first_site.id
    assert saved_site.address == "123 Main Street"
    assert db_session.query(Company).count() == 1
    assert db_session.query(CompanySite).count() == 2
    historical_job = SavedJob(
        job_id="historical-address",
        company="North Star",
        location="Allentown, PA, US",
    )
    db_session.add(historical_job)
    db_session.commit()
    sync_company_profiles(db_session)

    assert historical_job.company_id == company.id
    assert first_site.address == "123 Main Street"
    assert db_session.query(CompanySite).count() == 2


def test_backfill_uses_manual_application_identity_and_skips_remote_sites(db_session):
    job = SavedJob(job_id="linked-posting", company="Posting Employer", location="Seattle, WA")
    posting_company, _ = get_or_create_company_site(db_session, job.company, job.location)
    job.company_profile = posting_company
    db_session.add(job)
    db_session.commit()

    application = JobApplication(
        saved_job_id=job.id,
        title="Manually edited role",
        company="Manual Application Company",
        location="Portland, OR",
    )
    remote_job = SavedJob(
        job_id="remote-posting", company="RemoteCo", location="Remote (United States)"
    )
    db_session.add_all([application, remote_job])
    db_session.commit()

    sync_company_profiles(db_session)

    assert application.company_profile is not None
    assert application.company_profile.name == "Manual Application Company"
    assert application.company_profile.id != job.company_id
    assert [site.location for site in application.company_profile.sites] == ["Portland, OR, US"]
    assert remote_job.company_id is not None
    assert remote_job.company_profile is not None
    assert remote_job.company_profile.sites == []
    assert db_session.query(CompanySite).count() == 2


def test_unknown_company_skips_and_remote_company_has_no_site(db_session):
    assert get_or_create_company_site(db_session, " Unknown ", "Seattle, WA") == (None, None)
    assert get_or_create_company_site(db_session, "Unknown Company", "Seattle, WA") == (None, None)
    assert get_or_create_company_site(db_session, "RemoteCo", "Unknown")[1] is None

    company, site = get_or_create_company_site(db_session, "RemoteCo", "Work from home")
    assert company is not None
    assert site is None
    db_session.flush()
    assert company.sites == []


def test_scrape_refresh_and_application_edit_preserve_historical_sites(client, db_session):
    profile_response = client.post(
        "/profiles",
        data={
            "name": "Local",
            "positions": "Engineer",
            "location": "Allentown, PA",
            "distance_miles": 10,
        },
    )
    assert profile_response.status_code == 200
    from pyjobs.models import SearchProfile

    profile = db_session.query(SearchProfile).filter_by(name="Local").one()

    def scrape(location):
        task = create_task(profile.name, profile.id)
        with patch(
            "pyjobs.services.task_manager.fetch_jobs",
            return_value=[
                {
                    "job_id": "observed-1",
                    "company": "Acme",
                    "title": "Engineer",
                    "location": location,
                    "site": "linkedin",
                }
            ],
        ) as fetch:
            run_scrape_task_sync(task.task_id, profile.id, client.app.state.session_factory)
        assert fetch.call_args.kwargs["distance_miles"] == 10

    scrape("Allentown, PA")
    job = db_session.query(SavedJob).filter_by(job_id="observed-1").one()
    company = db_session.query(Company).filter_by(name_key="acme").one()
    assert job.company_id == company.id
    assert len(company.sites) == 1
    company.sites[0].address = "123 Main St"
    db_session.commit()
    scrape("Pittsburgh, PA")
    db_session.refresh(job)
    assert job.location == "Pittsburgh, PA"
    assert {site.location: site.address for site in company.sites} == {
        "Allentown, PA, US": "123 Main St",
        "Pittsburgh, PA, US": "",
    }
    sync_company_profiles(db_session)
    assert company.sites[0].address == "123 Main St"
    tracked = client.post(f"/job/{job.id}/track?status=saved")
    assert tracked.status_code == 200
    application = db_session.query(JobApplication).filter_by(saved_job_id=job.id).one()
    assert application.company_id == job.company_id
    edited = client.post(
        f"/applications/{application.id}/job-info",
        data={
            "company": "New Employer",
            "title": "Engineer",
            "location": "Boston, MA",
        },
        follow_redirects=False,
    )
    assert edited.status_code == 303
    db_session.refresh(job)
    db_session.refresh(application)
    assert job.company_id == application.company_id
    assert job.company_id != company.id
    assert [site.location for site in application.company_profile.sites] == ["Boston, MA, US"]
    assert company.sites[0].address == "123 Main St"
    manual = client.post(
        "/applications",
        data={
            "company": "new employer",
            "title": "Analyst",
            "location": "Boston, MA, US",
        },
        follow_redirects=False,
    )
    assert manual.status_code == 303
    assert (
        db_session.query(JobApplication).filter_by(title="Analyst").one().company_id
        == job.company_id
    )


def test_company_directory_sites_directions_and_home_origin(client, db_session):
    from pyjobs.models import SearchProfile

    profile = SearchProfile(name="Target", positions="Engineer", location="Allentown, PA")
    pref = UserPreference(location="Philadelphia, PA")
    company, site = get_or_create_company_site(db_session, " Maps & Co ", "Allentown, PA")
    remote, _ = get_or_create_company_site(db_session, "RemoteCo", "Remote")
    db_session.add_all([profile, pref])
    db_session.commit()
    assert company is not None and site is not None and remote is not None
    assert client.get("/companies/99999").status_code == 404
    directory = client.get("/companies")
    assert "Maps &amp; Co" in directory.text
    assert 'value=""' in directory.text
    no_origin = client.get(f"/companies/{company.id}")
    assert "Approximate (city center)" in " ".join(no_origin.text.split())
    assert 'href="/companies#home-location"' in no_origin.text
    assert "maps/dir/" not in no_origin.text
    assert "No physical sites observed" in client.get(f"/companies/{remote.id}").text

    home = "42 Main St & Broad, Philadelphia, PA"
    response = client.post(
        "/companies/home-location",
        data={"home_location": f"  {home}  "},
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(pref)
    assert pref.home_location == home
    assert pref.location == "Philadelphia, PA"
    assert profile.location == "Allentown, PA"
    detail = client.get(f"/companies/{company.id}")
    urls = re.findall(r'href="(https://www.google.com/maps/dir/[^"]+)"', detail.text)
    assert len(urls) == 1
    params = parse_qs(urlparse(html.unescape(urls[0])).query)
    assert params == {
        "api": ["1"],
        "origin": [home],
        "destination": ["Allentown, PA, US"],
        "travelmode": ["driving"],
    }
    assert "%26" in urls[0] and "Approximate (city center)" in " ".join(detail.text.split())
    assert "123" not in site.address
    assert (
        client.post(
            f"/companies/{company.id}/sites",
            data={
                "location": "Remote",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/companies/{company.id}/sites",
            data={
                "location": "   ",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/companies/{company.id}/sites",
            data={
                "location": "Allentown, PA, US",
            },
        ).status_code
        == 422
    )
    added = client.post(
        f"/companies/{company.id}/sites",
        data={
            "location": "Pittsburgh, PA (Hybrid)",
            "address": "  7 North Ave  ",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    other_site = (
        db_session.query(CompanySite)
        .filter_by(
            company_id=company.id,
            location_key="pittsburgh, pa, us",
        )
        .one()
    )
    assert other_site.address == "7 North Ave"
    assert (
        client.post(
            f"/companies/{remote.id}/sites/{site.id}",
            data={
                "address": "fake",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/companies/{company.id}/sites/99999",
            data={
                "address": "fake",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/companies/99999/sites",
            data={
                "location": "Miami, FL",
            },
        ).status_code
        == 404
    )
    update = client.post(
        f"/companies/{company.id}/sites/{site.id}",
        data={
            "address": "  14 Pine St & Vine  ",
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    db_session.refresh(site)
    assert site.address == "14 Pine St & Vine"
    detail = client.get(f"/companies/{company.id}")
    assert "destination=14+Pine+St+%26+Vine" in detail.text
    clear = client.post(
        f"/companies/{company.id}/sites/{site.id}",
        data={
            "address": "  ",
        },
        follow_redirects=False,
    )
    assert clear.status_code == 303
    db_session.refresh(site)
    assert site.address == ""
    assert "Approximate (city center)" in " ".join(
        client.get(f"/companies/{company.id}").text.split()
    )
    client.post("/companies/home-location", data={"home_location": ""})
    db_session.refresh(pref)
    assert pref.home_location == ""


def test_local_scrape_to_directions_and_filtered_export(client, db_session):
    import json

    from pyjobs.models import SearchProfile

    client.post(
        "/profiles",
        data={
            "name": "Ten mile search",
            "positions": "Engineer",
            "location": "Allentown, PA",
            "distance_miles": 10,
        },
    )
    profile = db_session.query(SearchProfile).filter_by(name="Ten mile search").one()
    task = create_task(profile.name, profile.id)
    with patch(
        "pyjobs.services.task_manager.fetch_jobs",
        return_value=[
            {
                "job_id": "smoke-1",
                "title": "Lead Engineer",
                "company": "Smoke Co",
                "location": "Allentown, PA",
                "site": "linkedin",
                "seniority_level": "Manager",
                "salary_bracket": "$120k - $160k",
            },
        ],
    ) as fetch:
        run_scrape_task_sync(task.task_id, profile.id, client.app.state.session_factory)
    assert fetch.call_args.kwargs["distance_miles"] == 10
    job = db_session.query(SavedJob).filter_by(job_id="smoke-1").one()
    home = client.post(
        "/companies/home-location",
        data={
            "home_location": "42 Main St, Bethlehem, PA",
        },
        follow_redirects=False,
    )
    assert home.status_code == 303
    directory = client.get("/companies")
    assert f"/companies/{job.company_id}" in directory.text
    detail = client.get(f"/companies/{job.company_id}")
    assert "destination=Allentown%2C+PA%2C+US" in detail.text
    address = client.post(
        f"/companies/{job.company_id}/sites",
        data={
            "location": "Allentown, PA, US",
            "address": "11 Market St, Allentown, PA",
        },
        follow_redirects=False,
    )
    assert address.status_code == 303
    detail = client.get(f"/companies/{job.company_id}")
    assert "destination=11+Market+St%2C+Allentown%2C+PA" in detail.text
    filters = [
        ("seniority", "Manager"),
        ("site", "linkedin"),
        ("profile_id", str(profile.id)),
        ("group_by", "location"),
        ("sort", "newest"),
        ("include_unspecified", "false"),
        ("salary_bracket", "$120k - $160k"),
    ]
    filtered = client.get("/jobs/filter", params=filters, headers={"HX-Request": "true"})
    assert filtered.status_code == 200
    assert f'id="job-{job.id}"' in filtered.text
    assert 'class="group-title">Allentown, PA, US' in filtered.text
    exported = client.get("/jobs/export", params=[*filters, ("format", "json")])
    assert [row["Title"] for row in json.loads(exported.text)] == ["Lead Engineer"]


def test_job_company_correction_updates_card_company_and_tracked_application(client, db_session):
    job = SavedJob(
        job_id="missing-employer",
        title="Engineer",
        company="none",
        location="Allentown, PA",
        description="Engineer role with an unlisted employer.",
    )
    application = JobApplication(saved_job=job, title=job.title, company=job.company)
    db_session.add_all([job, application])
    db_session.commit()

    feed = client.get("/")
    assert "Company not identified" in feed.text
    assert "Set company" in feed.text
    detail = client.get(f"/job/{job.id}")
    assert 'name="company"' in detail.text
    assert job.description in detail.text

    invalid = client.post(
        f"/job/{job.id}/company",
        data={"company": "none"},
        headers={"HX-Request": "true"},
    )
    assert "Enter a valid company name." in invalid.text
    db_session.refresh(job)
    assert job.company_id is None

    corrected = client.post(
        f"/job/{job.id}/company",
        data={"company": "  Example   Works  "},
        headers={"HX-Request": "true"},
    )
    assert corrected.status_code == 200
    assert corrected.headers["HX-Trigger-After-Swap"] == "companyUpdated"
    db_session.refresh(job)
    db_session.refresh(application)
    company = db_session.query(Company).filter_by(name_key="example works").one()
    assert job.company == application.company == company.name == "Example Works"
    assert job.company_id == application.company_id == company.id
    assert [(site.location, site.address) for site in company.sites] == [("Allentown, PA, US", "")]
    assert 'value="Example Works"' in corrected.text

    grouped = client.get("/jobs/filter?group_by=company", headers={"HX-Request": "true"})
    assert "Example Works" in grouped.text
    assert f'href="/companies/{company.id}"' in grouped.text
    assert "Company not identified" not in grouped.text


def test_job_company_correction_redirects_without_htmx_and_404s(client, db_session):
    job = SavedJob(job_id="unlinked-employer", title="Analyst", company="none")
    db_session.add(job)
    db_session.commit()
    response = client.post(
        f"/job/{job.id}/company",
        data={"company": "Corrected Employer"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/#job-{job.id}"
    db_session.refresh(job)
    assert job.company_id is not None

    missing = client.post("/job/999999/company", data={"company": "Example"})
    assert missing.status_code == 404


def test_placeholder_company_profiles_are_not_offered_as_employers(client, db_session):
    legacy = Company(name="none", name_key="none")
    db_session.add(legacy)
    db_session.commit()

    directory = client.get("/companies")
    assert f'href="/companies/{legacy.id}"' not in directory.text
    assert client.get(f"/companies/{legacy.id}").status_code == 404


def test_company_profile_shows_feed_jobs_and_tracker_applications(client, db_session):
    company, _ = get_or_create_company_site(db_session, "Atlas Labs", "Austin, TX")
    assert company is not None
    db_session.flush()
    job = SavedJob(
        job_id="atlas-posting",
        title="Research Engineer",
        company=company.name,
        company_id=company.id,
        location="Austin, TX",
        site="linkedin",
    )
    application = JobApplication(
        saved_job=job,
        title=job.title,
        company=company.name,
        company_id=company.id,
        location=job.location,
        status="applied",
        method="Company Website",
    )
    db_session.add_all([job, application])
    db_session.commit()

    directory = client.get("/companies")
    assert f'href="/companies/{company.id}"' in directory.text
    detail = client.get(f"/companies/{company.id}")
    assert detail.status_code == 200
    assert f'id="job-{job.id}"' in detail.text
    assert f'href="/companies/{company.id}"' in detail.text
    assert f'id="app-card-{application.id}"' in detail.text
    assert f'href="/applications/{application.id}"' in detail.text
    company_card = re.search(rf'<div\b[^>]*id="app-card-{application.id}"[^>]*>', detail.text)
    assert company_card is not None and 'draggable="false"' in company_card.group()

    tracker = client.get("/applications?view=kanban")
    assert tracker.status_code == 200
    tracker_card = re.search(rf'<div\b[^>]*id="app-card-{application.id}"[^>]*>', tracker.text)
    assert tracker_card is not None and 'draggable="true"' in tracker_card.group()


def test_company_directory_counts_visible_jobs_and_in_progress_applications(client, db_session):
    companies = {
        name: Company(name=name, name_key=name.casefold())
        for name in ("Active Co", "Archived Co", "Applications Co", "Postings Co")
    }
    db_session.add_all(companies.values())
    db_session.flush()

    jobs = [
        SavedJob(
            job_id=f"activity-{index}",
            company=companies[name].name,
            company_id=companies[name].id,
            is_hidden=hidden,
        )
        for index, (name, hidden) in enumerate(
            [
                ("Active Co", False),
                ("Active Co", False),
                ("Active Co", True),
                ("Archived Co", True),
                ("Postings Co", False),
            ]
        )
    ]
    applications = [
        JobApplication(
            company=companies[name].name,
            company_id=companies[name].id,
            status=status,
        )
        for name, status in [
            ("Active Co", "saved"),
            ("Active Co", "offer"),
            ("Active Co", "rejected"),
            ("Archived Co", "rejected"),
            ("Archived Co", "withdrawn"),
            ("Archived Co", "cancelled"),
            ("Applications Co", "applied"),
            ("Postings Co", "cancelled"),
        ]
    ]
    db_session.add_all([*jobs, *applications])
    db_session.commit()

    def visible_counts(response, name):
        company_id = companies[name].id
        match = re.search(
            rf'<a\b[^>]*href="/companies/{company_id}"[^>]*>(.*?)</a>',
            response.text,
            re.DOTALL,
        )
        if match is None:
            return None
        return tuple(
            int(value)
            for value in re.findall(
                r"(\d+)\s+(?:available posting|active application)", match.group(1)
            )
        )

    all_companies = client.get("/companies")
    assert all_companies.status_code == 200
    assert visible_counts(all_companies, "Active Co") == (2, 2)
    assert visible_counts(all_companies, "Archived Co") == (0, 0)
    assert visible_counts(all_companies, "Applications Co") == (0, 1)
    assert visible_counts(all_companies, "Postings Co") == (1, 0)

    filtered = client.get("/companies?hide_inactive=true")
    assert filtered.status_code == 200
    assert visible_counts(filtered, "Active Co") == (2, 2)
    assert visible_counts(filtered, "Archived Co") is None
    assert visible_counts(filtered, "Applications Co") == (0, 1)
    assert visible_counts(filtered, "Postings Co") == (1, 0)
    assert visible_counts(client.get("/companies?hide_inactive=false"), "Archived Co") == (
        0,
        0,
    )

    for job in jobs:
        job.is_hidden = True
    for application in applications:
        application.status = "withdrawn"
    db_session.commit()
    empty = client.get("/companies?hide_inactive=true")
    assert empty.status_code == 200
    assert all(visible_counts(empty, name) is None for name in companies)
