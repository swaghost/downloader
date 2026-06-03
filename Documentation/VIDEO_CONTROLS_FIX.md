# Video Controls Not Showing - Issue and Fix

## Issue Description

Users reported that some downloaded videos don't show play button controls in the Browse tab, even though:

- The posts are marked as `download_status='completed'` in the database
- The video files exist on disk and are properly saved
- The FileList in the database contains correct file information

## Root Cause

The issue occurs due to **page caching behavior**:

1. **Scenario**: User views a page before downloading posts on that page
2. **Page Cache**: Posts are loaded from database and cached with old status (`'awaiting scan'`)
3. **Download Completes**: Database is updated, but the page cache may become stale
4. **Cache Eviction**: If user navigates away, the page is eventually evicted from cache (max 5 pages)
5. **Return to Page**: When user returns to the page:
   - Page is reloaded from database with correct status (`'completed'`)
   - Tiles are created with correct data
   - Video controls **should** appear

However, there was a scenario where tiles weren't properly rebuilding after status changes.

## Technical Details

### Data Flow

```
Database (DL.content_entries + DL.files)
    ↓
get_content_entry() - Builds entry with FilesInformation
    ↓
convert_entry_to_post() - Converts to post format with download_status
    ↓
page_cache[page_num] - Cached posts
    ↓
create_tile_widget() - Creates tile UI
    ↓
get_downloaded_files() - Reads FileList from database
    ↓
_add_tile_media_display() - Adds video controls if video found
```

### Tile Creation Logic

When a tile is created, `_add_tile_media_display()` checks:

1. **Status Check**: Is `download_status` in `['downloaded', 'completed', 're-downloaded']`?
2. **File Retrieval**: Call `get_downloaded_files(shortcode)` to get files from database
3. **Type Detection**: Check if any file has `type` in `['video', 'mp4']`
4. **Control Display**:
   - Single video → Show video with play button
   - Carousel with videos → Show carousel with navigation + play button
   - Single image → Show image with hover preview

### Cache Update on Download

When a download completes, `handle_download_complete()` and `handle_single_download_complete()`:

1. Save file information to `DL.files` table via `add_file()`
2. Update content entry status to `'completed'`
3. **Update page cache**: Loop through cached pages and update `download_status`
4. **Update tile**: If on current page, call `update_tile_appearance()`

### The Refresh Button Solution

Added a **"🔄 Refresh"** button in the pagination controls that:

1. Removes current page from cache
2. Cancels any pending page loads
3. Clears tile tracking to force full rebuild
4. Reloads page from database
5. All tiles are recreated with latest data from database

## Solution for Users

If you see videos without play button controls:

1. **Click "🔄 Refresh" button** at the bottom of the page (next to pagination controls)
2. This forces reload from database with latest file information
3. Tiles will be rebuilt with proper video controls

## Prevention

The system already updates cached pages when downloads complete, but the Refresh button provides a manual way to force reload if the cache gets out of sync for any reason.

## Code Changes

### gui.py

1. **Added Refresh Button** (around line 1835):

   ```python
   refresh_page_btn = QPushButton("🔄 Refresh")
   refresh_page_btn.clicked.connect(self.refresh_current_page)
   refresh_page_btn.setToolTip("Reload current page from database (fixes missing video controls)")
   ```

2. **Added refresh_current_page() method** (around line 12354):
   - Clears page from cache
   - Cancels pending loads
   - Forces full tile rebuild
   - Reloads from database

## Verification

To verify a post should show video controls:

```python
# Check database entry
entry = content_db.db.get_content_entry(shortcode)
status = entry['ContentInformation']['downloadStatus']
file_list = entry['FilesInformation']['FileList']

# Should be: status == 'completed' and file_list has video files
```

## Future Improvements

Potential enhancements:

1. Auto-refresh pages when downloads complete (may cause UI flicker)
2. Better cache invalidation strategy
3. Real-time tile updates without full page reload
4. Background sync to check for database changes

## Related Files

- `gui.py`: UI and tile creation logic
- `database_manager_sqlserver.py`: Database file storage and retrieval
- `content_database_manager.py`: Database interface and post conversion
