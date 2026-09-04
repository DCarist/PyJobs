# PyJobs Development & Pair-Programming Guidelines

This repository follows a strict pair-programming workflow for feature development, testing, quality assurance, and commits. Every code modification must adhere to the 6-step cycle below.

---

## The 6-Step Development Cycle

Whenever the user suggests a next step or feature task:

### 1. Workstream & Branch Decision
* Check the current active branch (`git branch --show-current`).
* **New Workstream / Feature**:
  * Verify `main` is clean.
  * Create and checkout a descriptive feature branch:
    * New feature: `git checkout -b feat/<short-name>`
    * Bug fix: `git checkout -b fix/<short-name>`
    * Refactor / Chore: `git checkout -b refactor/<short-name>`
* **Continuation of Existing Workstream**:
  * Confirm you are on the correct active feature branch and continue development.
* **Never commit directly to `main` without explicit user instruction.**

### 2. Implementation
* Implement the requested feature, endpoint, UI element, or data model.
* Modern standards:
  * Python 3.14+ idioms.
  * SQLAlchemy 2.0 type annotations (`Mapped[T] = mapped_column(...)`).
  * Vanilla CSS & HTMX partials with dark-mode glassmorphic styling.
  * Explicit `type="button"` on buttons for accessibility.

### 3. Automated Test Generation
* Every new feature, route, or business logic update **must** be accompanied by automated tests in `tests/test_*.py`.
* Ensure tests:
  * Use the in-memory SQLite fixture (`sqlite:///:memory:`) from `conftest.py`.
  * Mock external network operations (`scraper.fetch_jobs`) to keep test runs sub-second and hermetic.

### 4. Quality Gate Verification
Run the unified verification script:
```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
```
Or verify individual components:
* **Python Linter**: `ruff check .` (auto-fix with `ruff check --fix .`)
* **Python Formatter**: `ruff format --check .` (auto-format with `ruff format .`)
* **Python Static Type Checker**: `ty check .`
* **Frontend Linter & Formatter**: `npx @biomejs/biome check static/ templates/` (auto-format with `--write`)
* **Test Suite**: `uv run pytest`

**All checks must pass with 0 errors before proceeding.**

### 5. Prepare Commit Message
Generate a clean conventional commit message with:
* Conventional prefix (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`).
* A concise imperative summary line.
* Bulleted description of changes, tests added, and quality validations.

### 6. User Review & Authorization (MANDATORY STOP)
* Present the summary of changes, test results, and proposed commit message to the user.
* **DO NOT run `git commit` automatically.**
* Wait for the user to review and explicitly authorize the commit.
