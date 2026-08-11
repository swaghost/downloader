# Beat-Composer - Music Video Synchronization

## Overview

The **Beat-Composer** tab is a professional music video creation tool that automatically synchronizes images and videos to beats in audio tracks. Perfect for creating engaging social media content with rhythm-based visual transitions.

## Features

### 1. **Automatic Beat Detection**

- **BPM Detection**: Automatically detects tempo (beats per minute)
- **Beat Positions**: Identifies exact timestamps for every beat
- **Downbeat Detection**: Finds the start of each measure
- **Time Signature**: Estimates the time signature (e.g., 4/4, 3/4)

### 2. **Flexible Timeline Configuration**

Three duration modes:

- **Full Audio**: Use the complete audio track
- **N Seconds**: Create a video of specific length
- **N Measures**: Build timeline based on musical measures

Beat type options:

- **All Beats**: Include every detected beat
- **Downbeats Only**: Use only measure starts for longer intervals

### 3. **Precise Beat Adjustment**

- **Independent Mode**: Move individual beats without affecting others
- **Unified Mode**: Shift beats together (moving one moves all subsequent beats)
- **Fine Control**: Adjust timestamps with 0.01-second precision

### 4. **Media Assignment**

- Assign images or videos to any beat
- Set custom display duration for each media element
- Visual indicators show which beats have assigned media
- Easy media removal and replacement

### 5. **Preview & Export**

- **Preview**: Watch your composition before final render
- **Export**: Save high-quality video optimized for social media
- **Format**: 1080x1920 vertical video (perfect for Instagram/TikTok)

### 6. **Project Management**

- **Save Projects**: Store your work as JSON files
- **Load Projects**: Resume editing anytime
- **Portability**: Projects include all settings and media assignments

## Quick Start

### Step 1: Load Audio

1. Click **"📂 Select Audio"**
2. Choose your music file (MP3, WAV, M4A, etc.)
3. View the **Audio Information Panel** that appears above, showing:
   - **Filename**: The name of your audio file
   - **Duration**: Total length in MM:SS format
   - **Title**: Song title from MP3 metadata (if available)
   - **Artist**: Artist name from MP3 metadata (if available)
4. Optional: Click **"▶️ Preview Audio"** to listen to the track
5. Optional: Click **"ℹ️ Audio Info"** to view detailed technical metadata

### Step 2: Detect Beats

1. Choose detection method:
   - **Librosa (Fast)**: Quick analysis, good for preview
   - **Madmom (Accurate)**: Production-quality detection (recommended)
2. Click **"🎵 Detect Beats"**
3. Wait for analysis (Madmom takes longer but is more accurate)
4. Review detection results: BPM, beat count, time signature

### Step 3: Configure Timeline

1. Select duration mode:
   - **Full Audio**: Use entire track
   - **N Seconds**: Specify exact duration
   - **N Measures**: Set number of musical measures
2. Choose beat type:
   - Check **"Include All Beats"** for frequent transitions
   - Check **"Use Downbeats Only"** for slower, measure-based cuts
3. Click **"🔨 Build Timeline"**

### Step 4: Assign Media

1. Click on a beat in the timeline list
2. Click **"🖼️ Assign Image"** or **"🎬 Assign Video"**
3. Select your media file
4. Adjust **"Display Duration"** if needed (default: 0.5s)
5. Repeat for all desired beats

### Step 5: Fine-Tune (Optional)

1. Select a beat in the timeline
2. Set **"Movement Mode"**:
   - **Independent**: Adjust only this beat
   - **Unified**: Move all subsequent beats together
3. Enter **"Offset (seconds)"** (positive or negative)
4. Click **"Apply Offset"**

### Step 6: Export

1. Click **"▶️ Preview Video"** to review (opens in default player)
2. If satisfied, click **"💾 Export Video"**
3. Choose save location
4. Wait for rendering
5. Your video is ready!

## Libraries Used

### Beat Detection

- **librosa**: Fast tempo and beat detection, good for prototyping
- **madmom**: State-of-the-art beat/downbeat detection using deep learning

