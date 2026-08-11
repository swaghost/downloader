"""
Test Beat-Composer functionality without full GUI.

This script tests the beat detection and timeline building features.
Run this to verify your installation of librosa/madmom.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from beat_composer_manager import BeatComposerManager

def test_beat_detection(audio_path: str):
    """Test beat detection on an audio file."""
    
    print("=" * 80)
    print("Beat-Composer Test Script")
    print("=" * 80)
    print()
    
    if not Path(audio_path).exists():
        print(f"❌ Error: Audio file not found: {audio_path}")
        return
    
    # Create manager
    print("Creating Beat Composer Manager...")
    manager = BeatComposerManager()
    
    # Create project
    print(f"Loading audio file: {Path(audio_path).name}")
    project_dir = manager.create_project(audio_path)
    print(f"✅ Project created: {project_dir}")
    print()
    
    # Get audio info
    print("Reading audio information...")
    info = manager.get_audio_info(audio_path)
    print(f"  Duration: {info['duration_seconds']:.2f} seconds")
    print(f"  Sample Rate: {info['sample_rate']:,} Hz")
    print(f"  Channels: {info['channels']}")
    print(f"  Format: {info['format']}")
    print(f"  File Size: {info['file_size_mb']:.2f} MB")
    print()
    
    # Test librosa detection
    print("Testing Librosa beat detection...")
    try:
        results = manager.detect_beats_librosa(audio_path)
        print(f"✅ Librosa Results:")
        print(f"  BPM: {results['bpm']:.1f}")
        print(f"  Beats: {results['beat_count']}")
        print(f"  Downbeats: {results['downbeat_count']}")
        print(f"  Time Signature: {results['time_signature'][0]}/{results['time_signature'][1]}")
        print(f"  First 5 beats: {[f'{t:.3f}s' for t in results['beats'][:5]]}")
        print()
    except ImportError as e:
        print(f"⚠️ Librosa not available: {e}")
        print()
    except Exception as e:
        print(f"❌ Librosa detection failed: {e}")
        print()
    
    # Test madmom detection
    print("Testing Madmom beat detection (this may take a moment)...")
    try:
        results = manager.detect_beats_madmom(audio_path)
        print(f"✅ Madmom Results:")
        print(f"  BPM: {results['bpm']:.1f}")
        print(f"  Beats: {results['beat_count']}")
        print(f"  Downbeats: {results['downbeat_count']}")
        print(f"  Time Signature: {results['time_signature'][0]}/{results['time_signature'][1]}")
        print(f"  First 5 beats: {[f'{t:.3f}s' for t in results['beats'][:5]]}")
        print()
    except ImportError as e:
        print(f"⚠️ Madmom not available: {e}")
        print()
    except Exception as e:
        print(f"❌ Madmom detection failed: {e}")
        print()
    
    # Test timeline building
    print("Testing timeline building...")
    try:
        # Build a 15-second timeline with all beats
        timeline = manager.build_timeline(
            duration_mode='seconds',
            duration_value=15.0,
            include_beats=True,
            include_downbeats=False
        )
        print(f"✅ Timeline built with {len(timeline)} beats")
        print(f"  First 5 timeline entries:")
        for beat in timeline[:5]:
            print(f"    Beat {beat['index']:03d} @ {beat['adjusted_time']:.3f}s ({beat['type']})")
        print()
    except Exception as e:
        print(f"❌ Timeline building failed: {e}")
        print()
    
    # Test project save
    print("Testing project save...")
    try:
        project_file = manager.save_project()
        print(f"✅ Project saved: {project_file}")
        print()
    except Exception as e:
        print(f"❌ Project save failed: {e}")
        print()
    
    print("=" * 80)
    print("Test Complete!")
    print("=" * 80)
    print()
    print("If all tests passed, your Beat-Composer installation is ready!")
    print("If some libraries are missing, install them:")
    print("  pip install librosa madmom moviepy ffmpeg-python soundfile audioread mutagen")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_beat_composer.py <audio_file>")
        print()
        print("Example:")
        print("  python test_beat_composer.py music.mp3")
        print()
        sys.exit(1)
    
    audio_file = sys.argv[1]
    test_beat_detection(audio_file)
