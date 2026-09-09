from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_hooks_json_validity():
    """Verify that .agents/hooks.json exists and is structured properly."""
    hooks_file = REPO_ROOT / ".agents" / "hooks.json"
    assert hooks_file.exists(), ".agents/hooks.json must exist"

    with open(hooks_file, encoding="utf-8") as f:
        data = json.load(f)

    assert "pyjobs-quality-checks" in data
    config = data["pyjobs-quality-checks"]
    assert "PostToolUse" in config
    assert len(config["PostToolUse"]) > 0

    entry = config["PostToolUse"][0]
    assert "matcher" in entry
    assert "hooks" in entry
    assert len(entry["hooks"]) > 0
    assert entry["hooks"][0]["type"] == "command"


def test_modular_rules_structure():
    """Verify that modular rules exist, are non-empty, and include required sections."""
    rules_dir = REPO_ROOT / ".agents" / "rules"
    assert rules_dir.is_dir(), ".agents/rules directory must exist"

    expected_rules = [
        "01-workflow.md",
        "02-python-backend.md",
        "03-frontend-ui.md",
        "04-testing-quality.md",
    ]

    for rule_name in expected_rules:
        rule_path = rules_dir / rule_name
        assert rule_path.exists(), f"Rule file {rule_name} must exist"
        content = rule_path.read_text(encoding="utf-8")
        assert len(content.strip()) > 50, f"Rule file {rule_name} must have substantive content"

    # Verify branch completion rule alignment check is documented
    workflow_content = (rules_dir / "01-workflow.md").read_text(encoding="utf-8")
    assert "Rule & Documentation Alignment Check" in workflow_content
    testing_content = (rules_dir / "04-testing-quality.md").read_text(encoding="utf-8")
    assert "Rule & Documentation Alignment Check" in testing_content


def test_hook_script_contract():
    """Verify that hook_post_tool.py adheres to the Antigravity PostToolUse contract."""
    hook_script = REPO_ROOT / "scripts" / "hook_post_tool.py"
    assert hook_script.exists(), "scripts/hook_post_tool.py must exist"

    payload = json.dumps(
        {
            "stepIdx": 42,
            "toolCall": {"name": "replace_file_content", "args": {}},
            "conversationId": "test-suite",
        }
    )

    res = subprocess.run(
        [sys.executable, str(hook_script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert res.returncode == 0, f"Hook exited with code {res.returncode}. Stderr: {res.stderr}"

    # Must output exactly valid JSON '{}'
    stdout_trimmed = res.stdout.strip()
    assert stdout_trimmed == "{}", f"Expected '{{}}' on stdout, got: {stdout_trimmed!r}"
