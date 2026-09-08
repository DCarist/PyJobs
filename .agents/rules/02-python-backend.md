# Python & Backend Development Standards

Guidelines and constraints for all backend code in PyJobs.

---

## 1. Modern Python Idioms
* Target Python 3.14+.
* Use modern built-in type annotations (`list[str]`, `dict[str, Any]`, `X | Y` unions).
* Always include `from __future__ import annotations` at the top of Python modules.
* Prefer `pathlib.Path` over `os.path`.

---

## 2. SQLAlchemy 2.0 & Database Patterns
* **Type Annotations**: All models must use SQLAlchemy 2.0 declarative mapping style:
  ```python
  class Application(Base):
      __tablename__ = "applications"

      id: Mapped[int] = mapped_column(primary_key=True)
      job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
      company: Mapped[str] = mapped_column(String(255), nullable=False)
      status: Mapped[str] = mapped_column(String(50), default="applied")
      created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
  ```
* **Session Management**: Use context managers or FastAPI dependency injection (`get_db`) to yield sessions and guarantee rollback/closure on error.
* **Hermetic Test Isolation**: Tests must never mutate or rely on the persistent `jobs.db` file. All database tests must inject the in-memory SQLite fixture (`sqlite:///:memory:`).

---

## 3. FastAPI & Routing
* Route handlers should be grouped logically into routers (`api_router`, `views_router`, etc.).
* Validate all request inputs using Pydantic schemas or standard FastAPI parameters.
* Return appropriate HTTP status codes (e.g. `201 Created`, `404 Not Found`, `422 Unprocessable Entity`).
* Ensure background tasks and scraping operations do not block the event loop.

---

## 4. Scrapers & Network Safety
* Scrapers must cleanly handle network failures, timeouts, and schema variations in third-party job boards.
* Use rate-limiting, polite delays, and realistic headers.
* **Testing Constraint**: Automated tests must NEVER make real network requests to external job boards. Always mock `fetch_jobs` or network clients in unit tests.
