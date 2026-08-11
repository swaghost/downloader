@echo off
REM Beat-Composer Installation Script for Windows
REM This installs dependencies in the correct order

echo =====================================================================
echo   Beat-Composer Installation
echo =====================================================================
echo.

echo [1/4] Installing essential dependencies...
echo.
pip install numpy Cython scipy
if errorlevel 1 (
    echo ERROR: Failed to install essential dependencies
    echo Please run: pip install numpy Cython scipy
    pause
    exit /b 1
)

echo.
echo [2/4] Installing audio processing libraries...
echo.
pip install soundfile audioread librosa

echo.
echo [3/4] Installing video processing libraries...
echo.
pip install "moviepy>=1.0.3" "ffmpeg-python>=0.2.0"

echo.
echo [4/4] Installing madmom (optional, may take a few minutes)...
echo.
pip install madmom
if errorlevel 1 (
    echo.
    echo NOTE: madmom installation failed - this is OK!
    echo The app will use Librosa for beat detection instead.
    echo.
)

echo.
echo =====================================================================
echo   Installation Complete
echo =====================================================================
echo.
echo Test the installation:
echo   python test_beat_composer.py your_music.mp3
echo.
echo Launch the app:
echo   python main.py
echo.
echo In the Beat-Composer tab, if madmom failed:
echo   - Use "Librosa (Fast)" detection method
echo   - It works great for social media content!
echo.
pause
