"""
Instagram Downloader - Main Entry Point

Clean, minimal Instagram saved posts downloader.
Uses instaloader library for reliability.
"""
import sys
import argparse
import logging
from pathlib import Path

import config
from gui import main as gui_main
from instagram_manager import InstagramManager, quick_download
from account_manager import AccountManager
from shot_breakdown_manager import ShotBreakdownManager


def setup_logging(verbose=False):
    """Configure logging"""
    level = logging.DEBUG if verbose else getattr(logging, config.LOG_LEVEL)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )


def cli_mode(args):
    """Run in command-line mode"""
    if args.command == 'download':
        # Quick download a single post
        output_dir = Path(args.output) if args.output else config.DEFAULT_DOWNLOAD_DIR
        success = quick_download(
            args.username,
            args.password,
            args.shortcode,
            output_dir
        )
        return 0 if success else 1
    
    elif args.command == 'list':
        # List saved posts
        manager = InstagramManager()
        session_file = config.SESSIONS_DIR / f"{args.username}.session"
        
        if manager.login(args.username, args.password, session_file):
            print(f"\nSaved posts for {args.username}:\n")
            for i, post in enumerate(manager.get_saved_posts(), 1):
                print(f"{i}. {post['shortcode']} - {post['owner_username']}")
                if post['caption']:
                    print(f"   {post['caption'][:60]}...")
                print()
            return 0
        else:
            print("Login failed")
            return 1
    
    elif args.command == 'accounts':
        # List saved accounts
        account_manager = AccountManager()
        accounts = account_manager.list_accounts()
        
        if accounts:
            print("\nSaved accounts:\n")
            for account in accounts:
                print(f"  • {account['username']} (Last login: {account['last_login'][:16]})")
            print()
        else:
            print("No saved accounts")
        return 0
    
    elif args.command == 'shot-breakdown':
        # Analyze video for shot breakdown
        print(f"\n🎬 Shot Breakdown Analysis\n")
        print(f"Video: {args.video}")
        print(f"Method: {args.method}")
        print(f"Threshold: {args.threshold}")
        print()
        
        try:
            manager = ShotBreakdownManager()
            results = manager.process_video(
                args.video,
                threshold=args.threshold,
                method=args.method
            )
            
            print(f"\n✅ Analysis complete!")
            print(f"📊 Detected {results['shot_count']} shots")
            print(f"📁 Results: {results['project_dir']}")
            print()
            
            return 0
        
        except Exception as e:
            print(f"\n❌ Error: {e}")
            return 1
    
    return 0


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Instagram Downloader - Clean, minimal saved posts downloader'
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('--cli', action='store_true', help='Run in CLI mode (no GUI)')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Download command
    download_parser = subparsers.add_parser('download', help='Download a single post')
    download_parser.add_argument('username', help='Instagram username')
    download_parser.add_argument('password', help='Instagram password')
    download_parser.add_argument('shortcode', help='Post shortcode (e.g., CdNmOtkIOM-)')
    download_parser.add_argument('-o', '--output', help='Output directory')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List saved posts')
    list_parser.add_argument('username', help='Instagram username')
    list_parser.add_argument('password', help='Instagram password')
    
    # Accounts command
    subparsers.add_parser('accounts', help='List saved accounts')
    
    # Shot breakdown command
    shot_parser = subparsers.add_parser('shot-breakdown', help='Analyze video for cinematic shot breakdown')
    shot_parser.add_argument('video', help='Path to video file')
    shot_parser.add_argument('-m', '--method', default='auto', 
                           choices=['auto', 'scenedetect', 'opencv'],
                           help='Detection method (default: auto)')
    shot_parser.add_argument('-t', '--threshold', type=float, default=27.0,
                           help='Detection sensitivity threshold (default: 27.0)')
    
    args = parser.parse_args()
    
    # Setup - ensure directories exist first, then configure logging
    config.ensure_directories()
    setup_logging(args.verbose)
    
    # Run appropriate mode
    if args.cli or args.command:
        return cli_mode(args)
    else:
        # Launch GUI
        gui_main()
        return 0


if __name__ == '__main__':
    sys.exit(main())
