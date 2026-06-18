<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

# Copilot instructions for this repository

## Project intent

This repository is a Python desktop application for downloading and organizing Instagram saved posts.

- Primary UI: `gui.py` using **PyQt5**
- Entry point: `main.py`
- Instagram integration: `instagram_manager.py` using **instaloader**
- Account persistence: `account_manager.py` using **SQL Server via pyodbc**
- Content persistence: `content_database_manager.py` and `database_manager_sqlserver.py`
- Shared settings and filesystem locations: `config.py`

Prefer simple, reliable changes over adding new abstractions.

## Repository-specific guidance

1. Keep the app working in both **GUI mode** and **CLI mode**. `main.py` supports:
   - `python main.py`
   - `python main.py download <username> <password> <shortcode>`
   - `python main.py list <username> <password>`
   - `python main.py accounts`
2. Treat **browser-cookie import** and **session reuse** as first-class login paths. Do not assume username/password login is the only or preferred flow.
3. Preserve the app's current architecture: GUI orchestration in `gui.py`, Instagram operations in `instagram_manager.py`, persistence in the database manager modules.
4. Reuse existing configuration values from `config.py` instead of hardcoding paths, filenames, sizes, or logging settings.
5. Be careful with account and content persistence code:
   - accounts are backed by **SQL Server**, not SQLite
   - `pyodbc` connection logic and existing schema assumptions should remain intact
   - do not silently change storage formats or table names
6. Preserve logging behavior and use the existing `logging` patterns instead of `print`, except for existing CLI output paths.
7. Avoid changes that break optional dependencies. Features using `browser-cookie3`, OpenCV, or VLC should fail clearly and degrade gracefully when those packages are unavailable.

## Editing expectations

1. Prefer **small, surgical edits** in existing modules.
2. Match the existing Python style in the touched file instead of introducing a new style.
3. Keep public behavior stable unless the task explicitly requires a behavior change.
4. Do not add unnecessary frameworks, background services, or web stacks.
5. Do not replace `instaloader` with custom scraping logic.

## PyQt5 guidance

When editing `gui.py`:

- keep long-running work off the UI thread
- preserve signal/slot based communication patterns already used in the file
- avoid blocking dialogs or synchronous network/database work on the main thread
- keep UI text and workflow consistent with the existing tabs and controls

## Data and filesystem guidance

- Session files live under `config.SESSIONS_DIR`
- Default downloads live under `config.DEFAULT_DOWNLOAD_DIR`
- The application creates required directories through `config.ensure_directories()`
- Be careful not to introduce hardcoded machine-specific paths

## Documentation map

Use the existing docs when changes affect user workflows:

- `README.md`
- `Documentation\QUICKSTART.md`
- `Documentation\TROUBLESHOOTING.md`
- `Documentation\SESSION_IMPORT_GUIDE.md`
- `Documentation\ARCHITECTURE.md`

## Good defaults for future changes

- Prefer reliability over cleverness
- Prefer explicit error reporting over silent fallback
- Preserve Windows-friendly behavior
- Keep secrets, credentials, and session data out of logs, docs, and committed files
