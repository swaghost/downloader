# Kill Chrome Processes Utility
# Use this script when you get "Access is denied" errors with ChromeDriver
# This happens when previous ChromeDriver processes didn't terminate properly

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Chrome/ChromeDriver Process Killer" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

# Check for running ChromeDriver processes
Write-Host "Checking for ChromeDriver processes..." -ForegroundColor Yellow
$chromedrivers = Get-Process chromedriver -ErrorAction SilentlyContinue
if ($chromedrivers) {
    Write-Host "Found $($chromedrivers.Count) ChromeDriver process(es)" -ForegroundColor Red
    Stop-Process -Name chromedriver -Force -ErrorAction SilentlyContinue
    Write-Host "✓ Killed all ChromeDriver processes" -ForegroundColor Green
} else {
    Write-Host "✓ No ChromeDriver processes running" -ForegroundColor Green
}

# Check for Chrome processes launched by automation
Write-Host "`nChecking for automated Chrome processes..." -ForegroundColor Yellow
$chromes = Get-Process chrome -ErrorAction SilentlyContinue
if ($chromes) {
    Write-Host "Found $($chromes.Count) Chrome process(es)" -ForegroundColor Yellow
    Write-Host "Note: Not killing Chrome automatically (may be your regular browser)" -ForegroundColor Yellow
    Write-Host "If you want to kill all Chrome processes, run: Stop-Process -Name chrome -Force" -ForegroundColor Yellow
} else {
    Write-Host "✓ No Chrome processes running" -ForegroundColor Green
}

# Option to clear WebDriver Manager cache
Write-Host "`n============================================================" -ForegroundColor Cyan
$wdmPath = Join-Path $env:USERPROFILE ".wdm"
if (Test-Path $wdmPath) {
    Write-Host "WebDriver Manager cache found at: $wdmPath" -ForegroundColor Yellow
    $size = (Get-ChildItem $wdmPath -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "Cache size: $([math]::Round($size, 2)) MB" -ForegroundColor Yellow
    
    $response = Read-Host "`nDo you want to delete the WebDriver cache? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        try {
            Remove-Item $wdmPath -Recurse -Force -ErrorAction Stop
            Write-Host "✓ WebDriver cache deleted" -ForegroundColor Green
            Write-Host "ChromeDriver will be re-downloaded on next run" -ForegroundColor Cyan
        } catch {
            Write-Host "✗ Failed to delete cache: $_" -ForegroundColor Red
            Write-Host "Try closing all applications and run this script as Administrator" -ForegroundColor Yellow
        }
    } else {
        Write-Host "Cache not deleted" -ForegroundColor Yellow
    }
} else {
    Write-Host "✓ No WebDriver cache found" -ForegroundColor Green
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "Done! You can now run the Instagram Downloader." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
