#!/usr/bin/env python
"""
Shot Breakdown - Quick Test Script

This script demonstrates the Shot Breakdown functionality
by processing a sample video and displaying the results.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from shot_breakdown_manager import ShotBreakdownManager
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main test function"""
    
    print("=" * 80)
    print("Shot Breakdown - Test Script")
    print("=" * 80)
    print()
    
    # Check if video path provided
    if len(sys.argv) < 2:
        print("Usage: python test_shot_breakdown.py <video_path>")
        print()
        print("Example:")
        print("  python test_shot_breakdown.py sample_video.mp4")
        print()
        sys.exit(1)
    
    video_path = sys.argv[1]
    
    # Verify video exists
    if not os.path.exists(video_path):
        print(f"❌ Error: Video file not found: {video_path}")
        sys.exit(1)
    
    print(f"📹 Video: {video_path}")
    print()
    
    # Initialize manager
    print("🔧 Initializing Shot Breakdown Manager...")
    manager = ShotBreakdownManager()
    print(f"✅ Output directory: {manager.output_dir}")
    print()
    
    # Get video info
    print("ℹ️  Reading video information...")
    try:
        video_info = manager.get_video_info(video_path)
        print(f"   Resolution: {video_info['width']}x{video_info['height']}")
        print(f"   FPS: {video_info['fps']:.2f}")
        print(f"   Duration: {video_info['duration_seconds']:.2f} seconds")
        print(f"   Frames: {video_info['frame_count']:,}")
        print(f"   Size: {video_info['file_size_mb']:.2f} MB")
        print()
    except Exception as e:
        print(f"❌ Error reading video: {e}")
        sys.exit(1)
    
    # Process video
    print("🎬 Processing video (this may take a while)...")
    print("   Detection method: Auto")
    print("   Threshold: 27.0")
    print()
    
    try:
        results = manager.process_video(
            video_path,
            threshold=27.0,
            method='auto'
        )
        
        print()
        print("=" * 80)
        print("✅ ANALYSIS COMPLETE!")
        print("=" * 80)
        print()
        
        # Summary
        print("📊 Summary:")
        print(f"   Shots detected: {results['shot_count']}")
        print(f"   Total duration: {results['total_duration']:.2f} seconds")
        print(f"   Detection method: {results['detection_method']}")
        print(f"   Average shot length: {results['total_duration'] / results['shot_count']:.2f}s")
        print()
        
        # Project location
        print("📁 Project Location:")
        print(f"   {results['project_dir']}")
        print()
        
        # Files created
        print("📄 Files Created:")
        print(f"   - shot_breakdown.json (complete analysis)")
        print(f"   - prompts.txt (AI-ready prompts)")
        print(f"   - {len(results['shots']) * 3} keyframe images")
        print()
        
        # Sample shots
        print("🎬 Sample Shots:")
        for i, shot in enumerate(results['shots'][:5], 1):
            print(f"\n   Shot {shot['shot_number']:03d}:")
            print(f"      Time: {shot['start_time']:.2f}s - {shot['end_time']:.2f}s ({shot['duration']:.2f}s)")
            print(f"      Type: {shot['labels'].get('shot_type_name', 'Unknown')}")
            print(f"      Movement: {shot['labels'].get('camera_movement_name', 'Unknown')}")
            print(f"      Lighting: {shot['labels'].get('lighting', 'unknown').title()}")
        
        if results['shot_count'] > 5:
            print(f"\n   ... and {results['shot_count'] - 5} more shots")
        
        print()
        
        # Prompt preview
        print("📝 Sample AI Prompt (Shot 1):")
        print("-" * 80)
        first_prompt = results['shots'][0]['prompt']
        # Print first 300 characters
        if len(first_prompt) > 300:
            print(first_prompt[:300] + "...")
        else:
            print(first_prompt)
        print("-" * 80)
        print()
        
        print("🎉 Success! Check the project folder for all outputs.")
        print()
        
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
