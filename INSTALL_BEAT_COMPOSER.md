# Beat-Composer Installation Guide

## Quick Fix for Current Error

The `madmom` installation error occurs because it needs Cython to compile. Here's how to fix it:

### Option 1: Use the Installation Script (Recommended)

```powershell
.\setup-beat-composer.ps1
```

This script will:

1. Install Cython and numpy first (build dependencies)
2. Install madmom (with proper error handling)
3. Install all other dependencies
4. Verify the installation

### Option 2: Manual Installation (Step-by-Step)

```powershell
# Step 1: Install build dependencies
pip install Cython numpy

# Step 2: Install madmom (may take a few minutes to compile)
pip install madmom

# Step 3: Install remaining dependencies
pip install librosa moviepy ffmpeg-python soundfile audioread mutagen
```

### Option 3: Skip madmom (Librosa Only)

If madmom fails to install (common on Python 3.14+), you can use Librosa only:

```powershell
# Install everything except madmom
pip install Cython numpy librosa moviepy ffmpeg-python soundfile audioread mutagen
```

**Note**: The app will still work! Just use "Librosa (Fast)" as the detection method in the GUI. It's slightly less accurate than madmom but works well for most music.

## Why Did This Happen?

`madmom` is a powerful library but requires:

1. **Cython** to compile its C extensions
2. **numpy** to be installed first
3. **C++ build tools** on some systems

Python 3.14 is very new (released 2025), and older packages like madmom (last updated 2018) may not fully support it yet.

## Troubleshooting

### Error: "No module named 'Cython'"

**Solution**: Install Cython first

```powershell
pip install Cython numpy
pip install madmom
```

### Error: "Microsoft Visual C++ 14.0 or greater is required"

**Solution**: Install Visual C++ Build Tools

1. Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. Install "Desktop development with C++" workload
3. Restart PowerShell and retry

### madmom still fails on Python 3.14

**Solution**: Use Librosa only (works great!)

```powershell
pip install librosa moviepy ffmpeg-python soundfile audioread
```

In the Beat-Composer tab, select **"Librosa (Fast)"** instead of "Madmom (Accurate)".

### FFmpeg errors during video export

**Solution**: Install FFmpeg separately

```powershell
# Using Chocolatey (easiest)
choco install ffmpeg

# Or download from: https://ffmpeg.org/download.html
# Add to PATH and restart terminal
```

## Verification

Test your installation:

```powershell
python test_beat_composer.py <path_to_audio_file.mp3>
```

This will show which libraries are working:

- ✓ librosa: Available
- ✓ moviepy: Available
- ✗ madmom: Not installed (if it failed)

## What Works Without madmom?

Everything still works! The differences:

| Feature            | Librosa     | Madmom          |
| ------------------ | ----------- | --------------- |
| Beat detection     | ✓ Fast      | ✓ More accurate |
| Downbeat detection | ✓ Estimated | ✓ Precise       |
| BPM detection      | ✓ Good      | ✓ Better        |
| Time signature     | ✓ Basic     | ✓ Advanced      |
| Speed              | ⚡ Fast     | 🐌 Slower       |
| Python 3.14+       | ✓ Works     | ⚠️ May fail     |

**Recommendation**: For social media content, Librosa is usually sufficient!

## Complete Dependency List

### Required (Core):

- `librosa` - Beat detection
- `moviepy` - Video composition
- `ffmpeg-python` - Video encoding
- `soundfile` - Audio I/O
- `audioread` - Audio format support
- `numpy` - Numerical operations

### Optional (Enhanced):

- `madmom` - Advanced beat detection
- `Cython` - Required to build madmom

### External:

- **FFmpeg** - Must be installed separately and in PATH

## Getting Help

If issues persist:

1. Check Python version: `python --version` (3.8-3.13 recommended)
2. Check pip version: `pip --version`
3. Try Python 3.11 or 3.12 if on 3.14
4. See [Documentation/BEAT_COMPOSER.md](Documentation/BEAT_COMPOSER.md)

## Summary

**For immediate use:**

```powershell
# Install Cython first
pip install Cython numpy

# Run the setup script
.\setup-beat-composer.ps1
```

**If madmom fails:**

- Use Librosa detection (works great!)
- The app is fully functional without madmom
- Only difference: slightly less accurate beat detection

**Happy composing! 🎵**
