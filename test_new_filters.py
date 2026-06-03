"""
Test the new filter options
"""
import sys
sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader')
from content_database_manager import ContentDatabaseManager
from account_manager import AccountManager

# Initialize
account_mgr = AccountManager()
accounts = account_mgr.list_accounts()
account = accounts[0]
username = account['username']

content_db = ContentDatabaseManager('', username)

print('Testing New Filter Options')
print('=' * 60)

# Test 1: Count all entries
print('\n1. All entries (no filter):')
all_entries = content_db.get_all_account_entries(limit=None)
print(f'   Total entries: {len(all_entries)}')

# Test 2: Only Categorized & Undownloaded (pink items)
print('\n2. Only Categorized & Undownloaded (pink items):')
pink_entries = content_db.get_all_account_entries(
    limit=None, 
    filter_type='categorized_undownloaded'
)
print(f'   Found {len(pink_entries)} entries')
if pink_entries:
    # Show a few examples
    sample = list(pink_entries.items())[:3]
    for shortcode, entry in sample:
        post = content_db.convert_entry_to_post(entry)
        status = post.get('download_status', 'unknown')
        topic_id = entry.get('ContentInformation', {}).get('topicID')
        print(f'   - {shortcode}: status={status}, has_topic={topic_id is not None}')

# Test 3: Only Error Items (red items)
print('\n3. Only Error Items (red items):')
error_entries = content_db.get_all_account_entries(
    limit=None, 
    filter_type='error'
)
print(f'   Found {len(error_entries)} entries')
if error_entries:
    # Show a few examples
    sample = list(error_entries.items())[:3]
    for shortcode, entry in sample:
        post = content_db.convert_entry_to_post(entry)
        status = post.get('download_status', 'unknown')
        print(f'   - {shortcode}: status={status}')

# Test 4: Verify count method also works
print('\n4. Test get_content_count with new filters:')
pink_count = content_db.db.get_content_count(filter_type='categorized_undownloaded')
error_count = content_db.db.get_content_count(filter_type='error')
print(f'   Categorized & Undownloaded count: {pink_count}')
print(f'   Error Items count: {error_count}')

print('\n' + '=' * 60)
print('✓ Filter tests complete!')
