# Beat-Composer Installation - Simple Approach
# This script installs dependencies in the correct order with fallbacks

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Beat-Composer Installation" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Essential dependencies (always work)
Write-Host "[1/4] Installing essential dependencies..." -ForegroundColor Yellow
Write-Host ""

$essential = @("numpy", "Cython", "scipy")
foreach ($pkg in $essential) {
    Write-Host "  Installing $pkg..." -NoNewline
    pip install --quiet $pkg 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host ""
        Write-Host "Error: Failed to install $pkg" -ForegroundColor Red
        Write-Host "Try: pip install $pkg" -ForegroundColor Yellow
        exit 1
    }
}

Write-Host ""

# Step 2: Audio processing (Librosa - always needed)
Write-Host "[2/4] Installing audio processing libraries..." -ForegroundColor Yellow
Write-Host ""

$audio = @("soundfile", "audioread", "librosa")
foreach ($pkg in $audio) {
    Write-Host "  Installing $pkg..." -NoNewline
    pip install --quiet $pkg 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " WARNING" -ForegroundColor Yellow
        Write-Host "    Note: $pkg failed but may not be critical" -ForegroundColor Gray
    }
}

Write-Host ""

# Step 3: Video processing (moviepy 2.x)
Write-Host "[3/4] Installing video processing libraries..." -ForegroundColor Yellow
Write-Host ""

Write-Host "  Installing moviepy 2.x..." -NoNewline
pip install --quiet "moviepy>=2.0.0" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Host " WARNING" -ForegroundColor Yellow
}

Write-Host "  Installing ffmpeg-python..." -NoNewline
pip install --quiet "ffmpeg-python>=0.2.0" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host " OK" -ForegroundColor Green
} else {
    Write-Host " WARNING" -ForegroundColor Yellow
}

Write-Host ""

# Step 4: Advanced beat detection (madmom - optional)
Write-Host "[4/4] Installing madmom (advanced beat detection - optional)..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  This may take 2-5 minutes to compile..." -ForegroundColor Gray
Write-Host "  Installing madmom..." -NoNewline

$madmomInstalled = $false
pip install madmom 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host " OK" -ForegroundColor Green
    $madmomInstalled = $true
} else {
    Write-Host " SKIPPED" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Note: madmom requires C++ compiler and may not work on Python 3.14+" -ForegroundColor Gray
    Write-Host "  The app will use Librosa for beat detection instead (works great!)" -ForegroundColor Gray
    $madmomInstalled = $false
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Installation Summary" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# Test imports
$testScript = @"
import sys
success = []
failed = []

try:
    import librosa
    success.append('librosa')
except:
    failed.append('librosa')

try:
    import moviepy.editor
    success.append('moviepy')
except:
    failed.append('moviepy')

try:
    import ffmpeg
    success.append('ffmpeg-python')
except:
    failed.append('ffmpeg-python')

try:
    import madmom
    success.append('madmom')
except:
    failed.append('madmom')

print('SUCCESS:' + ','.join(success))
print('FAILED:' + ','.join(failed))
"@

$result = python -c $testScript 2>&1
$successLine = ($result | Select-String "^SUCCESS:").Line
$failedLine = ($result | Select-String "^FAILED:").Line

$successPkgs = ($successLine -replace 'SUCCESS:', '').Split(',') | Where-Object { $_ }
$failedPkgs = ($failedLine -replace 'FAILED:', '').Split(',') | Where-Object { $_ }

Write-Host "Installed successfully:" -ForegroundColor Green
foreach ($pkg in $successPkgs) {
    if ($pkg) {
        Write-Host "  ✓ $pkg" -ForegroundColor Green
    }
}

if ($failedPkgs.Count -gt 0 -and $failedPkgs[0]) {
    Write-Host ""
    Write-Host "Not installed (optional):" -ForegroundColor Yellow
    foreach ($pkg in $failedPkgs) {
        if ($pkg) {
            Write-Host "  ○ $pkg" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# Check FFmpeg
Write-Host "Checking FFmpeg (required for video export)..." -ForegroundColor Cyan
$ffmpegExists = $false
try {
    ffmpeg -version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ FFmpeg is installed" -ForegroundColor Green
        $ffmpegExists = $true
    }
} catch {
    $ffmpegExists = $false
}

if (-not $ffmpegExists) {
    Write-Host "  ✗ FFmpeg not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "  FFmpeg is required for video export. Install it:" -ForegroundColor Yellow
    Write-Host "    Option 1 (Easy): choco install ffmpeg" -ForegroundColor White
    Write-Host "    Option 2: Download from https://ffmpeg.org/download.html" -ForegroundColor White
    Write-Host "              Extract and add to PATH" -ForegroundColor White
}

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  Next Steps" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

if ($ffmpegExists) {
    Write-Host "✓ You're ready to use Beat-Composer!" -ForegroundColor Green
} else {
    Write-Host "⚠ Install FFmpeg to enable video export" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "To test:" -ForegroundColor Cyan
Write-Host "  python test_beat_composer.py your_music.mp3" -ForegroundColor White
Write-Host ""
Write-Host "To launch the app:" -ForegroundColor Cyan
Write-Host "  python main.py" -ForegroundColor White
Write-Host ""

if (-not $madmomInstalled) {
    Write-Host "Note: In the Beat-Composer tab, use 'Librosa (Fast)' detection method" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "Documentation: Documentation\BEAT_COMPOSER.md" -ForegroundColor Cyan
Write-Host ""
