# PyJobs

PyJobs is a lightweight, full-stack Python application for intelligent job scraping, curation, and management. It scrapes multiple major job platforms (LinkedIn, Indeed, ZipRecruiter, Glassdoor) via `python-jobspy` and presents them in a modern, glassmorphic dashboard built with FastAPI, Jinja2, and HTMX.

---

## Getting Started

### Prerequisites
* Python 3.14+
* [uv](https://github.com/astral-sh/uv)
* Node.js & npm (for Biome)

### Installation
```bash
# Sync dependencies
uv sync

# Install ty globally (Astral Python type checker)
uv tool install ty
```

### Running the Application

**Option 1: One-Click Local Launcher (This Machine Only)**
Double-click `run.bat` in the project root. It will start the server on `127.0.0.1:8000` and automatically open PyJobs in your default web browser.

**Option 2: One-Click Local Network Launcher (Other Devices on LAN)**
Double-click `run_network.bat` in the project root. It binds to `0.0.0.0:8000`, automatically detects your machine's primary Wi-Fi/Ethernet LAN IP, and displays the direct access link:
```text
===================================================
             PyJobs Local Network Server
===================================================
  * Local machine:  http://localhost:8000
  * Local IP:       http://127.0.0.1:8000
  * LAN Network:    http://192.168.1.X:8000
---------------------------------------------------
  Connect any device on the same local Wi-Fi or LAN.
  Press Ctrl+C in this terminal to stop the server.
===================================================
```
Other laptops, smartphones, or tablets on the same local Wi-Fi can navigate directly to `http://<LAN_IP>:8000`.

**Option 3: CLI Commands**
```bash
# Standard local mode
uv run pyjobs

# Local network mode (accessible across LAN)
uv run python run.py --network

# Custom port or interface
uv run python run.py --host 0.0.0.0 --port 8080
```

**Option 4: Direct Uvicorn**
```bash
uv run uvicorn pyjobs.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Package Architecture (`pyjobs/`)

The application is structured into a modular Python package:
* **`pyjobs.main`**: Lightweight FastAPI entrypoint, lifespan manager, static file mount, and router registration.
* **`pyjobs.routers`**: Dedicated domain controllers:
  * `discovery`: Discovery dashboard, user preferences, and instant/background scraping endpoints.
  * `jobs`: Feed filtering, multi-format export, staleness verification, and 1-click tracking.
  * `profiles`: Search profiles management and drawer partials.
  * `applications`: Applications pipeline, Kanban/Table views, detail center, contacts, activities, and unemployment reports.
  * `resumes`: Resumes dashboard, versions management, PDF viewer, and templated downloads.
* **`pyjobs.services`**: Background workers and parsing engines:
  * `scraper`: JobSpy scraping engine, location parsing, and salary/seniority classification.
  * `scheduler`: In-app asyncio recurring search scheduler.
  * `task_manager`: Background scrape task runner and SSE event streaming.
  * `resume_parser`: PDF/DOCX text extraction, Word compilation, scoring, and dynamic filename generation.
* **`pyjobs.database` & `pyjobs.models`**: DeclarativeBase, SessionLocal, and SQLAlchemy 2.0 models.
* **`pyjobs.dependencies`**: Dependency injection (`get_db`, `templates`), upload path resolvers, and query helpers.
* **`pyjobs.launcher`**: CLI argument parser, LAN IP detection, browser spawning, and server launcher.

---

## Job Board Scraping & Location Syntax

### Supported Job Boards & Anti-Bot Protections
* **LinkedIn (`linkedin`)**: Highly reliable, returns rich job postings, titles, and companies rapidly. *(Active by default)*
* **Indeed (`indeed`)**: High volume, comprehensive coverage. Requires `country_indeed="usa"`. *(Active by default)*
* **Google Jobs (`google`)**: Aggregates postings from direct employer sites and job boards. *(Active by default)*
* **ZipRecruiter (`zip_recruiter`)**: Uses mobile API endpoints protected by Cloudflare WAF (`403 forbidden aa`). Deselected by default; requires residential proxies.
* **Glassdoor (`glassdoor`)**: Location lookup and GraphQL endpoints are protected by Cloudflare bot management (`400 location not parsed` / `403`). Deselected by default; requires residential proxies.

### Multi-Location & Remote Syntax
The Location input supports flexible, multi-target parsing:
* **Single City**: `Philadelphia`
* **City & State**: `Philadelphia, PA`
* **Multiple Cities**: `Philadelphia, PA; New York, NY` or `Philadelphia, PA, Boston, MA`
* **Remote Keywords**: `Philadelphia, PA, Remote` or `Remote` (or check the *Include Remote* box).

### Optional Proxy Configuration
To route scraper requests (especially for ZipRecruiter and Glassdoor) through proxy pools, set the `JOBSPY_PROXIES` environment variable:
```bash
# Comma-separated list or single proxy URL
set JOBSPY_PROXIES=http://user:pass@proxy1:port,http://user:pass@proxy2:port
```

---

## Search Profiles & Async Ingestion

### Multi-Query Search Profiles (`/profiles`)
* **Targeted Query Management**: Save independent search profiles with customized parameters:
  * Profile Name, Position Titles, and Required Skills/Fields.
  * Geographic Location, Search Radius (miles), and Remote Toggle.
  * Target Job Boards (`linkedin`, `indeed`, `google`, `zip_recruiter`, `glassdoor`).
  * Desired Result Count & Max Posting Age (days).
* **Sidebar Profile Switcher**: Switch active profiles seamlessly or create new profiles directly in the dashboard sidebar.
* **Feed Filtering by Profile**: Filter the main jobs feed to inspect opportunities discovered by specific profiles or view all aggregated jobs.

### Asynchronous Scraping & Live Progress (`/scrape/start`, `/scrape/status/{task_id}`)
* **Non-Blocking Execution**: Scrapes run asynchronously in background worker threads without freezing the UI or HTTP server.
* **Live Progress Tracking**: HTMX polling indicator displays real-time progress percentages and status updates.
* **4-Pillar Metric Summary**: Completion feedback highlighting:
  * **Newly Added**: Fresh job postings inserted into SQLite.
  * **Metadata Refreshed**: Postings re-encountered with updated salaries or descriptions.
  * **Aging (30d+)**: Postings that have passed the staleness threshold.
  * **Hidden Postings**: Postings currently filtered out or auto-hidden.
* **Instant Feed Refresh**: Out-of-band DOM swap immediately updates the job results view upon scrape completion.

### Automated Scheduling & Background Refresh
* **Per-Profile Intervals**: Configure automated background refreshes (Manual, 6h, 12h, 24h / Daily, 3 days, 5 days, or 7 days / Weekly).
* **Launch Check**: Mark profiles to scrape immediately on application launch (`refresh_on_launch`).
* **In-App Scheduler**: Lightweight asyncio lifespan scheduler checks eligible profiles without requiring external cron daemons.

### Posting Staleness & Expiration Management
* **Age-Based Staleness Badge**: Postings 30+ days old automatically display an amber `Stale (30d+)` badge.
* **Dead Link Verification**: Postings verified as dead/404 via HTTP `HEAD` checks show a red `Dead Link` warning.
* **1-Click Bulk Auto-Hide**: Hide all stale postings with a single click to keep your active pipeline clean.
* **Active vs. Stale Filtering**: Main feed filters allow viewing `All Postings`, `Active Only`, or `Stale Only`.
* **Hide Tracked Postings**: Instant toggle (`Hide tracked jobs`) filters out postings that are already being tracked in your pipeline (saved, applied, interviewing, cancelled, or URL-matched), with automatic cookie and localStorage state persistence across navigation.

---

## Application Tracking & Unemployment Compliance

### Application Pipeline (`/applications`)
* **1-Click Feed Tracking & Saving**: Track jobs as applied (`📌 Track Application`) or save them to apply later (`💾 Save Job`) directly from the search feed with automatic audit logging.
* **Interactive Kanban Board**: Visual drag-and-drop workflow across 6 pipeline stages:
  * `📌 Saved / To Apply`
  * `✉️ Applied`
  * `📞 Phone Screen`
  * `💼 Interviewing`
  * `🎉 Offer Received`
  * `📁 Closed / Archived` (Rejected, Withdrawn, Cancelled)
* **Detailed Table View**: Filterable table with quick stage dropdowns, contact counters, follow-up dates, and direct management links.
* **Follow-Up Reminders**: Visual indicators for `Due Today`, `Overdue`, and `Upcoming` follow-ups.
* **Application Detail Command Center (`/applications/{id}`)**:
  * **Job Info Editor**: Quick modal dialog to edit posting company, role title, location, salary range, and URL with automatic feed-job syncing.
  * **Key Contacts**: 1-to-many relationship tracking recruiters, hiring managers, and internal referrals with email, phone, and LinkedIn URLs.
  * **Activity Timeline**: Reverse-chronological audit log capturing status transitions, interview prep notes, and outreach.
  * **Job Description Snapshot**: Manually editable snapshot preserving the original posting text even if the live posting expires.
* **External Application Modal**: Log jobs applied to outside the feed (e.g. company careers portals, job fairs, direct emails).

### Unemployment Work-Search Audit Log (`/applications/unemployment-report`)
* **Weekly Claim Certification**: Automatically aggregates certified work-search applications, phone screens, interviews, and contacts into Saturday week-ending periods, while strictly excluding uncertified saved and cancelled job events.
* **Compliance Standards**: Highlights whether each claim period meets the standard 3+ work-search activities requirement with visual badges.
* **Audit Documentation**: Captures applicant portal creation, portal usernames, and confirmation numbers as official proof for state unemployment audits.
* **Export & Print**: Dedicated print-to-PDF stylesheet and instant CSV export for submitting weekly claims.

---

## Resume Management & Versioning (`/resumes`)

* **Targeted Resume Profiles & Person Tracking**: Organize resumes by role and candidate (e.g., "Douglas - MSAT Focused", "Marissa - General Resume") with dedicated Person associations and customizable tags.
* **Candidate Filtering**: Filter resume cards instantly by referenced Person via dedicated top-level filter pills, integrated with keyword search and tag filters.
* **Chronological Versioning**: Track document revisions over time (v1, v2, v3...) with explicit change notes and file metadata.
* **High-Fidelity Document Processing**: Strict validation and parsing for industry-standard **PDF** and **Word (.docx)** files using **PyMuPDF** and **python-docx**.
* **Automatic PDF Compilation**: Uploaded Word `.docx` documents are automatically compiled to `.pdf` upon upload, ensuring **100% of resume versions have a PDF available**.
* **In-Browser PDF Reader**: Review resumes directly within the application in a native embedded PDF viewer with full zoom, search, scroll, and print controls, alongside an ATS-extracted plain-text inspector.
* **Custom Retrieval Naming & Dating**: Download resumes with dynamic, template-driven naming patterns (e.g. `{name} {date}.{ext}` &rarr; `Douglas Jaymes Caristo 09-18-2026.docx`), automatically resolving `{name}` to each resume's assigned Person with fallback to global preferences.
* **Application Tracker Integration**: Select and link specific resume versions to each tracked job application, inspect submitted versions on the application detail command center, and receive keyword-matching resume recommendations.
* **Private, Hermetic Storage**: Uploaded files are safely stored in `uploads/resumes/`, strictly excluded from git tracking (`.gitignore`) to ensure privacy.


---

## Code Quality & Verification Gates

All code changes must pass the automated quality checks before merging back to `main`:

| Domain | Tool | Command |
| :--- | :--- | :--- |
| **Python Linting** | Ruff | `ruff check .` (auto-fix with `--fix`) |
| **Python Formatting** | Ruff | `ruff format --check .` (format with `ruff format .`) |
| **Python Type Checking** | Ty | `ty check .` (or `ty check --watch`) |
| **Frontend (CSS/HTML/JS)** | Biome | `npx @biomejs/biome check static/ templates/` |
| **Automated Tests** | pytest | `uv run pytest` |

### Unified Check Script
Run the entire quality gate in a single command:
```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
```
To check only staged files (used by the pre-commit hook):
```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1 -Staged
```

### Agent Lifecycle Hooks & Modular Rules
* **PostToolUse Hook (`.agents/hooks.json`)**: Automatically auto-fixes formatting (Ruff, Biome) and validates types (Ty) whenever an AI agent modifies code via `scripts/hook_post_tool.py`.
* **Modular Project Rules (`.agents/rules/`)**: Scoped rules covering workflow conventions, Python backend standards, HTMX frontend best practices, and branch-completion audits.

---

## Git Workflow & Feature Branches

1. Ensure your local `main` branch is up to date:
   ```bash
   git checkout main
   git pull
   ```
2. Create a feature or bugfix branch:
   ```bash
   git checkout -b feat/<feature-name>
   # or
   git checkout -b fix/<bug-name>
   ```
3. Make your modifications.
4. Run the quality gate to verify all checks pass:
   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
   ```
5. Commit and merge back to `main` once tested and verified.
