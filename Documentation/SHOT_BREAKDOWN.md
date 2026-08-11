# Shot Breakdown - Cinematic Video Analysis Tool

## Overview

The Shot Breakdown tool is a complete automated system for analyzing videos shot-by-shot, extracting cinematic metadata, and generating AI-ready prompts for video generation tools like Runway, Pika, Luma, Kling, and Stable Video.

## Features

### 1. **Video Ingestion**

- Support for multiple video formats: MP4, MOV, MKV, M4V, WebM, AVI, FLV
- Automatic video metadata extraction (resolution, FPS, duration, frame count)
- File size and codec detection

### 2. **Shot Detection**

Two detection methods available:

#### **PySceneDetect (Professional)**

- Uses content-aware scene detection algorithms
- More accurate cut detection
- Better handling of gradual transitions
- Requires `scenedetect[opencv]` package

#### **OpenCV (Basic)**

- Frame-difference based detection
- Always available (no extra dependencies beyond opencv-python)
- Good for hard cuts and simple transitions
- Faster processing on simple videos

**Sensitivity Control:**

- Adjustable threshold slider (10-50)
- Lower values = more sensitive (detects more shots)
- Higher values = less sensitive (fewer shots)
- Default: 27 (balanced)

### 3. **Frame Extraction**

For each detected shot, the system extracts:

- **First frame:** Shot opening
- **Middle frame:** Most representative frame
- **Last frame:** Frame before cut

All keyframes are saved as JPG images in the project's `keyframes/` folder.

### 4. **Scene Labeling**

Each shot is automatically labeled with structured metadata:

#### **Shot Type**

- Extreme Wide Shot (EWS)
- Wide Shot (WS)
- Full Shot
- Medium Full Shot
- Medium Shot (MS)
- Medium Close-Up (MCU)
- Close-Up (CU)
- Extreme Close-Up (ECU)

#### **Camera Angle**

- Eye Level
- Low Angle
- High Angle
- Dutch Tilt / Canted Angle
- Overhead / Bird's Eye
- Worm's Eye View

#### **Camera Movement**

- Static
- Pan
- Tilt
- Dolly
- Tracking Shot
- Handheld
- Crane Shot
- Zoom

#### **Composition Analysis**

- Resolution and aspect ratio
- Color histogram analysis
- Average hue, saturation, brightness
- Lighting classification (dark/mid/bright)
- Color temperature (warm/cool/neutral)
- Brightness distribution percentages

#### **Motion Detection**

- Optical flow analysis
- Movement magnitude and direction
- Motion type classification (static/moving)
- Direction vectors (up/down/left/right)

### 5. **Dependency Mapping**

The system analyzes continuity between shots:

#### **A. Visual Continuity**

- **Lighting Match:** Identifies shots with matching lighting conditions
- **Color Temperature Match:** Tracks warm/cool/neutral color consistency
- **Wardrobe Continuity:** (Framework in place for future ML integration)
- **Environment Match:** (Framework in place)

#### **B. Motion Continuity**

- **Direction Continuity:** Tracks consistent camera movement directions
- **Movement Type Match:** Identifies static/pan/tilt/dolly patterns
- **Pacing Consistency:** (Framework in place)

#### **C. Narrative Continuity**

- **Sequential Dependencies:** Tracks shot order and flow
- **Action Completion:** (Framework in place for action detection)
- **Temporal Ordering:** Maintains chronological relationships

#### **D. Emotional Continuity**

- Framework in place for:
  - Facial expression classification
  - Tone estimation
  - Audio sentiment analysis
  - Emotional pacing

### 6. **Prompt Generation**

Each shot is converted into an AI-ready prompt with:

**Core Description:**

- Shot type and framing
- Subject identification (when available)
- Action description (when available)

**Visual Style:**

- Lighting description (low-key/high-key/balanced)
- Color temperature (warm/cool/neutral)
- Mood and tone

