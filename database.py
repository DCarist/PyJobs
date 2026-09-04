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
            conn.commit()
