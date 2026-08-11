# Beat-Composer Dependency Installation Script
# Run this to install all required libraries for the Beat-Composer feature

Write-Host "=" -NoNewline
Write-Host ("=" * 79)
Write-Host "Beat-Composer Dependency Installer"
Write-Host "=" -NoNewline
Write-Host ("=" * 79)
Write-Host ""

# Check Python version
Write-Host "Checking Python version..." -ForegroundColor Cyan
$pythonVersion = python --version 2>&1
Write-Host "  $pythonVersion"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Python not found. Please install Python 3.8 or higher." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Check if pip is available
Write-Host "Checking pip..." -ForegroundColor Cyan
$pipVersion = pip --version 2>&1
Write-Host "  $pipVersion"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: pip not found. Please install pip." -ForegroundColor Red
    exit 1
}
Write-Host ""

# Install dependencies
Write-Host "Installing Beat-Composer dependencies..." -ForegroundColor Cyan
Write-Host ""

# Install Cython first (required for madmom compilation)
Write-Host "Step 1: Installing Cython (required for madmom)..." -ForegroundColor Yellow
pip install "Cython>=0.29.0" "numpy>=1.24.0"

if ($LASTEXITCODE -ne 0) {
    Write-Host "  Warning: Failed to install build dependencies" -ForegroundColor Yellow
} else {
    Write-Host "  ✓ Successfully installed Cython and numpy" -ForegroundColor Green
}
Write-Host ""

# Install madmom separately (may take time to compile)
Write-Host "Step 2: Installing madmom (this may take several minutes)..." -ForegroundColor Yellow
pip install "madmom>=0.16.1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "  ⚠ Failed to install madmom" -ForegroundColor Yellow
    Write-Host "  Note: madmom requires compilation and may not work on Python 3.14+" -ForegroundColor Yellow
    Write-Host "  You can still use Librosa for beat detection (faster, but less accurate)" -ForegroundColor Yellow
    $madmomFailed = $true
} else {
    Write-Host "  ✓ Successfully installed madmom" -ForegroundColor Green
    $madmomFailed = $false
}
Write-Host ""

# Install remaining dependencies
Write-Host "Step 3: Installing remaining dependencies..." -ForegroundColor Yellow
$dependencies = @(
    "librosa>=0.10.0",
    "moviepy>=1.0.3",
    "ffmpeg-python>=0.2.0",
    "soundfile>=0.12.0",
    "audioread>=3.0.0"
)

foreach ($dep in $dependencies) {
    Write-Host "Installing $dep..." -ForegroundColor Yellow
    pip install $dep
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Warning: Failed to install $dep" -ForegroundColor Yellow
    } else {
        Write-Host "  ✓ Successfully installed $dep" -ForegroundColor Green
    }
    Write-Host ""
}

Write-Host "=" -NoNewline
Write-Host ("=" * 79)
if ($madmomFailed) {
    Write-Host "Installation Partially Complete (madmom failed)" -ForegroundColor Yellow
} else {
    Write-Host "Installation Complete!" -ForegroundColor Green
}
Write-Host "=" -NoNewline
Write-Host ("=" * 79)
Write-Host ""

if ($madmomFailed) {
    Write-Host "⚠ Important Note:" -ForegroundColor Yellow
    Write-Host "  madmom failed to install. This is often due to:" -ForegroundColor Yellow
    Write-Host "  1. Python 3.14+ compatibility issues (madmom is older)" -ForegroundColor Yellow
    Write-Host "  2. Missing C++ build tools" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Solutions:" -ForegroundColor Cyan
    Write-Host "  • Use Librosa detection method (available, slightly less accurate)" -ForegroundColor White
    Write-Host "  • Install Visual C++ Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor White
    Write-Host "  • Use Python 3.11 or 3.12 instead of 3.14" -ForegroundColor White
    Write-Host ""
}

# Check FFmpeg
Write-Host "Checking for FFmpeg..." -ForegroundColor Cyan
$ffmpegCheck = ffmpeg -version 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ FFmpeg is installed" -ForegroundColor Green
    $ffmpegVersion = ($ffmpegCheck | Select-String "ffmpeg version").Line
    Write-Host "  $ffmpegVersion"
} else {
    Write-Host "  ⚠ FFmpeg not found in PATH" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "FFmpeg is required for video export. Install it:" -ForegroundColor Yellow
    Write-Host "  1. Download from: https://ffmpeg.org/download.html" -ForegroundColor Yellow
    Write-Host "  2. Extract to a folder (e.g., C:\ffmpeg)" -ForegroundColor Yellow
    Write-Host "  3. Add the 'bin' folder to your system PATH" -ForegroundColor Yellow
    Write-Host "  4. Restart this terminal" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Alternative (using Chocolatey):" -ForegroundColor Yellow
    Write-Host "  choco install ffmpeg" -ForegroundColor Yellow
}
Write-Host ""

# Test installation
Write-Host "Testing installation..." -ForegroundColor Cyan
Write-Host ""

$testScript = @"
import sys
try:
    import librosa
    print('✓ librosa:', librosa.__version__)
except ImportError as e:
    print('✗ librosa: Not installed')

try:
    import madmom
    print('✓ madmom:', madmom.__version__)
except ImportError as e:
    print('✗ madmom: Not installed')

try:
    import moviepy
    print('✓ moviepy:', moviepy.__version__)
except ImportError as e:
    print('✗ moviepy: Not installed')

try:
    import ffmpeg
    print('✓ ffmpeg-python: Installed')
except ImportError as e:
    print('✗ ffmpeg-python: Not installed')

try:
    import soundfile
    print('✓ soundfile:', soundfile.__version__)
if ($madmomFailed) {
    Write-Host "  1. In the Beat-Composer tab, use 'Librosa (Fast)' detection method"
    Write-Host "  2. If FFmpeg is missing, install it (see instructions above)"
    Write-Host "  3. Test Beat-Composer: python test_beat_composer.py <audio_file>"
    Write-Host "  4. Launch the app: python main.py"
    Write-Host "  5. Navigate to the 'Beat-Composer' tab"
} else {
    Write-Host "  1. If FFmpeg is missing, install it (see instructions above)"
    Write-Host "  2. Test Beat-Composer: python test_beat_composer.py <audio_file>"
    Write-Host "  3. Launch the app: python main.py"
    Write-Host "  4. Navigate to the 'Beat-Composer' tab"
}
    import audioread
    print('✓ audioread:', audioread.__version__)
except ImportError as e:
    print('✗ audioread: Not installed')
"@

python -c $testScript

Write-Host ""
Write-Host "=" -NoNewline
Write-Host ("=" * 79)
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "  1. If FFmpeg is missing, install it (see instructions above)"
Write-Host "  2. Test Beat-Composer: python test_beat_composer.py <audio_file>"
Write-Host "  3. Launch the app: python main.py"
Write-Host "  4. Navigate to the 'Beat-Composer' tab"
Write-Host ""
Write-Host "Documentation: Documentation\BEAT_COMPOSER.md" -ForegroundColor Cyan
Write-Host ""
Write-Host "Happy composing! 🎵" -ForegroundColor Green
