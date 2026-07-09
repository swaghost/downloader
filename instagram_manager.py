"""
Instagram Manager - Wrapper around instaloader library

Handles all Instagram API interactions using the instaloader library.
This keeps Instagram complexity isolated and maintainable.
"""
import instaloader
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Generator, Any
import logging
import threading
import time
import random
import re
import html
import requests

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
        # Backoff state for GraphQL thumbnail lookups when Instagram returns 403.
        self.thumbnail_graphql_block_until: float = 0.0
        self.thumbnail_graphql_failures: int = 0
    
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
            # Use the authenticated account from the active session. This is
            # more robust than looking up by self.username, which may be a
            # local/account identifier rather than an Instagram profile handle.
            profile = instaloader.Profile.own_profile(self.loader.context)
            
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
            # Validate session by resolving the authenticated profile directly.
            profile = instaloader.Profile.own_profile(self.loader.context)
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

    def _safe_post_attr(self, post, attr_name: str, default=None):
        """Safely read a Post attribute that may intermittently fail per item."""
        try:
            return getattr(post, attr_name)
        except Exception as e:
            logger.debug(
                f"Could not read post.{attr_name} for {getattr(post, 'shortcode', 'unknown')}: {e}"
            )
            return default

    def _is_transient_instagram_error(self, exc: Exception) -> bool:
        """Return True for errors that are worth retrying."""
        if isinstance(exc, (instaloader.exceptions.ConnectionException, instaloader.exceptions.BadResponseException)):
            return True

        msg = str(exc).lower()
        transient_markers = [
            "'nonetype' object is not subscriptable",
            "json query",
            "forbidden",
            "too many requests",
            "temporarily blocked",
            "feedback_required",
            "connection",
            "timeout",
        ]
        return any(marker in msg for marker in transient_markers)

    def _run_with_retries(
        self,
        operation,
        shortcode: str,
        label: str,
        max_attempts: int = 3,
        fast_fail_on_null_metadata: bool = False,
    ):
        """Run an Instagram operation with bounded retries for transient errors."""
        last_error = None
        for attempt in range(1, max_attempts + 1):
            try:
                return operation()
            except Exception as e:
                last_error = e
                if fast_fail_on_null_metadata:
                    category = self.classify_failure_category(e)
                    if category == 'null_metadata_shape':
                        logger.warning(
                            f"{label} failed for {shortcode} with null metadata shape; "
                            f"switching to fallback without further retries. Error: {e}"
                        )
                        raise

                if attempt >= max_attempts or not self._is_transient_instagram_error(e):
                    raise

                delay = min(12.0, 1.5 * attempt + random.uniform(0.4, 1.6))
                logger.warning(
                    f"{label} failed for {shortcode} (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {delay:.1f}s"
                )
                time.sleep(delay)

        # Defensive: should never reach here because loop either returns or raises.
        if last_error is not None:
            raise last_error

    def classify_failure_category(self, error: Exception | str) -> str:
        """Classify a failure into a UI-friendly diagnostics bucket."""
        msg = str(error).lower() if error is not None else ""

        hard_not_found_markers = [
            "post not found",
            "not found (404)",
            "invalid or incorrect shortcode",
            "never existed",
            "queryreturnednotfoundexception",
            "404",
        ]
        if any(marker in msg for marker in hard_not_found_markers):
            return "hard_not_found"

        auth_markers = [
            "login required",
            "session expired",
            "cookies are no longer valid",
            "must be logged in",
            "not logged in",
            "bad credentials",
            "two-factor",
        ]
        if any(marker in msg for marker in auth_markers):
            return "auth_session_issue"

        rate_limit_markers = [
            "feedback_required",
            "too many requests",
            "rate limit",
            "temporarily blocked",
            "forbidden",
            "403",
            "429",
        ]
        if any(marker in msg for marker in rate_limit_markers):
            return "rate_limit_gating_issue"

        null_shape_markers = [
            "'nonetype' object is not subscriptable",
            "xdt_shortcode_media",
            "shortcode_media",
            "fetching post metadata failed",
            "json query",
            "badresponseexception",
        ]
        if any(marker in msg for marker in null_shape_markers):
            return "null_metadata_shape"

        # Keep diagnostics in the requested four buckets.
        return "null_metadata_shape"

    def _extract_shortcode_media_from_json(self, response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract a post node from Instagram web JSON variants."""
        if not isinstance(response, dict):
            return None

        media = response.get("graphql", {}).get("shortcode_media")
        if isinstance(media, dict):
            return media

        data = response.get("data")
        if isinstance(data, dict):
            media = data.get("xdt_shortcode_media")
            if isinstance(media, dict):
                return media

        # Some responses include deeply nested media objects.
        for key in ("shortcode_media", "xdt_shortcode_media"):
            media = response.get(key)
            if isinstance(media, dict):
                return media

        return None

    def _post_from_web_json_fallback(self, context, shortcode: str) -> Optional[instaloader.Post]:
        """Try web JSON endpoints and build a Post without from_shortcode GraphQL path."""
        candidates = [
            (f"p/{shortcode}/", {"__a": "1", "__d": "dis"}),
            (f"p/{shortcode}/", {"__a": "1"}),
            (f"reel/{shortcode}/", {"__a": "1", "__d": "dis"}),
            (f"reel/{shortcode}/", {"__a": "1"}),
        ]

        # Avoid context.get_json here: its internal retries can be very slow/noisy
        # when Instagram returns unstable 500/404/HTML for __a endpoints.
        session = getattr(context, '_session', None)
        if session is None:
            return None

        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json,text/plain,*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': f'https://www.instagram.com/p/{shortcode}/',
            'X-Requested-With': 'XMLHttpRequest',
        }

        for path, params in candidates:
            try:
                endpoint = f'https://www.instagram.com/{path}'
                response = session.get(endpoint, params=params, headers=headers, timeout=12)
                if response.status_code != 200:
                    logger.debug(
                        f"Web JSON fallback got HTTP {response.status_code} for {shortcode} on {path}"
                    )
                    continue

                body = (response.text or '').strip()
                if not body or not body.startswith('{'):
                    logger.debug(
                        f"Web JSON fallback got non-JSON response for {shortcode} on {path}"
                    )
                    continue

                response_json = response.json()
                node = self._extract_shortcode_media_from_json(response_json)
                if isinstance(node, dict) and ("shortcode" in node or "code" in node):
                    post = instaloader.Post(context, node)
                    post._full_metadata_dict = node
                    logger.info(f"Recovered metadata for {shortcode} via web JSON fallback: {path}")
                    return post
            except Exception as e:
                logger.debug(f"Web JSON fallback failed for {shortcode} on {path}: {e}")

        return None

    def _post_from_iphone_api_fallback(self, context, shortcode: str) -> Optional[instaloader.Post]:
        """Try authenticated iPhone API to build a Post object from media info."""
        try:
            mediaid = instaloader.Post.shortcode_to_mediaid(shortcode)
            response = context.get_iphone_json(path=f"api/v1/media/{mediaid}/info/", params={})
            items = response.get("items") if isinstance(response, dict) else None
            if isinstance(items, list) and items:
                post = instaloader.Post.from_iphone_struct(context, items[0])
                logger.info(f"Recovered metadata for {shortcode} via authenticated iPhone API fallback")
                return post
        except Exception as e:
            logger.debug(f"iPhone API fallback failed for {shortcode}: {e}")

        return None

    def _extract_opengraph_media(self, shortcode: str) -> Optional[Dict[str, str]]:
        """Extract public media URLs from Instagram post HTML OpenGraph tags."""
        page_url = f"https://www.instagram.com/p/{shortcode}/"
        embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        try:
            response = requests.get(page_url, headers=headers, timeout=15)
        except Exception as e:
            logger.debug(f"OpenGraph fetch failed for {shortcode}: {e}")
            return None

        if int(response.status_code) != 200:
            logger.debug(f"OpenGraph fetch returned HTTP {response.status_code} for {shortcode}")
            return None

        html_text = response.text or ''

        def _meta_content(prop_name: str) -> str:
            pattern = rf'<meta[^>]+property="{prop_name}"[^>]+content="([^"]*)"'
            match = re.search(pattern, html_text, flags=re.IGNORECASE)
            return html.unescape(match.group(1)).strip() if match else ''

        image_url = _meta_content('og:image')
        video_url = _meta_content('og:video')
        description = _meta_content('og:description')
        is_video_hint = False

        # Some post pages omit og:video for reels/videos. The embed page often
        # includes escaped JSON with video_url and is_video markers.
        try:
            embed_resp = requests.get(embed_url, headers=headers, timeout=15)
            if int(embed_resp.status_code) == 200:
                embed_html = embed_resp.text or ''
                if re.search(r'\\"is_video\\"\s*:\s*true', embed_html, flags=re.IGNORECASE):
                    is_video_hint = True

                video_match = re.search(r'\\"video_url\\"\s*:\s*\\"([^\\"]+)\\"', embed_html)
                if video_match and not video_url:
                    raw_url = video_match.group(1)
                    # Decode escaped JSON URL fragments such as \/ and \u0026.
                    try:
                        video_url = raw_url.encode('utf-8').decode('unicode_escape')
                    except Exception:
                        video_url = raw_url
                    video_url = video_url.replace('\\/', '/').replace('\\u0026', '&').strip()
        except Exception as e:
            logger.debug(f"Embed OpenGraph fetch failed for {shortcode}: {e}")

        if not image_url and not video_url:
            return None

        return {
            'image_url': image_url,
            'video_url': video_url,
            'description': description,
            'page_url': page_url,
            'is_video_hint': 'true' if is_video_hint else 'false',
        }

    def _download_url_to_file(self, file_url: str, output_path: Path) -> bool:
        """Download a URL directly to a local file path."""
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            with requests.get(file_url, headers=headers, stream=True, timeout=30) as response:
                if int(response.status_code) != 200:
                    logger.debug(f"Direct media download returned HTTP {response.status_code} for {file_url}")
                    return False
                with open(output_path, 'wb') as handle:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            handle.write(chunk)
            return True
        except Exception as e:
            logger.debug(f"Direct media download failed for {file_url}: {e}")
            return False

    def _download_post_anonymous_opengraph_fallback(self, shortcode: str, target_dir: Path) -> Optional[tuple]:
        """Fallback anonymous download using OpenGraph media URLs from public HTML."""
        og = self._extract_opengraph_media(shortcode)
        if not og:
            return None

        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded_files: List[str] = []

        image_url = (og.get('image_url') or '').strip()
        video_url = (og.get('video_url') or '').strip()
        is_video_hint = str(og.get('is_video_hint') or '').lower() == 'true'

        # If this looks like a video post but no direct video URL is extractable,
        # let caller fall back to authenticated flow instead of returning thumbnail-only success.
        if is_video_hint and not video_url:
            logger.info(
                f"OpenGraph fallback detected video hints for {shortcode} but no direct video URL; "
                f"deferring to authenticated fallback."
            )
            return None

        if video_url:
            video_path = target_dir / f"{shortcode}.mp4"
            if self._download_url_to_file(video_url, video_path):
                downloaded_files.append(video_path.name)

        if image_url:
            image_path = target_dir / f"{shortcode}.jpg"
            if self._download_url_to_file(image_url, image_path):
                downloaded_files.append(image_path.name)

        if not downloaded_files:
            return None

        description = (og.get('description') or '').strip()
        caption = description
        owner = 'unknown'
        owner_match = re.search(r'-\s*([^\s]+)\s+on\s+', description)
        if owner_match:
            owner = owner_match.group(1).strip()
        if ':' in description:
            caption = description.split(':', 1)[1].strip()

        hashtags = re.findall(r'#(\w+)', caption)
        tags = ', '.join(hashtags) if hashtags else ''

        typename = 'GraphVideo' if any(name.lower().endswith('.mp4') for name in downloaded_files) else 'GraphImage'
        logger.info(f"Recovered anonymous download for {shortcode} via OpenGraph HTML fallback")
        return (True, {
            'caption': caption,
            'tags': tags,
            'files': sorted(downloaded_files),
            'owner': owner,
            'typename': typename,
        })

    def _get_post_with_fallback(self, shortcode: str, authenticated: bool = False) -> instaloader.Post:
        """Fetch a Post with robust fallbacks when GraphQL metadata intermittently fails."""
        context = self.loader.context if authenticated else self.anon_loader.context
        mode = "authenticated" if authenticated else "anonymous"

        try:
            return self._run_with_retries(
                lambda: instaloader.Post.from_shortcode(context, shortcode),
                shortcode,
                f"{mode.capitalize()} metadata fetch",
                max_attempts=2,
                fast_fail_on_null_metadata=True,
            )
        except Exception as primary_error:
            logger.warning(
                f"Primary {mode} metadata fetch failed for {shortcode}; trying fallback endpoints. "
                f"Error: {primary_error}"
            )

            # For authenticated mode, prioritize iPhone API fallback first.
            # Instagram web JSON (__a/__d) endpoints are increasingly unstable
            # (often 500/404/HTML), while iPhone API remains more reliable.
            if authenticated:
                iphone_post = self._post_from_iphone_api_fallback(context, shortcode)
                if iphone_post is not None:
                    return iphone_post

            web_post = self._post_from_web_json_fallback(context, shortcode)
            if web_post is not None:
                return web_post

            # iPhone API requires authenticated context/cookies.
            if authenticated:
                iphone_post = self._post_from_iphone_api_fallback(context, shortcode)
                if iphone_post is not None:
                    return iphone_post

            raise
    
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
            # For most anonymous failures, try authenticated fallback before failing.
            error_msg = str(e).lower()
            hard_not_found_markers = [
                'post not found',
                '404',
                'invalid or incorrect shortcode',
                'never existed',
            ]

            if any(marker in error_msg for marker in hard_not_found_markers):
                raise

            logger.warning(
                f"Anonymous download failed for {shortcode}; attempting authenticated fallback. Error: {e}",
                exc_info=True,
            )
            try:
                return self._download_post_authenticated(shortcode, target_dir)
            except Exception as auth_error:
                raise Exception(
                    f"Download failed in both anonymous and authenticated modes for {shortcode}. "
                    f"Anonymous error: {e} | Auth error: {auth_error}"
                ) from auth_error
    
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
            try:
                post = self._get_post_with_fallback(shortcode, authenticated=False)
            except Exception as metadata_error:
                og_result = self._download_post_anonymous_opengraph_fallback(shortcode, target_dir)
                if og_result is not None:
                    _, og_meta = og_result
                    recovered_files = [str(name).lower() for name in (og_meta or {}).get('files', [])]
                    recovered_video = any(name.endswith(('.mp4', '.m4v', '.mov', '.webm')) for name in recovered_files)
                    if recovered_video:
                        return og_result

                    # If HTML fallback only recovers an image, defer to authenticated flow
                    # so video posts still get their actual video when available.
                    logger.info(
                        f"OpenGraph fallback for {shortcode} recovered image-only media; "
                        f"escalating to authenticated fallback to preserve video downloads."
                    )
                raise metadata_error
            
            # Extract metadata before download (defensive: properties can fail on some posts)
            caption_value = self._safe_post_attr(post, 'caption', "")
            caption = caption_value if isinstance(caption_value, str) else ""

            # Extract hashtags from caption
            hashtags = re.findall(r'#(\w+)', caption)
            tags = ', '.join(hashtags) if hashtags else ""

            owner = self._safe_post_attr(post, 'owner_username', 'unknown') or 'unknown'
            typename = self._safe_post_attr(post, 'typename', 'Unknown') or 'Unknown'
            
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
                    self._run_with_retries(
                        lambda: self.anon_loader.download_post(post, target=dir_name),
                        shortcode,
                        "Anonymous download",
                    )
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
            logger.error(error_msg, exc_info=True)
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
            post = self._get_post_with_fallback(shortcode, authenticated=True)
            
            # Extract metadata before download (defensive: properties can fail on some posts)
            caption_value = self._safe_post_attr(post, 'caption', "")
            caption = caption_value if isinstance(caption_value, str) else ""

            # Extract hashtags from caption
            hashtags = re.findall(r'#(\w+)', caption)
            tags = ', '.join(hashtags) if hashtags else ""

            owner = self._safe_post_attr(post, 'owner_username', 'unknown') or 'unknown'
            typename = self._safe_post_attr(post, 'typename', 'Unknown') or 'Unknown'
            
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
                    self._run_with_retries(
                        lambda: self.loader.download_post(post, target=dir_name),
                        shortcode,
                        "Authenticated download",
                    )
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
            logger.error(error_msg, exc_info=True)
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
    
    def download_thumbnail(
        self,
        shortcode: str,
        target_path: Path,
        post_url: Optional[str] = None,
        local_media_path: Optional[str] = None,
    ) -> tuple:
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

        def _extract_from_local_file(source_file: Path):
            """Extract/create thumbnail from an existing local media file."""
            if not source_file or not source_file.exists():
                raise Exception("Local media file not found")

            logger.info(f"Using local media for thumbnail extraction: {source_file}")

            if source_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                img = Image.open(source_file)
                img.thumbnail((500, 500), Image.Resampling.LANCZOS)
                width, height = img.size

                target_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(target_path, 'JPEG', quality=85)
                logger.info(f"Thumbnail extracted from local image: {target_path} ({width}x{height})")
                return (True, (width, height))

            if source_file.suffix.lower() in ['.mp4', '.mov', '.m4v', '.avi', '.webm']:
                try:
                    import cv2
                    vidcap = cv2.VideoCapture(str(source_file))
                    success, image = vidcap.read()
                    vidcap.release()
                    if not success or image is None:
                        raise Exception("Could not decode first video frame")

                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(image_rgb)
                    img.thumbnail((500, 500), Image.Resampling.LANCZOS)
                    width, height = img.size

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    img.save(target_path, 'JPEG', quality=85)
                    logger.info(f"Thumbnail extracted from local video: {target_path} ({width}x{height})")
                    return (True, (width, height))
                except ImportError:
                    raise Exception("cv2 not available for local video thumbnail extraction")

            raise Exception(f"Unsupported local media type for thumbnail extraction: {source_file.suffix}")

        def _download_from_post_context(context, mode_label):
            """Fetch thumbnail URL via instaloader context and save image bytes."""
            post = instaloader.Post.from_shortcode(context, shortcode)
            thumbnail_url = post.url

            logger.info(f"Downloading thumbnail for {shortcode} from {thumbnail_url} ({mode_label})")
            response = requests.get(thumbnail_url, timeout=30)
            response.raise_for_status()

            img = Image.open(BytesIO(response.content))
            width, height = img.size

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Thumbnail saved: {target_path} ({width}x{height})")
            return (True, (width, height))

        def _download_from_page_meta(url: str, mode_label: str):
            """Fetch og:image from Instagram page HTML and save it as thumbnail."""
            if not url:
                raise Exception("No URL available for page-meta thumbnail lookup")

            session = None
            if self.logged_in and hasattr(self.loader, 'context') and hasattr(self.loader.context, '_session'):
                session = self.loader.context._session

            logger.info(f"Attempting page-meta thumbnail fetch for {shortcode} via {url} ({mode_label})")
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/126.0.0.0 Safari/537.36'
                )
            }

            if session is not None:
                page_resp = session.get(url, headers=headers, timeout=30)
            else:
                page_resp = requests.get(url, headers=headers, timeout=30)

            page_resp.raise_for_status()
            html_text = page_resp.text

            match = re.search(
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                html_text,
                re.IGNORECASE
            )
            if not match:
                match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                    html_text,
                    re.IGNORECASE
                )

            if not match:
                raise Exception("og:image not found in page HTML")

            thumbnail_url = html.unescape(match.group(1))
            if session is not None:
                img_resp = session.get(thumbnail_url, headers=headers, timeout=30)
            else:
                img_resp = requests.get(thumbnail_url, headers=headers, timeout=30)
            img_resp.raise_for_status()

            img = Image.open(BytesIO(img_resp.content))
            width, height = img.size

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'wb') as f:
                f.write(img_resp.content)

            logger.info(f"Thumbnail saved via page meta: {target_path} ({width}x{height})")
            return (True, (width, height))
        
        try:
            # Method 0: Prefer local media extraction when a known local file exists.
            if local_media_path:
                local_file = Path(local_media_path)
                if local_file.exists():
                    try:
                        return _extract_from_local_file(local_file)
                    except Exception as local_extract_err:
                        logger.debug(f"Local media thumbnail extraction failed for {shortcode}: {local_extract_err}")

            # Method 1: Try getting thumbnail from Instagram GraphQL contexts.
            graphql_allowed = time.time() >= self.thumbnail_graphql_block_until
            if graphql_allowed:
                graph_errors = []

                # Prefer authenticated first; anonymous often hits 403 earlier.
                if self.logged_in:
                    try:
                        result = _download_from_post_context(self.loader.context, "authenticated")
                        self.thumbnail_graphql_failures = 0
                        return result
                    except Exception as e:
                        graph_errors.append(e)
                        logger.debug(f"Authenticated thumbnail fetch failed for {shortcode}: {e}")

                try:
                    result = _download_from_post_context(self.anon_loader.context, "anonymous")
                    self.thumbnail_graphql_failures = 0
                    return result
                except instaloader.exceptions.LoginRequiredException:
                    logger.info(f"Thumbnail for {shortcode} requires login; anonymous mode rejected")
                except Exception as e:
                    graph_errors.append(e)
                    logger.debug(f"Anonymous thumbnail fetch failed for {shortcode}: {e}")

                if any('403' in str(err) or 'Forbidden' in str(err) for err in graph_errors):
                    self.thumbnail_graphql_failures += 1
                    cooldown_s = 900 if self.thumbnail_graphql_failures >= 1 else 300
                    self.thumbnail_graphql_block_until = time.time() + cooldown_s
                    logger.warning(
                        f"GraphQL thumbnail fetch received 403; pausing GraphQL thumbnail lookups for {cooldown_s}s"
                    )
            else:
                remaining = int(self.thumbnail_graphql_block_until - time.time())
                logger.info(f"GraphQL thumbnail lookup backoff active ({remaining}s remaining); using fallback methods")

            # Method 2: Try page HTML og:image extraction (no GraphQL).
            candidate_urls = []
            if post_url:
                candidate_urls.append(post_url)
            candidate_urls.append(f"https://www.instagram.com/p/{shortcode}/")
            candidate_urls.append(f"https://www.instagram.com/reel/{shortcode}/")

            seen = set()
            for url in candidate_urls:
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    return _download_from_page_meta(url, "page-meta")
                except Exception as e:
                    logger.debug(f"Page-meta thumbnail fetch failed for {shortcode} via {url}: {e}")

            # Method 3: Try to extract from downloaded files in the same directory
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
                    try:
                        return _extract_from_local_file(source_file)
                    except Exception as local_extract_err:
                        logger.debug(f"Could not extract thumbnail from local file {source_file}: {local_extract_err}")

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
            def _safe_value(name: str, default=None):
                """Read a Post property defensively because some fields can fail per post."""
                try:
                    return getattr(post, name)
                except Exception as field_error:
                    logger.debug(
                        f"Could not read post.{name} for {getattr(post, 'shortcode', 'unknown')}: {field_error}"
                    )
                    return default

            # Basic info (always available in most cases, but fetched defensively)
            shortcode = _safe_value('shortcode') or "unknown"
            typename = _safe_value('typename') or ""
            is_video = bool(_safe_value('is_video', False))

            result = {
                'shortcode': shortcode,
                'url': f"https://www.instagram.com/p/{shortcode}/" if shortcode != "unknown" else None,
                'owner_username': _safe_value('owner_username', ''),
                'typename': typename,  # GraphImage, GraphVideo, GraphSidecar
                'is_video': is_video,
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
                result['video_url'] = post.video_url if is_video else None
            except:
                result['video_url'] = None
            
            # Media count for carousels
            try:
                result['media_count'] = post.mediacount if typename == 'GraphSidecar' else 1
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
