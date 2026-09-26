from unittest.mock import patch

import pytest

from pyjobs.models import Company, JobApplication, SavedJob, SearchProfile, UserPreference
from pyjobs.services.companies import (
    company_name_from_scrape,
    get_or_create_company_site,
    infer_company_from_description,
    is_valid_company_name,
    sync_company_profiles,
)
from pyjobs.services.task_manager import ScrapeTaskState, _ingest_jobs_for_profile


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Company: Acme Robotics", "Acme Robotics"),
        ("## Employer: **Acme & Sons**", "Acme & Sons"),
        (
            "<div><strong>Employer:</strong> Acme&nbsp;Industries</div>",
            "Acme Industries",
        ),
        (
            "**Company:** [Acme Labs](https://example.test)\nRole details follow.",
            "Acme Labs",
        ),
        ("*Employer:* _Acme Labs_", "Acme Labs"),
    ],
)
def test_infers_only_explicit_company_or_employer_line(description, expected):
    assert infer_company_from_description(description) == expected


@pytest.mark.parametrize(
    "description",
    [
        "We are a company that builds dependable software for customers.",
        "Join Acme, an employer that values collaboration.",
        "The job is based in Austin. Company: Acme is mentioned in the body.",
        "Company: none",
        "Company: Acme Corp\nEmployer: Another Employer",
    ],
)
def test_does_not_infer_ambiguous_or_placeholder_attribution(description):
    assert infer_company_from_description(description) is None


def test_company_name_validation_rejects_scraper_sentinels():
    assert company_name_from_scrape(" none ", "Company: Acme") == "Acme"
    assert not is_valid_company_name(None)
    assert not is_valid_company_name(" NONE. ")
    assert is_valid_company_name(" Acme  Robotics ")


def test_modern_scrape_inference_and_manual_company_survive_refresh(db_session):
    profile = SearchProfile(name="Test profile", positions="Engineer", location="Remote")
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    task = ScrapeTaskState("task", profile.id, profile.name)
    initial = {
        "job_id": "modern-inferred-company",
        "title": "Software Engineer",
        "company": "none",
        "location": "Remote",
        "description": "<p><strong>Company:</strong> Acme Robotics</p>",
    }

    _ingest_jobs_for_profile(db_session, profile, [initial], task)
    saved_job = db_session.query(SavedJob).filter_by(job_id=initial["job_id"]).one()

    assert saved_job.company_id is not None
    acme = db_session.get(Company, saved_job.company_id)
    assert saved_job.company == "Acme Robotics"
    assert acme is not None and acme.name == "Acme Robotics"

    corrected_company, _ = get_or_create_company_site(
        db_session, "Manual Correction Inc.", "Remote"
    )
    assert corrected_company is not None
    db_session.flush()
    saved_job.company = "Manual Correction Inc."
    # The next refresh must reconcile this corrected name with its company relation.
    db_session.commit()

    _ingest_jobs_for_profile(
        db_session,
        profile,
        [
            {
                **initial,
                "company": "Scraper Conflicting Corp",
                "description": "Employer: Scraper Conflicting Corp",
            }
        ],
        task,
    )
    db_session.refresh(saved_job)
    assert saved_job.company == "Manual Correction Inc."
    assert saved_job.company_id == corrected_company.id

    _ingest_jobs_for_profile(
        db_session,
        profile,
        [
            {
                **initial,
                "company": "none",
                "description": "We are a growing company with customers worldwide.",
            }
        ],
        task,
    )
    db_session.refresh(saved_job)
    assert saved_job.company == "Manual Correction Inc."
    assert saved_job.company_id == corrected_company.id
    assert db_session.query(Company).filter_by(name_key="none").first() is None


def test_modern_scrape_does_not_create_company_for_placeholder_or_ambiguous_text(db_session):
    profile = SearchProfile(name="Test profile", positions="Engineer", location="Remote")
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)

    _ingest_jobs_for_profile(
        db_session,
        profile,
        [
            {
                "job_id": "placeholder-company",
                "title": "Engineer",
                "company": "none",
                "location": "Remote",
                "description": "We are a company with a strong engineering culture.",
            }
        ],
        ScrapeTaskState("task", profile.id, profile.name),
    )

    saved_job = db_session.query(SavedJob).filter_by(job_id="placeholder-company").one()
    assert saved_job.company == ""
    assert saved_job.company_id is None
    assert db_session.query(Company).filter_by(name_key="none").first() is None


def test_legacy_scrape_infers_company_and_preserves_it_on_unknown_refresh(client, db_session):
    db_session.add(UserPreference(location="Remote", positions="Engineer"))
    db_session.commit()
    scraped_job = {
        "job_id": "legacy-inferred-company",
        "title": "Engineer",
        "company": "none",
        "location": "Remote",
        "description": "<p><strong>Employer:</strong> Legacy Systems</p>",
    }

    with patch("pyjobs.routers.discovery.fetch_jobs", return_value=[scraped_job]):
        response = client.post("/search")
    assert response.status_code == 200

    saved_job = db_session.query(SavedJob).filter_by(job_id=scraped_job["job_id"]).one()
    inferred_company_id = saved_job.company_id
    assert inferred_company_id is not None
    assert saved_job.company == "Legacy Systems"
    assert db_session.get(Company, inferred_company_id) is not None

    corrected_company, _ = get_or_create_company_site(
        db_session, "Manual Legacy Correction", "Remote"
    )
    db_session.flush()
    assert corrected_company is not None
    saved_job.company = "Manual Legacy Correction"
    saved_job.company_id = corrected_company.id
    db_session.commit()
    company_id = corrected_company.id

    with patch(
        "pyjobs.routers.discovery.fetch_jobs",
        return_value=[
            {
                **scraped_job,
                "company": "none",
                "description": "We are a company building useful products.",
            }
        ],
    ):
        response = client.post("/search")
    assert response.status_code == 200

    db_session.refresh(saved_job)
    assert saved_job.company == "Manual Legacy Correction"
    assert saved_job.company_id == company_id
    assert db_session.query(Company).filter_by(name_key="none").first() is None


def test_backfill_detaches_historical_placeholder_company_without_losing_strings(db_session):
    placeholder = Company(name="none", name_key="none")
    db_session.add(placeholder)
    db_session.flush()
    job = SavedJob(
        job_id="old-placeholder-job",
        title="Engineer",
        company="none",
        location="Remote",
        company_id=placeholder.id,
    )
    application = JobApplication(
        title="Engineer",
        company="none",
        location="Remote",
        company_id=placeholder.id,
    )
    db_session.add_all([job, application])
    db_session.commit()

    sync_company_profiles(db_session)

    db_session.refresh(job)
    db_session.refresh(application)
    assert job.company == "none"
    assert application.company == "none"
    assert job.company_id is None
    assert application.company_id is None
