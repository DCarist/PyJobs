import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyjobs.database import SessionLocal, init_db
from pyjobs.models import (
    ApplicationActivity,
    ApplicationContact,
    JobApplication,
    SavedJob,
    UserPreference,
)


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        # Seed user preference
        pref = db.query(UserPreference).first()
        if not pref:
            pref = UserPreference(
                location="Philadelphia, PA, Remote",
                positions="Quality Assurance Engineer",
                fields="Automation, Python, Six Sigma",
                sites="linkedin,indeed,google",
                is_remote=True,
            )
            db.add(pref)
            print("Seeded default UserPreference.")
        else:
            print("UserPreference already exists.")

        # Seed sample jobs if empty
        if db.query(SavedJob).count() == 0:
            sample_jobs = [
                SavedJob(
                    job_id="seed-1",
                    site="linkedin",
                    title="Senior Quality Assurance Automation Engineer",
                    company="Comcast",
                    location="Philadelphia, PA",
                    salary_source="USD 125,000 - 145,000 / yearly",
                    job_url="https://www.linkedin.com",
                    description="Lead QA automation efforts for next-gen streaming platforms.",
                    date_posted=datetime.datetime.now(datetime.UTC),
                ),
                SavedJob(
                    job_id="seed-2",
                    site="indeed",
                    title="QA Lead (Six Sigma Certified)",
                    company="GlaxoSmithKline",
                    location="Philadelphia, PA",
                    salary_source="USD 110,000 - 135,000 / yearly",
                    job_url="https://www.indeed.com",
                    description=(
                        "Quality assurance lead overseeing pharmaceutical software validation."
                    ),
                    date_posted=datetime.datetime.now(datetime.UTC),
                ),
                SavedJob(
                    job_id="seed-3",
                    site="google",
                    title="Remote SDET (Python / Pytest)",
                    company="CloudScale Inc",
                    location="Remote",
                    salary_source="USD 130,000 - 160,000 / yearly",
                    job_url="https://google.com/jobs",
                    description="Full remote role building robust automation frameworks.",
                    date_posted=datetime.datetime.now(datetime.UTC),
                ),
            ]
            db.add_all(sample_jobs)
            db.flush()
            print(f"Seeded {len(sample_jobs)} sample jobs.")
        else:
            print(f"Database already has {db.query(SavedJob).count()} saved jobs.")

        # Seed sample tracked applications if empty
        if db.query(JobApplication).count() == 0:
            today = datetime.date.today()
            job1 = db.query(SavedJob).filter(SavedJob.job_id == "seed-1").first()
            job2 = db.query(SavedJob).filter(SavedJob.job_id == "seed-2").first()

            app1 = JobApplication(
                saved_job_id=job1.id if job1 else None,
                company=job1.company if job1 else "Comcast",
                title=job1.title if job1 else "Senior QA Automation Engineer",
                location=job1.location if job1 else "Philadelphia, PA",
                salary_stated="$125,000 - $145,000",
                method="LinkedIn",
                status="applied",
                applied_date=today - datetime.timedelta(days=5),
                follow_up_date=today + datetime.timedelta(days=9),
                job_url=job1.job_url if job1 else "https://www.linkedin.com",
                account_created=True,
                portal_username="candidate@gmail.com",
                confirmation_number="CC-QA-9821",
                description=job1.description if job1 else "QA automation leadership.",
            )
            db.add(app1)
            db.flush()

            act1 = ApplicationActivity(
                application_id=app1.id,
                activity_type="status_change",
                old_status=None,
                new_status="applied",
                note="Tracked application from feed (LinkedIn)",
                activity_date=today - datetime.timedelta(days=5),
            )
            db.add(act1)

            app2 = JobApplication(
                saved_job_id=job2.id if job2 else None,
                company=job2.company if job2 else "GlaxoSmithKline",
                title=job2.title if job2 else "QA Lead (Six Sigma Certified)",
                location=job2.location if job2 else "Philadelphia, PA",
                salary_stated="$110,000 - $135,000",
                method="Company Website",
                status="screening",
                applied_date=today - datetime.timedelta(days=12),
                follow_up_date=today + datetime.timedelta(days=2),
                job_url=job2.job_url if job2 else "https://www.indeed.com",
                account_created=True,
                portal_username="candidate@gmail.com",
                confirmation_number="GSK-REQ-4401",
                description=job2.description if job2 else "Pharmaceutical software validation.",
            )
            db.add(app2)
            db.flush()

            act2_apply = ApplicationActivity(
                application_id=app2.id,
                activity_type="status_change",
                old_status=None,
                new_status="applied",
                note="Applied via GSK Careers Portal",
                activity_date=today - datetime.timedelta(days=12),
            )
            act2_screen = ApplicationActivity(
                application_id=app2.id,
                activity_type="status_change",
                old_status="applied",
                new_status="screening",
                note="Invited for initial recruiter phone screen",
                activity_date=today - datetime.timedelta(days=3),
            )
            contact2 = ApplicationContact(
                application_id=app2.id,
                name="Sarah Jenkins",
                role="Recruiter",
                email="sarah.jenkins@gsk.example.com",
                phone="(215) 555-0199",
                notes="Coordinating first-round phone interview.",
            )
            db.add_all([act2_apply, act2_screen, contact2])

            app3 = JobApplication(
                saved_job_id=None,
                company="Anthropic",
                title="Lead Quality & Reliability Engineer",
                location="Remote",
                salary_stated="$175,000 - $210,000",
                method="Referral",
                status="interviewing",
                applied_date=today - datetime.timedelta(days=18),
                follow_up_date=today + datetime.timedelta(days=4),
                job_url="https://anthropic.com/careers",
                account_created=False,
                confirmation_number="ANTH-REF-712",
                description="Lead testing and reliability assurance for frontier AI workflows.",
            )
            db.add(app3)
            db.flush()

            act3_apply = ApplicationActivity(
                application_id=app3.id,
                activity_type="status_change",
                old_status=None,
                new_status="applied",
                note="Internal referral submitted by former colleague",
                activity_date=today - datetime.timedelta(days=18),
            )
            act3_int = ApplicationActivity(
                application_id=app3.id,
                activity_type="interview",
                note="Completed technical round with engineering team",
                activity_date=today - datetime.timedelta(days=7),
            )
            contact3 = ApplicationContact(
                application_id=app3.id,
                name="David Chen",
                role="Hiring Manager",
                email="dchen@anthropic.example.com",
                notes="Met during panel interview.",
            )
            db.add_all([act3_apply, act3_int, contact3])

            print("Seeded 3 sample JobApplications with contacts and activities.")

        db.commit()
        print("Database seeding completed successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
