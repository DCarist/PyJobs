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

        conn.commit()
