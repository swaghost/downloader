# Quick Install - Beat-Composer Dependencies

## TL;DR - Copy and Paste This

Open PowerShell or Command Prompt and run:

```powershell
# Install in correct order
pip install numpy Cython scipy
pip install soundfile audioread librosa mutagen
pip install moviepy ffmpeg-python
pip install madmom
```

**If madmom fails** (common on Python 3.14+), that's OK! Skip it and use Librosa instead.

## One-Command Install Scripts

### PowerShell (Recommended)

```powershell
.\install-beat-composer.ps1
```

### Command Prompt

```cmd
install-beat-composer.bat
```

## What Gets Installed

### Core (Required)

- **numpy** - Numerical operations
- **librosa** - Beat detection (works great!)
- **moviepy** - Video composition
- **ffmpeg-python** - Video encoding
- **soundfile** - Audio file I/O
- **audioread** - Audio format support
- **mutagen** - Audio metadata extraction (MP3 tags)

### Optional (Enhanced)

- **madmom** - Advanced beat detection
  - Requires: Cython, C++ compiler
  - May not work on Python 3.14+
  - **Not required** - Librosa works well!

### External

- **FFmpeg** - Download separately
  - Windows: `choco install ffmpeg`
  - Or: https://ffmpeg.org/download.html

## If Something Fails

### "No module named 'Cython'"

```powershell
pip install Cython numpy
pip install madmom
```

### madmom won't install

**Solution**: Skip it! Librosa is sufficient.

In the Beat-Composer tab, select **"Librosa (Fast)"** instead of "Madmom (Accurate)".

### "Microsoft Visual C++ required"

madmom needs a C++ compiler. Either:

1. Install Visual Studio Build Tools
2. Or skip madmom and use Librosa

### FFmpeg errors

```powershell
# Using Chocolatey
choco install ffmpeg

# Or download and add to PATH
```

## Test Installation

```powershell
python test_beat_composer.py sample.mp3
```

This will show what's working.

## Python Version Issues

- **Python 3.8-3.12**: Everything should work
- **Python 3.14+**: madmom may fail (use Librosa)

Check your version:

```powershell
python --version
```

## Minimal Install (Works Great!)

If you just want it to work without hassle:

```powershell
# Skip madmom entirely
pip install numpy librosa moviepy ffmpeg-python soundfile audioread
```

Then use "Librosa (Fast)" in the GUI - perfect for social media!

## Full Documentation

See [INSTALL_BEAT_COMPOSER.md](INSTALL_BEAT_COMPOSER.md) for complete troubleshooting.

---

**Bottom Line**: Even if madmom fails, you're good! Librosa works excellently for beat-synced videos. 🎵
