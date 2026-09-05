from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./pyjobs.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables and apply incremental schema changes for SQLite."""
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # 1. User preferences column migrations
        if "user_preferences" in tables:
            columns = [c["name"] for c in inspector.get_columns("user_preferences")]
            if "sites" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE user_preferences "
                        "ADD COLUMN sites VARCHAR DEFAULT 'linkedin,indeed,google'"
                    )
                )
            if "is_remote" not in columns:
                conn.execute(
                    text("ALTER TABLE user_preferences ADD COLUMN is_remote BOOLEAN DEFAULT 0")
                )

        # 2. Saved jobs column migrations
        if "saved_jobs" in tables:
            job_columns = [c["name"] for c in inspector.get_columns("saved_jobs")]
            column_defs = [
                ("min_salary", "ALTER TABLE saved_jobs ADD COLUMN min_salary FLOAT DEFAULT NULL"),
                ("max_salary", "ALTER TABLE saved_jobs ADD COLUMN max_salary FLOAT DEFAULT NULL"),
                (
                    "salary_interval",
                    "ALTER TABLE saved_jobs ADD COLUMN salary_interval VARCHAR DEFAULT 'yearly'",
                ),
                (
                    "seniority_level",
                    (
                        "ALTER TABLE saved_jobs ADD COLUMN seniority_level "
                        "VARCHAR DEFAULT 'Specialist / Contributor'"
                    ),
                ),
                (
                    "salary_bracket",
                    (
                        "ALTER TABLE saved_jobs ADD COLUMN salary_bracket "
                        "VARCHAR DEFAULT 'Unspecified'"
                    ),
                ),
                ("is_hidden", "ALTER TABLE saved_jobs ADD COLUMN is_hidden BOOLEAN DEFAULT 0"),
            ]
            for col_name, sql_stmt in column_defs:
                if col_name not in job_columns:
                    conn.execute(text(sql_stmt))

        # 3. Job applications column migrations
        if "job_applications" in tables:
            app_columns = [c["name"] for c in inspector.get_columns("job_applications")]
            app_defs = [
                (
                    "account_created",
                    "ALTER TABLE job_applications ADD COLUMN account_created BOOLEAN DEFAULT 0",
                ),
                (
                    "portal_username",
                    "ALTER TABLE job_applications ADD COLUMN portal_username VARCHAR DEFAULT NULL",
                ),
                (
                    "confirmation_number",
                    (
                        "ALTER TABLE job_applications "
                        "ADD COLUMN confirmation_number VARCHAR DEFAULT NULL"
                    ),
                ),
                (
                    "follow_up_date",
                    "ALTER TABLE job_applications ADD COLUMN follow_up_date DATE DEFAULT NULL",
                ),
            ]
            for col_name, sql_stmt in app_defs:
                if col_name not in app_columns:
                    conn.execute(text(sql_stmt))

        conn.commit()

    # Backfill and synchronize existing job classifications and salary data
    sync_job_classifications()


def sync_job_classifications(session=None) -> int:
    """Re-evaluates seniority levels and repairs salary data on existing jobs in SQLite.

    Ensures existing database records are automatically kept in sync whenever taxonomy rules
    or salary parser logic are updated, without requiring manual database re-seeding.
    """
    import re

    from models import SavedJob
    from scraper import categorize_salary, classify_seniority

    owns_session = False
    if session is None:
        session = SessionLocal()
        owns_session = True

    updated_count = 0
    try:
        jobs = session.query(SavedJob).all()
        for job in jobs:
            modified = False

            # 1. Re-evaluate seniority classification
            expected_seniority = classify_seniority(job.title)
            if job.seniority_level != expected_seniority:
                job.seniority_level = expected_seniority
                modified = True

            # 2. Clean corrupted salary_source strings (e.g. "None nan - nan / None")
            if job.salary_source and any(
                garbage in job.salary_source.lower() for garbage in ["nan", "none nan"]
            ):
                job.salary_source = None
                modified = True

            # 3. Backfill salary bracket and min/max if missing but salary_source has numbers
            if (job.min_salary is None and job.max_salary is None) and job.salary_source:
                m = re.search(r"([\d\.]+)\s*-\s*([\d\.]+)\s*/\s*(\w+)", job.salary_source)
                if m:
                    try:
                        raw_min = float(m.group(1))
                        raw_max = float(m.group(2))
                        interval = m.group(3)
                        ann_min, ann_max, intv, bracket = categorize_salary(
                            min_amount=raw_min,
                            max_amount=raw_max,
                            interval=interval,
                        )
                        job.min_salary = ann_min
                        job.max_salary = ann_max
                        job.salary_interval = intv
                        job.salary_bracket = bracket
                        modified = True
                    except ValueError, TypeError:
                        pass

            if modified:
                updated_count += 1

        if updated_count > 0:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()

    return updated_count
