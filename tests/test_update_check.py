from __future__ import annotations

import subprocess

import pytest

from pyjobs import update_check


def result(code: int = 0, output: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, output, "")


@pytest.mark.parametrize("branch", ["dev", "feature/search", "", "main"])
def test_only_clean_main_checks_remote(monkeypatch: pytest.MonkeyPatch, branch: str) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "branch":
            return result(output=branch)
        if args[0] == "status":
            return result(output=" M README.md")
        raise AssertionError("dirty or development checkout must not fetch")

    monkeypatch.setattr(update_check, "git", fake_git)
    assert update_check.check_for_updates() == 0
    assert ("fetch", "origin", "main") not in calls


def test_fast_forward_prompt_and_relaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "branch":
            return result(output="main")
        if args[0] == "rev-parse":
            return result(output="old" if args[1] == "HEAD" else "new")
        return result()

    monkeypatch.setattr(update_check, "git", fake_git)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert update_check.check_for_updates() == update_check.UPDATE_APPLIED
    assert ("fetch", "origin", "main") in calls
    assert ("merge", "--ff-only", "refs/remotes/origin/main") in calls


@pytest.mark.parametrize("failure", ["fetch", "merge-base", "decline"])
def test_offline_divergence_and_decline_do_not_merge(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "branch":
            return result(output="main")
        if args[0] == "rev-parse":
            return result(output="old" if args[1] == "HEAD" else "new")
        return result(code=1 if args[0] == failure else 0)

    monkeypatch.setattr(update_check, "git", fake_git)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert update_check.check_for_updates() == 0
    assert not any(args[0] == "merge" for args in calls)
