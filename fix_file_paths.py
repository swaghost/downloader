"""
Fix file paths in database - Update old paths to new location

This script updates file paths in the database when files have been moved
from one location to another (e.g., C: drive to G: drive).
"""
import sys
import os
from pathlib import Path

sys.path.append(r'c:\A7\qs\qs.python.instagram-downloader')
from content_database_manager import ContentDatabaseManager
from account_manager import AccountManager

def fix_file_paths(old_base_path, new_base_path, dry_run=True):
    """
    Update file paths in database from old location to new location.
    
    Args:
        old_base_path: Old base path (e.g., 'C:\\Users\\sasse\\Downloads\\Instagram\\sassenheimer')
        new_base_path: New base path (e.g., 'G:\\.stogram\\sassenheimer\\content')
        dry_run: If True, only show what would be changed without making changes
    """
    # Initialize managers
    account_mgr = AccountManager()
    accounts = account_mgr.list_accounts()
    
    if not accounts:
        print('No accounts found')
        return
    
    # Use first account
    account = accounts[0]
    username = account['username']
    print(f'Using account: {username}')
    
    # Initialize content database
    content_db = ContentDatabaseManager('', username)
    
    # Get all entries
    print('\nFetching all content entries...')
    entries_dict = content_db.db.get_all_content_entries()
    entries = list(entries_dict.values())
    print(f'Found {len(entries)} entries')
    
    # Track statistics
    stats = {
        'total_files': 0,
        'files_with_old_path': 0,
        'files_fixed': 0,
        'files_verified': 0,
        'files_not_found': 0
    }
    
    updates_to_apply = []
    
    print(f'\n{"="*80}')
    print(f'Analyzing file paths...')
    print(f'Old base: {old_base_path}')
    print(f'New base: {new_base_path}')
    print(f'Mode: {"DRY RUN (no changes)" if dry_run else "LIVE (will update database)"}')
    print(f'{"="*80}\n')
    
    for entry in entries:
        shortcode = entry.get('id')
        files_info = entry.get('FilesInformation', {})
        file_list = files_info.get('FileList', [])
        
        for file_entry in file_list:
            stats['total_files'] += 1
            
            old_path = file_entry.get('FileDestinationPath')
            if not old_path:
                continue
            
            # Check if this file has the old base path
            if not old_path.startswith(old_base_path):
                continue
            
            stats['files_with_old_path'] += 1
            
            # Calculate new path
            relative_path = old_path[len(old_base_path):].lstrip('\\').lstrip('/')
            new_path = os.path.join(new_base_path, relative_path)
            
            # Check if new path exists
            if os.path.exists(new_path):
                stats['files_verified'] += 1
                print(f'✓ {shortcode}: Found file at new location')
                print(f'  Old: {old_path}')
                print(f'  New: {new_path}')
                
                # Store update to apply
                file_id = file_entry.get('id')
                if file_id:
                    updates_to_apply.append({
                        'file_id': file_id,
                        'shortcode': shortcode,
                        'old_path': old_path,
                        'new_path': new_path
                    })
            else:
                stats['files_not_found'] += 1
                print(f'✗ {shortcode}: File not found at new location')
                print(f'  Old: {old_path}')
                print(f'  New: {new_path} (NOT FOUND)')
    
    # Apply updates if not dry run
    if not dry_run and updates_to_apply:
        print(f'\n{"="*80}')
        print(f'Applying {len(updates_to_apply)} updates to database...')
        print(f'{"="*80}\n')
        
        conn = content_db.db._get_connection()
        cursor = conn.cursor()
        
        for update in updates_to_apply:
            try:
                cursor.execute('''
                    UPDATE DL.files
                    SET file_destination_path = ?, updated_at = GETDATE()
                    WHERE id = ?
                ''', (update['new_path'], update['file_id']))
                
                stats['files_fixed'] += 1
                print(f'✓ Updated {update["shortcode"]}: {update["file_id"]}')
            except Exception as e:
                print(f'✗ Failed to update {update["shortcode"]}: {e}')
        
        conn.commit()
        print(f'\nCommitted {stats["files_fixed"]} updates to database')
    
    # Print summary
    print(f'\n{"="*80}')
    print('SUMMARY')
    print(f'{"="*80}')
    print(f'Total files in database: {stats["total_files"]}')
    print(f'Files with old path: {stats["files_with_old_path"]}')
    print(f'Files verified at new location: {stats["files_verified"]}')
    print(f'Files not found at new location: {stats["files_not_found"]}')
    
    if dry_run:
        print(f'\nFiles that WOULD be updated: {stats["files_verified"]}')
        print(f'\n⚠️  This was a DRY RUN - no changes were made')
        print(f'To apply changes, run: python fix_file_paths.py --apply')
    else:
        print(f'\nFiles updated in database: {stats["files_fixed"]}')
        print(f'\n✓ Changes have been applied to the database')


if __name__ == '__main__':
    # Configuration
    OLD_BASE = r'C:\Users\sasse\Downloads\Instagram\sassenheimer'
    NEW_BASE = r'G:\.stogram\sassenheimer\content'
    
    # Check for --apply flag
    dry_run = '--apply' not in sys.argv
    
    if dry_run:
        print('\n⚠️  DRY RUN MODE - No changes will be made')
        print('To apply changes, run with --apply flag\n')
    else:
        print('\n⚠️  LIVE MODE - Database will be updated!')
        response = input('Are you sure you want to continue? (yes/no): ')
        if response.lower() != 'yes':
            print('Aborted.')
            sys.exit(0)
        print()
    
    fix_file_paths(OLD_BASE, NEW_BASE, dry_run=dry_run)
