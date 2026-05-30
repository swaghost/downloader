# Instagram Downloader - Clean Architecture

## Design Philosophy

**Simplicity over features. Reliability over complexity.**

- Use `instaloader` library (actively maintained, handles Instagram API changes)
- Simple PyQt5 GUI for user experience
- Modular design: each file < 500 lines
- SQLite for minimal state storage
- No web scraping, no Selenium, no CDP network capture

## File Structure

```
instagram-downloader/
├── main.py                    # Entry point (50 lines)
├── gui.py                     # PyQt5 interface (400 lines)
├── instagram_manager.py       # Instaloader wrapper (250 lines)
├── account_manager.py         # Account persistence (150 lines)
├── config.py                  # Constants (50 lines)
├── requirements.txt           # Dependencies (6 packages)
├── README.md                  # Usage guide
└── data/                      # User data directory
    ├── accounts.db            # SQLite: accounts, settings
    └── {username}/            # Per-account downloads
        └── saved/             # Saved posts
```

**Total: ~900 lines of clean, focused code**

## Module Responsibilities

### 1. main.py

- Parse command line arguments
- Initialize application
- Launch GUI or CLI mode
- Handle graceful shutdown

### 2. gui.py (PyQt5)

**Tabs:**

- **Accounts** - Login, switch accounts, view status
- **Browse** - View saved posts (thumbnails, captions)
- **Download** - Queue management, progress bars
- **Settings** - Download location, quality preferences

**Key Features:**

- Async operations (don't freeze UI)
- Progress tracking
- Error handling with user-friendly messages
- Clean, intuitive layout

### 3. instagram_manager.py

**Wraps instaloader library:**

```python
class InstagramManager:
    def login(username, password)
    def get_saved_posts()
    def download_post(post, path)
    def get_post_metadata(post)
```

**Handles:**

- Session management
- Two-factor authentication
- Rate limiting (built into instaloader)
- Download retries
- Metadata extraction

### 4. account_manager.py

**Simple persistence:**

```python
class AccountManager:
    def save_account(username, session_file)
    def load_account(username)
    def list_accounts()
    def delete_account(username)
```

**SQLite schema:**

```sql
CREATE TABLE accounts (
    username TEXT PRIMARY KEY,
    session_file TEXT,
    last_login TIMESTAMP,
    download_path TEXT
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

### 5. config.py

```python
# Directories
DATA_DIR = Path.home() / '.instagram-downloader'
ACCOUNTS_DB = DATA_DIR / 'accounts.db'

# Download settings
DEFAULT_QUALITY = 'high'  # high, medium, low
MAX_CONCURRENT_DOWNLOADS = 3
CHUNK_SIZE = 8192

# UI settings
THUMBNAIL_SIZE = (200, 200)
WINDOW_TITLE = "Instagram Downloader"
```

## Key Differences from Old Implementation

| Old                     | New                   |
| ----------------------- | --------------------- |
| 5,600-line files        | < 500 lines per file  |
| Custom Selenium scraper | `instaloader` library |
| CDP network capture     | API calls             |
| Manual segment merging  | Built-in handling     |
| 130 debug scripts       | Zero debug scripts    |
| SQL Server + SQLite     | SQLite only           |
| Complex validation      | Simple, reliable      |
| 39 fix documents        | Clean from start      |
| 10 MB codebase          | < 100 KB              |

## Dependencies

```txt
instaloader==4.10.3      # Instagram API client
PyQt5==5.15.10           # GUI framework
Pillow==10.2.0           # Image handling
requests==2.31.0         # HTTP (instaloader dependency)
```

**That's it. 4 dependencies.**

## What We're NOT Doing

❌ Selenium/Chrome automation  
❌ Network packet capture  
❌ Manual video segment downloading  
❌ Audio/video merging  
❌ Complex CDN URL extraction  
❌ Multiple database backends  
❌ HTML parsing with BeautifulSoup  
❌ Manual cookie management  
❌ Custom retry logic  
❌ Fingerprint avoidance

**We let `instaloader` handle all Instagram complexity.**

## Development Timeline

**Day 1 (4 hours):**

- Core modules (config, account_manager, instagram_manager)
- Basic CLI functionality
- Test login and download

**Day 2 (4 hours):**

- PyQt5 GUI implementation
- Polish and error handling
- Documentation

**Total: 8 hours to working application**

## Success Criteria

✅ Login with Instagram credentials  
✅ View saved posts  
✅ Download posts (images, videos, carousels)  
✅ Switch between accounts  
✅ Preserve sessions (stay logged in)  
✅ Clean UI with progress tracking  
✅ No crashes or debugging required

## Maintainability

- **When Instagram changes:** Update `instaloader` package
- **Bug in download:** Check `instaloader` issues/docs
- **Want new feature:** Extend, don't patch

**Simple. Reliable. Maintainable.**
