$ErrorActionPreference = "Stop"

Write-Host "`n=== PyJobs Auto-Formatter & Linter Fixer ===" -ForegroundColor Cyan

Write-Host "`n[1/3] Running Ruff Linter Auto-Fix..." -ForegroundColor Green
& ruff check --fix .

Write-Host "`n[2/3] Running Ruff Formatter..." -ForegroundColor Green
& ruff format .

Write-Host "`n[3/3] Running Biome Auto-Fix & Format (CSS / HTML / JS)..." -ForegroundColor Green
& npx @biomejs/biome check --write static/ templates/

Write-Host "`n[4/4] Verifying with Ty Type Checker..." -ForegroundColor Green
& ty check .

Write-Host "`n✅ All files formatted, linted, and type-checked cleanly!" -ForegroundColor Green
