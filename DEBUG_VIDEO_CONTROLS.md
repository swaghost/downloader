# Video Controls Debug Guide

## Problem

Video controls are not showing for downloaded video content in the Browse tab.

## Debug Steps

### 1. Run GUI with Debug Logging

Run this command to start the GUI with full logging:

```bash
python test_video_controls.py > debug_output.txt 2>&1
```

Or run directly with logging enabled:

```bash
python main.py
```

### 2. Check the Log Output

When you load the Browse tab and see tiles, look for these log entries:

**Expected for videos that should show controls:**

```
[TILE] DTzjRsJjJWI: status=completed, downloaded_files count=1
[TILE] DTzjRsJjJWI: file 1: type=video, path exists=True
[MEDIA_DISPLAY] DTzjRsJjJWI: downloaded_files count=1
[MEDIA_DISPLAY] DTzjRsJjJWI: file_count=1, is_carousel=False, has_video=True
[MEDIA_DISPLAY] DTzjRsJjJWI: Creating VIDEO display with PLAY BUTTON
```

**If something is wrong, you might see:**

```
[TILE] DTzjRsJjJWI: status=completed but no downloaded files found!
[MEDIA_DISPLAY] DTzjRsJjJWI: No files - creating PLACEHOLDER
```

### 3. Manual Test

You can also test a specific shortcode in Python:

```python
import sys
sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader')
from content_database_manager import ContentDatabaseManager
from account_manager import AccountManager
import os

account_mgr = AccountManager()
accounts = account_mgr.list_accounts()
account = accounts[0]
username = account['username']
content_db = ContentDatabaseManager('', username)

# Test a specific shortcode (e.g., DTzjRsJjJWI)
shortcode = 'DTzjRsJjJWI'
entry = content_db.db.get_content_entry(shortcode)

if entry:
    print(f"Entry found for {shortcode}")
    print(f"Download status: {entry['ContentInformation']['downloadStatus']}")

    files_info = entry.get('FilesInformation', {})
    file_list = files_info.get('FileList', [])
    print(f"Files: {len(file_list)}")

    for i, f in enumerate(file_list):
        file_path = f.get('FileDestinationPath')
        file_status = f.get('FileDownloadStatus')
        file_type = f.get('FileType')
        exists = os.path.exists(file_path) if file_path else False

        print(f"  File {i+1}:")
        print(f"    Type: {file_type}")
        print(f"    Status: {file_status}")
        print(f"    Path: {file_path}")
        print(f"    Exists: {exists}")
else:
    print(f"No entry found for {shortcode}")
```

### 4. Use Refresh Button

Try clicking the **"🔄 Refresh"** button at the bottom of the Browse tab to force reload from database.

## Common Issues

### Issue 1: Status mismatch

- Database says `completed` but tile thinks it's `awaiting scan`
- **Solution:** Click Refresh button

### Issue 2: Files exist but wrong status

- Files have `FileDownloadStatus='awaiting'` instead of `'downloaded'` or `'completed'`
- **Solution:** Update database manually or re-download

### Issue 3: Cache corruption

- Page cache has stale post objects
- **Solution:** Click Refresh button to clear cache and reload

### Issue 4: GUI not updated

- Code changes not reflected
- **Solution:** Restart the GUI completely

## Quick Verification

Run this to check if any completed posts have video files:

```bash
python -c "import sys; sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader'); from content_database_manager import ContentDatabaseManager; from account_manager import AccountManager; import os; account_mgr = AccountManager(); accounts = account_mgr.list_accounts(); account = accounts[0]; content_db = ContentDatabaseManager('', account['username']); entries = list(content_db.db.get_all_content_entries(limit=10).values()); videos = [(e['id'], e['ContentInformation']['downloadStatus'], len([f for f in e['FilesInformation']['FileList'] if f['FileType']=='video'])) for e in entries if any(f.get('FileType')=='video' for f in e['FilesInformation']['FileList'])]; print('Videos found:'); [print(f'{v[0]}: status={v[1]}, video_count={v[2]}') for v in videos[:5]]"
```