**Camera Work:**

- Camera movement type and direction
- Camera angle specification

**Continuity Requirements:**

- Visual dependencies from previous shots
- Motion continuity notes
- Narrative connections

**Technical Specs:**

- Duration in seconds
- Resolution and aspect ratio

**Example Prompt:**

```
Create a Medium Close-Up in balanced lighting with neutral tones.
Camera: Static. Angle: Eye Level.

CONTINUITY: Maintains mid lighting from Shot 5.
Maintains neutral color temperature.

TONE: neutral

DURATION: 3.45 seconds
```

## Project Structure

Each video analysis creates a project folder:

```
Documents/ShotBreakdowns/
└── VideoName_20260801_123456_a1b2c3d4/
    ├── project.json           # Project metadata
    ├── shots/                 # Shot-specific data
    ├── frames/                # Extracted frames
    ├── keyframes/             # First/middle/last frames per shot
    │   ├── shot_0001_first_frame_000000.jpg
    │   ├── shot_0001_middle_frame_000015.jpg
    │   ├── shot_0001_last_frame_000029.jpg
    │   └── ...
    └── analysis/
        ├── shot_breakdown.json  # Complete analysis results
        └── prompts.txt          # AI-ready prompts text file
```

## Usage

### GUI Workflow

1. **Open the Shot Breakdown Tab**
   - Click the "🎬 Shot Breakdown" tab in the main window

2. **Select a Video**
   - Click "📂 Select Video"
   - Choose your video file
   - Optionally click "ℹ️ Video Info" to view metadata

3. **Configure Detection Settings**
   - Choose detection method:
     - **Auto:** Uses PySceneDetect if installed, otherwise OpenCV
     - **PySceneDetect:** Professional detection (recommended)
     - **OpenCV:** Basic detection (always available)
   - Adjust sensitivity slider (10-50)
     - Lower = more shots detected
     - Higher = fewer shots detected

4. **Process the Video**
   - Click "🎬 Process Video"
   - Wait for analysis to complete (progress bar shows status)
   - Processing time depends on video length and method

5. **Review Results**
   - Shot list displays all detected shots with timecodes
   - Click any shot to view:
     - Detailed metadata
     - Composition analysis
     - Dependencies
     - AI prompt
     - Keyframe previews

6. **Export Results**
   - **📄 Export JSON:** Complete analysis data for further processing
   - **📝 Export Prompts:** Text file with all AI prompts
   - **📁 Open Project Folder:** Browse all extracted frames and data

### Command-Line Usage

```bash
python shot_breakdown_manager.py video.mp4
```

This will:

- Create a project folder
- Detect shots
- Extract keyframes
- Generate labels and prompts
- Save JSON and text outputs

## API Usage

```python
from shot_breakdown_manager import ShotBreakdownManager

# Initialize manager
manager = ShotBreakdownManager()

# Process a video
results = manager.process_video(
    'path/to/video.mp4',
    threshold=27.0,
    method='auto'
)

# Access results
print(f"Detected {results['shot_count']} shots")

for shot in results['shots']:
    print(f"Shot {shot['shot_number']}: {shot['prompt']}")

# Results are saved to:
# - results['project_dir']/analysis/shot_breakdown.json
# - results['project_dir']/analysis/prompts.txt
```

## Installation

### Required Dependencies

```bash
# Core dependencies (already in requirements.txt)
pip install opencv-python numpy PyQt5
```

### Optional: Professional Shot Detection

```bash
# For PySceneDetect support (recommended)
pip install scenedetect[opencv]
```

The tool works without `scenedetect` but falls back to basic OpenCV frame-difference detection.

## Output Formats

### JSON Structure

