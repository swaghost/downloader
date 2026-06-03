"""
Quick test for new filter options using counts only
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

print('Testing New Filter Options (Count-Only)')
print('=' * 60)

# Test get_content_count with new filters
print('\nTesting get_content_count():')
print('-' * 60)

total_count = content_db.db.get_content_count()
print(f'Total entries: {total_count}')

ignored_count = content_db.db.get_content_count(filter_type='ignored')
print(f'Ignored: {ignored_count}')

uncategorized_count = content_db.db.get_content_count(filter_type='uncategorized')
print(f'Uncategorized: {uncategorized_count}')

pink_count = content_db.db.get_content_count(filter_type='categorized_undownloaded')
print(f'Categorized & Undownloaded (pink): {pink_count}')

error_count = content_db.db.get_content_count(filter_type='error')
print(f'Error Items (red): {error_count}')

# Test with get_all_account_entries (just first page)
print('\n\nTesting get_all_account_entries() with limit=5:')
print('-' * 60)

print('\nPink items (first 5):')
pink_entries = content_db.get_all_account_entries(
    limit=5, 
    filter_type='categorized_undownloaded'
)
for entry in pink_entries:
    post = content_db.convert_entry_to_post(entry)
    shortcode = post.get('shortcode', 'unknown')
    status = post.get('download_status', 'unknown')
    topic_id = entry.get('ContentInformation', {}).get('topicID')
    print(f'  {shortcode}: status={status}, topic_id={topic_id}')

print('\nError items (first 5):')
error_entries = content_db.get_all_account_entries(
    limit=5, 
    filter_type='error'
)
for entry in error_entries:
    post = content_db.convert_entry_to_post(entry)
    shortcode = post.get('shortcode', 'unknown')
    status = post.get('download_status', 'unknown')
    print(f'  {shortcode}: status={status}')

print('\n' + '=' * 60)
print('✓ Filter tests complete!')
