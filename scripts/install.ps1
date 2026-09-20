# PyJobs Installer & Updater Script
param(
    [switch]$NonInteractive,
    [switch]$SkipLaunch,
    [switch]$ForceUpdate
)

$ErrorActionPreference = "Stop"

# 1. Resolve Project Root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

function Write-PyJobsBanner {
    Write-Host "`n=======================================================" -ForegroundColor Cyan
    Write-Host "             PyJobs Installer & Updater" -ForegroundColor Cyan
    Write-Host "=======================================================`n" -ForegroundColor Cyan
}

function Refresh-EnvPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $localBin = Join-Path $HOME ".local\bin"
    $cargoBin = Join-Path $HOME ".cargo\bin"
    
    $paths = @($localBin, $cargoBin, $userPath, $machinePath) -join ";"
    $env:PATH = $paths
}

Write-PyJobsBanner

# 2. Determine Installation State (First-Time vs. Update)
$isExistingInstall = (Test-Path (Join-Path $projectRoot ".venv")) -or $ForceUpdate

if ($isExistingInstall) {
    Write-Host "[Update Mode] Existing installation detected." -ForegroundColor Yellow
    
    $hasGit = (Get-Command git -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $projectRoot ".git"))
    if ($hasGit) {
        Write-Host "Checking git repository status..." -ForegroundColor Gray
        $statusOutput = git status --porcelain 2>&1
        $isDirty = ($statusOutput | Measure-Object).Count -gt 0

        $proceedWithGit = $true
        $stashed = $false

        if ($isDirty) {
            Write-Host "`n[WARNING] Local uncommitted changes detected in repository:" -ForegroundColor Yellow
            $statusOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
            Write-Host ""
            
            if ($NonInteractive) {
                Write-Host "Non-interactive mode: Skipping git update to preserve local changes." -ForegroundColor Yellow
                $proceedWithGit = $false
            } else {
                Write-Host "Choose how to proceed with the update:" -ForegroundColor Cyan
                Write-Host "  [1] Stash local changes, pull main, and restore changes (Recommended)"
                Write-Host "  [2] Skip git update and sync dependencies only"
                Write-Host "  [3] Cancel installer"
                $gitChoice = Read-Host "Select option [1-3] (Default: 1)"
                if ([string]::IsNullOrWhiteSpace($gitChoice)) { $gitChoice = "1" }

                switch ($gitChoice) {
                    "1" {
                        Write-Host "Stashing local changes..." -ForegroundColor Gray
                        git stash push -m "Pre-update installer stash $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-Null
                        $stashed = $true
                    }
                    "2" {
                        Write-Host "Skipping git repository pull..." -ForegroundColor Yellow
                        $proceedWithGit = $false
                    }
                    "3" {
                        Write-Host "Installation cancelled by user." -ForegroundColor Red
                        exit 0
                    }
                    default {
                        Write-Host "Invalid option. Skipping git pull..." -ForegroundColor Yellow
                        $proceedWithGit = $false
                    }
                }
            }
        }

        if ($proceedWithGit) {
            try {
                Write-Host "Fetching updates from origin/main..." -ForegroundColor Green
                git checkout main
                git pull origin main
                if ($stashed) {
                    Write-Host "Re-applying stashed changes..." -ForegroundColor Gray
                    git stash pop | Out-Null
                }
            } catch {
                Write-Host "[WARNING] Git pull encountered an issue: $_" -ForegroundColor Yellow
                Write-Host "Continuing with dependency synchronization..." -ForegroundColor Gray
            }
        }
    } else {
        Write-Host "Git repository not detected. Skipping git update check." -ForegroundColor Gray
    }
} else {
    Write-Host "[Initial Setup Mode] Fresh installation detected." -ForegroundColor Green
}

# 3. Check and Install 'uv'
Write-Host "`n[1/2] Verifying 'uv' package manager..." -ForegroundColor Cyan
Refresh-EnvPath
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue

if (-not $uvCmd) {
    # Check standard paths directly in case PATH refresh didn't catch it
    $localUv = Join-Path $HOME ".local\bin\uv.exe"
    $cargoUv = Join-Path $HOME ".cargo\bin\uv.exe"
    if (Test-Path $localUv) {
        $env:PATH = (Split-Path $localUv) + ";" + $env:PATH
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    } elseif (Test-Path $cargoUv) {
        $env:PATH = (Split-Path $cargoUv) + ";" + $env:PATH
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    }
}

if (-not $uvCmd) {
    Write-Host "'uv' is not currently installed on your system." -ForegroundColor Yellow
    Write-Host "'uv' is an ultra-fast Python package manager used to install and run PyJobs." -ForegroundColor Gray
    
    $installUv = "Y"
    if (-not $NonInteractive) {
        $installUv = Read-Host "Would you like to install 'uv' now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($installUv)) { $installUv = "Y" }
    }

    if ($installUv -match '^(y|yes)$') {
        Write-Host "Downloading and installing uv via Astral installer..." -ForegroundColor Green
        try {
            Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
            Refresh-EnvPath
            $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
            if (-not $uvCmd) {
                $localUv = Join-Path $HOME ".local\bin\uv.exe"
                if (Test-Path $localUv) {
                    $env:PATH = (Split-Path $localUv) + ";" + $env:PATH
                    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
                }
            }
        } catch {
            Write-Host "[ERROR] Failed to download or install uv: $_" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "[ERROR] 'uv' is required to install PyJobs. Please install uv manually and re-run this script." -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] uv is installed: $(& uv --version)" -ForegroundColor Green

# 4. Synchronize Python Environment & Dependencies
Write-Host "`n[2/2] Synchronizing Python environment and project dependencies..." -ForegroundColor Cyan
Write-Host "Running: uv sync" -ForegroundColor Gray
& uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[ERROR] Dependency synchronization failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "[OK] Python virtual environment and dependencies synchronized successfully!" -ForegroundColor Green

# 5. Post-Install Launch Menu
if ($SkipLaunch) {
    Write-Host "`n[OK] PyJobs installation/update complete!" -ForegroundColor Green
    exit 0
}

Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "           PyJobs Setup Completed Successfully!" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan

if ($NonInteractive) {
    Write-Host "Non-interactive mode: Exiting without launching." -ForegroundColor Gray
    exit 0
}

Write-Host "`nChoose an action:" -ForegroundColor Cyan
Write-Host "  [1] Start PyJobs (Local) - Default"
Write-Host "  [2] Start PyJobs (Network / LAN)"
Write-Host "  [3] Exit"
$launchChoice = Read-Host "`nSelect option [1-3] (Default: 1)"
if ([string]::IsNullOrWhiteSpace($launchChoice)) { $launchChoice = "1" }

switch ($launchChoice) {
    "1" {
        Write-Host "`nStarting PyJobs (Local)..." -ForegroundColor Green
        cmd.exe /c run.bat
    }
    "2" {
        Write-Host "`nStarting PyJobs (Network / LAN)..." -ForegroundColor Green
        cmd.exe /c run_network.bat
    }
    "3" {
        Write-Host "`nSetup complete. You can run PyJobs anytime using run.bat or run_network.bat." -ForegroundColor Gray
        exit 0
    }
    default {
        Write-Host "`nStarting PyJobs (Local)..." -ForegroundColor Green
        cmd.exe /c run.bat
    }
}
