# Audio Transcription Installation
# This script installs faster-whisper for speech-to-text functionality

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Audio Transcription Installation" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "This will install faster-whisper for audio/video transcription." -ForegroundColor White
Write-Host ""

# Check if ffmpeg is available
Write-Host "Checking for ffmpeg..." -NoNewline
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Host " NOT FOUND" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Warning: ffmpeg is required for video file transcription." -ForegroundColor Yellow
    Write-Host "Audio files will work without it, but video files need ffmpeg." -ForegroundColor Yellow
    Write-Host "Download from: https://ffmpeg.org/download.html" -ForegroundColor Cyan
    Write-Host ""
}

# Install faster-whisper
Write-Host "Installing faster-whisper..." -NoNewline
pip install --quiet faster-whisper 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Host " FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: Failed to install faster-whisper" -ForegroundColor Red
    Write-Host "Try manually: pip install faster-whisper" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "You can now use the transcription feature in the Audio Tools tab." -ForegroundColor White
Write-Host ""
Write-Host "Note: The first time you run a transcription, faster-whisper will" -ForegroundColor Yellow
Write-Host "download the 'base' model (~140MB). This is a one-time download." -ForegroundColor Yellow
Write-Host ""
Write-Host "Press any key to continue..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
