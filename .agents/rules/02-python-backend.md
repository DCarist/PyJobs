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
* **Hermetic Test Isolation**: Tests must never mutate or rely on persistent `pyjobs.db`. With `PYJOBS_TESTING=1` and no explicit `PYJOBS_DB_PATH`, app startup uses shared-connection in-memory SQLite. Route/database tests also inject the in-memory SQLite fixture (`sqlite:///:memory:`); browser smoke may set a temporary `PYJOBS_DB_PATH`.
* **Company/site identity**: Use `pyjobs.services.companies.get_or_create_company_site` in every posting or application write path. It does not commit; the caller owns transaction boundaries. Keep original company/location strings on jobs and applications, with normalized `company_id` links and canonical site keys. Never infer a street address from a city label; preserve manually edited `CompanySite.address` on scrape and backfill.
* **Separate home origin**: `UserPreference.home_location` is solely the optional Google Maps directions origin. `UserPreference.location` and `SearchProfile.location` remain search targets. No geocoding/background Maps requests.

---

## 3. FastAPI & Package Architecture
* All application logic is packaged under `pyjobs/` with a standard PEP 517 build backend (`hatchling`):
  * `pyjobs.main`: Thin FastAPI orchestrator, lifespan management, static mounting, and router registration.
  * `pyjobs.routers`: Route controllers (`discovery`, `jobs`, `profiles`, `applications`, `companies`, `resumes`).
  * `pyjobs.services`: Background engines and parsers (`scraper`, `scheduler`, `task_manager`, `companies`, `locations`, `resume_parser`).
  * `pyjobs.dependencies`: Dependency injection (`get_db`, `templates`), path resolvers, and query helpers.
  * `pyjobs.database` & `pyjobs.models`: SQLAlchemy 2.0 ORM engine, declarative models, and schema migrations.
  * `pyjobs.launcher`: Network-enabled server launcher wrapped by the root `run.py` shim and `pyjobs` CLI entry point.
* Validate all request inputs using Pydantic schemas or standard FastAPI parameters.
* Return appropriate HTTP status codes (e.g. `201 Created`, `404 Not Found`, `422 Unprocessable Entity`).
* Ensure background tasks and scraping operations do not block the event loop (run in worker threads via `asyncio.to_thread`).
* Retrieve session factories for background tasks dynamically via `getattr(request.app.state, "session_factory", SessionLocal)` to support in-memory test isolation.
* Background workers and the recurring scheduler loop must check `os.environ.get("PYJOBS_TESTING")` to prevent unmanaged background threads or network calls during test suites.

---

## 4. Scrapers & Network Safety
* Scrapers must cleanly handle network failures, timeouts, and schema variations in third-party job boards.
* Use rate-limiting, polite delays, and realistic headers.
* **Testing Constraint**: Automated tests must NEVER make real network requests to external job boards. Always mock `fetch_jobs` or network clients in unit tests.

---

## 5. File Storage & Upload Safety
* Local uploads are stored in `uploads/resumes/` within the project root and MUST remain gitignored for privacy and security.
* Automated tests must NEVER write to or depend upon files in the project root `uploads/` directory. All file-based tests must use `tempfile.TemporaryDirectory()`.
* When versions or resumes are deleted, remove physical files using `pathlib.Path.unlink(missing_ok=True)`.

---

## 6. Document Processing & Ingestion
* **Text Extraction**: Use `pyjobs.services.resume_parser.extract_text` via PyMuPDF (`fitz`) for PDF and `python-docx` for Word documents.
* **Automatic PDF Compilation**: All uploaded `.docx` files must be compiled to `.pdf` via `convert_docx_to_pdf` to ensure in-browser PDF viewer compatibility.
* **Hermetic Testing**: Under `PYJOBS_TESTING=1`, document conversion must use `convert_docx_to_pdf_pure_pymupdf` to avoid unmanaged Word COM processes and maintain sub-second test execution.
* **Filename Templating**: Use `generate_download_filename` to resolve dynamic tokens (`{name}`, `{date}`, `{title}`, `{company}`, `{job_title}`, `{version}`) and sanitize OS-illegal characters across platforms.

---

## 7. UI Filter State & Navigation Persistence
* Feed filter toggles that must persist across navigation (e.g. `pyjobs_exclude_tracked`) must use HTTP cookies (`max-age=31536000, samesite="lax", path="/"`) synchronized with `localStorage`.
* Base endpoints (`GET /`) must check the cookie when query parameters are absent, rendering the initial page response already filtered with zero client-side layout shift.
* Explicit query parameters take precedence over cookies and update the cookie state upon evaluation.
* Curation's `seniority`, `salary_bracket`, `site`, and `profile_id` are repeated query keys with OR within a dimension and AND between dimensions. Full-page `/` and `/jobs/filter` renders, HTMX partials, and `/jobs/export` share `CurationFilters` and `query_filtered_jobs`; URLs restore native checkbox menus on full-page navigation. Group headings stay alphabetical while sorted postings retain SQL order within each group.

