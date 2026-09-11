# Pair-Programming Workflow & Branch Lifecycle

This repository strictly adheres to a collaborative, pair-programming workflow for every feature, bug fix, chore, or refactor.

---

## 1. Branch Strategy

* **Always check active branch**: `git branch --show-current`
* **Never commit directly to `main` without explicit user instruction.**
* **Branch naming conventions**:
  * New features: `feat/<short-name>`
  * Bug fixes: `fix/<short-name>`
  * Maintenance / setup: `chore/<short-name>`
  * Refactoring: `refactor/<short-name>`
* **Branching base**: Branches are created from `main` or the active feature development branch (e.g. `dev`).

---

## 2. The 6-Step Development Cycle

Whenever undertaking any implementation or improvement:

1. **Workstream & Branch Decision**:
   - Check branch status and ensure clean working tree.
   - Create or switch to the appropriate feature branch.
2. **Implementation**:
   - Write clean, modular, modern code complying with project standards.
3. **Automated Test Generation**:
   - Accompany every functional change with comprehensive automated tests in `tests/test_*.py`.
4. **Quality Gate Verification**:
   - Run the unified quality check script:
     ```powershell
     powershell -ExecutionPolicy Bypass -File ./scripts/check.ps1
     ```
   - All linters, formatters, type checks, and tests must pass with 0 errors.
5. **Prepare Commit Message & Rule Alignment**:
   - Prepare a conventional commit message (`feat:`, `fix:`, `chore:`, `refactor:`).
   - **Branch Completion: Rule & Documentation Alignment Check**:
     - Before concluding a development branch, verify that any new dependencies, architectural patterns, database models, or tools are reflected in `.agents/rules/`, `AGENTS.md`, and `README.md`.
     - Update documentation and rules so future agent sessions remain aligned with current reality.
6. **User Review & Authorization (MANDATORY STOP)**:
   - Present a concise summary of changes, test verification results, rule updates, and the proposed commit message.
   - **DO NOT execute `git commit` automatically.**
   - Wait for explicit user authorization.
