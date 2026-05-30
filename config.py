"""
Configuration constants for Instagram Downloader
"""
from pathlib import Path

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

def ensure_directories():
    """Create necessary directories if they don't exist"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
