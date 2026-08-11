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
        self.loader = self._create_loader()

        # Anonymous loader (used only for lightweight public probes/fallbacks)
        self.anon_loader = self._create_loader()
        
        self.username: Optional[str] = None
        self.logged_in = False
        self.session_file: Optional[Path] = None
        self.last_session_check: Optional[float] = None
        self.last_runtime_status: Dict[str, Any] = {
            'step': 'idle',
            'code': 'idle',
            'message': 'Idle',
            'recommendation': '',
            'username': None,
        }
        # Protect process-wide state used by instaloader download flow (os.chdir).
        self._download_lock = threading.Lock()
        # Backoff state for GraphQL thumbnail lookups when Instagram returns 403.
        self.thumbnail_graphql_block_until: float = 0.0
        self.thumbnail_graphql_failures: int = 0
        # Lightweight global cap to prevent bursty thumbnail network requests.
        self._thumbnail_request_semaphore = threading.BoundedSemaphore(value=2)
        # Thread-local thumbnail failure reason for UI diagnostics.
        self._thumbnail_thread_state = threading.local()

    def _set_last_thumbnail_failure_reason(self, reason: str):
        """Store per-thread thumbnail failure reason for GUI process diagnostics."""
        self._thumbnail_thread_state.thumbnail_failure_reason = str(reason or '')

    def get_last_thumbnail_failure_reason(self) -> str:
        """Read per-thread thumbnail failure reason set by download_thumbnail."""
        return str(getattr(self._thumbnail_thread_state, 'thumbnail_failure_reason', '') or '')

    def _classify_thumbnail_failure_reason(self, error: Exception | str) -> str:
        """Classify thumbnail failure reason into concise UI-friendly buckets."""
        msg = str(error).lower() if error is not None else ''
        if 'parse-miss' in msg or 'opengraph preview image not found' in msg or 'preview image url was empty' in msg:
            return 'parse-miss'
        if '403' in msg or 'forbidden' in msg:
            return '403'
        if 'timed out' in msg or 'timeout' in msg:
            return 'timeout'
        if 'cannot identify image file' in msg or 'decode-fail' in msg or 'truncated image' in msg:
            return 'decode-fail'
        return 'other'

    def _create_loader(self):
        """Create an Instaloader instance with app-standard settings."""
        return instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern='',
            max_connection_attempts=config.RETRY_ATTEMPTS,
            filename_pattern='{shortcode}'
        )

    def _set_runtime_status(self, step: str, code: str, message: str, recommendation: str = ''):
        """Record the latest high-level runtime state for UI diagnostics."""
        self.last_runtime_status = {
            'step': str(step),
            'code': str(code),
            'message': str(message),
            'recommendation': str(recommendation or ''),
            'username': self.username,
        }
        logger.info("InstagramManager status [%s/%s]: %s", step, code, message)

    def get_runtime_status(self) -> Dict[str, Any]:
        """Return the latest runtime status snapshot for the UI."""
        return dict(self.last_runtime_status)

    def _clear_login_state(self):
        """Clear active authenticated session state."""
        self.username = None
        self.logged_in = False
        self.session_file = None

    def _reset_authenticated_loader(self):
        """Reset authenticated loader after invalid session/login state."""
        self.loader = self._create_loader()
        self._clear_login_state()

    def _validate_authenticated_session(self, expected_username: Optional[str] = None) -> tuple[bool, str, Optional[str]]:
        """Validate the active authenticated Instaloader session."""
        try:
            resolved_username = self.loader.test_login()
        except Exception as e:
            return False, f"Session validation failed: {e}", None

        if not resolved_username:
            return False, "Session validation failed: Instaloader could not confirm a logged-in user.", None

        if expected_username and resolved_username.lower() != str(expected_username).strip().lower():
            return (
                False,
                f"Session belongs to @{resolved_username}, not @{expected_username}.",
                resolved_username,
            )

        self.username = resolved_username
        self.logged_in = True
        self.last_session_check = time.time()
        return True, f"Session validated for @{resolved_username}.", resolved_username

    def login_detailed(self, username: str, password: str, session_file: Optional[Path] = None) -> Dict[str, Any]:
        """Login and return a detailed result for UI diagnostics."""
        requested_username = str(username or '').strip()
        session_path = Path(session_file) if session_file else None

        try:
            if session_path and session_path.exists():
                self._set_runtime_status(
                    'loading_session',
                    'session_load_started',
                    f"Loading Instaloader session for @{requested_username} from {session_path.name}.",
                )
                self.loader.load_session_from_file(requested_username, str(session_path))
                self.session_file = session_path
                self._set_runtime_status(
                    'validating_session',
                    'session_validation_started',
                    f"Validating session for @{requested_username}.",
                )
                ok, message, resolved_username = self._validate_authenticated_session(requested_username)
                if ok:
                    self.session_file = session_path
                    self._set_runtime_status('session_valid', 'session_valid', message)
                    return {
                        'success': True,
                        'message': message,
                        'ig_username': resolved_username,
                        'step': 'session_valid',
                        'code': 'session_valid',
                    }

                recommendation = 'Refresh cookies from your browser and recreate the session.'
                self._reset_authenticated_loader()
                self._set_runtime_status('session_invalid', 'session_invalid', message, recommendation)
                return {
                    'success': False,
                    'message': message,
                    'ig_username': resolved_username,
                    'step': 'session_invalid',
                    'code': 'session_invalid',
                    'recommendation': recommendation,
                }

            if not requested_username or not password:
                message = 'Username and password are required when no valid session file is available.'
                self._set_runtime_status('login_blocked', 'missing_credentials', message)
                return {
                    'success': False,
                    'message': message,
                    'ig_username': None,
                    'step': 'login_blocked',
                    'code': 'missing_credentials',
                }

            self._set_runtime_status('logging_in', 'password_login_started', f"Logging in as @{requested_username}.")
            self.loader.login(requested_username, password)
            ok, message, resolved_username = self._validate_authenticated_session(requested_username)
            if not ok:
                recommendation = 'Try importing browser cookies instead of password login.'
                self._reset_authenticated_loader()
                self._set_runtime_status('login_failed', 'session_validation_failed', message, recommendation)
                return {
                    'success': False,
                    'message': message,
                    'ig_username': resolved_username,
                    'step': 'login_failed',
                    'code': 'session_validation_failed',
                    'recommendation': recommendation,
                }

            if session_path:
                session_path.parent.mkdir(parents=True, exist_ok=True)
                self.loader.save_session_to_file(str(session_path))
                self.session_file = session_path
                logger.info("Session saved to %s", session_path)

            self._set_runtime_status('session_valid', 'login_success', message)
            return {
                'success': True,
                'message': message,
                'ig_username': resolved_username,
                'step': 'session_valid',
                'code': 'login_success',
            }

        except instaloader.exceptions.BadCredentialsException:
            message = 'Invalid Instagram username or password.'
            self._reset_authenticated_loader()
            self._set_runtime_status('login_failed', 'bad_credentials', message, 'Check credentials or use browser cookie import.')
            return {
                'success': False,
                'message': message,
                'ig_username': None,
                'step': 'login_failed',
                'code': 'bad_credentials',
                'recommendation': 'Check credentials or use browser cookie import.',
            }
        except instaloader.exceptions.TwoFactorAuthRequiredException:
            message = 'Two-factor authentication is required and is not implemented in this flow.'
            self._reset_authenticated_loader()
            self._set_runtime_status('login_failed', 'two_factor_required', message, 'Import a browser session instead.')
            return {
                'success': False,
                'message': message,
                'ig_username': None,
                'step': 'login_failed',
                'code': 'two_factor_required',
                'recommendation': 'Import a browser session instead.',
            }
        except instaloader.exceptions.ConnectionException as e:
            message = f'Instagram connection error: {e}'
            self._reset_authenticated_loader()
            self._set_runtime_status('login_failed', 'connection_error', message, 'Retry later or refresh browser cookies.')
            return {
                'success': False,
                'message': message,
                'ig_username': None,
                'step': 'login_failed',
                'code': 'connection_error',
                'recommendation': 'Retry later or refresh browser cookies.',
            }
        except Exception as e:
            message = f'Login failed: {e}'
            self._reset_authenticated_loader()
            self._set_runtime_status('login_failed', 'unexpected_login_error', message, 'Inspect logs and validate the session source.')
            return {
                'success': False,
                'message': message,
                'ig_username': None,
                'step': 'login_failed',
                'code': 'unexpected_login_error',
                'recommendation': 'Inspect logs and validate the session source.',
            }
    
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
        result = self.login_detailed(username, password, session_file)
        return bool(result.get('success'))

    def import_session_from_cookies(self, expected_username: str, cookie_source: Any, session_file: Path) -> Dict[str, Any]:
        """Create and validate an Instaloader-native session from browser cookies."""
        expected_username = str(expected_username or '').strip()
        session_path = Path(session_file)
        session_path.parent.mkdir(parents=True, exist_ok=True)

        self._set_runtime_status(
            'importing_cookies',
            'cookie_import_started',
            f"Importing browser cookies for @{expected_username or 'unknown'}.",
        )

        try:
            temp_loader = self._create_loader()
            if isinstance(cookie_source, dict):
                cookie_dict = {str(key): str(value) for key, value in cookie_source.items() if value is not None}
                temp_loader.context._session.cookies.update(cookie_dict)
            else:
                cookie_dict = {}
                temp_loader.context._session.cookies.update(cookie_source)
                cookie_dict = temp_loader.context._session.cookies.get_dict().copy()

            if not cookie_dict.get('sessionid') or not cookie_dict.get('csrftoken'):
                message = 'Browser cookies are missing required Instagram session cookies (sessionid/csrftoken).'
                self._set_runtime_status('session_invalid', 'missing_required_cookies', message, 'Export fresh instagram.com cookies and retry.')
                return {
                    'success': False,
                    'message': message,
                    'ig_username': None,
                    'step': 'session_invalid',
                    'code': 'missing_required_cookies',
                    'recommendation': 'Export fresh instagram.com cookies and retry.',
                }

            if cookie_dict.get('csrftoken'):
                temp_loader.context._session.headers.update({'X-CSRFToken': cookie_dict['csrftoken']})

            resolved_username = temp_loader.test_login()
            if not resolved_username:
                message = 'Cookie import failed: Instaloader could not validate a logged-in Instagram user from the provided cookies.'
                self._set_runtime_status('session_invalid', 'cookie_validation_failed', message, 'Refresh browser cookies and make sure you are logged into Instagram.')
                return {
                    'success': False,
                    'message': message,
                    'ig_username': None,
                    'step': 'session_invalid',
                    'code': 'cookie_validation_failed',
                    'recommendation': 'Refresh browser cookies and make sure you are logged into Instagram.',
                }

            temp_loader.context.username = resolved_username
            temp_loader.save_session_to_file(str(session_path))

            self.loader = temp_loader
            self.username = resolved_username
            self.logged_in = True
            self.session_file = session_path
            self.last_session_check = time.time()

            if expected_username and resolved_username.lower() != expected_username.lower():
                message = f"Cookies validated for @{resolved_username}. Updated account username from @{expected_username}."
                code = 'cookie_username_mismatch'
            else:
                message = f"Browser cookies validated and session saved for @{resolved_username}."
                code = 'cookie_import_success'

            self._set_runtime_status('session_valid', code, message)
            return {
                'success': True,
                'message': message,
                'ig_username': resolved_username,
                'step': 'session_valid',
                'code': code,
            }

        except Exception as e:
            message = f'Cookie import failed: {e}'
            self._set_runtime_status('session_invalid', 'cookie_import_error', message, 'Use fresh browser cookies and retry.')
            return {
                'success': False,
                'message': message,
                'ig_username': None,
                'step': 'session_invalid',
                'code': 'cookie_import_error',
                'recommendation': 'Use fresh browser cookies and retry.',
            }
    
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
            self._set_runtime_status('validating_session', 'session_validation_started', f"Validating session for @{self.username or 'unknown'}.")
            ok, message, resolved_username = self._validate_authenticated_session(self.username)
            if ok:
                self._set_runtime_status('session_valid', 'session_valid', message)
                return True, message
            self._set_runtime_status('session_invalid', 'session_invalid', message, 'Refresh browser cookies and retry.')
            if resolved_username and not self.username:
                self.username = resolved_username
            return False, message
        except instaloader.exceptions.BadResponseException:
            return False, "Session expired - cookies are no longer valid"
        except instaloader.exceptions.ConnectionException as e:
            return False, f"Connection error: {str(e)}"
        except Exception as e:
            return False, f"Session test failed: {str(e)}"

    def resolve_post_authenticated(self, shortcode: str) -> instaloader.Post:
        """Resolve a post shortcode with the authenticated loader only."""
        if not self.logged_in:
            raise RuntimeError('A valid authenticated Instagram session is required before resolving a post.')

        shortcode = str(shortcode or '').strip()
        self._set_runtime_status('resolving_post', 'post_resolution_started', f"Resolving Instagram post {shortcode} with authenticated session.")

        post = self._get_post_with_fallback(shortcode, authenticated=True)
        owner = self._safe_post_attr(post, 'owner_username', 'unknown') or 'unknown'
        typename = self._safe_post_attr(post, 'typename', 'Unknown') or 'Unknown'
        self._set_runtime_status('post_resolved', 'post_resolved', f"Resolved {shortcode} as {typename} by @{owner}.")
        return post
    
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

        thumbnail_fetch_markers = [
            "parse-miss",
            "decode-fail",
            "cannot identify image file",
            "timeout:",
            "timed out",
            "thumbnail fetch",
            "opengraph preview image",
        ]
        if any(marker in msg for marker in thumbnail_fetch_markers):
            # Thumbnail retrieval failures are usually rate-limit/challenge/CDN gating
            # when anonymous endpoints return HTML/non-image payloads.
            return "rate_limit_gating_issue"

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

    def _extract_opengraph_media(self, shortcode: str) -> Optional[Dict[str, Any]]:
        """Extract public media URLs from Instagram post HTML OpenGraph tags."""
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        def _decode_candidate_url(raw_url: str) -> str:
            value = str(raw_url or '').strip()
            if not value:
                return ''
            try:
                value = value.encode('utf-8').decode('unicode_escape')
            except Exception:
                pass
            value = html.unescape(value)
            value = value.replace('\\/', '/').replace('\\u0026', '&').strip()
            return value

        def _extract_ranked_image_candidates(*html_chunks: str) -> List[str]:
            """Find and score image URLs embedded in page payloads.

            Prefer non-cropped variants and larger dimensions when available.
            """
            all_candidates: List[str] = []
            patterns = [
                r'\\"display_url\\"\s*:\s*\\"([^\\\"]+)\\"',
                r'\\"thumbnail_src\\"\s*:\s*\\"([^\\\"]+)\\"',
                r'\\"image_url\\"\s*:\s*\\"([^\\\"]+)\\"',
                r'\\"src\\"\s*:\s*\\"([^\\\"]+)\\"',
                r'"display_url"\s*:\s*"([^"]+)"',
                r'"thumbnail_src"\s*:\s*"([^"]+)"',
                r'"image_url"\s*:\s*"([^"]+)"',
                r'"src"\s*:\s*"([^"]+)"',
            ]

            for chunk in html_chunks:
                if not chunk:
                    continue
                for pattern in patterns:
                    try:
                        for match in re.findall(pattern, chunk, flags=re.IGNORECASE):
                            decoded = _decode_candidate_url(match)
                            lowered = decoded.lower()
                            if decoded.startswith('http') and (
                                'cdninstagram.com' in lowered
                                or 'fbcdn.net' in lowered
                                or 'instagram.' in lowered
                            ):
                                all_candidates.append(decoded)
                    except Exception:
                        continue

            if not all_candidates:
                return []

            def _score(url: str) -> int:
                score = 0
                lowered = url.lower()

                # Favor URLs that look like full media variants.
                if 'display' in lowered:
                    score += 4
                if 'p1080x1080' in lowered or 's1080x1080' in lowered:
                    score += 6
                elif 'p750x750' in lowered or 's750x750' in lowered:
                    score += 4
                elif 'p640x640' in lowered or 's640x640' in lowered:
                    score += 2

                # Prefer non-square dimensions that often preserve full framing.
                if re.search(r'(?:p|s)(?:1080|750|640)x(?:1350|1440|1920)', lowered):
                    score += 8

                # Penalize explicitly cropped transforms like stp=c288.0.864.864a
                if 'stp=c' in lowered or '/stp/c' in lowered:
                    score -= 14

                # Favor fit transforms over crop transforms when present.
                if 'stp=dst-jpg' in lowered or '/stp/dst-jpg' in lowered:
                    score += 3

                # Slightly favor larger query payload URLs (often richer transforms).
                score += min(4, len(url) // 150)
                return score

            unique = list(dict.fromkeys(all_candidates))
            return sorted(unique, key=_score, reverse=True)

        page_candidates = [
            f"https://www.instagram.com/p/{shortcode}/",
            f"https://www.instagram.com/reel/{shortcode}/",
        ]

        for page_url in page_candidates:
            try:
                response = requests.get(page_url, headers=headers, timeout=15)
            except Exception as e:
                logger.debug(f"OpenGraph fetch failed for {shortcode} via {page_url}: {e}")
                continue

            if int(response.status_code) != 200:
                logger.debug(f"OpenGraph fetch returned HTTP {response.status_code} for {shortcode} via {page_url}")
                continue

            html_text = response.text or ''

            def _meta_content(prop_name: str) -> str:
                pattern = rf'<meta[^>]+property="{prop_name}"[^>]+content="([^"]*)"'
                match = re.search(pattern, html_text, flags=re.IGNORECASE)
                return html.unescape(match.group(1)).strip() if match else ''

            image_url = _meta_content('og:image')
            video_url = _meta_content('og:video')
            description = _meta_content('og:description')
            is_video_hint = False
            payload_image_url = ''
            image_candidates: List[str] = []

            embed_url = page_url.rstrip('/') + '/embed/captioned/'
            embed_html = ''

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
                logger.debug(f"Embed OpenGraph fetch failed for {shortcode} via {embed_url}: {e}")

            # Prefer richer page payload image URLs over og:image when available.
            payload_candidates = _extract_ranked_image_candidates(html_text, embed_html)
            if payload_candidates:
                image_candidates.extend(payload_candidates)
                payload_image_url = payload_candidates[0]
                image_url = payload_image_url
                logger.debug(
                    "OpenGraph thumbnail source for %s selected payload candidate: %s",
                    shortcode,
                    payload_image_url[:220],
                )
            elif image_url:
                logger.debug(
                    "OpenGraph thumbnail source for %s using og:image fallback: %s",
                    shortcode,
                    image_url[:220],
                )

            if image_url and image_url not in image_candidates:
                image_candidates.append(image_url)

            if image_url or video_url:
                return {
                    'image_url': image_url,
                    'image_candidates': image_candidates,
                    'video_url': video_url,
                    'description': description,
                    'page_url': page_url,
                    'is_video_hint': 'true' if is_video_hint else 'false',
                }

        return None

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
        
        # Try anonymous first for public content (reduces rate limiting on authenticated session)
        try:
            self._set_runtime_status('resolving_post', 'download_started', f"Attempting anonymous download for {shortcode}")
            return self._download_post_anonymous(shortcode, target_dir)
        except instaloader.exceptions.LoginRequiredException:
            # Post is private - use authenticated session
            logger.info(f"Post {shortcode} requires authentication, using logged-in session")
            self._set_runtime_status('resolving_post', 'download_retry_auth', f"Retrying with authentication for {shortcode}")
            return self._download_post_authenticated(shortcode, target_dir)
    
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
            post = self.resolve_post_authenticated(shortcode) if self.logged_in else self._get_post_with_fallback(shortcode, authenticated=False)
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

        def _build_image_request_headers(page_url: str = '') -> Dict[str, str]:
            lang = random.choice(['en-US,en;q=0.9', 'en-US,en;q=0.8', 'en;q=0.9'])
            headers = {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/126.0.0.0 Safari/537.36'
                ),
                'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': lang,
                'DNT': random.choice(['1', '0']),
            }
            if page_url:
                headers['Referer'] = page_url
            return headers

        def _retry_delay(attempt: int, base_min: float = 0.9, base_max: float = 1.8) -> float:
            return min(8.0, random.uniform(base_min, base_max) + (attempt * 0.7))

        def _build_cropless_thumbnail_url(url: str) -> str:
            value = str(url or '').strip()
            if not value:
                return ''

            # Remove explicit crop transform query token.
            value = re.sub(r'([?&])stp=c[^&]*&?', r'\1', value, flags=re.IGNORECASE)
            # Remove explicit crop transform path token.
            value = re.sub(r'/stp/c[^/]+/', '/', value, flags=re.IGNORECASE)

            # Normalize separators after query edits.
            value = value.replace('?&', '?')
            value = re.sub(r'[?&]$', '', value)
            value = re.sub(r'&&+', '&', value)
            return value

        def _fetch_image_bytes_with_retries(
            image_url: str,
            headers: Optional[Dict[str, str]],
            mode_label: str,
            max_attempts: int = 3,
            page_url: str = '',
            session: Optional[requests.Session] = None,
        ) -> bytes:
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    request_headers = dict(headers or _build_image_request_headers(page_url))
                    if page_url and 'Referer' not in request_headers:
                        request_headers['Referer'] = page_url

                    http_client = session if session is not None else requests
                    response = http_client.get(image_url, headers=request_headers, timeout=30)
                    response.raise_for_status()

                    final_url = str(response.url or '').lower()
                    if '/accounts/login' in final_url or '/challenge/' in final_url:
                        raise Exception(f"403: challenge/login interstitial for thumbnail URL ({mode_label})")

                    content_type = str(response.headers.get('Content-Type') or '').lower()
                    body_head_bytes = (response.content or b'')[:1024]
                    body_head_text = body_head_bytes.decode('utf-8', errors='ignore').lower()

                    if body_head_text.startswith('<!doctype html') or '<html' in body_head_text:
                        raise Exception(
                            f"decode-fail: html response for thumbnail URL content-type={content_type or 'unknown'} ({mode_label})"
                        )

                    if content_type and not content_type.startswith('image/'):
                        # Instagram sometimes returns HTML/challenge content for blocked anonymous requests.
                        if '<html' in body_head_text or 'instagram' in body_head_text:
                            raise Exception(
                                f"decode-fail: non-image content-type={content_type} ({mode_label})"
                            )

                    # Validate image decodability before writing to disk.
                    with Image.open(BytesIO(response.content)) as img:
                        img.load()

                    return response.content
                except Exception as e:
                    last_error = e
                    error_text = str(e).lower()
                    non_retry_markers = [
                        'challenge/login interstitial',
                        'decode-fail: non-image content-type',
                        'decode-fail: html response',
                        'cannot identify image file',
                        '403:',
                    ]
                    if any(marker in error_text for marker in non_retry_markers):
                        break
                    if attempt >= max_attempts:
                        break
                    delay = _retry_delay(attempt)
                    logger.warning(
                        f"Thumbnail fetch retry for {shortcode} ({mode_label}) attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)

            if last_error is not None:
                raise last_error
            raise Exception(f"Thumbnail fetch failed with unknown error ({mode_label})")

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
            page_url = f"https://www.instagram.com/p/{shortcode}/"
            headers = _build_image_request_headers(page_url)
            image_bytes = _fetch_image_bytes_with_retries(
                thumbnail_url,
                headers=headers,
                mode_label=f"{mode_label}-graphql-image",
                max_attempts=3,
                page_url=page_url,
            )

            img = Image.open(BytesIO(image_bytes))
            width, height = img.size

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'wb') as f:
                f.write(image_bytes)

            logger.info(f"Thumbnail saved: {target_path} ({width}x{height})")
            return (True, (width, height))

        def _download_from_opengraph(shortcode_value: str, mode_label: str):
            """Fetch preview image anonymously from resilient OpenGraph extraction."""
            og = self._extract_opengraph_media(shortcode_value)
            if not og:
                raise Exception("parse-miss: OpenGraph preview image not found in public Instagram HTML")

            page_url = og.get('page_url') or f"https://www.instagram.com/p/{shortcode_value}/"
            logger.info(f"Attempting OpenGraph thumbnail fetch for {shortcode_value} via {page_url} ({mode_label})")

            thumbnail_url = str(og.get('image_url') or '').strip()
            if not thumbnail_url:
                raise Exception("parse-miss: OpenGraph preview image URL was empty")

            headers = _build_image_request_headers(page_url)
            image_bytes = None
            last_error = None
            session = requests.Session()

            # Warm-up anonymous page session so image CDN requests carry related cookies.
            try:
                session.get(page_url, headers=_build_image_request_headers(page_url), timeout=15)
                embed_url = page_url.rstrip('/') + '/embed/captioned/'
                session.get(embed_url, headers=_build_image_request_headers(page_url), timeout=15)
            except Exception as warm_err:
                logger.debug(f"Anonymous thumbnail session warm-up failed for {shortcode_value}: {warm_err}")

            ranked_candidates = [url for url in (og.get('image_candidates') or []) if str(url).strip()]
            if thumbnail_url not in ranked_candidates:
                ranked_candidates.insert(0, thumbnail_url)

            candidate_urls: List[str] = []
            for candidate in ranked_candidates[:4]:
                candidate_urls.append(candidate)
                cropped_fallback_url = _build_cropless_thumbnail_url(candidate)
                if cropped_fallback_url and cropped_fallback_url != candidate:
                    candidate_urls.append(cropped_fallback_url)

            unique_candidate_urls = list(dict.fromkeys([u for u in candidate_urls if u]))

            for index, candidate_url in enumerate(unique_candidate_urls, start=1):
                try:
                    logger.debug(
                        "OpenGraph thumbnail candidate %s/%s for %s: %s",
                        index,
                        len(unique_candidate_urls),
                        shortcode_value,
                        candidate_url[:220],
                    )
                    image_bytes = _fetch_image_bytes_with_retries(
                        candidate_url,
                        headers=headers,
                        mode_label=f"{mode_label}-candidate-{index}",
                        max_attempts=2,
                        page_url=page_url,
                        session=session,
                    )
                    if image_bytes:
                        break
                except Exception as e:
                    last_error = e
                    continue

            if image_bytes is None:
                if last_error is not None:
                    raise last_error
                raise Exception("decode-fail: OpenGraph image download returned empty payload")

            img = Image.open(BytesIO(image_bytes))
            width, height = img.size

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, 'wb') as f:
                f.write(image_bytes)

            logger.info(f"Thumbnail saved via page meta: {target_path} ({width}x{height})")
            return (True, (width, height))
        
        try:
            self._set_last_thumbnail_failure_reason('')
            skip_graphql_after_opengraph = False
            opengraph_failure_text = ''

            # Method 0: Prefer local media extraction when a known local file exists.
            if local_media_path:
                local_file = Path(local_media_path)
                if local_file.exists():
                    try:
                        return _extract_from_local_file(local_file)
                    except Exception as local_extract_err:
                        logger.debug(f"Local media thumbnail extraction failed for {shortcode}: {local_extract_err}")

            network_slot_acquired = self._thumbnail_request_semaphore.acquire(timeout=20)
            if not network_slot_acquired:
                raise Exception("timeout: waiting for thumbnail request slot")

            # Method 1: Prefer anonymous HTML OpenGraph extraction. This is the
            # least invasive network path and does not rely on a logged-in session.
            try:
                return _download_from_opengraph(shortcode, "opengraph-anonymous")
            except Exception as e:
                logger.debug(f"Anonymous OpenGraph thumbnail fetch failed for {shortcode}: {e}")
                opengraph_failure_text = str(e or '')
                opengraph_error_text = str(e).lower()
                if (
                    'decode-fail: html response' in opengraph_error_text
                    or 'challenge/login interstitial' in opengraph_error_text
                    or 'decode-fail: non-image content-type' in opengraph_error_text
                    or '403:' in opengraph_error_text
                ):
                    skip_graphql_after_opengraph = True
                    self.thumbnail_graphql_block_until = max(self.thumbnail_graphql_block_until, time.time() + 300)
                    logger.info(
                        f"Skipping anonymous GraphQL thumbnail fallback for {shortcode}: OpenGraph indicates gating/challenge"
                    )

            # Method 2: Cookie/session-backed fallback (no password prompt).
            # If an authenticated/cookie session is already active, use it before
            # hitting anonymous GraphQL fallback paths.
            if self.logged_in:
                try:
                    logger.info(f"Trying cookie-session thumbnail fallback for {shortcode}")
                    result = _download_from_post_context(self.loader.context, "cookie-session")
                    return result
                except Exception as e:
                    logger.debug(f"Cookie-session thumbnail fallback failed for {shortcode}: {e}")
                    if self.classify_failure_category(e) == 'auth_session_issue':
                        logger.info(
                            f"Cookie-session thumbnail fallback for {shortcode} failed due to auth/session issue; "
                            "continuing with anonymous fallbacks without prompting for password"
                        )

            # Method 3: Try anonymous Instaloader GraphQL context.
            graphql_allowed = (time.time() >= self.thumbnail_graphql_block_until) and not skip_graphql_after_opengraph
            if graphql_allowed:
                graph_errors = []
                opengraph_parse_miss = 'parse-miss' in opengraph_failure_text.lower()
                max_graphql_attempts = 1 if opengraph_parse_miss else 3
                if opengraph_parse_miss:
                    logger.info(
                        f"OpenGraph parse-miss for {shortcode}; limiting anonymous GraphQL thumbnail fallback to {max_graphql_attempts} attempt"
                    )

                for attempt in range(1, max_graphql_attempts + 1):
                    try:
                        result = _download_from_post_context(self.anon_loader.context, f"anonymous-attempt-{attempt}")
                        self.thumbnail_graphql_failures = 0
                        return result
                    except instaloader.exceptions.LoginRequiredException:
                        logger.info(f"Thumbnail for {shortcode} requires login; anonymous mode rejected")
                        break
                    except Exception as e:
                        graph_errors.append(e)
                        logger.debug(f"Anonymous thumbnail fetch failed for {shortcode} attempt {attempt}: {e}")
                        category = self.classify_failure_category(e)
                        if category == 'rate_limit_gating_issue':
                            logger.info(
                                f"Anonymous GraphQL thumbnail fallback for {shortcode} hit rate-limit/gating; stopping retries"
                            )
                            break
                        if attempt < max_graphql_attempts:
                            delay = _retry_delay(attempt, base_min=1.2, base_max=2.6)
                            time.sleep(delay)

                if any(
                    ('403' in str(err) or 'Forbidden' in str(err) or self.classify_failure_category(err) == 'rate_limit_gating_issue')
                    for err in graph_errors
                ):
                    self.thumbnail_graphql_failures += 1
                    cooldown_s = 900 if self.thumbnail_graphql_failures >= 1 else 300
                    self.thumbnail_graphql_block_until = time.time() + cooldown_s
                    logger.warning(
                        f"GraphQL thumbnail fetch received 403; pausing GraphQL thumbnail lookups for {cooldown_s}s"
                    )
            else:
                remaining = int(self.thumbnail_graphql_block_until - time.time())
                logger.info(f"Anonymous GraphQL thumbnail lookup backoff active ({remaining}s remaining); using local fallbacks")

            # Method 4: Try to extract from downloaded files in the same directory
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
            raise Exception("parse-miss: Could not fetch thumbnail from Instagram or extract from local files")
        
        except Exception as e:
            self._set_last_thumbnail_failure_reason(self._classify_thumbnail_failure_reason(e))
            logger.error(f"Failed to download thumbnail for {shortcode}: {e}")
            return (False, None)
        finally:
            if 'network_slot_acquired' in locals() and network_slot_acquired:
                try:
                    self._thumbnail_request_semaphore.release()
                except ValueError:
                    pass
    
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
            
            # Avoid triggering extra GraphQL video metadata calls during list ingest.
            # `video_url` is not required for browse rows and can emit noisy warnings
            # for otherwise valid saved posts when Instagram gates metadata endpoints.
            result['video_url'] = None
            if fetch_full_metadata and is_video:
                try:
                    result['video_url'] = post.video_url
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
