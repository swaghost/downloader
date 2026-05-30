# GitHub Automation Setup Script for Windows
# Run this after cloning the repository to setup all development tools

Write-Host "`n🚀 Instagram Downloader - Development Setup`n" -ForegroundColor Cyan

# Check Python version
Write-Host "Checking Python version..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
Write-Host "✓ $pythonVersion" -ForegroundColor Green

# Install development dependencies
Write-Host "`nInstalling development dependencies..." -ForegroundColor Yellow
pip install -r requirements-dev.txt

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Development dependencies installed" -ForegroundColor Green
} else {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Setup pre-commit hooks
Write-Host "`nSetting up pre-commit hooks..." -ForegroundColor Yellow
pre-commit install

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Pre-commit hooks installed" -ForegroundColor Green
} else {
    Write-Host "❌ Failed to setup pre-commit hooks" -ForegroundColor Red
    exit 1
}

# Run pre-commit on all files (optional, can be slow)
Write-Host "`nRunning initial pre-commit check..." -ForegroundColor Yellow
Write-Host "(This may take a few minutes on first run)" -ForegroundColor Gray
pre-commit run --all-files

# Summary
Write-Host "`n✅ SETUP COMPLETE`n" -ForegroundColor Green
Write-Host "Your development environment is ready!" -ForegroundColor Cyan
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  1. Make changes to your code"
Write-Host "  2. git add <files>"
Write-Host "  3. git commit -m 'message'"
Write-Host "  4. Pre-commit hooks will run automatically"
Write-Host "`nUseful commands:" -ForegroundColor Yellow
Write-Host "  pre-commit run --all-files  # Run all hooks manually"
Write-Host "  pre-commit autoupdate       # Update hook versions"
Write-Host "  git commit --no-verify      # Bypass hooks (use sparingly)"
Write-Host "`nDocumentation:" -ForegroundColor Yellow
Write-Host "  See Documentation/GITHUB_AUTOMATION.md for more details`n"
