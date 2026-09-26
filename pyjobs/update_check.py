"""Optional, fast-forward-only updates for the Windows launcher."""

from __future__ import annotations

import subprocess

UPDATE_APPLIED = 75


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False, timeout=15)


def check_for_updates() -> int:
    """Check origin/main only on a clean main checkout; never update silently."""
    try:
        branch = git("branch", "--show-current")
        if branch.returncode != 0 or branch.stdout.strip() != "main":
            return 0
        status = git("status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip():
            print("[Update] Cannot confirm clean checkout; skipping update check.")
            return 0
        fetched = git("fetch", "origin", "main")
        if fetched.returncode != 0:
            print("[Update] Could not reach origin/main; starting installed version.")
            return 0
        local = git("rev-parse", "HEAD")
        remote = git("rev-parse", "refs/remotes/origin/main")
        if local.returncode != 0 or remote.returncode != 0:
            return 0
        if local.stdout.strip() == remote.stdout.strip():
            return 0
        if git("merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/main").returncode != 0:
            print("[Update] Local main has diverged from origin/main; update manually.")
            return 0
        answer = input("[Update] New changes on origin/main. Update and relaunch? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            return 0
        merged = git("merge", "--ff-only", "refs/remotes/origin/main")
        if merged.returncode != 0:
            print("[Update] Update failed; starting installed version.")
            return 0
        print("[Update] Updated from origin/main; relaunching.")
        return UPDATE_APPLIED
    except OSError, subprocess.TimeoutExpired, EOFError:
        print("[Update] Check unavailable; starting installed version.")
        return 0


if __name__ == "__main__":
    raise SystemExit(check_for_updates())
