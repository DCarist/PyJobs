from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_BAT = PROJECT_ROOT / "install.bat"
INSTALL_PS1 = PROJECT_ROOT / "scripts" / "install.ps1"


def test_installer_files_exist():
    assert INSTALL_BAT.is_file(), "install.bat must exist in project root"
    assert INSTALL_PS1.is_file(), "scripts/install.ps1 must exist"


def test_install_bat_delegation():
    content = INSTALL_BAT.read_text(encoding="utf-8")
    assert "powershell -ExecutionPolicy Bypass -NoProfile -File" in content
    assert "scripts\\install.ps1" in content
    assert "%*" in content


def test_install_ps1_contains_expected_parameters_and_logic():
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert "[switch]$NonInteractive" in content
    assert "[switch]$SkipLaunch" in content
    assert "[switch]$ForceUpdate" in content
    assert "[switch]$SkipGit" in content
    assert "uv sync" in content
    assert "Refresh-EnvPath" in content
    assert "Write-PyJobsBanner" in content
    assert "run.bat" in content
    assert "run_network.bat" in content


def test_install_ps1_powershell_syntax_and_execution():
    powershell_cmd = shutil.which("powershell")
    if not powershell_cmd:
        return

    # Check AST parsing of the script
    ast_script = (
        f"$errs = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1.as_posix()}', "
        f"[ref]$null, [ref]$errs); "
        f"if ($errs) {{ $errs | ForEach-Object {{ Write-Error $_.Message }}; exit 1 }}"
    )
    ast_check = subprocess.run(
        [powershell_cmd, "-NoProfile", "-Command", ast_script],
        capture_output=True,
        text=True,
    )
    assert ast_check.returncode == 0, f"AST parser found errors: {ast_check.stderr}"

    # Run in non-interactive, skip-launch, skip-git mode
    run_result = subprocess.run(
        [
            powershell_cmd,
            "-ExecutionPolicy",
            "Bypass",
            "-NoProfile",
            "-File",
            str(INSTALL_PS1),
            "-NonInteractive",
            "-SkipLaunch",
            "-SkipGit",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, f"Installer failed: {run_result.stderr}\n{run_result.stdout}"
    assert "PyJobs Installer & Updater" in run_result.stdout
    assert "Synchronizing Python environment" in run_result.stdout
    assert "synchronized successfully" in run_result.stdout


def test_pyproject_build_system_and_wheel_overrides():
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml must exist"
    content = pyproject_path.read_text(encoding="utf-8")
    assert "[build-system]" in content
    assert 'build-backend = "hatchling.build"' in content
    assert "[tool.uv]" in content
    assert "override-dependencies" in content
    assert "regex>=2026.9.10" in content
