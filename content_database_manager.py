"""
Content Database Manager - Integrates Instagram posts with SQL Server content database
Manages saved posts persistence with duplicate checking
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from database_factory import get_database_manager

logger = logging.getLogger(__name__)


class ContentDatabaseManager:
    """
    Manages Instagram content in SQL Server database.
    Saves posts, checks for duplicates, and tracks content.
    """
    
    def __init__(self, user_dir: str, account_name: str):
        """
        Initialize content database manager.
        
        Args:
            user_dir: User directory path
            account_name: Instagram account name for multi-account support
        """
        self.account_name = account_name
        self.db = get_database_manager(user_dir, account_name)
        logger.info(f"Initialized content database for account: {account_name}")
    
    def save_post(self, post: Dict) -> bool:
        """
        Save an Instagram post to the database.
        
        Args:
            post: Post dictionary from Instagram API
        
        Returns:
            True if saved (new post), False if duplicate
        """
        try:
            # Create content entry in database format
            entry = self._convert_post_to_entry(post)
            
            # Try to add (will return False if duplicate)
            result = self.db.add_content_entry(entry)
            
            if result:
                logger.info(f"Saved new post: {post['shortcode']}")
            else:
                logger.debug(f"Duplicate post skipped: {post['shortcode']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to save post {post.get('shortcode', 'unknown')}: {e}")
            return False
    
    def save_posts_batch(self, posts: List[Dict]) -> Dict[str, int]:
        """
        Save multiple posts to database.
        
        Args:
            posts: List of post dictionaries
        
        Returns:
            Dictionary with counts: {'saved': N, 'duplicates': N, 'errors': N}
        """
        stats = {'saved': 0, 'duplicates': 0, 'errors': 0}
        
        for post in posts:
            try:
                result = self.save_post(post)
                if result:
                    stats['saved'] += 1
                else:
                    stats['duplicates'] += 1
            except Exception as e:
                logger.error(f"Error saving post {post.get('shortcode')}: {e}")
                stats['errors'] += 1
        
        return stats
    
    def is_duplicate(self, shortcode: str) -> bool:
        """
        Check if a post already exists in database.
        
        Args:
            shortcode: Instagram post shortcode
        
        Returns:
            True if post exists, False otherwise
        """
        try:
            entry = self.db.get_content_entry(shortcode)
            return entry is not None
        except Exception as e:
            logger.error(f"Error checking duplicate for {shortcode}: {e}")
            return False
    
    def get_saved_count(self) -> int:
        """Get total count of saved posts for this account."""
        try:
            entries = self.db.get_all_content_entries()
            return len([e for e in entries if e.get('account_name') == self.account_name])
        except Exception as e:
            logger.error(f"Error getting saved count: {e}")
            return 0
    
    def _convert_post_to_entry(self, post: Dict) -> Dict:
        """
        Convert Instagram post format to database content entry format.
        
        Args:
            post: Post from Instagram API
        
        Returns:
            Entry dictionary in database format
        """
        shortcode = post['shortcode']
        
        # Determine content type
        typename = post.get('typename', 'GraphImage')
        if typename == 'GraphVideo':
            content_type = 'reel'  # Videos are treated as reels
            content_sub_type = 'single-video'
        elif typename == 'GraphSidecar':
            content_type = 'carousel'
            content_sub_type = None  # Will be determined by files
        else:
            content_type = 'post'
            content_sub_type = 'single-image'
        
        # Parse date field - handle Unix timestamp, ISO string, or empty
        date_field = post.get('date', '')
        if isinstance(date_field, int):
            # Unix timestamp from Instagram export
            date_added = datetime.fromtimestamp(date_field).isoformat()
        elif isinstance(date_field, str) and date_field:
            # Already formatted string (from instaloader)
            date_added = date_field
        else:
            # Empty or invalid, use current time
            date_added = datetime.now().isoformat()
        
        # Build FilesInformation
        file_list = []
        media_count = post.get('media_count', 1)
        
        for i in range(media_count):
            file_entry = {
                'file_number': i + 1,
                'cdn_url': '',  # Will be filled when downloaded
                'cdn_mechanism': '',
                'file_name': f"{shortcode}_{i+1}",
                'download_filename': '',
                'file_caption': post.get('caption', ''),
                'file_tags': '',
                'file_type': 'video' if post.get('is_video') else 'image',
                'file_quality': 'high',
                'file_size_bytes': 0,
                'file_download_status': 'not yet started',
                'file_download_date': None,
                'file_segment_count': 0,
                'file_assembly_status': 'not yet assembled',
                'file_save_status': 'not yet saved',
                'file_destination_path': '',
                'file_debug_path': '',
                'has_audio': False,
                'audio_url': None,
                'audio_segment_count': 0,
                'xpv_asset_id': None,
                'url_source_issue': None,
                'url_auto_corrected': False,
                'url_correction_log': None
            }
            file_list.append(file_entry)
        
        # Build content entry
        entry = {
            'id': shortcode,
            'media_url': post['url'],
            'text': post.get('caption', ''),
            'Source': 'Instagram Saved Posts',
            'type': content_type,
            'ContentInformation': {
                'date_added': date_added,
                'ContentType': content_type,
                'cdnAcquisitionStatus': 'awaiting scan',
                'downloadStatus': 'awaiting scan',
                'reviewState': 'not yet reviewed',
                'purgeStatus': False,
                'isDuplicate': False,
                'has_instagram_issues': False,
                'instagram_issue_notes': None
            },
            'FilesInformation': {
                'FileList': file_list
            }
        }
        
        return entry
    
    def get_post_status(self, shortcode: str) -> Dict:
        """
        Get the download status and other info for a post.
        
        Args:
            shortcode: Instagram post shortcode
        
        Returns:
            Dictionary with status info, or None if not found
        """
        try:
            entry = self.db.get_content_entry(shortcode)
            if not entry:
                return None
            
            return {
                'download_status': entry.get('download_status', 'awaiting scan'),
                'cdn_acquisition_status': entry.get('cdn_acquisition_status', 'awaiting scan'),
                'review_state': entry.get('review_state', 'not yet reviewed'),
                'is_duplicate': entry.get('is_duplicate', False),
                'date_added': entry.get('date_added')
            }
        except Exception as e:
            logger.error(f"Error getting status for {shortcode}: {e}")
            return None
    
    def get_content_count(self) -> int:
        """
        Get total count of content entries (fast query).
        
        Returns:
            Count of entries for current account
        """
        try:
            # Use existing get_content_count() method with no filters
            count = self.db.get_content_count(filters=None)
            return count
        except Exception as e:
            logger.error(f"Error getting content count: {e}")
            return 0
    
    def get_all_account_entries(self, limit: int = None, offset: int = 0, sort_by: str = 'row_number', 
                                sort_direction: str = 'DESC', filter_type: str = None, 
                                topic_filter: str = None) -> List[Dict]:
        """
        Get all content entries for the current account with optional sorting and filtering.
        
        Args:
            limit: Maximum number of entries to return (None = all)
            offset: Number of entries to skip
            sort_by: Field to sort by ('row_number', 'saved_time', 'posted_time', 'import_time')
            sort_direction: Sort direction ('ASC' or 'DESC')
            filter_type: Filter type ('ignored', 'uncategorized', 'categorized_undownloaded', 'error', or None for all)
            topic_filter: Topic name to filter by (or None for all topics)
        
        Returns:
            List of content entry dictionaries
        """
        try:
            entries = self.db.get_all_content_entries(
                limit=limit, 
                offset=offset, 
                sort_by=sort_by,
                sort_direction=sort_direction,
                filter_type=filter_type,
                topic_filter=topic_filter
            )
            # get_all_content_entries returns dict[id: entry], so iterate over values
            account_entries = [e for e in entries.values() if e.get('account_name') == self.account_name]
            logger.info(f"Retrieved {len(account_entries)} entries for {self.account_name} (limit={limit}, offset={offset}, sort={sort_by} {sort_direction}, filter={filter_type}, topic={topic_filter})")
            return account_entries
        except Exception as e:
            logger.error(f"Error getting account entries: {e}")
            return []
    
    def convert_entry_to_post(self, entry: Dict) -> Dict:
        """
        Convert database content entry format back to Instagram post format.
        
        Args:
            entry: Content entry from database
        
        Returns:
            Post dictionary in Instagram API format, or None if conversion fails
        """
        try:
            entry_id = entry.get('id', 'unknown')
            content_info = entry.get('ContentInformation', {})
            files_info = entry.get('FilesInformation', {})
            file_list = files_info.get('FileList', [])
            
            # Determine typename from content type
            content_type = entry.get('type', 'post')
            if not content_type:  # Handle NULL/empty type
                content_type = 'post'
            
            if content_type == 'reel':
                typename = 'GraphVideo'
            elif content_type == 'carousel':
                typename = 'GraphSidecar'
            else:
                typename = 'GraphImage'
            
            # Check if it's a video
            is_video = any(f.get('file_type') == 'video' for f in file_list)
            
            # entry_id IS the shortcode (no timestamp suffix is added when saving)
            # Shortcodes can contain underscores (e.g., C5zOI_yqnrD), so don't split
            shortcode_only = entry_id
            
            post = {
                'shortcode': shortcode_only,
                'url': entry.get('media_url', ''),
                'caption': entry.get('text', ''),
                'typename': typename,
                'date': content_info.get('date_added', ''),
                'owner_username': entry.get('account_name', self.account_name),
                'is_video': is_video,
                'media_count': len(file_list),
                'row_number': content_info.get('rowNumber', 0),  # Add row_number for sorting
                'download_status': content_info.get('downloadStatus', 'awaiting scan'),  # Include status
                'review_state': content_info.get('reviewState', 'not yet reviewed'),
                'is_duplicate': content_info.get('isDuplicate', False)
            }
            
            return post
        except Exception as e:
            logger.error(f"Error converting entry {entry.get('id', 'unknown')} to post: {e}", exc_info=True)
            return None
    
    def get_statistics(self) -> Dict:
        """Get statistics about saved content for this account using efficient COUNT queries."""
        try:
            # Use efficient COUNT queries instead of loading all entries
            total = self.db.get_content_count(filters=None)
            
            # Count by status using SQL queries (much faster than loading all entries)
            awaiting_scan = self.db.get_content_count(filters={'cdn_acquisition_status': 'awaiting scan'})
            downloaded = self.db.get_content_count(filters={'download_status': 'completed'})
            errors = self.db.get_content_count(filters={'download_status': 'failed'})
            
            stats = {
                'total': total,
                'awaiting_scan': awaiting_scan,
                'downloaded': downloaded,
                'errors': errors
            }
            
            logger.info(f"Statistics for {self.account_name}: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {'total': 0, 'awaiting_scan': 0, 'downloaded': 0, 'errors': 0}
