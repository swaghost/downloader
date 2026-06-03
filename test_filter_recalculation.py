"""
Test filter recalculation logic after downloads

This simulates the scenarios that need to be handled:
1. Filter active, items downloaded, some remain - refresh current page
2. Filter active, on last page, items downloaded, page now empty - move to previous page
3. Filter active, all items downloaded, none remain - reset to "All" filter
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

TILES_PER_PAGE = 50

print('Filter Recalculation Test Scenarios')
print('=' * 70)
print(f'Items per page: {TILES_PER_PAGE}')
print('=' * 70)

# Test Case 1: Categorized & Undownloaded (pink items)
print('\n\nScenario 1: "Only Categorized & Undownloaded" Filter')
print('-' * 70)
filter_type = 'categorized_undownloaded'
count = content_db.db.get_content_count(filter_type=filter_type)
total_pages = (count + TILES_PER_PAGE - 1) // TILES_PER_PAGE

print(f'Current items: {count}')
print(f'Current pages: {total_pages}')
print(f'\nIf user is on page {total_pages} and downloads 45 items:')
print(f'  New count would be: {count - 45}')
new_pages = (count - 45 + TILES_PER_PAGE - 1) // TILES_PER_PAGE
print(f'  New pages would be: {new_pages}')
if new_pages < total_pages:
    print(f'  ⚠️ Action: Move from page {total_pages} to page {new_pages}')
else:
    print(f'  ✓ Action: Stay on page {total_pages}, refresh')

# Test Case 2: Error Items (red items)
print('\n\nScenario 2: "Only Error Items" Filter')
print('-' * 70)
filter_type = 'error'
count = content_db.db.get_content_count(filter_type=filter_type)
total_pages = max(1, (count + TILES_PER_PAGE - 1) // TILES_PER_PAGE)

print(f'Current items: {count}')
print(f'Current pages: {total_pages}')

if count > 0:
    print(f'\nIf user is on page {total_pages} and re-downloads all {count} items successfully:')
    print(f'  New count would be: 0')
    print(f'  ⚠️ Action: Reset filter to "All (Unfiltered)", show dialog')
else:
    print('\n⚠️ No error items currently, cannot test this scenario')

# Test Case 3: Ignored Items
print('\n\nScenario 3: "Only Ignored (Black) Items" Filter')
print('-' * 70)
filter_type = 'ignored'
count = content_db.db.get_content_count(filter_type=filter_type)
total_pages = (count + TILES_PER_PAGE - 1) // TILES_PER_PAGE

print(f'Current items: {count}')
print(f'Current pages: {total_pages}')
print(f'\nIf user is on page 5 and un-ignores 3 items:')
print(f'  New count would be: {count - 3}')
new_pages = (count - 3 + TILES_PER_PAGE - 1) // TILES_PER_PAGE
print(f'  New pages would be: {new_pages}')
if 5 <= total_pages:
    print(f'  ✓ Action: Stay on page 5, refresh')
else:
    print(f'  (User not on page 5 in this test)')

print('\n' + '=' * 70)
print('Expected Behaviors:')
print('=' * 70)
print('1. Current page < last page:')
print('   → Clear cache for current page, refresh in place')
print()
print('2. Current page = last page AND page now empty:')
print('   → Move to previous page (new last page), clear cache, refresh')
print()
print('3. Filter has 0 items remaining:')
print('   → Reset filter to "All (Unfiltered)"')
print('   → Show dialog: "All items matching filter have been processed"')
print('   → Apply new filter and reload')
print('=' * 70)
