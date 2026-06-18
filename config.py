"""
Configuration constants for Instagram Downloader
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Application info
APP_NAME = "Instagram Downloader"
APP_VERSION = "2.0.0"
APP_AUTHOR = "Clean Rewrite"

# Directory structure
DATA_DIR = Path.home() / '.instagram-downloader'
SESSIONS_DIR = DATA_DIR / 'sessions'

# Download settings
DEFAULT_DOWNLOAD_DIR = Path.home() / 'Downloads' / 'Instagram'
DEFAULT_QUALITY = 'high'  # high, medium, low (affects video compression)
MAX_CONCURRENT_DOWNLOADS = 3
CHUNK_SIZE = 8192  # bytes per chunk when downloading

# Rate limiting (instaloader handles this, but we can configure)
MAX_POSTS_PER_REQUEST = 50
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5  # seconds

# UI settings
THUMBNAIL_SIZE = (200, 200)
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 800
PREVIEW_SIZE = (400, 400)

# Logging
LOG_FILE = DATA_DIR / 'app.log'
LOG_LEVEL = 'INFO'  # DEBUG, INFO, WARNING, ERROR

# Database schema version (for migrations)
DB_VERSION = 1

# Soccr API client environment modes
SOCCR_API_CLIENT_MODES = ('off', 'dev', 'prod')
SOCCR_API_CLIENT_HOSTS = {
    'dev': 'http://localhost:1761',
    'prod': 'https://www.soccr.org'
}


def normalize_soccr_api_client_mode(mode):
    """Normalize Soccr API mode to one of: off, dev, prod."""
    normalized = (mode or 'dev').strip().lower()
    if normalized not in SOCCR_API_CLIENT_MODES:
        return 'dev'
    return normalized


def get_soccr_api_client_host(mode):
    """Resolve configured Soccr API host for a mode; returns None when off."""
    normalized = normalize_soccr_api_client_mode(mode)
    if normalized == 'off':
        return None
    return SOCCR_API_CLIENT_HOSTS[normalized]


def create_soccr_api_client_configuration(mode):
    """Create soccr_api_client Configuration for current mode, or None when off."""
    host = get_soccr_api_client_host(mode)
    if not host:
        return None

    try:
        from soccr_api_client.configuration import Configuration
    except ImportError as exc:
        raise RuntimeError(
            "soccr_api_client is not installed. Install with: pip install -e <path-to-qs.api.client.soccr.io.python>"
        ) from exc

    logger.info("Using soccr_api_client host: %s", host)
    return Configuration(host=host)

def ensure_directories():
    """Create necessary directories if they don't exist"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
