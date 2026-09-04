import datetime

from database import SessionLocal, init_db
from models import SavedJob, UserPreference


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
            print(f"Seeded {len(sample_jobs)} sample jobs.")
        else:
            print(f"Database already has {db.query(SavedJob).count()} saved jobs.")

        db.commit()
        print("Database seeding completed successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
