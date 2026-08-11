"""
Shot Breakdown Manager - Video Analysis and Cinematic Breakdown System

Automated pipeline for:
1. Video ingestion and validation
2. Shot detection using PySceneDetect + OpenCV
3. Frame extraction and keyframe generation
4. Scene labeling with cinematic metadata
5. Dependency mapping (visual, motion, narrative, emotional continuity)
6. Prompt generation for AI video tools (Runway, Pika, Luma, Kling, etc.)
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any
import hashlib

import cv2
import numpy as np

logger = logging.getLogger(__name__)

try:
    from scenedetect import detect, ContentDetector, AdaptiveDetector
    SCENEDETECT_AVAILABLE = True
except ImportError:
    logger.warning("PySceneDetect not available. Shot detection will use basic OpenCV method.")
    SCENEDETECT_AVAILABLE = False


def convert_numpy_types(obj):
    """
    Recursively convert numpy types to Python native types for JSON serialization.
    
    Args:
        obj: Object to convert
        
    Returns:
        Object with numpy types converted to Python native types
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    else:
        return obj


class ShotBreakdownManager:
    """
    Manages video shot detection, analysis, and prompt generation.
    """
    
    # Shot type definitions
    SHOT_TYPES = {
        'extreme_wide': 'Extreme Wide Shot (EWS)',
        'wide': 'Wide Shot (WS)',
        'full': 'Full Shot',
        'medium_full': 'Medium Full Shot',
        'medium': 'Medium Shot (MS)',
        'medium_closeup': 'Medium Close-Up (MCU)',
        'closeup': 'Close-Up (CU)',
        'extreme_closeup': 'Extreme Close-Up (ECU)'
    }
    
    # Camera angles
    CAMERA_ANGLES = {
        'eye_level': 'Eye Level',
        'low_angle': 'Low Angle',
        'high_angle': 'High Angle',
        'dutch_tilt': 'Dutch Tilt / Canted Angle',
        'overhead': 'Overhead / Bird\'s Eye',
        'worm_eye': 'Worm\'s Eye View'
    }
    
    # Camera movements
    CAMERA_MOVEMENTS = {
        'static': 'Static',
        'pan': 'Pan',
        'tilt': 'Tilt',
        'dolly': 'Dolly',
        'tracking': 'Tracking Shot',
        'handheld': 'Handheld',
        'crane': 'Crane Shot',
        'zoom': 'Zoom'
    }
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the Shot Breakdown Manager.
        
        Args:
            output_dir: Directory for output files (shots, frames, JSON). 
                       Defaults to user's Documents/ShotBreakdowns
        """
        if output_dir is None:
            self.output_dir = Path.home() / 'Documents' / 'ShotBreakdowns'
        else:
            self.output_dir = Path(output_dir)
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.current_project_dir = None
        self.current_video_path = None
        self.shots = []
        
        logger.info(f"Shot Breakdown Manager initialized. Output: {self.output_dir}")
    
    def create_project(self, video_path: str) -> str:
        """
        Create a new project directory for a video analysis.
        
        Args:
            video_path: Path to the input video file
            
        Returns:
            Path to the created project directory
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        # Create project directory with video name and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_hash = hashlib.md5(video_path.name.encode()).hexdigest()[:8]
        project_name = f"{video_path.stem}_{timestamp}_{video_hash}"
        project_dir = self.output_dir / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (project_dir / 'shots').mkdir(exist_ok=True)
        (project_dir / 'frames').mkdir(exist_ok=True)
        (project_dir / 'keyframes').mkdir(exist_ok=True)
        (project_dir / 'analysis').mkdir(exist_ok=True)
        
        self.current_project_dir = project_dir
        self.current_video_path = video_path
        
        # Save project metadata
        metadata = {
            'video_name': video_path.name,
            'video_path': str(video_path),
            'created': timestamp,
            'project_dir': str(project_dir)
        }
        
        with open(project_dir / 'project.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Created project: {project_dir}")
        return str(project_dir)
    
    def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """
        Extract video metadata using OpenCV.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Dictionary with video properties
        """
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        info = {
            'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            'fps': cap.get(cv2.CAP_PROP_FPS),
            'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            'duration_seconds': 0,
            'codec': '',
            'file_size_mb': os.path.getsize(video_path) / (1024 * 1024)
        }
        
        if info['fps'] > 0:
            info['duration_seconds'] = info['frame_count'] / info['fps']
        
        cap.release()
        
        logger.info(f"Video info: {info['width']}x{info['height']}, {info['fps']} fps, {info['duration_seconds']:.2f}s")
        return info
    
    def detect_shots_scenedetect(self, video_path: str, threshold: float = 27.0) -> List[Dict]:
        """
        Detect shots using PySceneDetect library (if available).
        
        Args:
            video_path: Path to video file
            threshold: Content detection threshold (lower = more sensitive)
            
        Returns:
            List of shot dictionaries with timecodes and frame numbers
        """
        if not SCENEDETECT_AVAILABLE:
            raise ImportError("PySceneDetect is not installed. Install with: pip install scenedetect[opencv]")
        
        logger.info(f"Detecting shots with PySceneDetect (threshold={threshold})...")
        
        # Detect scenes
        scene_list = detect(video_path, ContentDetector(threshold=threshold))
        
        shots = []
        for i, scene in enumerate(scene_list):
            start_frame = scene[0].get_frames()
            end_frame = scene[1].get_frames()
            start_time = scene[0].get_seconds()
            end_time = scene[1].get_seconds()
            
            shot = {
                'shot_number': i + 1,
                'start_frame': start_frame,
                'end_frame': end_frame,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time,
                'frame_count': end_frame - start_frame
            }
            shots.append(shot)
        
        logger.info(f"Detected {len(shots)} shots using PySceneDetect")
        return shots
    
    def detect_shots_opencv(self, video_path: str, threshold: float = 30.0) -> List[Dict]:
        """
        Detect shots using basic OpenCV frame difference method.
        Fallback when PySceneDetect is not available.
        
        Args:
            video_path: Path to video file
            threshold: Frame difference threshold (0-100)
            
        Returns:
            List of shot dictionaries
        """
        logger.info(f"Detecting shots with OpenCV (threshold={threshold})...")
        
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        prev_frame = None
        shot_boundaries = [0]  # Start with frame 0
        frame_idx = 0
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            # Convert to grayscale and resize for faster processing
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (320, 240))
            
            if prev_frame is not None:
                # Calculate frame difference
                diff = cv2.absdiff(prev_frame, gray)
                mean_diff = np.mean(diff)
                
                # If difference exceeds threshold, mark as shot boundary
                if mean_diff > threshold:
                    shot_boundaries.append(frame_idx)
                    logger.debug(f"Shot boundary at frame {frame_idx}, diff={mean_diff:.2f}")
            
            prev_frame = gray
            frame_idx += 1
            
            # Progress logging every 100 frames
            if frame_idx % 100 == 0:
                logger.debug(f"Processed {frame_idx}/{frame_count} frames")
        
        cap.release()
        
        # Add final frame as boundary
        shot_boundaries.append(frame_count)
        
        # Convert boundaries to shot list
        shots = []
        for i in range(len(shot_boundaries) - 1):
            start_frame = shot_boundaries[i]
            end_frame = shot_boundaries[i + 1]
            start_time = start_frame / fps
            end_time = end_frame / fps
            
            shot = {
                'shot_number': i + 1,
                'start_frame': start_frame,
                'end_frame': end_frame,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time,
                'frame_count': end_frame - start_frame
            }
            shots.append(shot)
        
        logger.info(f"Detected {len(shots)} shots using OpenCV")
        return shots
    
    def detect_shots(self, video_path: str, method: str = 'auto', threshold: float = 27.0) -> List[Dict]:
        """
        Detect shots in video using specified method.
        
        Args:
            video_path: Path to video file
            method: 'auto', 'scenedetect', or 'opencv'
            threshold: Detection threshold
            
        Returns:
            List of shot dictionaries
        """
        if method == 'auto':
            method = 'scenedetect' if SCENEDETECT_AVAILABLE else 'opencv'
        
        if method == 'scenedetect':
            return self.detect_shots_scenedetect(video_path, threshold)
        elif method == 'opencv':
            return self.detect_shots_opencv(video_path, threshold)
        else:
            raise ValueError(f"Unknown detection method: {method}")
    
    def extract_keyframe(self, video_path: str, frame_number: int, output_path: str) -> bool:
        """
        Extract a single frame from video.
        
        Args:
            video_path: Path to video file
            frame_number: Frame index to extract
            output_path: Path to save frame image
            
        Returns:
            True if successful
        """
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            cv2.imwrite(output_path, frame)
            return True
        
        return False
    
    def extract_shot_keyframes(self, video_path: str, shot: Dict, output_dir: Path) -> List[str]:
        """
        Extract keyframes for a shot (first, middle, last frames).
        
        Args:
            video_path: Path to video file
            shot: Shot dictionary
            output_dir: Directory to save keyframes
            
        Returns:
            List of saved keyframe paths
        """
        shot_num = shot['shot_number']
        start = shot['start_frame']
        end = shot['end_frame']
        middle = (start + end) // 2
        
        keyframes = []
        positions = [
            ('first', start),
            ('middle', middle),
            ('last', end - 1)  # Last frame before cut
        ]
        
        for pos_name, frame_num in positions:
            filename = f"shot_{shot_num:04d}_{pos_name}_frame_{frame_num:06d}.jpg"
            output_path = output_dir / filename
            
            if self.extract_keyframe(video_path, frame_num, str(output_path)):
                keyframes.append(str(output_path))
                logger.debug(f"Extracted keyframe: {filename}")
        
        return keyframes
    
    def analyze_shot_composition(self, frame_path: str) -> Dict[str, Any]:
        """
        Analyze a frame for composition metrics.
        
        Args:
            frame_path: Path to frame image
            
        Returns:
            Dictionary with composition analysis
        """
        img = cv2.imread(frame_path)
        if img is None:
            return {}
        
        height, width = img.shape[:2]
        
        # Color analysis
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        avg_hue = np.mean(hsv[:, :, 0])
        avg_saturation = np.mean(hsv[:, :, 1])
        avg_brightness = np.mean(hsv[:, :, 2])
        
        # Brightness histogram
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        
        # Detect dominant lighting (dark, mid, bright)
        dark_pixels = np.sum(hist[:85])
        mid_pixels = np.sum(hist[85:170])
        bright_pixels = np.sum(hist[170:])
        total_pixels = dark_pixels + mid_pixels + bright_pixels
        
        lighting = 'mid'
        if dark_pixels > total_pixels * 0.5:
            lighting = 'dark'
        elif bright_pixels > total_pixels * 0.5:
            lighting = 'bright'
        
        # Color temperature estimation (warm vs cool)
        b, g, r = cv2.split(img)
        avg_warmth = (np.mean(r) - np.mean(b)) / 255.0
        color_temp = 'warm' if avg_warmth > 0.1 else ('cool' if avg_warmth < -0.1 else 'neutral')
        
        return {
            'width': width,
            'height': height,
            'aspect_ratio': round(width / height, 2),
            'avg_hue': round(avg_hue, 2),
            'avg_saturation': round(avg_saturation, 2),
            'avg_brightness': round(avg_brightness, 2),
            'lighting': lighting,
            'color_temperature': color_temp,
            'dark_percent': round(dark_pixels / total_pixels * 100, 1),
            'mid_percent': round(mid_pixels / total_pixels * 100, 1),
            'bright_percent': round(bright_pixels / total_pixels * 100, 1)
        }
    
    def detect_camera_movement(self, video_path: str, shot: Dict) -> Dict[str, Any]:
        """
        Detect camera movement in a shot using optical flow.
        
        Args:
            video_path: Path to video file
            shot: Shot dictionary
            
        Returns:
            Dictionary with movement analysis
        """
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, shot['start_frame'])
        
        # Sample frames from the shot (max 10 frames for performance)
        frame_count = min(shot['frame_count'], 10)
        step = max(1, shot['frame_count'] // frame_count)
        
        prev_gray = None
        movements = []
        
        for i in range(frame_count):
            frame_pos = shot['start_frame'] + (i * step)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            
            if not ret:
                break
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (320, 240))
            
            if prev_gray is not None:
                # Calculate optical flow
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray, None, 
                    0.5, 3, 15, 3, 5, 1.2, 0
                )
                
                # Calculate average flow magnitude and direction
                mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                avg_mag = np.mean(mag)
                avg_ang = np.mean(ang)
                
                movements.append({
                    'magnitude': avg_mag,
                    'angle': avg_ang
                })
            
            prev_gray = gray
        
        cap.release()
        
        if not movements:
            return {
                'type': 'static',
                'magnitude': 0,
                'direction': 'none'
            }
        
        # Analyze movement pattern
        avg_magnitude = np.mean([m['magnitude'] for m in movements])
        
        movement_type = 'static'
        if avg_magnitude > 1.5:
            movement_type = 'moving'
        
        # Determine primary direction
        avg_angle = np.mean([m['angle'] for m in movements])
        direction = 'none'
        
        if movement_type == 'moving':
            # Convert angle to direction
            angle_deg = np.degrees(avg_angle)
            if 45 <= angle_deg < 135:
                direction = 'left'
            elif 135 <= angle_deg < 225:
                direction = 'down'
            elif 225 <= angle_deg < 315:
                direction = 'right'
            else:
                direction = 'up'
        
        return {
            'type': movement_type,
            'magnitude': round(avg_magnitude, 2),
            'direction': direction,
            'angle_degrees': round(np.degrees(avg_angle), 2)
        }
    
    def label_shot(self, shot: Dict, video_path: str, keyframes: List[str]) -> Dict[str, Any]:
        """
        Generate comprehensive labels and metadata for a shot.
        
        Args:
            shot: Shot dictionary
            video_path: Path to video file
            keyframes: List of keyframe paths
            
        Returns:
            Enhanced shot dictionary with labels
        """
        # Analyze middle keyframe (most representative)
        if len(keyframes) >= 2:
            middle_frame = keyframes[1]
            composition = self.analyze_shot_composition(middle_frame)
        else:
            composition = {}
        
        # Detect camera movement
        movement = self.detect_camera_movement(video_path, shot)
        
        # Estimate shot type based on composition
        # (In a full implementation, this would use ML/CV models)
        shot_type = 'medium'  # Default
        
        # Simple heuristic based on brightness distribution
        if composition.get('bright_percent', 0) > 60:
            shot_type = 'wide'
        elif composition.get('dark_percent', 0) > 60:
            shot_type = 'closeup'
        
        # Estimate camera angle (placeholder - would use ML in production)
        camera_angle = 'eye_level'
        
        # Enhanced shot data
        labeled_shot = {
            **shot,
            'keyframes': keyframes,
            'composition': composition,
            'movement': movement,
            'labels': {
                'shot_type': shot_type,
                'shot_type_name': self.SHOT_TYPES.get(shot_type, 'Medium Shot'),
                'camera_angle': camera_angle,
                'camera_angle_name': self.CAMERA_ANGLES.get(camera_angle, 'Eye Level'),
                'camera_movement': movement['type'],
                'camera_movement_name': self.CAMERA_MOVEMENTS.get(movement['type'], 'Static'),
                'lighting': composition.get('lighting', 'mid'),
                'color_temperature': composition.get('color_temperature', 'neutral')
            },
            'metadata': {
                'subjects': [],  # Would be populated by object detection
                'action': '',  # Would be populated by action recognition
                'environment': 'unknown',
                'mood': 'neutral',
                'notes': ''
            }
        }
        
        return labeled_shot
    
    def map_dependencies(self, shots: List[Dict]) -> List[Dict]:
        """
        Map dependencies between shots for continuity.
        
        Args:
            shots: List of labeled shot dictionaries
            
        Returns:
            Shots with dependency information added
        """
        for i, shot in enumerate(shots):
            dependencies = {
                'visual': [],
                'motion': [],
                'narrative': [],
                'emotional': []
            }
            
            # Compare with previous shot
            if i > 0:
                prev_shot = shots[i - 1]
                
                # Visual continuity check
                if shot.get('composition') and prev_shot.get('composition'):
                    curr_lighting = shot['composition'].get('lighting')
                    prev_lighting = prev_shot['composition'].get('lighting')
                    
                    if curr_lighting == prev_lighting:
                        dependencies['visual'].append({
                            'type': 'lighting_match',
                            'shot': prev_shot['shot_number'],
                            'description': f'Maintains {curr_lighting} lighting from Shot {prev_shot["shot_number"]}'
                        })
                    
                    # Color temperature continuity
                    curr_temp = shot['composition'].get('color_temperature')
                    prev_temp = prev_shot['composition'].get('color_temperature')
                    
                    if curr_temp == prev_temp:
                        dependencies['visual'].append({
                            'type': 'color_temperature_match',
                            'shot': prev_shot['shot_number'],
                            'description': f'Maintains {curr_temp} color temperature'
                        })
                
                # Motion continuity
                if shot.get('movement') and prev_shot.get('movement'):
                    curr_dir = shot['movement'].get('direction')
                    prev_dir = prev_shot['movement'].get('direction')
                    
                    if curr_dir != 'none' and prev_dir != 'none' and curr_dir == prev_dir:
                        dependencies['motion'].append({
                            'type': 'direction_continuity',
                            'shot': prev_shot['shot_number'],
                            'description': f'Maintains {curr_dir} movement direction'
                        })
                
                # Narrative continuity (sequential relationship)
                dependencies['narrative'].append({
                    'type': 'sequential',
                    'shot': prev_shot['shot_number'],
                    'description': f'Follows Shot {prev_shot["shot_number"]}'
                })
            
            shot['dependencies'] = dependencies
        
        return shots
    
    def generate_shot_prompt(self, shot: Dict) -> str:
        """
        Generate an AI-ready prompt for a shot.
        
        Args:
            shot: Labeled shot dictionary with dependencies
            
        Returns:
            Formatted prompt string
        """
        labels = shot.get('labels', {})
        comp = shot.get('composition', {})
        movement = shot.get('movement', {})
        deps = shot.get('dependencies', {})
        metadata = shot.get('metadata', {})
        
        # Build prompt components
        parts = []
        
        # Shot type and framing
        shot_type = labels.get('shot_type_name', 'Medium Shot')
        parts.append(f"Create a {shot_type}")
        
        # Subject and action (if available)
        if metadata.get('subjects'):
            subjects = ', '.join(metadata['subjects'])
            parts.append(f"of {subjects}")
        
        if metadata.get('action'):
            parts.append(f"{metadata['action']}")
        
        # Lighting
        lighting = labels.get('lighting', 'mid')
        color_temp = labels.get('color_temperature', 'neutral')
        
        lighting_desc = {
            'dark': 'low-key dramatic',
            'bright': 'bright, high-key',
            'mid': 'balanced'
        }.get(lighting, lighting)
        
        parts.append(f"in {lighting_desc} lighting")
        
        if color_temp != 'neutral':
            parts.append(f"with {color_temp} tones")
        
        # Camera movement
        camera_movement = labels.get('camera_movement_name', 'Static')
        if camera_movement != 'Static':
            direction = movement.get('direction', '')
            if direction and direction != 'none':
                parts.append(f"Camera: {camera_movement} {direction}")
            else:
                parts.append(f"Camera: {camera_movement}")
        
        # Camera angle
        angle = labels.get('camera_angle_name', 'Eye Level')
        if angle != 'Eye Level':
            parts.append(f"Angle: {angle}")
        
        prompt = '. '.join(parts) + '.'
        
        # Add continuity requirements
        continuity_notes = []
        
        for visual_dep in deps.get('visual', []):
            continuity_notes.append(visual_dep['description'])
        
        for motion_dep in deps.get('motion', []):
            continuity_notes.append(motion_dep['description'])
        
        if continuity_notes:
            prompt += '\n\nCONTINUITY: ' + ' '.join(continuity_notes) + '.'
        
        # Add mood if specified
        if metadata.get('mood') and metadata['mood'] != 'neutral':
            prompt += f'\n\nTONE: {metadata["mood"]}'
        
        # Duration information
        duration = shot.get('duration', 0)
        prompt += f'\n\nDURATION: {duration:.2f} seconds'
        
        return prompt
    
    def process_video(self, video_path: str, threshold: float = 27.0, 
                     method: str = 'auto') -> Dict[str, Any]:
        """
        Full pipeline: detect shots, extract frames, label, and generate prompts.
        
        Args:
            video_path: Path to input video
            threshold: Detection threshold
            method: Detection method ('auto', 'scenedetect', 'opencv')
            
        Returns:
            Complete analysis results
        """
        logger.info(f"Starting shot breakdown pipeline for: {video_path}")
        
        # Create project
        project_dir = self.create_project(video_path)
        
        # Get video info
        video_info = self.get_video_info(video_path)
        
        # Detect shots
        shots = self.detect_shots(video_path, method=method, threshold=threshold)
        
        # Extract keyframes and label each shot
        labeled_shots = []
        for shot in shots:
            shot_num = shot['shot_number']
            logger.info(f"Processing shot {shot_num}/{len(shots)}...")
            
            # Extract keyframes
            keyframes_dir = Path(self.current_project_dir) / 'keyframes'
            keyframes = self.extract_shot_keyframes(video_path, shot, keyframes_dir)
            
            # Label shot
            labeled_shot = self.label_shot(shot, video_path, keyframes)
            labeled_shots.append(labeled_shot)
        
        # Map dependencies
        labeled_shots = self.map_dependencies(labeled_shots)
        
        # Generate prompts
        prompts = []
        for shot in labeled_shots:
            prompt = self.generate_shot_prompt(shot)
            shot['prompt'] = prompt
            prompts.append({
                'shot_number': shot['shot_number'],
                'prompt': prompt
            })
        
        # Save results
        results = {
            'video_info': video_info,
            'project_dir': str(self.current_project_dir),
            'video_path': str(video_path),
            'shot_count': len(labeled_shots),
            'total_duration': video_info['duration_seconds'],
            'detection_method': method,
            'threshold': threshold,
            'shots': labeled_shots,
            'prompts': prompts,
            'created': datetime.now().isoformat()
        }
        
        # Convert numpy types to Python native types for JSON serialization
        results = convert_numpy_types(results)
        
        # Save JSON
        analysis_file = Path(self.current_project_dir) / 'analysis' / 'shot_breakdown.json'
        with open(analysis_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Analysis complete: {len(labeled_shots)} shots detected")
        logger.info(f"Results saved to: {analysis_file}")
        
        # Save prompts as text file
        prompts_file = Path(self.current_project_dir) / 'analysis' / 'prompts.txt'
        with open(prompts_file, 'w') as f:
            f.write(f"Shot Breakdown Prompts - {Path(video_path).name}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            for i, shot in enumerate(labeled_shots, 1):
                f.write(f"SHOT {i}\n")
                f.write("-" * 80 + "\n")
                f.write(f"Timecode: {shot['start_time']:.2f}s - {shot['end_time']:.2f}s\n")
                f.write(f"Duration: {shot['duration']:.2f}s\n\n")
                f.write(shot['prompt'])
                f.write("\n\n" + "=" * 80 + "\n\n")
        
        logger.info(f"Prompts saved to: {prompts_file}")
        
        self.shots = labeled_shots
        return results


if __name__ == '__main__':
    # Example usage
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("Usage: python shot_breakdown_manager.py <video_path>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    manager = ShotBreakdownManager()
    
    results = manager.process_video(video_path)
    
    print(f"\n✅ Analysis complete!")
    print(f"📁 Project directory: {results['project_dir']}")
    print(f"🎬 Shots detected: {results['shot_count']}")
    print(f"⏱️  Total duration: {results['total_duration']:.2f}s")