### Video Composition

- **moviepy**: High-level video editing and composition
- **ffmpeg-python**: Professional video encoding and rendering

## Installation

Install the required dependencies:

```powershell
pip install librosa madmom moviepy ffmpeg-python soundfile audioread mutagen
```

**Note**: Some systems may require separate FFmpeg installation:

- **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt-get install ffmpeg`

## Tips & Best Practices

### For Best Beat Detection

1. **Use Madmom** for final projects (more accurate)
2. **Use Librosa** for quick tests and experimentation
3. **Clean audio** works best (avoid heavily compressed files)
4. **Electronic music** and tracks with clear percussion detect best

### For Great Compositions

1. **Match content to beats**: Fast beats = quick cuts, slow beats = longer displays
2. **Downbeats for emphasis**: Use downbeats for important moments
3. **Vary display duration**: Not all media needs the same timing
4. **Preview often**: Check your work before final export

### For Smooth Workflow

1. **Save your project** regularly using **"💾 Save Project"**
2. **Name media files clearly** for easier identification
3. **Test with shorter durations** first (e.g., 15 seconds)
4. **Organize media** in folders by type or theme

## Timeline Legend

Timeline beats show these indicators:

- **⭕** - No media assigned
- **📁** - Media assigned (image or video)
- **Beat XXX** - Beat number in sequence
- **X.XXXs** - Timestamp in seconds
- **Type** - Beat or downbeat

## Output Specifications

Default export settings:

- **Resolution**: 1080x1920 (9:16 vertical)
- **FPS**: 30 frames per second
- **Codec**: H.264 (MP4)
- **Audio**: AAC
- **Background**: Black (customizable in code)

Perfect for:

- Instagram Reels
- TikTok
- YouTube Shorts
- Instagram Stories

## Troubleshooting

### "librosa not available" error

```powershell
pip install librosa soundfile audioread mutagen
```

### "madmom not available" error

```powershell
pip install madmom
```

### "moviepy not available" error

```powershell
pip install moviepy
```

### FFmpeg errors

- Ensure FFmpeg is installed and in system PATH
- Windows: Download from ffmpeg.org and add to PATH
- Restart the application after installing FFmpeg

### Beat detection too sensitive/not sensitive enough

- This is controlled by the underlying algorithms
- Try both detection methods to see which works better
- Madmom generally provides more consistent results

### Preview doesn't open

- Ensure you have a default video player installed
- Try manually opening the preview file from:
  - Windows: `%TEMP%\beat_composer_preview\preview.mp4`
  - macOS/Linux: `/tmp/beat_composer_preview/preview.mp4`

### Video export is slow

- Video rendering is CPU-intensive
- Typical speeds: 0.5-2x realtime
- Longer videos and more media = longer render times
- Close other applications to free up resources

## Project File Format

Projects are saved as JSON with this structure:

```json
{
  "version": "1.0",
  "audio_path": "/path/to/audio.mp3",
  "bpm": 128.5,
  "duration": 180.0,
  "time_signature": [4, 4],
  "beats": [0.0, 0.468, 0.937, ...],
  "downbeats": [0.0, 1.875, 3.750, ...],
  "timeline": [
    {
      "index": 0,
      "original_time": 0.0,
      "adjusted_time": 0.0,
      "type": "beat",
      "duration": 0.5,
      "media": {
        "type": "image",
        "path": "/path/to/image.jpg"
      }
    },
    ...
  ]
}
```

## Advanced Usage

### Custom Resolution

Edit `beat_composer_manager.py`, modify the `compose_video` call:

```python
resolution=(1920, 1080)  # Horizontal video
```

### Custom Background Color

```python
background_color=(255, 255, 255)  # White background
```

### Custom FPS

```python
fps=60  # Smoother motion
```

## Support

For issues or questions:

1. Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Review [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
3. Check the main [README.md](../README.md)

---

**Created**: 2026-08-04  
**Version**: 1.0  
**Status**: Production Ready
