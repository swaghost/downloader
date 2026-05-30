"""
Instagram Manager - Wrapper around instaloader library

Handles all Instagram API interactions using the instaloader library.
This keeps Instagram complexity isolated and maintainable.
"""
import instaloader
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Generator
import logging
import threading

import config

logger = logging.getLogger(__name__)


class InstagramManager:
    """Manages Instagram operations using instaloader library"""
    
    def __init__(self):
        # Authenticated loader (used for saved posts, stories, private accounts)
        self.loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,  # Don't need thumbnails
            download_comments=False,
            save_metadata=False,  # Don't save JSON metadata files
            compress_json=False,
            post_metadata_txt_pattern='',  # Don't create txt files
            max_connection_attempts=config.RETRY_ATTEMPTS,
            filename_pattern='{shortcode}'  # Use simple shortcode-based naming
        )
        
        # Anonymous loader (used for public posts to reduce rate limiting)
        self.anon_loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern='',
            max_connection_attempts=config.RETRY_ATTEMPTS,
            filename_pattern='{shortcode}'
        )
        
        self.username: Optional[str] = None
        self.logged_in = False
        self.session_file: Optional[Path] = None
        self.last_session_check: Optional[float] = None
        # Protect process-wide state used by instaloader download flow (os.chdir).
        self._download_lock = threading.Lock()
    
    def login(self, username: str, password: str, session_file: Optional[Path] = None) -> bool:
        """
        Login to Instagram
        
        Args:
            username: Instagram username
            password: Instagram password
            session_file: Path to saved session file (to avoid re-login)
        
        Returns:
            True if login successful, False otherwise
        """
        try:
            # Try loading existing session first
            if session_file and session_file.exists():
                logger.info(f"Loading session from {session_file}")
                self.loader.load_session_from_file(username, str(session_file))
                self.username = username
                self.logged_in = True
                self.session_file = session_file
                logger.info(f"Logged in as {username} (from session)")
                return True
            
            # Fresh login
            logger.info(f"Logging in as {username}")
            self.loader.login(username, password)
            self.username = username
            self.logged_in = True
            
            # Save session for future use
            if session_file:
                session_file.parent.mkdir(parents=True, exist_ok=True)
                self.loader.save_session_to_file(str(session_file))
                logger.info(f"Session saved to {session_file}")
            
            return True
            
        except instaloader.exceptions.BadCredentialsException:
            logger.error("Invalid username or password")
            return False
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            logger.error("Two-factor authentication required - not yet implemented")
            return False
        except instaloader.exceptions.ConnectionException as e:
            logger.error(f"Instagram connection error: {e}")
            logger.error("Instagram may be blocking automated logins. Try using session import from browser.")
            return False
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Login failed: {error_msg}")
            
            # Provide helpful guidance for common Instagram blocks
            if "null login result" in error_msg.lower() or "fail" in error_msg.lower():
                logger.error("╔═══════════════════════════════════════════════════════════════╗")
                logger.error("║ Instagram is blocking automated login attempts.              ║")
                logger.error("║                                                               ║")
                logger.error("║ WORKAROUND: Import session from browser                      ║")
                logger.error("║ 1. Login to Instagram in Chrome/Firefox                      ║")
                logger.error("║ 2. Use instaloader --login from command line                 ║")
                logger.error("║ 3. Or manually copy cookies to session file                  ║")
                logger.error("║                                                               ║")
                logger.error("║ See TROUBLESHOOTING.md for detailed instructions             ║")
                logger.error("╚═══════════════════════════════════════════════════════════════╝")
            
            return False
    
    def get_saved_posts(self) -> Generator[Dict, None, None]:
        """
        Get all saved posts for the logged-in user
        
        Yields:
            Dict with post information
        """
        if not self.logged_in:
            raise RuntimeError("Must be logged in to get saved posts")
        
        try:
            logger.info(f"Fetching saved posts for {self.username}")
            profile = instaloader.Profile.from_username(self.loader.context, self.username)
            
            count = 0
            for post in profile.get_saved_posts():
                count += 1
                logger.debug(f"Fetched saved post #{count}: {post.shortcode}")
                try:
                    # fetch_full_metadata=False makes this MUCH faster
                    # We don't need likes/comments for the list view
                    post_dict = self._post_to_dict(post, fetch_full_metadata=False)
                    yield post_dict
                except Exception as e:
                    logger.error(f"Error converting post {post.shortcode} to dict: {e}")
                    # Continue with next post instead of failing completely
                    continue
            
            logger.info(f"Finished fetching {count} saved posts")
                
        except Exception as e:
            logger.error(f"Failed to get saved posts: {e}")
            logger.exception("Full exception details:")
            raise
    
    def test_session(self) -> tuple[bool, str]:
        """Test if the current session is valid by making a lightweight API call.
        
        Returns:
            Tuple of (is_valid, message)
        """
        if not self.logged_in:
            return False, "Not logged in"
        
        try:
            # Try to get the logged-in user's profile (lightweight operation)
            profile = instaloader.Profile.from_username(self.loader.context, self.username)
            # If we can get basic info without error, session is valid
            _ = profile.username
            
            import time
            self.last_session_check = time.time()
            
            return True, "Session is valid"
        except instaloader.exceptions.BadResponseException:
            return False, "Session expired - cookies are no longer valid"
        except instaloader.exceptions.ConnectionException as e:
            return False, f"Connection error: {str(e)}"
        except Exception as e:
            return False, f"Session test failed: {str(e)}"
    
    def get_session_age(self) -> Optional[float]:
        """Get the age of the session file in seconds.
        
        Returns:
            Age in seconds, or None if no session file
        """
        if not self.session_file or not self.session_file.exists():
            return None
        
        import os
        import time
        
        file_mtime = os.path.getmtime(self.session_file)
        current_time = time.time()
        return current_time - file_mtime
    
    def keep_session_alive(self) -> bool:
        """Make a lightweight API call to keep the session active.
        
        Returns:
            True if session is still valid, False if expired
        """
        is_valid, message = self.test_session()
        if is_valid:
            logger.info("Session keep-alive successful")
        else:
            logger.warning(f"Session keep-alive failed: {message}")
        return is_valid
    
    def download_post(self, shortcode: str, target_dir: Path) -> tuple:
        """
        Download a single post
        
        Attempts anonymous download first for public posts to reduce rate limiting.
        Falls back to authenticated download if the post requires login.
        
        Args:
            shortcode: Instagram post shortcode (e.g., "CdNmOtkIOM-")
            target_dir: Directory to save files (full path)
        
        Returns:
            Tuple of (success: bool, metadata: dict) where metadata includes:
                - caption: str
                - tags: str (comma-separated hashtags)
                - files: list of downloaded file names
                - owner: str
                - typename: str
        
        Raises:
            Exception: Re-raises exceptions with detailed error messages
        """
        if not self.logged_in:
            raise RuntimeError("Must be logged in to download")
        
        # Try anonymous download first for public posts
        try:
            return self._download_post_anonymous(shortcode, target_dir)
        except instaloader.exceptions.LoginRequiredException:
            logger.info(f"Post {shortcode} requires login → Using authenticated session for fallback")
            return self._download_post_authenticated(shortcode, target_dir)
        except Exception as e:
            # For other errors during anonymous download, fall back to authenticated
            error_msg = str(e).lower()
            if 'login' in error_msg or 'private' in error_msg or 'authorization' in error_msg:
                logger.info(f"Post {shortcode} may be private → Using authenticated session for fallback")
                return self._download_post_authenticated(shortcode, target_dir)
            else:
                # Other errors shouldn't be retried with auth
                raise
    
    def _download_post_anonymous(self, shortcode: str, target_dir: Path) -> tuple:
        """
        Download a post without authentication (public posts only)
        
        Raises:
            LoginRequiredException: If post requires authentication
            Other exceptions: For various download errors
        """
        logger.info(f"Attempting anonymous download for {shortcode}")
        
        try:
            target_dir.mkdir(parents=True, exist_ok=True)

            import os
            import re

            def files_for_shortcode(directory: Path, code: str) -> set:
                """Return files that belong to this shortcode only."""
                if not directory.exists():
                    return set()
                matched = set()
                for name in os.listdir(directory):
                    # instaloader naming is shortcode-based (e.g., CODE.jpg, CODE_1.jpg, CODE.mp4)
                    if name.startswith(code):
                        matched.add(name)
                return matched

            # Snapshot only this shortcode's files, not all directory files.
            files_before = files_for_shortcode(target_dir, shortcode)
            
            # Attempt to fetch post metadata first - this will catch unavailable posts quickly
            logger.info(f"Fetching post metadata for {shortcode} (anonymous)")
            logger.info(f"Instagram URL: https://www.instagram.com/p/{shortcode}/")
            post = instaloader.Post.from_shortcode(self.anon_loader.context, shortcode)
            
            # Extract metadata before download
            caption = post.caption if post.caption else ""
            
            # Extract hashtags from caption
            hashtags = re.findall(r'#(\w+)', caption)
            tags = ', '.join(hashtags) if hashtags else ""
            
            owner = post.owner_username
            typename = post.typename
            
            # If we got here, the post exists and is accessible
            logger.info(f"Downloading post {shortcode} (owner: {owner})")
            logger.info(f"Caption: {caption[:100]}{'...' if len(caption) > 100 else ''}")
            logger.info(f"Tags: {tags if tags else 'None'}")
            
            # IMPORTANT: instaloader's target parameter is a SUBDIRECTORY NAME, not a full path.
            # os.chdir is process-global, so protect this critical section with a lock.
            with self._download_lock:
                original_cwd = os.getcwd()
                try:
                    # Ensure target directory exists
                    target_dir.mkdir(parents=True, exist_ok=True)

                    parent_dir = target_dir.parent
                    dir_name = target_dir.name

                    # Validate paths before changing directory
                    if not parent_dir or str(parent_dir) == '.':
                        # If parent is current directory or invalid, use target_dir as-is
                        logger.warning(f"Invalid parent directory for {target_dir}, using absolute path")
                        parent_dir = target_dir.resolve().parent
                        dir_name = target_dir.resolve().name

                    logger.info(f"Changing to parent directory: {parent_dir}")
                    logger.info(f"Current working directory before change: {original_cwd}")

                    # Ensure parent directory exists
                    parent_dir.mkdir(parents=True, exist_ok=True)

                    os.chdir(str(parent_dir))
                    logger.info(f"Changed to: {os.getcwd()}")

                    logger.info(f"Downloading to subdirectory: {dir_name} (anonymous)")
                    self.anon_loader.download_post(post, target=dir_name)
                finally:
                    # Always restore original working directory
                    os.chdir(original_cwd)
                    logger.info(f"Restored working directory: {original_cwd}")
            
            # Verify files were actually downloaded
            files_after = files_for_shortcode(target_dir, shortcode)
            new_files = sorted(list(files_after - files_before))
            
            # Build metadata dict
            metadata = {
                'caption': caption,
                'tags': tags,
                'files': new_files,
                'owner': owner,
                'typename': typename
            }
            
            if not new_files:
                # No new files - this is normal if files already exist (instaloader skips duplicates)
                logger.info(f"Post {shortcode} already exists in {target_dir} - database entry updated")
                # Check if files actually exist in the directory
                existing_files = sorted(list(files_after))
                if existing_files:
                    logger.info(f"Verified {len(existing_files)} existing file(s): {', '.join(sorted(existing_files)[:3])}")
                    # Return the existing files so the database can be updated properly
                    metadata['files'] = existing_files
            else:
                logger.info(f"Downloaded {len(new_files)} file(s) for {shortcode}: {', '.join(sorted(new_files)[:5])}")
            
            return (True, metadata)
        
        except instaloader.exceptions.LoginRequiredException:
            # Re-raise to trigger fallback to authenticated download
            raise
        
        except instaloader.exceptions.QueryReturnedNotFoundException:
            error_msg = (
                f"Post not found: {shortcode}\n\n"
                f"This post has been deleted, removed, or never existed.\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                f"Possible reasons:\n"
                f"• Post was deleted by the owner\n"
                f"• Post was removed by Instagram for policy violations\n"
                f"• Invalid or incorrect shortcode"
            )
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except instaloader.exceptions.BadResponseException as e:
            # Check if it's a 404 error (post not found)
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                error_msg = (
                    f"Post not found (404): {shortcode}\n\n"
                    f"This post is unavailable or has been deleted.\n"
                    f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                    f"The post may have been:\n"
                    f"• Deleted by the owner\n"
                    f"• Removed by Instagram\n"
                    f"• Made private (if you don't follow the account)"
                )
            else:
                error_msg = (
                    f"Failed to download post {shortcode}\n\n"
                    f"Instagram returned an error: {e}\n"
                    f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                    f"Possible reasons:\n"
                    f"• Session expired - try refreshing cookies from browser\n"
                    f"• Rate limiting - wait 15-30 minutes before retrying\n"
                    f"• Network connection issues\n"
                    f"• Instagram API changes"
                )
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except instaloader.exceptions.ConnectionException as e:
            error_msg = (
                f"Connection error for post: {shortcode}\n\n"
                f"Network error: {e}\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                f"Possible solutions:\n"
                f"• Check your internet connection\n"
                f"• Try again in a few minutes\n"
                f"• Check if Instagram is accessible in your browser"
            )
            logger.error(error_msg)
            raise Exception(error_msg)
            
        except Exception as e:
            import os
            error_msg = (
                f"Unexpected error downloading post {shortcode}\n\n"
                f"Error type: {type(e).__name__}\n"
                f"Error message: {e}\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n"
                f"Target directory: {target_dir}\n"
                f"Current working directory: {os.getcwd()}\n\n"
                f"This may be a new type of error. Please report this if it persists."
            )
            logger.error(error_msg)
            raise Exception(error_msg) from e
    
    def _download_post_authenticated(self, shortcode: str, target_dir: Path) -> tuple:
        """
        Download a post using authenticated session (for private posts, stories, etc.)
        
        Raises:
            Various exceptions for different download errors
        """
        logger.info(f"Using authenticated session for {shortcode}")
        
        try:
            target_dir.mkdir(parents=True, exist_ok=True)

            import os
            import re

            def files_for_shortcode(directory: Path, code: str) -> set:
                """Return files that belong to this shortcode only."""
                if not directory.exists():
                    return set()
                matched = set()
                for name in os.listdir(directory):
                    # instaloader naming is shortcode-based (e.g., CODE.jpg, CODE_1.jpg, CODE.mp4)
                    if name.startswith(code):
                        matched.add(name)
                return matched

            # Snapshot only this shortcode's files, not all directory files.
            files_before = files_for_shortcode(target_dir, shortcode)
            
            # Attempt to fetch post metadata first - this will catch unavailable posts quickly
            logger.info(f"Fetching post metadata for {shortcode} (authenticated)")
            logger.info(f"Instagram URL: https://www.instagram.com/p/{shortcode}/")
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            # Extract metadata before download
            caption = post.caption if post.caption else ""
            
            # Extract hashtags from caption
            hashtags = re.findall(r'#(\w+)', caption)
            tags = ', '.join(hashtags) if hashtags else ""
            
            owner = post.owner_username
            typename = post.typename
            
            # If we got here, the post exists and is accessible
            logger.info(f"Downloading post {shortcode} (owner: {owner})")
            logger.info(f"Caption: {caption[:100]}{'...' if len(caption) > 100 else ''}")
            logger.info(f"Tags: {tags if tags else 'None'}")
            
            # IMPORTANT: instaloader's target parameter is a SUBDIRECTORY NAME, not a full path.
            # os.chdir is process-global, so protect this critical section with a lock.
            with self._download_lock:
                original_cwd = os.getcwd()
                try:
                    # Ensure target directory exists
                    target_dir.mkdir(parents=True, exist_ok=True)

                    parent_dir = target_dir.parent
                    dir_name = target_dir.name

                    # Validate paths before changing directory
                    if not parent_dir or str(parent_dir) == '.':
                        # If parent is current directory or invalid, use target_dir as-is
                        logger.warning(f"Invalid parent directory for {target_dir}, using absolute path")
                        parent_dir = target_dir.resolve().parent
                        dir_name = target_dir.resolve().name

                    logger.info(f"Changing to parent directory: {parent_dir}")
                    logger.info(f"Current working directory before change: {original_cwd}")

                    # Ensure parent directory exists
                    parent_dir.mkdir(parents=True, exist_ok=True)

                    os.chdir(str(parent_dir))
                    logger.info(f"Changed to: {os.getcwd()}")

                    logger.info(f"Downloading to subdirectory: {dir_name} (authenticated)")
                    self.loader.download_post(post, target=dir_name)
                finally:
                    # Always restore original working directory
                    os.chdir(original_cwd)
                    logger.info(f"Restored working directory: {original_cwd}")
            
            # Verify files were actually downloaded
            files_after = files_for_shortcode(target_dir, shortcode)
            new_files = sorted(list(files_after - files_before))
            
            # Build metadata dict
            metadata = {
                'caption': caption,
                'tags': tags,
                'files': new_files,
                'owner': owner,
                'typename': typename
            }
            
            if not new_files:
                # No new files - this is normal if files already exist (instaloader skips duplicates)
                logger.info(f"Post {shortcode} already exists in {target_dir} - database entry updated")
                # Check if files actually exist in the directory
                existing_files = sorted(list(files_after))
                if existing_files:
                    logger.info(f"Verified {len(existing_files)} existing file(s): {', '.join(sorted(existing_files)[:3])}")
                    # Return the existing files so the database can be updated properly
                    metadata['files'] = existing_files
            else:
                logger.info(f"Downloaded {len(new_files)} file(s) for {shortcode}: {', '.join(sorted(new_files)[:5])}")
            
            return (True, metadata)
        
        except instaloader.exceptions.QueryReturnedNotFoundException:
            error_msg = (
                f"Post not found: {shortcode}\n\n"
                f"This post has been deleted, removed, or never existed.\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                f"Possible reasons:\n"
                f"• Post was deleted by the owner\n"
                f"• Post was removed by Instagram for policy violations\n"
                f"• Invalid or incorrect shortcode"
            )
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except instaloader.exceptions.LoginRequiredException:
            error_msg = (
                f"Login required for post: {shortcode}\n\n"
                f"Your Instagram session has expired or is invalid.\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                f"Solution:\n"
                f"• Go to Accounts tab\n"
                f"• Click 'Extract from Browser Cookies'\n"
                f"• Make sure you're logged into Instagram in your browser\n"
                f"• Try downloading again"
            )
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except instaloader.exceptions.BadResponseException as e:
            # Check if it's a 404 error (post not found)
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                error_msg = (
                    f"Post not found (404): {shortcode}\n\n"
                    f"This post is unavailable or has been deleted.\n"
                    f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                    f"The post may have been:\n"
                    f"• Deleted by the owner\n"
                    f"• Removed by Instagram\n"
                    f"• Made private (if you don't follow the account)"
                )
            else:
                error_msg = (
                    f"Failed to download post {shortcode}\n\n"
                    f"Instagram returned an error: {e}\n"
                    f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                    f"Possible reasons:\n"
                    f"• Session expired - try refreshing cookies from browser\n"
                    f"• Rate limiting - wait 15-30 minutes before retrying\n"
                    f"• Network connection issues\n"
                    f"• Instagram API changes"
                )
            logger.error(error_msg)
            raise Exception(error_msg)
        
        except instaloader.exceptions.ConnectionException as e:
            error_msg = (
                f"Connection error for post: {shortcode}\n\n"
                f"Network error: {e}\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n\n"
                f"Possible solutions:\n"
                f"• Check your internet connection\n"
                f"• Try again in a few minutes\n"
                f"• Check if Instagram is accessible in your browser"
            )
            logger.error(error_msg)
            raise Exception(error_msg)
            
        except Exception as e:
            import os
            error_msg = (
                f"Unexpected error downloading post {shortcode}\n\n"
                f"Error type: {type(e).__name__}\n"
                f"Error message: {e}\n"
                f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n"
                f"Target directory: {target_dir}\n"
                f"Current working directory: {os.getcwd()}\n\n"
                f"This may be a new type of error. Please report this if it persists."
            )
            logger.error(error_msg)
            raise Exception(error_msg) from e
    
    def get_post_info(self, shortcode: str) -> Optional[Dict]:
        """
        Get information about a post without downloading
        
        Args:
            shortcode: Instagram post shortcode
        
        Returns:
            Dict with post info, or None if failed
        """
        try:
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            return self._post_to_dict(post)
        except Exception as e:
            logger.error(f"Failed to get post info for {shortcode}: {e}")
            return None
    
    def download_thumbnail(self, shortcode: str, target_path: Path) -> tuple:
        """
        Download thumbnail/preview image for a post
        
        Args:
            shortcode: Instagram post shortcode
            target_path: Full path where to save the thumbnail (including filename)
            
        Returns:
            tuple: (success: bool, dimensions: tuple or None)
                dimensions is (width, height) if successful
        """
        import requests
        from PIL import Image
        from io import BytesIO
        
        try:
            # Method 1: Try getting thumbnail from Instagram
            try:
                post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
                thumbnail_url = post.url
                
                logger.info(f"Downloading thumbnail for {shortcode} from {thumbnail_url}")
                response = requests.get(thumbnail_url, timeout=30)
                response.raise_for_status()
                
                # Open image to get dimensions
                img = Image.open(BytesIO(response.content))
                width, height = img.size
                
                # Save to file
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Thumbnail saved: {target_path} ({width}x{height})")
                return (True, (width, height))
            except Exception as e:
                logger.debug(f"Could not fetch thumbnail from Instagram for {shortcode}: {e}")
                
                # Method 2: Try to extract from downloaded files in the same directory
                # Look for downloaded files with this shortcode
                download_dir = target_path.parent.parent  # Go up from .thumbnails to account dir
                logger.info(f"Searching for downloaded files in: {download_dir}")
                
                # List files for debugging
                try:
                    existing_files = list(download_dir.glob(f"{shortcode}*"))[:5]  # Show first 5 matches
                    logger.info(f"Files with shortcode prefix: {[f.name for f in existing_files]}")
                except:
                    pass
                
                # Try common patterns
                for pattern in [f"{shortcode}.jpg", f"{shortcode}.mp4", f"{shortcode}_*.jpg", f"{shortcode}_*.mp4"]:
                    logger.info(f"Trying pattern: {pattern}")
                    matches = list(download_dir.glob(pattern))
                    if matches:
                        source_file = matches[0]
                        logger.info(f"Found downloaded file: {source_file}, extracting thumbnail...")
                        
                        if source_file.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                            # Image file - just copy and resize
                            img = Image.open(source_file)
                            # Create thumbnail (max 500x500)
                            img.thumbnail((500, 500), Image.Resampling.LANCZOS)
                            width, height = img.size
                            
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            img.save(target_path, 'JPEG', quality=85)
                            logger.info(f"Thumbnail extracted from image: {target_path} ({width}x{height})")
                            return (True, (width, height))
                        
                        elif source_file.suffix.lower() in ['.mp4', '.mov']:
                            # Video file - extract first frame
                            try:
                                import cv2
                                vidcap = cv2.VideoCapture(str(source_file))
                                success, image = vidcap.read()
                                if success:
                                    # Convert BGR to RGB
                                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                                    img = Image.fromarray(image_rgb)
                                    img.thumbnail((500, 500), Image.Resampling.LANCZOS)
                                    width, height = img.size
                                    
                                    target_path.parent.mkdir(parents=True, exist_ok=True)
                                    img.save(target_path, 'JPEG', quality=85)
                                    logger.info(f"Thumbnail extracted from video: {target_path} ({width}x{height})")
                                    return (True, (width, height))
                                vidcap.release()
                            except ImportError:
                                logger.debug("cv2 not available for video thumbnail extraction")
                            except Exception as video_err:
                                logger.debug(f"Could not extract frame from video: {video_err}")
                
                # If we got here, no methods worked
                raise Exception(f"Could not fetch thumbnail from Instagram or extract from local files")
        
        except Exception as e:
            logger.error(f"Failed to download thumbnail for {shortcode}: {e}")
            return (False, None)
    
    def _post_to_dict(self, post, fetch_full_metadata=False) -> Dict:
        """
        Convert instaloader Post object to dictionary
        
        Args:
            post: Instaloader Post object
            fetch_full_metadata: If True, fetch likes/comments (slow - requires extra API calls)
                                If False, only get basic info (fast)
        """
        try:
            # Basic info (always available, no extra API calls)
            result = {
                'shortcode': post.shortcode,
                'url': f"https://www.instagram.com/p/{post.shortcode}/",
                'owner_username': post.owner_username,
                'typename': post.typename,  # GraphImage, GraphVideo, GraphSidecar
                'is_video': post.is_video,
            }
            
            # Caption (may be None)
            try:
                result['caption'] = post.caption if post.caption else ""
            except:
                result['caption'] = ""
            
            # Date (usually available)
            try:
                result['date'] = post.date_utc.isoformat()
            except:
                result['date'] = datetime.now().isoformat()
            
            # Video URL
            try:
                result['video_url'] = post.video_url if post.is_video else None
            except:
                result['video_url'] = None
            
            # Media count for carousels
            try:
                result['media_count'] = post.mediacount if post.typename == 'GraphSidecar' else 1
            except:
                result['media_count'] = 1
            
            # Thumbnail
            try:
                result['thumbnail_url'] = post.url
            except:
                result['thumbnail_url'] = None
            
            # SLOW: Engagement metrics (requires additional API calls - only fetch if requested)
            if fetch_full_metadata:
                try:
                    result['likes'] = post.likes
                except:
                    result['likes'] = 0
                    logger.debug(f"Could not fetch likes for {post.shortcode}")
                
                try:
                    result['comments'] = post.comments
                except:
                    result['comments'] = 0
                    logger.debug(f"Could not fetch comments for {post.shortcode}")
            else:
                # Don't fetch these - they're slow and not needed for the list view
                result['likes'] = None
                result['comments'] = None
            
            return result
            
        except Exception as e:
            logger.error(f"Error in _post_to_dict for post {getattr(post, 'shortcode', 'unknown')}: {e}")
            raise
    
    def logout(self):
        """Logout and clear session"""
        self.logged_in = False
        self.username = None
        logger.info("Logged out")


# Convenience function for quick operations
def quick_download(username: str, password: str, shortcode: str, output_dir: Path) -> bool:
    """
    Quick function to download a single post
    
    Usage:
        quick_download('myuser', 'mypass', 'CdNmOtkIOM-', Path('./downloads'))
    """
    manager = InstagramManager()
    if manager.login(username, password):
        return manager.download_post(shortcode, output_dir)
    return False
