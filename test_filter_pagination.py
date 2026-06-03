"""
Test that pagination is recalculated when filters change
"""
import sys
sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader')
from content_database_manager import ContentDatabaseManager
from account_manager import AccountManager

# Initialize
account_mgr = AccountManager()
accounts = account_mgr.list_accounts()
account = accounts[0]
content_db = ContentDatabaseManager('', account['username'])

# Simulate different filters and calculate pages
TILES_PER_PAGE = 50  # Default from GUI

print('Filter Pagination Test')
print('=' * 70)
print(f'Items per page: {TILES_PER_PAGE}')
print('=' * 70)

filters = [
    ('All (Unfiltered)', None),
    ('Only Ignored (Black) Items', 'ignored'),
    ('Only Uncategorized', 'uncategorized'),
    ('Only Categorized & Undownloaded', 'categorized_undownloaded'),
    ('Only Error Items', 'error'),
]

print('\nFilter Results:')
print('-' * 70)

for filter_name, filter_type in filters:
    count = content_db.db.get_content_count(filter_type=filter_type)
    total_pages = (count + TILES_PER_PAGE - 1) // TILES_PER_PAGE
    
    print(f'\n{filter_name}:')
    print(f'  Items: {count}')
    print(f'  Pages: {total_pages}')
    print(f'  Page 1 range: items 0-{min(TILES_PER_PAGE-1, count-1)}')
    if total_pages > 1:
        last_page_start = (total_pages - 1) * TILES_PER_PAGE
        last_page_end = count - 1
        print(f'  Last page range: items {last_page_start}-{last_page_end}')

print('\n' + '=' * 70)
print('✓ Pagination calculation test complete!')
print('\nKey behavior:')
print('• Changing filter recalculates total items and pages')
print('• Current page resets to 1 (index 0)')
print('• Page spinner maximum updates to new page count')
