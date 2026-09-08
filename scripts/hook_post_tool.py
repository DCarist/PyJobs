#!/usr/bin/env python3
"""PyJobs PostToolUse Lifecycle Hook.

Executes rapid auto-formatting, lint fixes, and type checks whenever
an agent edit tool (replace_file_content, multi_replace_file_content, write_to_file)
modifies files.

Antigravity Hook Contract:
- Input: Receives JSON metadata on stdin.
- Output: Must output valid JSON `{}` to stdout.
- Exit code: 0 on success.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Determine workspace root (PyJobs root directory)
REPO_ROOT = Path(__file__).resolve().parent.parent


def read_stdin_safely() -> dict:
    """Read JSON payload from stdin without failing on empty or invalid input."""
    try:
        if not sys.stdin.isatty():
            content = sys.stdin.read().strip()
            if content:
                return json.loads(content)
    except Exception as exc:
        sys.stderr.write(f"[hook_post_tool] Warning reading stdin: {exc}\n")
    return {}


def run_cmd(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute a shell command, writing stdout/stderr to stderr to keep stdout clean."""
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        sys.stderr.write(f"[hook_post_tool] Command error {cmd}: {exc}\n")
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=str(exc))


def main() -> int:
    _payload = read_stdin_safely()

    # 1. Python Ruff auto-fix
    if shutil.which("ruff"):
        run_cmd(["ruff", "check", "--fix", "."], cwd=REPO_ROOT)
        run_cmd(["ruff", "format", "."], cwd=REPO_ROOT)

    # 2. Frontend Biome auto-fix & format
    npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
    if npx_cmd:
        run_cmd(
            [npx_cmd, "@biomejs/biome", "check", "--write", "static/", "templates/"], cwd=REPO_ROOT
        )

    # 3. Ty type check
    if shutil.which("ty"):
        res = run_cmd(["ty", "check", "."], cwd=REPO_ROOT)
        if res.returncode != 0 and res.stderr:
            sys.stderr.write(f"[hook_post_tool] Ty type check notices:\n{res.stderr}\n")

    # Hook Contract: Must output empty JSON object to stdout
    sys.stdout.write("{}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
