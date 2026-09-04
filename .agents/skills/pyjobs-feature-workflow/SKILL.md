---
name: pyjobs-feature-workflow
description: Step-by-step feature development, testing, quality verification, and commit authorization workflow for PyJobs. Use whenever developing, updating, or reviewing features in this workspace.
---

# PyJobs Feature Workflow Skill

Use this workflow to ensure consistent, reliable development in the PyJobs codebase.

## Workflow Sequence

1. **Branch Check**:
   - Check current branch: `git branch --show-current`
   - If starting a new feature, branch from `main`:
     ```bash
     git checkout main
     git checkout -b feat/<feature-name>
     ```
   - If continuing, stay on the active branch.

2. **Code Implementation**:
   - Write clean, type-annotated code adhering to SQLAlchemy 2.0 `Mapped` styles and FastAPI conventions.
   - Use Biome-compliant HTML/CSS (explicit `type="button"` attributes).

3. **Generate Automated Tests**:
   - Add test cases in `tests/test_*.py`.
   - Never call external scraping services in tests; mock `main.fetch_jobs`.

4. **Execute Quality Gate**:
   ```powershell
   powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
   ```
   Ensure:
   - `ruff check .` -> clean
   - `ruff format --check .` -> clean
   - `ty check .` -> clean
   - `npx @biomejs/biome check static/ templates/` -> clean
   - `uv run pytest` -> all passing

5. **Draft Commit Message**:
   - Formulate conventional commit message (`feat: ...`, `fix: ...`).

6. **Request User Authorization**:
   - Present diff summary, test output, and proposed commit message.
   - Wait for explicit user authorization before executing `git commit`.
