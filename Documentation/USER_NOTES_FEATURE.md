# User Notes Feature

## Overview

The Instagram Downloader now supports adding custom notes to each file in your saved posts. This is particularly useful for:

- Adding context or reminders for specific images/videos
- Tagging carousel items individually
- Annotating content for later reference

## Features

### ✨ What's New

1. **Per-File Notes**: Each file (image/video) can have its own custom note
2. **Database Storage**: Notes are stored in the SQL Server database and persist across sessions
3. **Easy Editing**: Simple dialog interface for adding/editing notes
4. **Display Integration**: Notes appear in the Details panel alongside other file information

## How to Use

### Viewing Notes

1. In the **Browse** tab, click on any post in the table or tile view
2. The **Details panel** (right side) will show information about the post
3. If any files have notes, you'll see them displayed as: `📝 Notes: <your note>`

### Adding/Editing Notes

1. Select a post in the Browse tab
2. Click the **📝 Edit Notes** button in the Details panel
3. A dialog will open showing all files in the post
4. Enter or edit notes for each file (you can leave some blank)
5. Click **💾 Save** to save your changes

### Notes Display Example

```
Files (3):
  1. C7RmXbxhXr6_1
     Type: image | Status: not yet started
     📝 Notes: Beautiful sunset photo

  2. C7RmXbxhXr6_2
     Type: image | Status: not yet started
     📝 Notes: Group photo - remember to share with Tom

  3. C7RmXbxhXr6_3
     Type: video | Status: not yet started
```

## Use Cases

### Single Posts/Reels

- Add context notes about when/where the content was created
- Tag people or locations
- Add reminders for follow-up actions

### Carousels

- Different notes for each image in the carousel
- Identify specific items or people in different slides
- Track which images you want to keep vs. delete

### Stories

- Add timestamps or context
- Note related content or references

## Technical Details

### Database Schema

A new column `user_notes` was added to the `DL.files` table:

- **Type**: NVARCHAR(MAX)
- **Nullable**: Yes
- **Default**: NULL (empty)

### API Methods

**Update Notes**:

```python
db.update_file_user_notes(content_id, file_number, notes_text)
```

**Retrieve Notes**:
Notes are included in the standard file information when retrieving entries:

```python
entry = db.get_content_entry(shortcode)
files = entry['FilesInformation']['FileList']
for file in files:
    notes = file.get('UserNotes', '')
```

## Migration

The feature was added via the migration script:

- **Script**: `add_user_notes_column.py`
- **Status**: ✓ Applied successfully
- **Backward Compatible**: Yes - existing entries will have empty notes by default

## Files Modified

1. **database_manager_sqlserver.py**
   - Added `user_notes` column to INSERT and UPDATE statements
   - Added `update_file_user_notes()` method
   - Updated `_map_file_to_ui_format()` to include UserNotes

2. **gui.py**
   - Added "📝 Edit Notes" button in Details panel
   - Added `edit_file_notes()` dialog for editing notes
   - Added `save_file_notes()` method to persist changes
   - Updated details display to show notes (both table and tile views)

3. **Database Schema**
   - Added `user_notes` column to `DL.files` table

## Testing

A test script (`test_user_notes.py`) is included to verify the functionality:

```bash
python test_user_notes.py
```

The test confirms:

- ✓ Notes can be added to files
- ✓ Notes are persisted in the database
- ✓ Notes can be retrieved correctly

## Future Enhancements (Optional)

Possible future improvements:

- Bulk note editing for multiple posts
- Note templates/quick tags
- Search/filter posts by note content
- Export notes to CSV/JSON
- Rich text formatting in notes
