"""
Quick fix for file paths - SQL-based update

Updates all file paths from old C: drive location to new G: drive location.
"""
import sys
sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader')
from content_database_manager import ContentDatabaseManager
from account_manager import AccountManager

# Configuration
OLD_BASE = r'C:\Users\sasse\Downloads\Instagram\sassenheimer'
NEW_BASE = r'G:\.stogram\sassenheimer\content'

print('Quick File Path Fix')
print('=' * 60)
print(f'Old base: {OLD_BASE}')
print(f'New base: {NEW_BASE}')
print('=' * 60)

# Initialize
account_mgr = AccountManager()
accounts = account_mgr.list_accounts()
account = accounts[0]
username = account['username']
print(f'\nUsing account: {username}')

content_db = ContentDatabaseManager('', username)
conn = content_db.db._get_connection()
cursor = conn.cursor()

# Count files with old path
print('\nCounting files with old path...')
cursor.execute('''
    SELECT COUNT(*) 
    FROM DL.files 
    WHERE file_destination_path LIKE ?
''', (OLD_BASE + '%',))
count = cursor.fetchone()[0]
print(f'Found {count} files with old path')

if count == 0:
    print('\n✓ No files need updating!')
    sys.exit(0)

# Show sample
print('\nSample files to update:')
cursor.execute('''
    SELECT TOP 5 content_id, file_destination_path 
    FROM DL.files 
    WHERE file_destination_path LIKE ?
''', (OLD_BASE + '%',))
for row in cursor.fetchall():
    shortcode, old_path = row
    print(f'  {shortcode}: {old_path}')

# Ask for confirmation
print('\n' + '=' * 60)
response = input(f'Update {count} file paths? (yes/no): ')
if response.lower() != 'yes':
    print('Aborted.')
    sys.exit(0)

# Update paths using SQL REPLACE
print('\nUpdating paths...')
cursor.execute('''
    UPDATE DL.files
    SET file_destination_path = REPLACE(file_destination_path, ?, ?),
        updated_at = GETDATE()
    WHERE file_destination_path LIKE ?
''', (OLD_BASE, NEW_BASE, OLD_BASE + '%'))

updated = cursor.rowcount
conn.commit()

print(f'\n✓ Updated {updated} file paths')
print('\n' + '=' * 60)
print('Done! Video controls should now appear in the GUI.')
print('You may need to click the "🔄 Refresh" button in Browse tab.')
print('=' * 60)
