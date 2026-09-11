# Testing & Quality Assurance Standards

Quality gates, test requirements, and documentation alignment checks for PyJobs.

---

## 1. Automated Test Principles
* **Every Feature Requires Tests**: All new endpoints, models, query helpers, and UI routes must have automated tests in `tests/test_*.py`.
* **Fast & Hermetic**:
  * The entire test suite must complete in sub-second to low-second times (e.g. `uv run pytest` under 3s).
  * Use the in-memory SQLite fixture (`sqlite:///:memory:`) defined in `conftest.py`.
  * External network requests are strictly prohibited in tests. Mock all external dependencies (`fetch_jobs`, HTTP clients).
* **Deterministic**: Tests must not depend on execution order or persistent database artifacts.

---

## 2. Quality Gate Verification
Before any feature or bugfix is ready for commit or review, it must pass the unified verification script:

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
```

Individual verification tools:
* **Python Linter**: `ruff check .` (auto-fix: `ruff check --fix .`)
* **Python Formatter**: `ruff format --check .` (format: `ruff format .`)
* **Python Static Type Checker**: `ty check .`
* **Frontend Linter & Formatter**: `npx @biomejs/biome check static/ templates/` (format: `npx @biomejs/biome check --write static/ templates/`)
* **Automated Test Suite**: `uv run pytest`

**Zero errors are permitted across all tools.**

---

## 3. Branch Completion: Rule & Documentation Alignment Check
At the conclusion of any feature or development branch before merging:
1. **Rule Audit**:
   - Check if any new conventions, packages, schemas, or architectural patterns were added.
   - If so, update the relevant files in `.agents/rules/` and `AGENTS.md`.
2. **Documentation Audit**:
   - Update `README.md` and `project-overview.md` if user-facing features, CLI commands, or endpoints were added or modified.
3. **Skill & Tool Audit**:
   - Ensure `.agents/skills/` and `.agents/hooks.json` are current and functional.
