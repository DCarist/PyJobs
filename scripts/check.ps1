param (
    [switch]$Staged = $false
)

$ErrorActionPreference = "Stop"
$failed = $false

Write-Host "`n=== PyJobs Quality Gate ===" -ForegroundColor Cyan

$pyFiles = @()
$webFiles = @()

if ($Staged) {
    Write-Host "Mode: Checking STAGED files only..." -ForegroundColor Yellow
    $stagedFiles = git diff --cached --name-only --diff-filter=ACMR
    foreach ($file in $stagedFiles) {
        if ($file -match '\.py$') { $pyFiles += $file }
        if ($file -match '\.(css|html|js)$') { $webFiles += $file }
    }
} else {
    Write-Host "Mode: Full project check..." -ForegroundColor Yellow
    $pyFiles = @(".")
    $webFiles = @("static/", "templates/")
}

# 1. Python Checks (Ruff + Ty)
if ($pyFiles.Count -gt 0) {
    Write-Host "`n[1/4] Running Ruff Linter..." -ForegroundColor Green
    & ruff check $pyFiles
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Ruff linter failed!" -ForegroundColor Red
        $failed = $true
    }

    Write-Host "`n[2/4] Running Ruff Formatter Check..." -ForegroundColor Green
    & ruff format --check $pyFiles
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Ruff formatter check failed! Run 'ruff format .' to fix." -ForegroundColor Red
        $failed = $true
    }

    Write-Host "`n[3/4] Running Ty Type Checker..." -ForegroundColor Green
    & ty check .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Ty type check failed!" -ForegroundColor Red
        $failed = $true
    }
} else {
    Write-Host "`n[Python] No staged Python files to check." -ForegroundColor Gray
}

# 2. Frontend Checks (Biome)
if ($webFiles.Count -gt 0) {
    Write-Host "`n[4/4] Running Biome (CSS / HTML / JS)..." -ForegroundColor Green
    & npx @biomejs/biome check $webFiles
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Biome check failed! Run 'npx @biomejs/biome check --write' to auto-fix." -ForegroundColor Red
        $failed = $true
    }
} else {
    Write-Host "`n[Frontend] No staged web files (.css, .html, .js) to check." -ForegroundColor Gray
}

# 3. Automated Tests (pytest)
Write-Host "`n[5/5] Running Test Suite (pytest)..." -ForegroundColor Green
& uv run pytest
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Pytest test suite failed!" -ForegroundColor Red
    $failed = $true
}

if ($failed) {
    Write-Host "`n❌ Quality gate checks FAILED. Please resolve errors before proceeding." -ForegroundColor Red
    exit 1
} else {
    Write-Host "`n✅ All quality gate checks PASSED cleanly!" -ForegroundColor Green
    exit 0
}
