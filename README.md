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

**Option 1: One-Click Launcher (Recommended)**
Double-click `run.bat` in the project root. It will start the server and automatically open PyJobs in your default web browser.

**Option 2: CLI Command**
```bash
uv run pyjobs
```

**Option 3: Direct Uvicorn**
```bash
uv run uvicorn main:app --reload
```
Navigate to `http://localhost:8000` in your browser.

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

## Application Tracking & Unemployment Compliance

### Application Pipeline (`/applications`)
* **1-Click Feed Tracking**: Track jobs directly from the curated feed with automatic follow-up dates (+14 days) and audit logging.
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
  * **Key Contacts**: 1-to-many relationship tracking recruiters, hiring managers, and internal referrals with email, phone, and LinkedIn URLs.
  * **Activity Timeline**: Reverse-chronological audit log capturing status transitions, interview prep notes, and outreach.
  * **Job Description Snapshot**: Manually editable snapshot preserving the original posting text even if the live posting expires.
* **External Application Modal**: Log jobs applied to outside the feed (e.g. company careers portals, job fairs, direct emails).

### Unemployment Work-Search Audit Log (`/applications/unemployment-report`)
* **Weekly Claim Certification**: Automatically aggregates all application submissions, phone screens, interviews, and contacts into Saturday week-ending periods.
* **Compliance Standards**: Highlights whether each claim period meets the standard 3+ work-search activities requirement with visual badges.
* **Audit Documentation**: Captures applicant portal creation, portal usernames, and confirmation numbers as official proof for state unemployment audits.
* **Export & Print**: Dedicated print-to-PDF stylesheet and instant CSV export for submitting weekly claims.

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