```json
{
  "video_info": {
    "width": 1920,
    "height": 1080,
    "fps": 24.0,
    "frame_count": 720,
    "duration_seconds": 30.0
  },
  "shot_count": 8,
  "detection_method": "scenedetect",
  "threshold": 27.0,
  "shots": [
    {
      "shot_number": 1,
      "start_frame": 0,
      "end_frame": 45,
      "start_time": 0.0,
      "end_time": 1.875,
      "duration": 1.875,
      "keyframes": ["path/to/keyframe1.jpg", ...],
      "composition": {
        "width": 1920,
        "height": 1080,
        "aspect_ratio": 1.78,
        "lighting": "bright",
        "color_temperature": "warm"
      },
      "movement": {
        "type": "static",
        "magnitude": 0.5,
        "direction": "none"
      },
      "labels": {
        "shot_type": "medium",
        "camera_angle": "eye_level",
        "camera_movement": "static"
      },
      "dependencies": {
        "visual": [],
        "motion": [],
        "narrative": []
      },
      "prompt": "Create a Medium Shot..."
    }
  ]
}
```

### Text Prompts Format

```
Shot Breakdown Prompts - video.mp4
Generated: 2026-08-01 12:34:56
================================================================================

SHOT 001
--------------------------------------------------------------------------------
Timecode: 0.00s - 1.88s
Duration: 1.88s

Create a Medium Shot in bright, high-key lighting with warm tones.
Camera: Static. Angle: Eye Level.

DURATION: 1.88 seconds

================================================================================
```

## Performance

### Processing Speed

- **PySceneDetect:** ~0.5-2x realtime (30-min video = 15-60 min processing)
- **OpenCV:** ~1-3x realtime (30-min video = 10-30 min processing)

Factors affecting speed:

- Video resolution (4K is slower than 1080p)
- Frame rate (60fps is slower than 24fps)
- Detection sensitivity (lower threshold = slower)
- System hardware (CPU/GPU)

### Storage

Each project creates:

- **Keyframes:** ~3 JPG images per shot (typically 100-500 KB each)
- **JSON:** 1-10 MB depending on shot count
- **Prompts:** 10-100 KB text file

Example: 30-minute video with 100 shots:

- ~300 keyframe images = ~90 MB
- JSON = ~2 MB
- Total project size = ~100 MB

## Troubleshooting

### PySceneDetect Not Found

**Symptom:** "PySceneDetect not available" warning

**Solution:**

```bash
pip install scenedetect[opencv]
```

Or use OpenCV method (already available).

### Too Many/Few Shots Detected

**Symptom:** Shot list is too granular or misses obvious cuts

**Solution:**

- **Too many shots:** Increase sensitivity slider (30-40)
- **Too few shots:** Decrease sensitivity slider (15-25)
- Try switching detection methods (PySceneDetect vs OpenCV)

### Out of Memory

**Symptom:** Process crashes during analysis

**Solution:**

- Close other applications
- Process shorter video segments
- Use OpenCV method (lower memory usage)

### Slow Processing

**Symptom:** Takes very long to process

**Solution:**

- Increase sensitivity threshold (processes fewer frames)
- Use OpenCV method (faster but less accurate)
- Consider processing at lower resolution first

## Future Enhancements

The current implementation provides a solid foundation with placeholders for:

1. **ML-Based Shot Classification**
   - Train models to classify shot types automatically
   - Subject detection and recognition
   - Action recognition

2. **Audio Analysis**
   - Dialogue detection
   - Music/sound effect classification
   - Audio sentiment analysis

3. **Advanced Dependency Mapping**
   - Object tracking across shots
   - Face recognition for character continuity
   - Automatic match-cut detection

4. **Cinematic Metrics**
   - Rule of thirds analysis
   - Composition scoring
   - Color grading patterns

5. **Integration with Video Generation APIs**
   - Direct upload to Runway/Pika/Luma
   - API-based prompt submission
   - Result downloading and comparison

## License

Part of the Instagram Downloader project. See main project README for license information.

## Support

For issues, questions, or feature requests, please refer to the main project documentation or open an issue in the project repository.
