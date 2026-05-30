<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

# Instagram Downloader - Clean Implementation

## Project Overview

Simple, reliable Instagram saved posts downloader with PyQt5 GUI. Built on the proven `instaloader` library.

**Design Philosophy:** Simplicity over features. Reliability over complexity.

## Architecture

### Core Modules

- **main.py** - Entry point and CLI mode
- **gui.py** - PyQt5 interface with three tabs (Accounts, Browse, Download)
- **instagram_manager.py** - Instaloader wrapper for Instagram operations
- **account_manager.py** - Account persistence and session management
- **content_database_manager.py** - SQL Server content database operations
- **config.py** - Configuration constants

### Key Features

✅ Download saved posts (images, videos, carousels)  
✅ Direct browser cookie extraction (Chrome/Firefox)  
✅ Multi-account support with session persistence  
✅ Clean PyQt5 GUI with progress tracking  
✅ CLI mode available  
✅ Built on actively maintained `instaloader` library

### Storage

- **Accounts Database:** SQL Server (shared across machines)
- **Session Files:** Stored per account for ~90 day persistence
- **Downloads:** Organized by account in data/{username}/saved/

## Usage

**GUI Mode:**

```bash
python main.py
```

**CLI Mode:**

```bash
python main.py download username password CdNmOtkIOM-
python main.py list username password
```

## Dependencies

- instaloader >= 4.10
- PyQt5 >= 5.15.0
- Pillow >= 10.0.0
- requests >= 2.28.0
- browser-cookie3 >= 0.19.0 (optional, for browser cookie extraction)
- opencv-python >= 4.8.0 (optional, for video thumbnails)
- python-vlc >= 3.0.0 (optional, for video player)

## Documentation

- **README.md** - Complete user guide
- **QUICKSTART.md** - Quick start guide with browser cookie extraction
- **ARCHITECTURE.md** - Design philosophy and code structure
- **COMPARISON.md** - Comparison with previous complex implementation
- **SESSION_IMPORT_GUIDE.md** - Session import methods
- **TROUBLESHOOTING.md** - Common issues and solutions
