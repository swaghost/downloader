# Audio Tools Tab - User Guide

## Overview

The "Audio Tools" tab (formerly "Extract Audio") now includes two powerful features:

1. **Audio Extraction** - Extract audio from video files
2. **Audio Transcription** - Convert speech to text using AI

## Audio Extraction (Existing Feature - Enhanced)

### What's New

- **Drag & Drop Support**: Now you can drag video files directly onto the drop zone instead of using Browse
- Supports: MP4, MOV, AVI, MKV, WebM, FLV, WMV, M4V

### How to Use

1. Drop a video file in the drop zone OR click "Browse..."
2. Set trim range using the slider
3. Preview the audio
4. Save as MP3, M4A, or WAV

## Audio Transcription (NEW)

### What It Does

Converts speech in audio/video files to text with timestamps using Faster-Whisper AI.

### Installation

Run this command to install the transcription feature:

```powershell
.\install-transcription.ps1
```

Or manually:

```bash
pip install faster-whisper
```

**Note**: The first transcription will download the AI model (~140MB one-time download).

### Supported Formats

- **Audio**: MP3, WAV, M4A, AAC, OGG, FLAC
- **Video**: MP4, MOV, AVI, MKV, WebM, M4V
  - For videos, audio is automatically extracted before transcription

### How to Use

1. **Load Media File**:
   - Drag & drop an audio/video file onto the transcription drop zone, OR
   - Click "Browse..." to select a file

2. **Start Transcription**:
   - Click "Start Transcription"
   - Wait while the AI processes (displays progress in status label)

3. **View Results**:
   - Transcription appears in the table with two columns:
     - **Time**: Timestamp in MM:SS.mmm format
     - **Text**: Transcribed speech

4. **Copy Results**:
   - **Copy with Timestamps**: Copies text like `[00:15.230] Hello world`
   - **Copy Text Only**: Copies just the transcribed text

5. **Save Results**:
   - Click "Save as Text File..."
   - Choose destination (app remembers last folder used)
   - File saved with timestamps in format: `[00:15.230] text`

### Tips

- Use shorter audio clips (under 10 minutes) for faster processing
- Clearer audio = better accuracy
- Background noise may affect transcription quality
- The "base" model provides good speed/accuracy balance

### Troubleshooting

**"Faster-Whisper is not installed"**

- Run `.\install-transcription.ps1` or `pip install faster-whisper`

**"ffmpeg is required to extract audio from video files"**

- Download ffmpeg from https://ffmpeg.org/download.html
- Add ffmpeg to your system PATH
- Audio files will work without ffmpeg, only videos need it

**Slow transcription**

- First run downloads the model (~140MB)
- Subsequent runs are faster
- CPU model is used for compatibility (GPU version available separately)

## Requirements

- Python 3.8+
- ffmpeg (for video files)
- faster-whisper (installed via script)

## Model Information

- Default model: "base" (~140MB)
- Language: Auto-detected
- Device: CPU with int8 optimization
- Other models available: tiny, small, medium, large (see Faster-Whisper docs)
