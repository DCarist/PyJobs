import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pyjobs.models import ApplicationActivity, ApplicationContact, JobApplication, SavedJob


def test_track_job_from_feed(client: TestClient, db_session: Session):
    # Seed a saved job
    job = SavedJob(
        job_id="test-job-001",
        title="Senior Python Backend Engineer",
        company="TechCorp Global",
        location="Remote",
        salary_bracket="$120k - $160k",
        site="linkedin",
        job_url="https://linkedin.com/jobs/view/123",
        description="We are seeking an experienced Python developer.",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # 1-Click Track from feed
    resp = client.post(f"/job/{job.id}/track")
    assert resp.status_code == 200
    assert "Applied" in resp.text
    assert "View Application" in resp.text

    # Verify JobApplication in database
    app_record = (
        db_session.query(JobApplication).filter(JobApplication.saved_job_id == job.id).first()
    )
    assert app_record is not None
    assert app_record.title == "Senior Python Backend Engineer"
    assert app_record.company == "TechCorp Global"
    assert app_record.status == "applied"
    assert app_record.applied_date == datetime.date.today()
    assert app_record.follow_up_date == datetime.date.today() + datetime.timedelta(days=14)

    # Verify initial activity was recorded
    assert len(app_record.activities) == 1
    assert app_record.activities[0].activity_type == "status_change"
    assert app_record.activities[0].new_status == "applied"


def test_track_job_as_saved_from_feed(client: TestClient, db_session: Session):
    job = SavedJob(
        job_id="test-job-save-001",
        title="Lead DevOps Engineer",
        company="CloudScale Inc",
        location="Remote",
        site="indeed",
        job_url="https://indeed.com/viewjob?jk=789",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    # 1. Click "Save Job" (?status=saved)
    resp = client.post(f"/job/{job.id}/track?status=saved")
    assert resp.status_code == 200
    assert "Saved" in resp.text
    assert "View Application" in resp.text
    assert "Applied" not in resp.text

    # Verify DB state: status is saved, no applied_date yet
    app_record = (
        db_session.query(JobApplication).filter(JobApplication.saved_job_id == job.id).first()
    )
    assert app_record is not None
    assert app_record.status == "saved"
    assert app_record.applied_date is None
    assert len(app_record.activities) == 1
    assert app_record.activities[0].new_status == "saved"

    # 2. Later click "Track Application" (?status=applied) to upgrade
    resp_upgrade = client.post(f"/job/{job.id}/track?status=applied")
    assert resp_upgrade.status_code == 200
    assert "Applied" in resp_upgrade.text
    assert "View Application" in resp_upgrade.text

    db_session.refresh(app_record)
    assert app_record.status == "applied"
    assert app_record.applied_date == datetime.date.today()
    assert len(app_record.activities) == 2
    assert app_record.activities[0].new_status == "applied"


def test_track_duplicate_job_idempotent(client: TestClient, db_session: Session):
    job = SavedJob(
        job_id="test-job-002",
        title="Data Engineer",
        company="DataCo",
        site="indeed",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    resp1 = client.post(f"/job/{job.id}/track")
    assert resp1.status_code == 200

    resp2 = client.post(f"/job/{job.id}/track")
    assert resp2.status_code == 200

    count = db_session.query(JobApplication).filter(JobApplication.saved_job_id == job.id).count()
    assert count == 1


def test_create_manual_application(client: TestClient, db_session: Session):
    data = {
        "company": "Stripe",
        "title": "Staff Infrastructure Engineer",
        "location": "San Francisco, CA",
        "salary_stated": "$200k+",
        "method": "Company Website",
        "status": "applied",
        "applied_date": "2026-09-01",
        "follow_up_date": "",  # should auto-default to +14 days from applied_date
        "job_url": "https://stripe.com/jobs/123",
        "account_created": "true",
        "portal_username": "candidate@example.com",
        "confirmation_number": "STRIPE-789",
        "description": "Infrastructure scalability and distributed systems.",
    }
    resp = client.post("/applications", data=data, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/applications"

    app_record = db_session.query(JobApplication).filter(JobApplication.company == "Stripe").first()
    assert app_record is not None
    assert app_record.applied_date == datetime.date(2026, 9, 1)
    assert app_record.follow_up_date == datetime.date(2026, 9, 15)
    assert app_record.account_created is True
    assert app_record.portal_username == "candidate@example.com"
    assert app_record.confirmation_number == "STRIPE-789"
    assert len(app_record.activities) == 1


def test_update_application_status_and_audit_log(client: TestClient, db_session: Session):
    app_record = JobApplication(
        company="OpenAI",
        title="Research Engineer",
        status="applied",
        applied_date=datetime.date(2026, 9, 1),
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # Move to screening
    resp = client.post(
        f"/applications/{app_record.id}/status",
        data={"new_status": "screening", "note": "Recruiter scheduled phone screen"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(app_record)
    assert app_record.status == "screening"

    # Check activity log
    activities = (
        db_session.query(ApplicationActivity)
        .filter(ApplicationActivity.application_id == app_record.id)
        .all()
    )
    assert len(activities) == 1
    assert activities[0].old_status == "applied"
    assert activities[0].new_status == "screening"
    assert "Recruiter scheduled phone screen" in activities[0].note


def test_applications_dashboard_views(client: TestClient, db_session: Session):
    app1 = JobApplication(company="Anthropic", title="Frontend Architect", status="interviewing")
    app2 = JobApplication(company="Google", title="Site Reliability", status="saved")
    db_session.add_all([app1, app2])
    db_session.commit()

    # Kanban View
    resp_kanban = client.get("/applications?view=kanban")
    assert resp_kanban.status_code == 200
    assert "Frontend Architect" in resp_kanban.text
    assert "Site Reliability" in resp_kanban.text
    assert "Pipeline Board" in resp_kanban.text
    assert 'draggable="true"' in resp_kanban.text
    assert f'data-app-id="{app1.id}"' in resp_kanban.text
    assert 'data-stage="interviewing"' in resp_kanban.text
    assert f"/applications/{app1.id}" in resp_kanban.text
    assert "+ Log External Application" in resp_kanban.text

    # Table View
    resp_table = client.get("/applications?view=table")
    assert resp_table.status_code == 200
    assert "Frontend Architect" in resp_table.text
    assert "Table View" in resp_table.text

    # Filter query
    resp_filter = client.get("/applications?q=Anthropic")
    assert resp_filter.status_code == 200
    assert "Anthropic" in resp_filter.text
    assert "Google" not in resp_filter.text


def test_kanban_drag_drop_status_update_with_hx_target(client: TestClient, db_session: Session):
    app_record = JobApplication(company="Figma", title="Product Designer", status="applied")
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    resp = client.post(
        f"/applications/{app_record.id}/status?view=kanban",
        data={"new_status": "interviewing"},
        headers={"HX-Target": "applications-content"},
    )
    assert resp.status_code == 200
    assert "Product Designer" in resp.text
    assert 'data-stage="interviewing"' in resp.text

    db_session.refresh(app_record)
    assert app_record.status == "interviewing"


def test_application_detail_command_center(client: TestClient, db_session: Session):
    app_record = JobApplication(
        company="Microsoft",
        title="Principal Software Engineer",
        status="applied",
        applied_date=datetime.date(2026, 9, 1),
        follow_up_date=datetime.date(2026, 9, 15),
        description="Lead Azure developer platform teams.",
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # GET detail
    resp = client.get(f"/applications/{app_record.id}")
    assert resp.status_code == 200
    assert "Principal Software Engineer" in resp.text
    assert "Lead Azure developer platform teams." in resp.text

    # POST update settings
    update_data = {
        "applied_date": "2026-09-02",
        "follow_up_date": "2026-09-18",
        "method": "LinkedIn",
        "account_created": "true",
        "portal_username": "myuser@outlook.com",
        "confirmation_number": "MSFT-001",
    }
    resp_update = client.post(
        f"/applications/{app_record.id}", data=update_data, follow_redirects=False
    )
    assert resp_update.status_code == 303

    db_session.refresh(app_record)
    assert app_record.applied_date == datetime.date(2026, 9, 2)
    assert app_record.follow_up_date == datetime.date(2026, 9, 18)
    assert app_record.portal_username == "myuser@outlook.com"
    assert app_record.account_created is True

    # POST description update
    resp_desc = client.post(
        f"/applications/{app_record.id}/description",
        data={"description": "Updated job description text with interview notes."},
        follow_redirects=False,
    )
    assert resp_desc.status_code == 303
    db_session.refresh(app_record)
    assert app_record.description == "Updated job description text with interview notes."


def test_contacts_management(client: TestClient, db_session: Session):
    app_record = JobApplication(company="Meta", title="Systems Engineer")
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # Add contact
    # Verify detail page initially has only ONE contacts count badge (aligned right in card header)
    resp_init = client.get(f"/applications/{app_record.id}")
    assert resp_init.status_code == 200
    assert resp_init.text.count('id="contacts-count-badge"') == 1

    # Add contact via HTMX
    contact_data = {
        "name": "Sarah Connor",
        "role": "Hiring Manager",
        "email": "sarah@meta.com",
        "phone": "555-1234",
        "linkedin_url": "https://linkedin.com/in/sarah",
        "notes": "Discussed distributed caching systems",
    }
    resp = client.post(
        f"/applications/{app_record.id}/contacts",
        data=contact_data,
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "Sarah Connor" in resp.text
    assert "Hiring Manager" in resp.text
    assert 'id="contacts-count-badge"' in resp.text
    assert 'hx-swap-oob="true"' in resp.text

    contact = (
        db_session.query(ApplicationContact)
        .filter(ApplicationContact.application_id == app_record.id)
        .first()
    )
    assert contact is not None
    assert contact.name == "Sarah Connor"

    # Verify detail page still has exactly ONE counter badge on full render
    resp_after_add = client.get(f"/applications/{app_record.id}")
    assert resp_after_add.status_code == 200
    assert resp_after_add.text.count('id="contacts-count-badge"') == 1

    # Edit contact via HTMX
    edit_data = {
        "name": "Sarah Connor-Reese",
        "role": "Recruiter",
        "email": "sarah.connor@meta.com",
        "phone": "555-9999",
        "linkedin_url": "https://linkedin.com/in/sarah-reese",
        "notes": "Updated contact info after initial phone screen",
    }
    resp_edit = client.post(
        f"/applications/{app_record.id}/contacts/{contact.id}",
        data=edit_data,
        headers={"HX-Request": "true"},
    )
    assert resp_edit.status_code == 200
    assert "Sarah Connor-Reese" in resp_edit.text
    assert "Recruiter" in resp_edit.text
    db_session.refresh(contact)
    assert contact.name == "Sarah Connor-Reese"
    assert contact.role == "Recruiter"
    assert contact.email == "sarah.connor@meta.com"

    # Verify contact update activity was logged
    act = (
        db_session.query(ApplicationActivity)
        .filter(
            ApplicationActivity.application_id == app_record.id,
            ApplicationActivity.activity_type == "contact",
        )
        .order_by(ApplicationActivity.id.desc())
        .first()
    )
    assert act is not None
    assert "Updated contact: Sarah Connor-Reese" in act.note

    # Delete contact via HTMX
    resp_del = client.delete(
        f"/applications/{app_record.id}/contacts/{contact.id}",
        headers={"HX-Request": "true"},
    )
    assert resp_del.status_code == 200
    assert 'id="contacts-count-badge"' in resp_del.text
    assert (
        db_session.query(ApplicationContact).filter(ApplicationContact.id == contact.id).first()
        is None
    )

    # Verify detail page after delete still has exactly ONE counter badge
    resp_after_del = client.get(f"/applications/{app_record.id}")
    assert resp_after_del.status_code == 200
    assert resp_after_del.text.count('id="contacts-count-badge"') == 1


def test_cancelled_status_and_closed_bucket(client: TestClient, db_session: Session):
    app_record = JobApplication(
        company="Netflix",
        title="Senior Platform Engineer",
        status="applied",
        job_url="https://netflix.jobs/123",
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # Change status to cancelled
    resp = client.post(
        f"/applications/{app_record.id}/status",
        data={"new_status": "cancelled", "note": "Position cancelled by company"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.refresh(app_record)
    assert app_record.status == "cancelled"

    # Verify status change activity
    act = (
        db_session.query(ApplicationActivity)
        .filter(ApplicationActivity.application_id == app_record.id)
        .first()
    )
    assert act is not None
    assert act.new_status == "cancelled"
    assert "Position cancelled by company" in act.note

    # Verify appearance in closed filter
    resp_closed = client.get("/applications?status=closed")
    assert resp_closed.status_code == 200
    assert "Senior Platform Engineer" in resp_closed.text
    assert "Netflix" in resp_closed.text

    # Verify appearance on kanban board closed column with cancelled badge
    resp_kanban = client.get("/applications?view=kanban")
    assert resp_kanban.status_code == 200
    assert "Senior Platform Engineer" in resp_kanban.text
    assert "Cancelled" in resp_kanban.text

    # Verify detail view has Cancelled step and btn-delete-app
    resp_detail = client.get(f"/applications/{app_record.id}")
    assert resp_detail.status_code == 200
    assert "Cancelled" in resp_detail.text
    assert "btn-delete-app" in resp_detail.text
    assert "Open Original Posting ↗" in resp_detail.text


def test_activities_logging(client: TestClient, db_session: Session):
    app_record = JobApplication(company="Apple", title="iOS Core Developer")
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # Add custom activity
    activity_data = {
        "activity_type": "interview",
        "activity_date": "2026-09-04",
        "note": "Completed 45m technical round on concurrency & memory management.",
    }
    resp = client.post(f"/applications/{app_record.id}/activities", data=activity_data)
    assert resp.status_code == 200
    assert "Interview Note" in resp.text
    assert "Completed 45m technical round" in resp.text

    act = (
        db_session.query(ApplicationActivity)
        .filter(ApplicationActivity.application_id == app_record.id)
        .first()
    )
    assert act is not None
    assert act.activity_type == "interview"


def test_unemployment_report_and_export(client: TestClient, db_session: Session):
    app1 = JobApplication(
        company="Amazon",
        title="Software Dev Engineer II",
        applied_date=datetime.date(2026, 8, 31),
        method="Company Website",
        account_created=True,
        confirmation_number="AMZN-9988",
        status="applied",
    )
    app2 = JobApplication(
        company="Netflix",
        title="Senior UI Engineer",
        applied_date=datetime.date(2026, 9, 2),
        method="LinkedIn",
        status="applied",
    )
    # Saved and cancelled applications should NOT be listed in activities for the report
    app_saved = JobApplication(
        company="SavedCo Technologies",
        title="Wishlist Architect",
        applied_date=datetime.date(2026, 9, 1),
        method="Company Website",
        status="saved",
    )
    app_cancelled = JobApplication(
        company="Avalere Health",
        title="Senior Medical Writer",
        applied_date=datetime.date(2026, 9, 1),
        method="Indeed",
        status="cancelled",
    )
    db_session.add_all([app1, app2, app_saved, app_cancelled])
    db_session.commit()

    # Activity on a cancelled job should also be excluded
    act_cancelled = ApplicationActivity(
        application_id=app_cancelled.id,
        activity_type="custom",
        note="Applied to senior role instead. Cancelled.",
        activity_date=datetime.date(2026, 9, 2),
    )
    db_session.add(act_cancelled)
    db_session.commit()

    # GET report page
    resp = client.get("/applications/unemployment-report")
    assert resp.status_code == 200
    assert "Work-Search Activity Log" in resp.text
    assert "Amazon" in resp.text
    assert "Netflix" in resp.text
    assert "Week Ending: Saturday" in resp.text
    # Ensure saved and cancelled job events are NOT listed in the report activities
    assert "SavedCo Technologies" not in resp.text
    assert "Wishlist Architect" not in resp.text
    assert "Avalere Health" not in resp.text
    assert "Senior Medical Writer" not in resp.text
    assert "Applied to senior role instead" not in resp.text

    # GET CSV export
    resp_export = client.get("/applications/unemployment-report/export")
    assert resp_export.status_code == 200
    assert resp_export.headers["content-type"].startswith("text/csv")
    csv_text = resp_export.text
    assert "Claim Week Ending" in csv_text
    assert "Amazon" in csv_text
    assert "Netflix" in csv_text
    assert "SavedCo Technologies" not in csv_text
    assert "Wishlist Architect" not in csv_text
    assert "Avalere Health" not in csv_text
    assert "Senior Medical Writer" not in csv_text


def test_delete_application(client: TestClient, db_session: Session):
    app_record = JobApplication(company="Uber", title="Backend Engineer")
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # DELETE endpoint
    resp = client.delete(f"/applications/{app_record.id}")
    assert resp.status_code == 200

    deleted = db_session.query(JobApplication).filter(JobApplication.id == app_record.id).first()
    assert deleted is None


def test_seed_script_populates_pipeline_and_contacts(db_session: Session):
    from unittest.mock import patch

    from scripts.seed import seed

    with patch("scripts.seed.SessionLocal", return_value=db_session), patch("scripts.seed.init_db"):
        seed()
        assert db_session.query(SavedJob).count() == 3
        assert db_session.query(JobApplication).count() == 3
        assert db_session.query(ApplicationContact).count() == 2
        assert db_session.query(ApplicationActivity).count() == 5

        # Verify idempotency on second run
        seed()
        assert db_session.query(JobApplication).count() == 3


def test_update_application_job_info(client: TestClient, db_session: Session):
    # Setup a saved job and application with incomplete or "None" company
    job = SavedJob(
        job_id="test-job-edit-info",
        title="Sr. Manager, Quality Systems and Compliance Technology",
        company="None",
        location="Chesterbrook, PA, US",
        job_url="https://indeed.com/viewjob?jk=12345",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    app_record = JobApplication(
        saved_job_id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        job_url=job.job_url,
        status="applied",
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # Verify initial detail page shows Edit Job Info button and modal
    detail_resp = client.get(f"/applications/{app_record.id}")
    assert detail_resp.status_code == 200
    assert "Edit Job Info" in detail_resp.text
    assert "edit-job-dialog" in detail_resp.text

    # Post updated job info (fix company name, refine title, salary, url)
    post_resp = client.post(
        f"/applications/{app_record.id}/job-info",
        data={
            "company": "AmerisourceBergen",
            "title": "Director, Quality Systems & Compliance",
            "location": "Chesterbrook, PA, US (Hybrid)",
            "salary_stated": "$175k - $210k",
            "job_url": "https://careers.amerisourcebergen.com/jobs/999",
        },
        follow_redirects=True,
    )
    assert post_resp.status_code == 200
    assert "AmerisourceBergen" in post_resp.text
    assert "Director, Quality Systems &amp; Compliance" in post_resp.text
    assert "Chesterbrook, PA, US (Hybrid)" in post_resp.text
    assert "$175k - $210k" in post_resp.text

    # Verify DB state for application
    db_session.refresh(app_record)
    assert app_record.company == "AmerisourceBergen"
    assert app_record.title == "Director, Quality Systems & Compliance"
    assert app_record.location == "Chesterbrook, PA, US (Hybrid)"
    assert app_record.salary_stated == "$175k - $210k"
    assert app_record.job_url == "https://careers.amerisourcebergen.com/jobs/999"

    # Verify underlying SavedJob was also synced
    db_session.refresh(job)
    assert job.company == "AmerisourceBergen"
    assert job.title == "Director, Quality Systems & Compliance"
    assert job.location == "Chesterbrook, PA, US (Hybrid)"
    assert job.salary_bracket == "$175k - $210k"
    assert job.job_url == "https://careers.amerisourcebergen.com/jobs/999"


def test_update_application_follow_up_date(client: TestClient, db_session: Session):
    app_record = JobApplication(
        company="Regeneron",
        title="Senior Validation Scientist",
        status="applied",
        applied_date=datetime.date(2026, 9, 10),
        follow_up_date=None,
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # 1. Update follow-up date (e.g. +2 weeks or change input)
    resp = client.post(
        f"/applications/{app_record.id}/follow-up",
        data={"follow_up_date": "2026-09-24"},
    )
    assert resp.status_code == 200
    assert "save-status-badge" in resp.text
    assert "Reminder Date Saved" in resp.text

    db_session.refresh(app_record)
    assert app_record.follow_up_date == datetime.date(2026, 9, 24)
    # Ensure no activity log was generated
    assert len(app_record.activities) == 0

    # 2. Clear follow-up date
    resp_clear = client.post(
        f"/applications/{app_record.id}/follow-up",
        data={"follow_up_date": ""},
    )
    assert resp_clear.status_code == 200
    assert "save-status-badge" in resp_clear.text
    db_session.refresh(app_record)
    assert app_record.follow_up_date is None
    assert len(app_record.activities) == 0


def test_update_application_compliance_htmx_save_badge(client: TestClient, db_session: Session):
    app_record = JobApplication(
        company="Moderna",
        title="Principal Platform Engineer",
        status="applied",
        applied_date=datetime.date(2026, 9, 1),
        method="Company Website",
        account_created=False,
    )
    db_session.add(app_record)
    db_session.commit()
    db_session.refresh(app_record)

    # HTMX request returns responsive save badge
    resp = client.post(
        f"/applications/{app_record.id}",
        data={
            "applied_date": "2026-09-12",
            "method": "LinkedIn",
            "account_created": "true",
            "portal_username": "dev@moderna.com",
            "confirmation_number": "REQ-7788",
        },
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "save-status-badge" in resp.text
    assert "Changes Saved" in resp.text

    db_session.refresh(app_record)
    assert app_record.applied_date == datetime.date(2026, 9, 12)
    assert app_record.method == "LinkedIn"
    assert app_record.account_created is True
    assert app_record.portal_username == "dev@moderna.com"
    assert app_record.confirmation_number == "REQ-7788"
    assert len(app_record.activities) == 0


def test_create_manual_application_saved_status(client: TestClient, db_session: Session):
    today = datetime.date.today()
    data = {
        "company": "Anthropic",
        "title": "Systems Engineer",
        "location": "Remote",
        "salary_stated": "$180k - $220k",
        "method": "Company Website",
        "status": "saved",
        "applied_date": "",  # saved status clears/has no applied_date
        "follow_up_date": "",  # should auto-default to +7 days from today
    }
    resp = client.post("/applications", data=data, follow_redirects=False)
    assert resp.status_code == 303

    app_record = (
        db_session.query(JobApplication).filter(JobApplication.company == "Anthropic").first()
    )
    assert app_record is not None
    assert app_record.status == "saved"
    assert app_record.applied_date is None
    assert app_record.follow_up_date == today + datetime.timedelta(days=7)


def test_manual_application_modal_ui_tweaks(client: TestClient):
    resp = client.get("/applications")
    assert resp.status_code == 200

    # 1. Verify Confirmation / App # label does not include "(For Unemployment)"
    assert "Confirmation / App #" in resp.text
    assert "Confirmation / App # (For Unemployment)" not in resp.text

    # 2. Verify Cancel and Save Application buttons have equal flex: 1 1 0 width styling
    assert (
        'style="flex: 1 1 0; min-width: 0; justify-content: center; text-align: center;"'
        in resp.text
    )
    assert "Save Application" in resp.text
    assert "Cancel" in resp.text

    # 3. Verify status select onchange handler is wired
    assert 'onchange="window.handleManualAppStatusChange(this.value)"' in resp.text
