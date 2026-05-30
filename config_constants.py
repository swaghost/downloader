# Configuration constants for main.py
import os

# Directory for configuration files
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Configuration')

# Media URL Acquisition Strategies
# These are the methods used to extract media CDN URLs from Instagram posts
ACQUISITION_STRATEGIES = {
    'CDP_NETWORK_CAPTURE': 'CDP Network Traffic Capture',
    'META_TAG_EXTRACTION': 'Meta Tag Extraction (og:video/og:image)',
    'META_TAG_EXTRACTION_AUTHENTICATED': 'Meta Tag Extraction (Authenticated)',
    'JSON_PARSING': 'JSON Data Parsing from Page Source',
    'DOM_ELEMENT_EXTRACTION': 'DOM Element Extraction',
    'DIRECT_API': 'Direct API Request (future)',
    'FALLBACK_MANUAL': 'Manual Entry/Fallback',
}

# Strategy execution order (priority)
STRATEGY_EXECUTION_ORDER = [
    'CDP_NETWORK_CAPTURE',
    'META_TAG_EXTRACTION',
    'JSON_PARSING',
    'DOM_ELEMENT_EXTRACTION',
]

# ============================================================================
# DATABASE CONFIGURATION - SQL Server Only
# ============================================================================

# Try to load local configuration first (not in version control)
# If config_local.py doesn't exist, use default values
try:
    from config_local import SQL_SERVER_CONFIG, DEFAULT_ACCOUNT_NAME
except ImportError:
    # Default configuration (for new installations)
    # COPY config_local.example.py to config_local.py and update with your credentials
    SQL_SERVER_CONFIG = {
        'server': 'localhost',
        'database': 'DOWNLOAD-SYSTEM',
        'username': 'YOUR_USERNAME',  # Update in config_local.py
        'password': 'YOUR_PASSWORD',  # Update in config_local.py
        'schema': 'DL'
    }
    
    # Default account name for multi-account support
    DEFAULT_ACCOUNT_NAME = 'your_instagram_username'  # Update in config_local.py
    
    print("⚠️  WARNING: Using default database config. Copy config_local.example.py to config_local.py and update credentials.")
