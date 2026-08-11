"""
Beat Composer Manager - Music Beat Detection and Video Composition System

Automated pipeline for:
1. Audio analysis (BPM, beat positions, downbeats, time signature)
2. Timeline generation based on detected beats
3. Media (images/videos) assignment to beat timestamps
4. Video composition synchronized to music
5. Preview and export functionality
6. Project save/load

Libraries:
- librosa: Basic beat detection and tempo analysis
- madmom: Advanced beat/downbeat detection
- moviepy: Video assembly and composition
- ffmpeg-python: Final rendering
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
import hashlib

import numpy as np

logger = logging.getLogger(__name__)

# Optional imports with fallback
try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    logger.warning("librosa not available. Install with: pip install librosa")
    LIBROSA_AVAILABLE = False

try:
    import madmom
    from madmom.features.beats import RNNBeatProcessor, DBNBeatTrackingProcessor
    from madmom.features.downbeats import RNNDownBeatProcessor, DBNDownBeatTrackingProcessor
    MADMOM_AVAILABLE = True
except ImportError:
    logger.warning("madmom not available. Install with: pip install Cython numpy && pip install madmom")
    MADMOM_AVAILABLE = False
except Exception as e:
    logger.warning(f"madmom import failed: {e}. Using librosa only.")
    MADMOM_AVAILABLE = False

try:
    from moviepy.editor import (
        VideoFileClip, ImageClip, CompositeVideoClip, 
        AudioFileClip, concatenate_videoclips
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    logger.warning("moviepy not available. Install with: pip install moviepy")
    MOVIEPY_AVAILABLE = False

try:
    import ffmpeg
    FFMPEG_AVAILABLE = True
except ImportError:
    logger.warning("ffmpeg-python not available. Install with: pip install ffmpeg-python")
    FFMPEG_AVAILABLE = False


class BeatComposerManager:
    """
    Manages music beat detection, timeline generation, and video composition.
    """
    
    MOVEMENT_MODES = {
        'independent': 'Independent - Changes just this beat',
        'unified': 'Unified - Moves all subsequent beats together'
    }
    
    DURATION_MODES = {
        'seconds': 'N Seconds',
        'measures': 'N Measures',
        'full': 'Complete Audio Duration'
    }
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the Beat Composer Manager.
        
        Args:
            output_dir: Directory for output files. Defaults to Documents/BeatComposer
        """
        if output_dir is None:
            self.output_dir = Path.home() / 'Documents' / 'BeatComposer'
        else:
            self.output_dir = Path(output_dir)
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Project state
        self.current_project_dir = None
        self.audio_path = None
        self.audio_data = None
        self.sample_rate = None
        self.duration = None
        
        # Beat detection results
        self.bpm = None
        self.beats = []  # List of beat timestamps in seconds
        self.downbeats = []  # List of downbeat timestamps
        self.time_signature = None
        
        # Timeline configuration
        self.timeline_beats = []  # Working timeline with adjustments
        self.beat_media_assignments = {}  # {beat_index: {'type': 'image'/'video', 'path': '...'}}
        
        logger.info(f"Beat Composer Manager initialized. Output: {self.output_dir}")
    
    def create_project(self, audio_path: str) -> str:
        """
        Create a new beat composer project.
        
        Args:
            audio_path: Path to the input audio file
            
        Returns:
            Path to the created project directory
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        
        # Create project directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_hash = hashlib.md5(audio_path.name.encode()).hexdigest()[:8]
        project_name = f"{audio_path.stem}_{timestamp}_{audio_hash}"
        project_dir = self.output_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (project_dir / 'media').mkdir(exist_ok=True)
        (project_dir / 'exports').mkdir(exist_ok=True)
        
        self.current_project_dir = project_dir
        self.audio_path = audio_path
        
        # Save project metadata
        metadata = {
            'audio_name': audio_path.name,
            'audio_path': str(audio_path),
            'created': timestamp,
            'project_dir': str(project_dir)
        }
        
        with open(project_dir / 'project.json', 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Created project: {project_dir}")
        return str(project_dir)
    
    def get_audio_info(self, audio_path: str) -> Dict[str, Any]:
        """
        Get basic audio file information.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Dictionary with audio properties
        """
        if not LIBROSA_AVAILABLE:
            raise ImportError("librosa is required for audio analysis")
        
        # Load audio
        y, sr = librosa.load(audio_path, sr=None)
        duration = librosa.get_duration(y=y, sr=sr)
        
        info = {
            'duration_seconds': duration,
            'sample_rate': sr,
            'channels': 1 if len(y.shape) == 1 else y.shape[0],
            'file_size_mb': os.path.getsize(audio_path) / (1024 * 1024),
            'format': Path(audio_path).suffix[1:].upper()
        }
        
        logger.info(f"Audio info: {duration:.2f}s, {sr}Hz")
        return info
    
    def detect_beats_librosa(self, audio_path: str) -> Dict[str, Any]:
        """
        Detect beats using librosa (faster, good for preview).
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Dictionary with beat detection results
        """
        if not LIBROSA_AVAILABLE:
            raise ImportError("librosa is required for beat detection")
        
        logger.info("Detecting beats with librosa...")
        
        # Load audio
        y, sr = librosa.load(audio_path, sr=None)
        self.audio_data = y
        self.sample_rate = sr
        self.duration = librosa.get_duration(y=y, sr=sr)
        
        # Detect tempo and beats
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        
        # Estimate time signature (simple approach)
        time_signature = self._estimate_time_signature(beat_times)
        
        # Handle tempo being either scalar or array
        self.bpm = float(np.asarray(tempo).item())
        self.beats = beat_times.tolist()
        self.time_signature = time_signature
        
        # Estimate downbeats (every N beats based on time signature)
        if time_signature:
            beats_per_measure = time_signature[0]
            self.downbeats = [self.beats[i] for i in range(0, len(self.beats), beats_per_measure) 
                             if i < len(self.beats)]
        else:
            self.downbeats = []
        
        logger.info(f"Detected {len(self.beats)} beats at {self.bpm:.1f} BPM")
        
        return {
            'bpm': self.bpm,
            'beat_count': len(self.beats),
            'beats': self.beats,
            'downbeat_count': len(self.downbeats),
            'downbeats': self.downbeats,
            'time_signature': time_signature,
            'duration': self.duration
        }
    
    def detect_beats_madmom(self, audio_path: str) -> Dict[str, Any]:
        """
        Detect beats using madmom (more accurate, production quality).
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Dictionary with beat detection results
        """
        if not MADMOM_AVAILABLE:
            raise ImportError("madmom is required for advanced beat detection")
        
        if not LIBROSA_AVAILABLE:
            raise ImportError("librosa is required for audio loading")
        
        logger.info("Detecting beats with madmom (this may take a moment)...")
        
        # Load audio with librosa for basic info
        y, sr = librosa.load(audio_path, sr=None)
        self.audio_data = y
        self.sample_rate = sr
        self.duration = librosa.get_duration(y=y, sr=sr)
        
        # Detect beats with madmom
        proc_beat = DBNBeatTrackingProcessor(fps=100)
        act_beat = RNNBeatProcessor()(audio_path)
        beat_times = proc_beat(act_beat)
        
        # Detect downbeats with madmom
        proc_downbeat = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
        act_downbeat = RNNDownBeatProcessor()(audio_path)
        downbeat_data = proc_downbeat(act_downbeat)
        
        # Extract downbeat timestamps (position 1 in each measure)
        downbeat_times = downbeat_data[downbeat_data[:, 1] == 1, 0]
        
        # Calculate BPM
        if len(beat_times) > 1:
            beat_intervals = np.diff(beat_times)
            avg_interval = np.median(beat_intervals)
            bpm = 60.0 / avg_interval
        else:
            bpm = 120.0  # Default fallback
        
        # Estimate time signature from downbeats
        if len(downbeat_times) > 1:
            beats_between_downbeats = []
            for i in range(len(downbeat_times) - 1):
                count = np.sum((beat_times >= downbeat_times[i]) & 
                              (beat_times < downbeat_times[i + 1]))
                beats_between_downbeats.append(count)
            
            if beats_between_downbeats:
                common_beats = int(np.median(beats_between_downbeats))
                time_signature = (common_beats, 4)  # Assume quarter note denominator
            else:
                time_signature = (4, 4)
        else:
            time_signature = (4, 4)
        
        self.bpm = bpm
        self.beats = beat_times.tolist()
        self.downbeats = downbeat_times.tolist()
        self.time_signature = time_signature
        
        logger.info(f"Detected {len(self.beats)} beats at {self.bpm:.1f} BPM, "
                   f"{len(self.downbeats)} downbeats")
        
        return {
            'bpm': self.bpm,
            'beat_count': len(self.beats),
            'beats': self.beats,
            'downbeat_count': len(self.downbeats),
            'downbeats': self.downbeats,
            'time_signature': time_signature,
            'duration': self.duration
        }
    
    def _estimate_time_signature(self, beat_times: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Simple time signature estimation based on beat patterns.
        
        Args:
            beat_times: Array of beat timestamps
            
        Returns:
            Tuple of (beats_per_measure, note_value) or None
        """
        # This is a simplified approach - real time signature detection is complex
        # Common signatures: 4/4, 3/4, 6/8
        
        if len(beat_times) < 8:
            return (4, 4)  # Default to 4/4
        
        # Analyze beat strength patterns (simplified)
        # In production, you'd use onset strength or spectral flux
        return (4, 4)  # Default to 4/4 for now
    
    def build_timeline(self, duration_mode: str = 'full', duration_value: float = None,
                      include_beats: bool = True, include_downbeats: bool = False) -> List[Dict]:
        """
        Build a timeline of beats based on configuration.
        
        Args:
            duration_mode: 'seconds', 'measures', or 'full'
            duration_value: Number of seconds/measures (ignored for 'full')
            include_beats: Include all beats
            include_downbeats: Include only downbeats (if True, overrides include_beats)
            
        Returns:
            List of timeline beat dictionaries
        """
        if not self.beats:
            raise ValueError("No beats detected. Run detect_beats first.")
        
        timeline = []
        
        # Determine which beats to use
        if include_downbeats and self.downbeats:
            source_beats = self.downbeats
            beat_type = 'downbeat'
        elif include_beats:
            source_beats = self.beats
            beat_type = 'beat'
        else:
            source_beats = self.beats
            beat_type = 'beat'
        
        # Determine end time
        if duration_mode == 'full':
            end_time = self.duration
        elif duration_mode == 'seconds':
            end_time = min(duration_value, self.duration)
        elif duration_mode == 'measures':
            if self.time_signature and self.downbeats:
                beats_per_measure = self.time_signature[0]
                num_beats = int(duration_value * beats_per_measure)
                if num_beats < len(source_beats):
                    end_time = source_beats[num_beats]
                else:
                    end_time = self.duration
            else:
                end_time = self.duration
        else:
            end_time = self.duration
        
        # Build timeline
        for i, beat_time in enumerate(source_beats):
            if beat_time <= end_time:
                timeline.append({
                    'index': i,
                    'original_time': beat_time,
                    'adjusted_time': beat_time,  # Can be modified by user
                    'type': beat_type,
                    'duration': 0.5,  # Default duration for media playback
                    'media': None  # Will hold {'type': 'image'/'video', 'path': '...'}
                })
        
        self.timeline_beats = timeline
        logger.info(f"Built timeline with {len(timeline)} {beat_type}s")
        
        return timeline
    
    def adjust_beat_time(self, beat_index: int, offset_seconds: float, 
                        movement_mode: str = 'independent'):
        """
        Adjust a beat's timestamp.
        
        Args:
            beat_index: Index of beat to adjust
            offset_seconds: Time offset in seconds (can be negative)
            movement_mode: 'independent' or 'unified'
        """
        if beat_index < 0 or beat_index >= len(self.timeline_beats):
            raise ValueError(f"Invalid beat index: {beat_index}")
        
        if movement_mode == 'independent':
            # Only adjust this beat
            self.timeline_beats[beat_index]['adjusted_time'] += offset_seconds
        
        elif movement_mode == 'unified':
            # Adjust this beat and all subsequent beats
            for i in range(beat_index, len(self.timeline_beats)):
                self.timeline_beats[i]['adjusted_time'] += offset_seconds
        
        logger.info(f"Adjusted beat {beat_index} by {offset_seconds}s ({movement_mode} mode)")
    
    def assign_media_to_beat(self, beat_index: int, media_path: str, media_type: str = None):
        """
        Assign an image or video to a beat.
        
        Args:
            beat_index: Index of beat
            media_path: Path to image or video file
            media_type: 'image' or 'video' (auto-detected if None)
        """
        if beat_index < 0 or beat_index >= len(self.timeline_beats):
            raise ValueError(f"Invalid beat index: {beat_index}")
        
        media_path = Path(media_path)
        if not media_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_path}")
        
        # Auto-detect media type
        if media_type is None:
            ext = media_path.suffix.lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                media_type = 'image'
            elif ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']:
                media_type = 'video'
            else:
                raise ValueError(f"Unknown media type for extension: {ext}")
        
        self.timeline_beats[beat_index]['media'] = {
            'type': media_type,
            'path': str(media_path)
        }
        
        logger.info(f"Assigned {media_type} to beat {beat_index}: {media_path.name}")
    
    def remove_media_from_beat(self, beat_index: int):
        """Remove media assignment from a beat."""
        if beat_index < 0 or beat_index >= len(self.timeline_beats):
            raise ValueError(f"Invalid beat index: {beat_index}")
        
        self.timeline_beats[beat_index]['media'] = None
        logger.info(f"Removed media from beat {beat_index}")
    
    def compose_video(self, output_path: str = None, resolution: Tuple[int, int] = (1080, 1920),
                     fps: int = 30, background_color: Tuple[int, int, int] = (0, 0, 0)) -> str:
        """
        Compose final video from timeline and media assignments.
        
        Args:
            output_path: Path for output video (auto-generated if None)
            resolution: (width, height) of output video
            fps: Frames per second
            background_color: RGB tuple for background
            
        Returns:
            Path to the composed video
        """
        if not MOVIEPY_AVAILABLE:
            raise ImportError("moviepy is required for video composition")
        
        if not self.timeline_beats:
            raise ValueError("No timeline built. Run build_timeline first.")
        
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.current_project_dir / 'exports' / f'composition_{timestamp}.mp4'
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Composing video: {resolution[0]}x{resolution[1]} @ {fps}fps")
        
        # Load audio
        audio_clip = AudioFileClip(str(self.audio_path))
        
        # Create clips for each beat with media
        clips = []
        
        for beat in self.timeline_beats:
            media = beat.get('media')
            if not media:
                continue
            
            start_time = beat['adjusted_time']
            duration = beat['duration']
            
            try:
                if media['type'] == 'image':
                    clip = (ImageClip(media['path'])
                           .set_start(start_time)
                           .set_duration(duration)
                           .resize(resolution))
                
                elif media['type'] == 'video':
                    video_clip = VideoFileClip(media['path'])
                    clip = (video_clip
                           .subclip(0, min(duration, video_clip.duration))
                           .set_start(start_time)
                           .resize(resolution))
                
                clips.append(clip)
            
            except Exception as e:
                logger.error(f"Error processing media at beat {beat['index']}: {e}")
                continue
        
        if not clips:
            raise ValueError("No media clips to compose. Assign media to beats first.")
        
        # Create background
        from moviepy.editor import ColorClip
        background = ColorClip(size=resolution, color=background_color, 
                             duration=audio_clip.duration)
        
        # Composite all clips on background
        final_video = CompositeVideoClip([background] + clips, size=resolution)
        final_video = final_video.set_audio(audio_clip)
        final_video = final_video.set_fps(fps)
        
        # Write video
        logger.info(f"Rendering video to: {output_path}")
        final_video.write_videofile(
            str(output_path),
            codec='libx264',
            audio_codec='aac',
            fps=fps,
            preset='medium',
            threads=4
        )
        
        # Cleanup
        final_video.close()
        audio_clip.close()
        for clip in clips:
            clip.close()
        
        logger.info(f"Video composition complete: {output_path}")
        return str(output_path)
    
    def save_project(self, project_path: str = None) -> str:
        """
        Save current project state to JSON.
        
        Args:
            project_path: Path to save project (auto-generated if None)
            
        Returns:
            Path to saved project file
        """
        if project_path is None:
            project_path = self.current_project_dir / 'project_data.json'
        
        project_path = Path(project_path)
        
        project_data = {
            'version': '1.0',
            'audio_path': str(self.audio_path) if self.audio_path else None,
            'bpm': self.bpm,
            'duration': self.duration,
            'time_signature': self.time_signature,
            'beats': self.beats,
            'downbeats': self.downbeats,
            'timeline': self.timeline_beats,
            'created': datetime.now().isoformat()
        }
        
        with open(project_path, 'w', encoding='utf-8') as f:
            json.dump(project_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Project saved to: {project_path}")
        return str(project_path)
    
    def load_project(self, project_path: str):
        """
        Load project state from JSON file.
        
        Args:
            project_path: Path to project file
        """
        project_path = Path(project_path)
        if not project_path.exists():
            raise FileNotFoundError(f"Project file not found: {project_path}")
        
        with open(project_path, 'r', encoding='utf-8') as f:
            project_data = json.load(f)
        
        self.audio_path = Path(project_data['audio_path']) if project_data.get('audio_path') else None
        self.bpm = project_data.get('bpm')
        self.duration = project_data.get('duration')
        self.time_signature = tuple(project_data['time_signature']) if project_data.get('time_signature') else None
        self.beats = project_data.get('beats', [])
        self.downbeats = project_data.get('downbeats', [])
        self.timeline_beats = project_data.get('timeline', [])
        
        # Set project directory to parent of project file
        self.current_project_dir = project_path.parent
        
        logger.info(f"Project loaded from: {project_path}")
        logger.info(f"  BPM: {self.bpm}, Beats: {len(self.beats)}, Timeline: {len(self.timeline_beats)}")
