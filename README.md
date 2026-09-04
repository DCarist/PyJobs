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
```bash
uv run uvicorn main:app --reload
```
Navigate to `http://localhost:8000` in your browser.

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
