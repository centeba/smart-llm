<#
.SYNOPSIS
    Setup script for 'smart-llm' library.
.DESCRIPTION
    Creates a virtual environment and installs the package in editable mode.
#>

Write-Host "===========================" -ForegroundColor Cyan
Write-Host "smart-llm Library Setup" -ForegroundColor Cyan
Write-Host "===========================" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[1/3] Checking Prerequisites..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python is not installed or not in PATH."
    exit 1
} else {
    Write-Host "  Found $pythonVersion" -ForegroundColor Green
}

# 2. Virtual Environment
Write-Host "`n[2/3] Setting up Virtual Environment..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  Created .venv directory." -ForegroundColor Green
} else {
    Write-Host "  .venv already exists." -ForegroundColor Green
}

# 3. Install Package
Write-Host "`n[3/3] Installing Package (Editable)..." -ForegroundColor Yellow
& ".\.venv\Scripts\pip.exe" install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install package."
    exit 1
} else {
    Write-Host "  Package installed successfully." -ForegroundColor Green
}

Write-Host "`nSetup Complete!" -ForegroundColor Green
Write-Host "-------------------------------------------"
Write-Host "To run the demo:"
Write-Host "1. Activate venv:   .\.venv\Scripts\Activate.ps1"
Write-Host "2. Set API keys in: .env"
Write-Host "3. Run demo:        python examples/agent_demo.py"
Write-Host "-------------------------------------------"
