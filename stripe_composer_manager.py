"""
3-Stripe Composer Manager
Handles video composition for split-screen stripe videos.
"""

import logging
from pathlib import Path
from typing import Tuple, List, Dict, Optional, Callable
import tempfile

logger = logging.getLogger(__name__)

# Try MoviePy 2.x imports first, fall back to 1.x
try:
    from moviepy import (
        VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip, 
        ColorClip, concatenate_videoclips
    )
    MOVIEPY_VERSION = 2
    logger.info("Using MoviePy 2.x")
except ImportError:
    try:
        from moviepy.editor import (
            VideoFileClip, ImageClip, AudioFileClip, CompositeVideoClip,
            ColorClip, concatenate_videoclips
        )
        MOVIEPY_VERSION = 1
        logger.info("Using MoviePy 1.x")
    except ImportError:
        logger.warning("MoviePy not available")
        MOVIEPY_VERSION = None


class StripeComposerManager:
    """Manager for 3-stripe video composition"""
    
    def __init__(self, output_dir: str = None):
        """
        Initialize the Stripe Composer Manager.
        
        Args:
            output_dir: Directory for output files (default: temp directory)
        """
        if output_dir is None:
            output_dir = Path(tempfile.gettempdir()) / 'stripe_composer'
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Stripe Composer Manager initialized. Output: {self.output_dir}")
    
    def compose_video(
        self,
        stripe_files: List[List[Dict]],
        output_path: str,
        resolution: Tuple[int, int] = (1920, 1080),
        direction: str = 'horizontal',
        total_duration: float = 30.0,
        fps: int = 30,
        opening_file: Optional[Dict] = None,
        closing_file: Optional[Dict] = None,
        progress_callback: Optional[Callable] = None
    ) -> str:
        """
        Compose a 3-stripe video.
        
        Args:
            stripe_files: List of 3 lists, each containing dicts with 'path' and 'duration'
            output_path: Output video file path
            resolution: (width, height) tuple
            direction: 'horizontal' or 'vertical'
            total_duration: Total duration of the main video
            fps: Frames per second
            opening_file: Optional dict with 'path' and 'duration' for opening
            closing_file: Optional dict with 'path' and 'duration' for closing
            progress_callback: Optional callback(current, total, status) for progress updates
            
        Returns:
            Path to the created video file
        """
        if MOVIEPY_VERSION is None:
            raise ImportError("MoviePy is not installed. Install with: pip install moviepy")
        
        if len(stripe_files) != 3:
            raise ValueError("Must provide exactly 3 stripe file lists")
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        width, height = resolution
        
        # Calculate stripe dimensions
        if direction == 'horizontal':
            # Split horizontally: left, center, right
            stripe_width = width // 3
            stripe_height = height
            positions = [
                (0, 0),                          # Left
                (stripe_width, 0),               # Center
                (stripe_width * 2, 0)            # Right
            ]
            stripe_size = (stripe_width, stripe_height)
        else:
            # Split vertically: top, middle, bottom
            stripe_width = width
            stripe_height = height // 3
            positions = [
                (0, 0),                          # Top
                (0, stripe_height),              # Middle
                (0, stripe_height * 2)           # Bottom
            ]
            stripe_size = (stripe_width, stripe_height)
        
        logger.info(f"Composing {direction} stripe video: {width}x{height} @ {fps}fps")
        
        all_clips = []
        
        # Create opening clip if provided
        if opening_file and opening_file.get('path'):
            if progress_callback:
                progress_callback(0, 100, "Processing opening...")
            
            opening_clip = self._create_full_frame_clip(
                opening_file['path'],
                opening_file.get('duration', 2.0),
                resolution,
                fps
            )
            if opening_clip:
                all_clips.append(opening_clip)
        
        # Create main stripe video
        if progress_callback:
            progress_callback(20, 100, "Creating stripe compositions...")
        
        stripe_clip = self._create_stripe_composition(
            stripe_files,
            stripe_size,
            positions,
            resolution,
            total_duration,
            fps,
            progress_callback
        )
        
        if stripe_clip:
            all_clips.append(stripe_clip)
        
        # Create closing clip if provided
        if closing_file and closing_file.get('path'):
            if progress_callback:
                progress_callback(80, 100, "Processing closing...")
            
            closing_clip = self._create_full_frame_clip(
                closing_file['path'],
                closing_file.get('duration', 2.0),
                resolution,
                fps
            )
            if closing_clip:
                all_clips.append(closing_clip)
        
        # Concatenate all segments
        if progress_callback:
            progress_callback(90, 100, "Combining segments...")
        
        if not all_clips:
            raise ValueError("No clips created. Check your input files.")
        
        if len(all_clips) == 1:
            final_video = all_clips[0]
        else:
            final_video = concatenate_videoclips(all_clips, method='compose')
        
        final_video = final_video.with_fps(fps)
        
        # Write video
        if progress_callback:
            progress_callback(95, 100, "Rendering video...")
        
        logger.info(f"Rendering video to: {output_path}")
        
        # Custom progress logger for write_videofile
        if progress_callback:
            class ProgressLogger:
                def __init__(self, callback):
                    self.callback = callback
                
                def __call__(self, **kwargs):
                    if 't' in kwargs and 'total_duration' in kwargs:
                        current_time = kwargs['t']
                        total_time = kwargs['total_duration']
                        percent = int((current_time / total_time) * 100) if total_time > 0 else 0
                        self.callback(current_time * fps, total_time * fps, 
                                    f"Rendering: {percent}% ({current_time:.1f}/{total_time:.1f}s)")
            
            progress_logger = ProgressLogger(progress_callback)
            logger_param = progress_logger
        else:
            logger_param = 'bar'
        
        final_video.write_videofile(
            str(output_path),
            codec='libx264',
            audio_codec='aac',
            fps=fps,
            preset='medium',
            threads=4,
            logger=logger_param
        )
        
        # Cleanup
        final_video.close()
        for clip in all_clips:
            clip.close()
        
        logger.info(f"Stripe video composition complete: {output_path}")
        return str(output_path)
    
    def _create_full_frame_clip(self, file_path: str, duration: float, 
                                 resolution: Tuple[int, int], fps: int):
        """Create a full-frame clip from an image or video"""
        try:
            ext = Path(file_path).suffix.lower()
            
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                # Image
                clip = ImageClip(file_path).with_duration(duration)
            else:
                # Video
                clip = VideoFileClip(file_path)
                if clip.duration < duration:
                    # Loop if too short
                    num_loops = int(duration / clip.duration) + 1
                    clip = concatenate_videoclips([clip] * num_loops)
                clip = clip.subclipped(0, min(duration, clip.duration))
            
            # Scale to resolution
            clip = clip.resized(resolution).with_fps(fps)
            
            return clip
        
        except Exception as e:
            logger.error(f"Error creating full frame clip from {file_path}: {e}")
            return None
    
    def _create_stripe_composition(
        self,
        stripe_files: List[List[Dict]],
        stripe_size: Tuple[int, int],
        positions: List[Tuple[int, int]],
        full_resolution: Tuple[int, int],
        total_duration: float,
        fps: int,
        progress_callback: Optional[Callable] = None
    ):
        """Create the main stripe composition"""
        
        # Create background
        try:
            background = ColorClip(size=full_resolution, color=(0, 0, 0), 
                                 duration=total_duration).with_fps(fps)
        except:
            from moviepy.editor import ColorClip
            background = ColorClip(size=full_resolution, color=(0, 0, 0), 
                                 duration=total_duration).set_fps(fps)
        
        all_stripe_clips = [background]
        
        # Create each stripe
        for stripe_idx, (files, position) in enumerate(zip(stripe_files, positions)):
            if progress_callback:
                progress_callback(
                    30 + (stripe_idx * 15), 100, 
                    f"Processing Stripe {stripe_idx + 1}..."
                )
            
            stripe_clips = self._create_stripe_sequence(
                files, stripe_size, position, total_duration, fps
            )
            all_stripe_clips.extend(stripe_clips)
        
        # Composite all stripes
        composite = CompositeVideoClip(all_stripe_clips, size=full_resolution)
        composite = composite.with_duration(total_duration).with_fps(fps)
        
        return composite
    
    def _create_stripe_sequence(
        self,
        files: List[Dict],
        stripe_size: Tuple[int, int],
        position: Tuple[int, int],
        max_duration: float,
        fps: int
    ) -> List:
        """Create a sequence of clips for one stripe"""
        
        if not files:
            return []
        
        clips = []
        current_time = 0.0
        
        for file_data in files:
            file_path = file_data.get('path')
            duration = file_data.get('duration', 3.0)
            
            if not file_path or not Path(file_path).exists():
                logger.warning(f"File not found: {file_path}")
                continue
            
            # Don't exceed max duration
            if current_time >= max_duration:
                break
            
            duration = min(duration, max_duration - current_time)
            
            try:
                ext = Path(file_path).suffix.lower()
                
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                    # Image
                    clip = ImageClip(file_path).with_duration(duration)
                else:
                    # Video
                    clip = VideoFileClip(file_path)
                    if clip.duration < duration:
                        # Loop if too short
                        num_loops = int(duration / clip.duration) + 1
                        looped = concatenate_videoclips([clip] * num_loops)
                        clip = looped.subclipped(0, duration)
                    else:
                        clip = clip.subclipped(0, min(duration, clip.duration))
                
                # Scale to stripe size (crop to fit)
                clip = self._crop_to_fit(clip, stripe_size)
                
                # Position and timing
                clip = clip.with_position(position).with_start(current_time)
                
                clips.append(clip)
                current_time += duration
            
            except Exception as e:
                logger.error(f"Error processing stripe file {file_path}: {e}")
                continue
        
        # If clips don't fill the duration, add a black clip
        if current_time < max_duration:
            try:
                filler = ColorClip(size=stripe_size, color=(0, 0, 0),
                                 duration=max_duration - current_time)
                filler = filler.with_position(position).with_start(current_time)
                clips.append(filler)
            except:
                from moviepy.editor import ColorClip
                filler = ColorClip(size=stripe_size, color=(0, 0, 0),
                                 duration=max_duration - current_time)
                filler = filler.set_position(position).set_start(current_time)
                clips.append(filler)
        
        return clips
    
    def _crop_to_fit(self, clip, target_size: Tuple[int, int]):
        """Scale and crop clip to fit target size (maintains aspect ratio)"""
        target_width, target_height = target_size
        target_aspect = target_width / target_height
        
        clip_width, clip_height = clip.size
        clip_aspect = clip_width / clip_height
        
        # Scale to cover the target area
        if clip_aspect > target_aspect:
            # Clip is wider - scale by height, crop width
            scaled_clip = clip.resized(height=target_height)
        else:
            # Clip is taller - scale by width, crop height
            scaled_clip = clip.resized(width=target_width)
        
        # Crop to exact target size (centered)
        try:
            # MoviePy 2.x
            cropped = scaled_clip.cropped(
                x_center=scaled_clip.w / 2,
                y_center=scaled_clip.h / 2,
                width=target_width,
                height=target_height
            )
        except AttributeError:
            # MoviePy 1.x fallback
            from moviepy.video.fx.crop import crop
            x1 = (scaled_clip.w - target_width) / 2
            y1 = (scaled_clip.h - target_height) / 2
            cropped = crop(scaled_clip, x1=x1, y1=y1, width=target_width, height=target_height)
        
        return cropped


def check_dependencies_available() -> bool:
    """Check if required dependencies are available"""
    return MOVIEPY_VERSION is not None
