"""
SQL Server Database Manager for Instagram Downloader
Manages content entries, files, segments, and CDN discovery attempts
Multi-account support with account_name field
"""

import pyodbc
import json
import os
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class DatabaseManagerSQLServer:
    """Manages SQL Server database operations for Instagram content repository."""
    
    def __init__(self, user_dir: str, account_name: str = "sassenheimer", 
                 server: str = "localhost", 
                 database: str = "DOWNLOAD-SYSTEM",
                 username: str = "DOWLOAD-SYSTEM",
                 password: str = "DOWLOAD-SYSTEM-1971~"):
        """
        Initialize SQL Server database manager.
        
        Args:
            user_dir: User directory path (for compatibility, not used for SQL Server)
            account_name: Instagram account name for multi-account support
            server: SQL Server instance
            database: Database name
            username: SQL Server username
            password: SQL Server password
        """
        self.user_dir = user_dir
        self.account_name = account_name
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        self.connection = None
        self._local = threading.local()
        self._saved_posts_proc_ready = False
        
        # Build connection string with explicit collation
        self.connection_string = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"TrustServerCertificate=yes;"
            f"AutoTranslate=no;"  # Prevent automatic character translation
        )
        
        # Test connection
        self._get_connection()
    
    def _get_connection(self) -> pyodbc.Connection:
        """Get or create database connection (thread-safe)."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            try:
                self._local.connection = pyodbc.connect(self.connection_string, timeout=30)
                self._local.connection.autocommit = False  # Explicit transaction control
                
                # Set deterministic SQL Server session options required for
                # indexed views/computed columns/filtered indexes.
                cursor = self._local.connection.cursor()
                cursor.execute("SET ANSI_NULLS ON")
                cursor.execute("SET ANSI_PADDING ON")
                cursor.execute("SET ANSI_WARNINGS ON")
                cursor.execute("SET ARITHABORT ON")
                cursor.execute("SET CONCAT_NULL_YIELDS_NULL ON")
                cursor.execute("SET QUOTED_IDENTIFIER ON")
                cursor.execute("SET NUMERIC_ROUNDABORT OFF")
                cursor.close()
                
            except pyodbc.Error as e:
                raise Exception(f"Failed to connect to SQL Server: {e}")
        return self._local.connection
    
    def _dict_from_row(self, cursor, row) -> Dict:
        """Convert SQL Server row to dictionary."""
        if row is None:
            return None
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, row))
    
    def add_content_entry(self, entry: Dict[str, Any]) -> bool:
        """
        Add a new content entry to the database.
        
        Args:
            entry: Content entry dictionary with ContentInformation structure
            
        Returns:
            True if added successfully, False if duplicate
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        entry_id = entry.get('id')
        media_url = entry.get('media_url', '')
        
        # Check if already exists by ID
        cursor.execute('SELECT id FROM DL.content_entries WHERE id = ?', (entry_id,))
        if cursor.fetchone():
            return False  # Duplicate by ID
        
        # ALSO check by media_url to prevent duplicates with different IDs (e.g., timestamp suffixes)
        if media_url:
            cursor.execute('SELECT id FROM DL.content_entries WHERE media_url = ? AND account_name = ?', 
                          (media_url, self.account_name))
            if cursor.fetchone():
                logger.info(f"Duplicate detected by media_url: {media_url}")
                return False  # Duplicate by URL
        
        # Extract ContentInformation
        content_info = entry.get('ContentInformation', {})
        
        # Analyze files to determine content classification
        files_info = entry.get('FilesInformation', {})
        file_list = files_info.get('FileList', [])
        
        # Count video and image files
        content_count_videos = sum(1 for f in file_list if f.get('fileType') == 'video')
        content_count_images = sum(1 for f in file_list if f.get('fileType') == 'image')
        
        # Determine content_sub_type
        content_type = content_info.get('ContentType', 'post')
        content_sub_type = None
        
        if content_type == 'reel':
            content_sub_type = 'single-video'
        elif content_type in ('post', 'carousel'):
            if content_count_videos == 1 and content_count_images == 0:
                content_sub_type = 'single-video'
            elif content_count_images == 1 and content_count_videos == 0:
                content_sub_type = 'single-image'
            elif content_count_videos > 1 and content_count_images == 0:
                content_sub_type = 'carousel-videos-only'
            elif content_count_images > 1 and content_count_videos == 0:
                content_sub_type = 'carousel-images-only'
            elif content_count_videos > 0 and content_count_images > 0:
                content_sub_type = 'carousel-mixed-content'
        
        # Get next row_number
        cursor.execute('SELECT ISNULL(MAX(row_number), 0) + 1 FROM DL.content_entries WHERE account_name = ?', 
                      (self.account_name,))
        next_row_number = cursor.fetchone()[0]
        
        try:
            cursor.execute('''
                INSERT INTO DL.content_entries (
                    id, account_name, media_url, text, source, type, date_added,
                    content_type, content_sub_type, content_count_videos, content_count_images,
                    cdn_acquisition_status, download_status,
                    review_state, purge_status, is_duplicate, row_number,
                    has_instagram_issues, instagram_issue_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                entry_id,
                self.account_name,
                entry.get('media_url', ''),
                entry.get('text', ''),
                entry.get('Source', ''),
                entry.get('type', ''),
                content_info.get('date_added', datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                content_type,
                content_sub_type,
                content_count_videos,
                content_count_images,
                content_info.get('cdnAcquisitionStatus', 'awaiting scan'),
                content_info.get('downloadStatus', 'awaiting scan'),
                content_info.get('reviewState', 'not yet reviewed'),
                1 if content_info.get('purgeStatus', False) else 0,
                1 if content_info.get('isDuplicate', False) else 0,
                next_row_number,
                1 if content_info.get('has_instagram_issues', False) else 0,
                content_info.get('instagram_issue_notes')
            ))
            
            # Add files
            for file_entry in file_list:
                self._add_file_entry(cursor, entry_id, file_entry)
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to add content entry {entry_id}: {e}")

    def _ensure_saved_posts_batch_procedure(self):
        """Create or update fast cursor-based batch procedure for saved-post inserts."""
        if self._saved_posts_proc_ready:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE OR ALTER PROCEDURE DL.sp_insert_saved_posts_batch
                @account_name NVARCHAR(100),
                @posts_json NVARCHAR(MAX)
            AS
            BEGIN
                SET NOCOUNT ON;
                SET XACT_ABORT ON;

                DECLARE @results TABLE (
                    shortcode NVARCHAR(50) NOT NULL,
                    is_inserted BIT NOT NULL,
                    row_number INT NULL
                );

                DECLARE @batch TABLE (
                    shortcode NVARCHAR(50) NOT NULL,
                    media_url NVARCHAR(500) NOT NULL,
                    caption NVARCHAR(MAX) NULL,
                    source NVARCHAR(100) NULL,
                    entry_type NVARCHAR(50) NULL,
                    date_added DATETIME2 NULL,
                    content_type NVARCHAR(50) NOT NULL,
                    content_sub_type NVARCHAR(50) NULL,
                    content_count_videos INT NOT NULL,
                    content_count_images INT NOT NULL
                );

                INSERT INTO @batch (
                    shortcode,
                    media_url,
                    caption,
                    source,
                    entry_type,
                    date_added,
                    content_type,
                    content_sub_type,
                    content_count_videos,
                    content_count_images
                )
                SELECT
                    j.shortcode,
                    j.media_url,
                    j.caption,
                    COALESCE(j.source, 'Instagram Saved Posts'),
                    COALESCE(j.entry_type, j.content_type),
                    COALESCE(j.date_added, GETDATE()),
                    COALESCE(j.content_type, 'post'),
                    j.content_sub_type,
                    COALESCE(j.content_count_videos, 0),
                    COALESCE(j.content_count_images, 1)
                FROM OPENJSON(@posts_json)
                WITH (
                    shortcode NVARCHAR(50) '$.shortcode',
                    media_url NVARCHAR(500) '$.media_url',
                    caption NVARCHAR(MAX) '$.caption',
                    source NVARCHAR(100) '$.source',
                    entry_type NVARCHAR(50) '$.entry_type',
                    date_added DATETIME2 '$.date_added',
                    content_type NVARCHAR(50) '$.content_type',
                    content_sub_type NVARCHAR(50) '$.content_sub_type',
                    content_count_videos INT '$.content_count_videos',
                    content_count_images INT '$.content_count_images'
                ) j
                WHERE j.shortcode IS NOT NULL
                  AND LTRIM(RTRIM(j.shortcode)) <> ''
                  AND j.media_url IS NOT NULL
                  AND LTRIM(RTRIM(j.media_url)) <> '';

                BEGIN TRANSACTION;

                DECLARE
                    @shortcode NVARCHAR(50),
                    @media_url NVARCHAR(500),
                    @caption NVARCHAR(MAX),
                    @source NVARCHAR(100),
                    @entry_type NVARCHAR(50),
                    @date_added DATETIME2,
                    @content_type NVARCHAR(50),
                    @content_sub_type NVARCHAR(50),
                    @content_count_videos INT,
                    @content_count_images INT,
                    @next_row_number INT;

                SELECT @next_row_number = ISNULL(MAX(row_number), 0) + 1
                FROM DL.content_entries WITH (UPDLOCK, HOLDLOCK)
                WHERE account_name = @account_name;

                DECLARE post_cursor CURSOR LOCAL FAST_FORWARD FOR
                    SELECT
                        shortcode,
                        media_url,
                        caption,
                        source,
                        entry_type,
                        date_added,
                        content_type,
                        content_sub_type,
                        content_count_videos,
                        content_count_images
                    FROM @batch
                    ORDER BY shortcode;

                OPEN post_cursor;

                FETCH NEXT FROM post_cursor INTO
                    @shortcode,
                    @media_url,
                    @caption,
                    @source,
                    @entry_type,
                    @date_added,
                    @content_type,
                    @content_sub_type,
                    @content_count_videos,
                    @content_count_images;

                WHILE @@FETCH_STATUS = 0
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM DL.content_entries WITH (UPDLOCK, HOLDLOCK)
                        WHERE id = @shortcode
                           OR (account_name = @account_name AND media_url = @media_url)
                    )
                    BEGIN
                        INSERT INTO @results (shortcode, is_inserted, row_number)
                        VALUES (@shortcode, 0, NULL);
                    END
                    ELSE
                    BEGIN
                        INSERT INTO DL.content_entries (
                            id,
                            account_name,
                            media_url,
                            text,
                            source,
                            type,
                            date_added,
                            content_type,
                            content_sub_type,
                            content_count_videos,
                            content_count_images,
                            cdn_acquisition_status,
                            download_status,
                            review_state,
                            purge_status,
                            is_duplicate,
                            row_number,
                            has_instagram_issues,
                            instagram_issue_notes
                        )
                        VALUES (
                            @shortcode,
                            @account_name,
                            @media_url,
                            COALESCE(@caption, ''),
                            COALESCE(@source, 'Instagram Saved Posts'),
                            COALESCE(@entry_type, @content_type),
                            COALESCE(@date_added, GETDATE()),
                            COALESCE(@content_type, 'post'),
                            @content_sub_type,
                            COALESCE(@content_count_videos, 0),
                            COALESCE(@content_count_images, 1),
                            'awaiting scan',
                            'awaiting scan',
                            'not yet reviewed',
                            0,
                            0,
                            @next_row_number,
                            0,
                            NULL
                        );

                        INSERT INTO @results (shortcode, is_inserted, row_number)
                        VALUES (@shortcode, 1, @next_row_number);

                        SET @next_row_number = @next_row_number + 1;
                    END

                    FETCH NEXT FROM post_cursor INTO
                        @shortcode,
                        @media_url,
                        @caption,
                        @source,
                        @entry_type,
                        @date_added,
                        @content_type,
                        @content_sub_type,
                        @content_count_videos,
                        @content_count_images;
                END

                CLOSE post_cursor;
                DEALLOCATE post_cursor;

                COMMIT TRANSACTION;

                SELECT shortcode, is_inserted, row_number
                FROM @results;
            END
        ''')
        conn.commit()
        self._saved_posts_proc_ready = True

    def add_saved_posts_batch(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Insert saved posts quickly using a SQL cursor procedure with duplicate protection."""
        stats: Dict[str, Any] = {
            'saved': 0,
            'duplicates': 0,
            'errors': 0,
            'saved_shortcodes': [],
            'duplicate_shortcodes': [],
            'row_numbers': {},
        }

        if not posts:
            return stats

        self._ensure_saved_posts_batch_procedure()

        payload = []
        for post in posts:
            shortcode = str(post.get('shortcode') or '').strip()
            if not shortcode:
                stats['errors'] += 1
                continue

            typename = post.get('typename', 'GraphImage')
            if typename == 'GraphVideo':
                content_type = 'reel'
                content_sub_type = 'single-video'
                content_count_videos = 1
                content_count_images = 0
            elif typename == 'GraphSidecar':
                content_type = 'carousel'
                content_sub_type = None
                media_count = int(post.get('media_count', 1) or 1)
                # For mixed/unknown sidecar composition, default to image count for pending scan.
                content_count_videos = 0
                content_count_images = max(1, media_count)
            else:
                content_type = 'post'
                content_sub_type = 'single-image'
                content_count_videos = 0
                content_count_images = 1

            date_field = post.get('date')
            if isinstance(date_field, int):
                date_added = datetime.fromtimestamp(date_field).isoformat()
            elif isinstance(date_field, str) and date_field.strip():
                date_added = date_field.strip()
            else:
                date_added = datetime.now().isoformat()

            media_url = str(post.get('url') or '').strip()
            if not media_url:
                media_url = f"https://www.instagram.com/p/{shortcode}/"

            payload.append({
                'shortcode': shortcode,
                'media_url': media_url,
                'caption': post.get('caption', ''),
                'source': 'Instagram Saved Posts',
                'entry_type': content_type,
                'date_added': date_added,
                'content_type': content_type,
                'content_sub_type': content_sub_type,
                'content_count_videos': content_count_videos,
                'content_count_images': content_count_images,
            })

        if not payload:
            return stats

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'EXEC DL.sp_insert_saved_posts_batch @account_name = ?, @posts_json = ?',
                (self.account_name, json.dumps(payload, ensure_ascii=False))
            )
            rows = cursor.fetchall()
            conn.commit()
            for row in rows:
                shortcode = row[0]
                is_inserted = bool(row[1])
                row_number = row[2]
                if is_inserted:
                    stats['saved'] += 1
                    stats['saved_shortcodes'].append(shortcode)
                    if row_number is not None:
                        stats['row_numbers'][shortcode] = int(row_number)
                else:
                    stats['duplicates'] += 1
                    stats['duplicate_shortcodes'].append(shortcode)

            unmatched = len(payload) - len(rows)
            if unmatched > 0:
                stats['errors'] += unmatched

            return stats
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to batch insert saved posts: {e}")
    
    def _add_file_entry(self, cursor, content_id: str, file_entry: Dict[str, Any]):
        """Add a file entry (called within a transaction)."""
        cursor.execute('''
            INSERT INTO DL.files (
                content_id, file_number, cdn_url, cdn_mechanism,
                file_name, download_filename, file_caption, file_tags,
                file_type, file_quality, file_size_bytes,
                file_download_status, file_download_date,
                file_segment_count, file_assembly_status, file_save_status,
                file_destination_path, file_debug_path,
                has_audio, audio_url, audio_segment_count, xpv_asset_id,
                url_source_issue, url_auto_corrected, url_correction_log, user_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            content_id,
            file_entry.get('file_number', 1),
            file_entry.get('cdn_url', ''),
            file_entry.get('cdn_mechanism', ''),
            file_entry.get('file_name', ''),
            file_entry.get('download_filename', ''),
            file_entry.get('file_caption', ''),
            file_entry.get('file_tags', ''),
            file_entry.get('file_type', ''),
            file_entry.get('file_quality', 'high'),
            file_entry.get('file_size_bytes', 0),
            file_entry.get('file_download_status', 'awaiting'),
            file_entry.get('file_download_date'),
            file_entry.get('file_segment_count', 0),
            file_entry.get('file_assembly_status', 'awaiting'),
            file_entry.get('file_save_status', 'awaiting'),
            file_entry.get('file_destination_path', ''),
            file_entry.get('file_debug_path', ''),
            1 if file_entry.get('has_audio', False) else 0,
            file_entry.get('audio_url', ''),
            file_entry.get('audio_segment_count', 0),
            file_entry.get('xpv_asset_id', ''),
            file_entry.get('url_source_issue'),
            1 if file_entry.get('url_auto_corrected', False) else 0,
            file_entry.get('url_correction_log'),
            file_entry.get('user_notes', '')
        ))
        
        # Get the file_id
        cursor.execute('SELECT @@IDENTITY')
        file_id = cursor.fetchone()[0]
        
        # Add CDN discovery attempts
        cdn_attempts = file_entry.get('cdn_discovery_attempts', [])
        for attempt in cdn_attempts:
            cursor.execute('''
                INSERT INTO DL.cdn_discovery_attempts (
                    file_id, mechanism, success, cdn_url_result,
                    failure_reason, attempt_order
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                file_id,
                attempt.get('mechanism', ''),
                1 if attempt.get('success', False) else 0,
                attempt.get('cdn_url_result', ''),
                attempt.get('failure_reason', ''),
                attempt.get('attempt_order', 0)
            ))
        
        # Add segments
        segments = file_entry.get('segments', [])
        for segment in segments:
            cursor.execute('''
                INSERT INTO DL.segments (
                    file_id, segment_type, segment_url,
                    segment_size_bytes, segment_order, segment_download_status
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                file_id,
                segment.get('segment_type', 'video'),
                segment.get('segment_url', ''),
                segment.get('segment_size_bytes'),
                segment.get('segment_order', 0),
                segment.get('segment_download_status', 'pending')
            ))
    
    def _map_file_to_ui_format(self, file_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Map database file fields to UI-expected PascalCase format."""
        # Create a new dict with both formats for compatibility
        mapped = file_entry.copy()
        
        # Add PascalCase mappings that the UI expects
        mapped['FileNumber'] = file_entry.get('file_number')
        mapped['FileName'] = file_entry.get('file_name')
        mapped['FileType'] = file_entry.get('file_type')
        mapped['FileQuality'] = file_entry.get('file_quality')
        mapped['FileSizeBytes'] = file_entry.get('file_size_bytes')
        mapped['FileDownloadStatus'] = file_entry.get('file_download_status')
        mapped['FileSegmentCount'] = file_entry.get('file_segment_count')
        mapped['HasAudio'] = file_entry.get('has_audio')
        mapped['XpvAssetId'] = file_entry.get('xpv_asset_id')
        mapped['FileDestinationPath'] = file_entry.get('file_destination_path')
        mapped['FileCDNUrl'] = file_entry.get('cdn_url')
        mapped['FileCDNURLFoundViaMechanism'] = file_entry.get('cdn_mechanism')
        mapped['AudioSegmentCount'] = file_entry.get('audio_segment_count')
        mapped['FileCaption'] = file_entry.get('file_caption')
        mapped['FileTags'] = file_entry.get('file_tags')
        mapped['UserNotes'] = file_entry.get('user_notes', '')
        
        return mapped
    
    def get_content_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Get a content entry by ID with all associated data."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get content entry with topic_id via LEFT JOIN
        cursor.execute('''
            SELECT ce.*, ta.topic_id
            FROM DL.content_entries ce
            LEFT JOIN (
                SELECT content_id, MIN(topic_id) as topic_id
                FROM DL.topic_assignments
                GROUP BY content_id
            ) ta ON ce.id = ta.content_id
            WHERE ce.id = ?
        ''', (entry_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        entry = self._dict_from_row(cursor, row)
        
        # Get files
        cursor.execute('SELECT * FROM DL.files WHERE content_id = ? ORDER BY file_number', (entry_id,))
        files = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
        
        # For each file, get segments and CDN attempts
        for file_entry in files:
            file_id = file_entry['id']
            
            cursor.execute('SELECT * FROM DL.segments WHERE file_id = ? ORDER BY segment_order', (file_id,))
            file_entry['segments'] = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
            
            cursor.execute('SELECT * FROM DL.cdn_discovery_attempts WHERE file_id = ? ORDER BY attempt_order', (file_id,))
            file_entry['cdn_discovery_attempts'] = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
        
        # Map files to UI format (PascalCase)
        mapped_files = [self._map_file_to_ui_format(f) for f in files]
        
        # Build structure similar to SQLite version
        entry['ContentInformation'] = {
            'rowNumber': entry.get('row_number'),
            'date_added': entry.get('date_added'),
            'ContentType': entry.get('content_type'),
            'cdnAcquisitionStatus': entry.get('cdn_acquisition_status'),
            'downloadStatus': entry.get('download_status'),
            'reviewState': entry.get('review_state'),
            'purgeStatus': bool(entry.get('purge_status')),
            'isDuplicate': bool(entry.get('is_duplicate')),
            'topicID': entry.get('topic_id')  # Add topic_id to ContentInformation
        }

        entry['FilesInformation'] = {
            'FileList': mapped_files
        }
        
        # CRITICAL: Ensure 'shortcode' field exists for GUI compatibility
        # Database uses 'id' field, but GUI expects 'shortcode'
        if 'shortcode' not in entry and 'id' in entry:
            entry['shortcode'] = entry['id']

        return entry
    
    def update_content_entry(self, entry_id: str, updates: Dict[str, Any]) -> bool:
        """Update content entry fields."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Build dynamic UPDATE statement
        set_clauses = []
        values = []
        
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        
        if not set_clauses:
            return False
        
        values.append(entry_id)
        sql = f"UPDATE DL.content_entries SET {', '.join(set_clauses)}, updated_at = GETDATE() WHERE id = ?"
        
        try:
            cursor.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to update entry {entry_id}: {e}")
    
    def get_all_content_entries(self, account_name: str = None, limit: int = None, offset: int = 0, 
                                sort_by: str = 'row_number', sort_direction: str = 'DESC',
                                filter_type: str = None, topic_filter: str = None) -> Dict[str, Dict[str, Any]]:
        """
        Get all content entries for the account with files, with optional sorting and filtering.
        
        Args:
            account_name: Account to filter by (uses self.account_name if None)
            limit: Maximum number of entries to return (None = all)
            offset: Number of entries to skip
            sort_by: Field to sort by ('row_number', 'saved_time', 'posted_time', 'import_time')
            sort_direction: Sort direction ('ASC' or 'DESC')
            filter_type: Filter type ('ignored', 'uncategorized', 'categorized_undownloaded', 'error', or None for all)
            topic_filter: Topic name to filter by (or None for all topics)
        
        Returns:
            Dictionary of {entry_id: entry_dict} to match SQLite interface
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if account_name is None:
            account_name = self.account_name

        if topic_filter == '__NO_TOPICS__':
            return {}
        
        # Validate sort_by to prevent SQL injection
        valid_sort_fields = ['row_number', 'saved_time', 'posted_time', 'import_time']
        if sort_by not in valid_sort_fields:
            sort_by = 'row_number'
        
        # Validate sort_direction
        if sort_direction.upper() not in ['ASC', 'DESC']:
            sort_direction = 'DESC'
        
        # Build WHERE clause based on filters
        where_clauses = ['ce.account_name = ?']
        params = [account_name]
        
        if filter_type == 'ignored':
            where_clauses.append("ce.download_status = 'ignored'")
        elif filter_type == 'uncategorized':
            # Content with no topic assignments
            where_clauses.append('''NOT EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = ce.id AND ta.account_name = ?
            )''')
            params.append(account_name)
        elif filter_type == 'categorized_undownloaded':
            # Content with topic assigned but not downloaded (pink items)
            where_clauses.append('''EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = ce.id AND ta.account_name = ?
            )''')
            params.append(account_name)
            where_clauses.append("ce.download_status NOT IN ('downloaded', 'completed', 're-downloaded', 'ignored')")
        elif filter_type == 'error':
            # Items with error or failed status (red items)
            where_clauses.append("ce.download_status IN ('error', 'failed', 'success_with_issues')")
        elif filter_type == 'specific_topic_undownloaded':
            # Topic-assigned items that have not been downloaded yet
            where_clauses.append('''EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = ce.id AND ta.account_name = ?
            )''')
            params.append(account_name)
            where_clauses.append("ce.download_status NOT IN ('downloaded', 'completed', 're-downloaded', 'ignored')")
        
        if topic_filter:
            # Get topic_id from topic name
            cursor.execute('SELECT id FROM DL.topics WHERE topic_name = ?', (topic_filter,))
            topic_row = cursor.fetchone()
            if topic_row:
                topic_id = topic_row[0]
                where_clauses.append(f'''EXISTS (
                    SELECT 1 FROM DL.topic_assignments ta 
                    WHERE ta.content_id = ce.id 
                    AND ta.account_name = '{self.account_name}'
                    AND ta.topic_id = {topic_id}
                )''')
        
        where_clause = ' AND '.join(where_clauses)
        
        # Get content entries with optional pagination and sorting
        # LEFT JOIN to get topic_id (using MIN to get one topic per content item)
        if limit is not None:
            query = f'''
                SELECT ce.*, ta.topic_id
                FROM DL.content_entries ce
                LEFT JOIN (
                    SELECT content_id, MIN(topic_id) as topic_id
                    FROM DL.topic_assignments
                    WHERE account_name = ?
                    GROUP BY content_id
                ) ta ON ce.id = ta.content_id
                WHERE {where_clause}
                ORDER BY ce.{sort_by} {sort_direction}
                OFFSET ? ROWS
                FETCH NEXT ? ROWS ONLY
            '''
            cursor.execute(query, [account_name] + params + [offset, limit])
        else:
            query = f'''
                SELECT ce.*, ta.topic_id
                FROM DL.content_entries ce
                LEFT JOIN (
                    SELECT content_id, MIN(topic_id) as topic_id
                    FROM DL.topic_assignments
                    WHERE account_name = ?
                    GROUP BY content_id
                ) ta ON ce.id = ta.content_id
                WHERE {where_clause}
                ORDER BY ce.{sort_by} {sort_direction}
            '''
            cursor.execute(query, [account_name] + params)
        
        entries = {}
        entry_ids = []
        
        for row in cursor.fetchall():
            entry_dict = self._dict_from_row(cursor, row)
            entry_id = entry_dict.get('id')
            if entry_id:
                entry_ids.append(entry_id)
                
                # Build ContentInformation structure to match SQLite interface
                entry_dict['ContentInformation'] = {
                    'rowNumber': entry_dict.get('row_number'),
                    'date_added': entry_dict.get('date_added'),
                    'ContentType': entry_dict.get('content_type'),
                    'cdnAcquisitionStatus': entry_dict.get('cdn_acquisition_status'),
                    'downloadStatus': entry_dict.get('download_status'),
                    'reviewState': entry_dict.get('review_state'),
                    'purgeStatus': bool(entry_dict.get('purge_status')),
                    'isDuplicate': bool(entry_dict.get('is_duplicate')),
                    'topicID': entry_dict.get('topic_id')  # Add topic_id to ContentInformation
                }
                
                # Initialize FilesInformation with empty list (will be populated below)
                entry_dict['FilesInformation'] = {
                    'FileList': []
                }
                
                entries[entry_id] = entry_dict
        
        if not entry_ids:
            return entries
        
        # Load files for each entry (using individual queries for reliability)
        # Note: This could be optimized with table-valued parameters or temp tables
        # but this approach is simpler and works reliably with pyodbc
        files_by_entry = {}
        all_file_ids = []
        
        for entry_id in entry_ids:
            cursor.execute('''
                SELECT * FROM DL.files 
                WHERE content_id = ?
                ORDER BY file_number
            ''', (entry_id,))
            
            for row in cursor.fetchall():
                file_dict = self._dict_from_row(cursor, row)
                file_id = file_dict['id']
                
                if entry_id not in files_by_entry:
                    files_by_entry[entry_id] = []
                
                # Initialize segments and cdn_discovery_attempts
                file_dict['segments'] = []
                file_dict['cdn_discovery_attempts'] = []
                
                files_by_entry[entry_id].append(file_dict)
                all_file_ids.append(file_id)
        
        # Load segments for each file
        for file_id in all_file_ids:
            cursor.execute('''
                SELECT * FROM DL.segments 
                WHERE file_id = ?
                ORDER BY segment_order
            ''', (file_id,))
            
            segments = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
            
            # Find the file and add segments
            for content_id, file_list in files_by_entry.items():
                for file_entry in file_list:
                    if file_entry['id'] == file_id:
                        file_entry['segments'] = segments
                        break
        
        # Load CDN discovery attempts for each file
        for file_id in all_file_ids:
            cursor.execute('''
                SELECT * FROM DL.cdn_discovery_attempts 
                WHERE file_id = ?
                ORDER BY attempt_order
            ''', (file_id,))
            
            attempts = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
            
            # Find the file and add attempts
            for content_id, file_list in files_by_entry.items():
                for file_entry in file_list:
                    if file_entry['id'] == file_id:
                        file_entry['cdn_discovery_attempts'] = attempts
                        break
        
        # Assign files to their entries (map to UI format first)
        for entry_id, file_list in files_by_entry.items():
            if entry_id in entries:
                mapped_files = [self._map_file_to_ui_format(f) for f in file_list]
                entries[entry_id]['FilesInformation']['FileList'] = mapped_files
        
        # CRITICAL: Ensure 'shortcode' field exists in all entries for GUI compatibility
        # Database uses 'id' field, but GUI expects 'shortcode'
        for entry_id, entry in entries.items():
            if 'shortcode' not in entry and 'id' in entry:
                entry['shortcode'] = entry['id']
        
        return entries

    def get_content_entries_for_topic_with_flags(self, topic_id: int, account_name: str = None,
                                                 limit: int = None, offset: int = 0,
                                                 sort_by: str = 'row_number', sort_direction: str = 'DESC') -> Dict[str, Dict[str, Any]]:
        """
        Get content entries assigned to a topic or any of its descendants, including tri-state assignment flags.

        Returns:
            Dictionary of {entry_id: entry_dict} with extra fields:
            - assignment_topic_id
            - TreeUpdated
            - SiteUpdated
            - VidPrepUpdated
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if account_name is None:
            account_name = self.account_name

        valid_sort_fields = ['row_number', 'saved_time', 'posted_time', 'import_time']
        if sort_by not in valid_sort_fields:
            sort_by = 'row_number'

        if sort_direction.upper() not in ['ASC', 'DESC']:
            sort_direction = 'DESC'

        base_query = f'''
            WITH topic_scope AS (
                SELECT id
                FROM DL.topics
                WHERE id = ?

                UNION ALL

                SELECT child.id
                FROM DL.topics child
                INNER JOIN topic_scope parent_scope ON child.parent_topic_id = parent_scope.id
            ),
            topic_rows AS (
                SELECT
                    ta.account_name,
                    ta.topic_id,
                    ta.content_id,
                    ta.row_number,
                    ta.TreeUpdated,
                    ta.SiteUpdated,
                    ta.VidPrepUpdated,
                    ta.assigned_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY ta.account_name, COALESCE(CAST(ta.row_number AS NVARCHAR(50)), ta.content_id)
                        ORDER BY
                            CASE WHEN ta.topic_id = ? THEN 0 ELSE 1 END,
                            ta.assigned_at DESC
                    ) AS rn
                FROM DL.topic_assignments ta
                WHERE ta.account_name = ?
                  AND ta.topic_id IN (SELECT id FROM topic_scope)
            )
            SELECT
                ce.*,
                tr.topic_id AS assignment_topic_id,
                tr.TreeUpdated,
                tr.SiteUpdated,
                tr.VidPrepUpdated
            FROM topic_rows tr
            INNER JOIN DL.content_entries ce
                ON ce.account_name = tr.account_name
               AND (
                    (tr.row_number IS NOT NULL AND ce.row_number = tr.row_number)
                 OR (tr.row_number IS NULL AND ce.id = tr.content_id)
               )
            WHERE tr.rn = 1
            ORDER BY ce.{sort_by} {sort_direction}
        '''

        if limit is not None:
            query = base_query + '\nOFFSET ? ROWS FETCH NEXT ? ROWS ONLY'
            cursor.execute(query, (int(topic_id), int(topic_id), account_name, offset, limit))
        else:
            cursor.execute(base_query, (int(topic_id), int(topic_id), account_name))

        entries = {}
        entry_ids = []

        for row in cursor.fetchall():
            entry_dict = self._dict_from_row(cursor, row)
            entry_id = entry_dict.get('id')
            if not entry_id:
                continue

            entry_dict['ContentInformation'] = {
                'rowNumber': entry_dict.get('row_number'),
                'date_added': entry_dict.get('date_added'),
                'ContentType': entry_dict.get('content_type'),
                'cdnAcquisitionStatus': entry_dict.get('cdn_acquisition_status'),
                'downloadStatus': entry_dict.get('download_status'),
                'reviewState': entry_dict.get('review_state'),
                'purgeStatus': bool(entry_dict.get('purge_status')),
                'isDuplicate': bool(entry_dict.get('is_duplicate')),
                'topicID': entry_dict.get('assignment_topic_id'),
            }
            entry_dict['FilesInformation'] = {'FileList': []}
            if 'shortcode' not in entry_dict and 'id' in entry_dict:
                entry_dict['shortcode'] = entry_dict['id']

            entries[entry_id] = entry_dict
            entry_ids.append(entry_id)

        if not entry_ids:
            return entries

        files_by_entry = {}
        all_file_ids = []

        for entry_id in entry_ids:
            cursor.execute('''
                SELECT * FROM DL.files
                WHERE content_id = ?
                ORDER BY file_number
            ''', (entry_id,))

            for row in cursor.fetchall():
                file_dict = self._dict_from_row(cursor, row)
                file_id = file_dict['id']

                if entry_id not in files_by_entry:
                    files_by_entry[entry_id] = []

                file_dict['segments'] = []
                file_dict['cdn_discovery_attempts'] = []
                files_by_entry[entry_id].append(file_dict)
                all_file_ids.append(file_id)

        for file_id in all_file_ids:
            cursor.execute('''
                SELECT * FROM DL.segments
                WHERE file_id = ?
                ORDER BY segment_order
            ''', (file_id,))
            segments = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]

            for content_id, file_list in files_by_entry.items():
                for file_entry in file_list:
                    if file_entry['id'] == file_id:
                        file_entry['segments'] = segments
                        break

        for file_id in all_file_ids:
            cursor.execute('''
                SELECT * FROM DL.cdn_discovery_attempts
                WHERE file_id = ?
                ORDER BY attempt_order
            ''', (file_id,))
            attempts = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]

            for content_id, file_list in files_by_entry.items():
                for file_entry in file_list:
                    if file_entry['id'] == file_id:
                        file_entry['cdn_discovery_attempts'] = attempts
                        break

        for entry_id, file_list in files_by_entry.items():
            if entry_id in entries:
                mapped_files = [self._map_file_to_ui_format(f) for f in file_list]
                entries[entry_id]['FilesInformation']['FileList'] = mapped_files

        return entries
    
    def delete_content_entry(self, entry_id: str) -> bool:
        """Delete a content entry (CASCADE will handle files, segments, etc.)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM DL.content_entries WHERE id = ?', (entry_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to delete entry {entry_id}: {e}")
    
    def reset_content_entry(self, entry_id: str) -> bool:
        """
        Reset a single content entry to unscanned/undownloaded state.
        Efficiently updates using SQL without loading/converting entire entry.
        
        This operation clears:
        - All files for this content entry
        - All segments for those files (CASCADE DELETE)
        - All cdn_discovery_attempts for those files (CASCADE DELETE)
        - Sets content_type based on URL (reel vs post)
        
        Args:
            entry_id: Content entry ID to reset
            
        Returns:
            True if entry was reset, False if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if entry exists and get media_url
            cursor.execute('SELECT id, media_url FROM DL.content_entries WHERE id = ?', (entry_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            media_url = row[1] if len(row) > 1 else ''
            
            # Determine content type from URL
            if '/reel/' in media_url or '/reels/' in media_url:
                content_type = 'reel'
            else:
                content_type = 'post'  # Default to post, will be updated to carousel if needed when scanned
            
            # Update content entry status and content_type
            cursor.execute('''
                UPDATE DL.content_entries 
                SET download_status = 'Unattempted',
                    review_state = 'not yet reviewed',
                    content_type = ?,
                    updated_at = GETDATE()
                WHERE id = ?
            ''', (content_type, entry_id))
            
            # Delete all files for this entry
            # CASCADE DELETE automatically removes:
            #   - All segments WHERE file_id IN (deleted files)
            #   - All cdn_discovery_attempts WHERE file_id IN (deleted files)
            cursor.execute('DELETE FROM DL.files WHERE content_id = ?', (entry_id,))
            
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to reset entry {entry_id}: {e}")
    
    def bulk_update_review_state(self, review_state: str) -> int:
        """
        Bulk update review state for all entries in the current account.
        
        Args:
            review_state: The review state to set (e.g., 'approved', 'rejected', 'not yet reviewed')
            
        Returns:
            Number of entries updated
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE DL.content_entries 
                SET review_state = ?, updated_at = GETDATE()
                WHERE account_name = ?
            ''', (review_state, self.account_name))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to bulk update review state: {e}")
    
    def reset_all_content_entries(self) -> int:
        """
        Reset all content entries to unscanned/undownloaded state.
        Uses bulk SQL operations for maximum efficiency.
        
        This operation clears:
        - All files in the repository for this account
        - All segments (CASCADE DELETE)
        - All cdn_discovery_attempts (CASCADE DELETE)
        
        Returns:
            Number of entries reset
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Count entries for this account
            cursor.execute('SELECT COUNT(*) FROM DL.content_entries WHERE account_name = ?', (self.account_name,))
            count = cursor.fetchone()[0]
            
            if count == 0:
                return 0
            
            # Bulk update all content entries for this account
            # Set content_type based on URL (reel if contains '/reel/', otherwise 'post')
            cursor.execute('''
                UPDATE DL.content_entries 
                SET download_status = 'Unattempted',
                    review_state = 'not yet reviewed',
                    content_type = CASE 
                        WHEN media_url LIKE '%/reel/%' OR media_url LIKE '%/reels/%' THEN 'reel'
                        ELSE 'post'
                    END,
                    updated_at = GETDATE()
                WHERE account_name = ?
            ''', (self.account_name,))
            
            # Delete all files for this account's content entries
            # CASCADE DELETE automatically removes:
            #   - All segments
            #   - All cdn_discovery_attempts
            cursor.execute('''
                DELETE FROM DL.files 
                WHERE content_id IN (
                    SELECT id FROM DL.content_entries WHERE account_name = ?
                )
            ''', (self.account_name,))
            
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to reset all entries: {e}")
    
    def get_content_count(self, filters: Dict[str, Any] = None, filter_type: str = None, 
                          topic_filter: str = None) -> int:
        """
        Get count of content entries with optional filters.
        
        Args:
            filters: Legacy dict filters (for backward compatibility)
            filter_type: Filter type ('ignored', 'uncategorized', 'categorized_undownloaded', 'error', or None)
            topic_filter: Topic name to filter by (or None)
        
        Returns:
            Count of matching entries
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if topic_filter == '__NO_TOPICS__':
            return 0
        
        where_clauses = [f"account_name = '{self.account_name}'"]
        
        # Legacy filter support
        if filters:
            for key, value in filters.items():
                if value is not None:
                    where_clauses.append(f"{key} = '{value}'")
        
        # New filter type support
        if filter_type == 'ignored':
            where_clauses.append("download_status = 'ignored'")
        elif filter_type == 'uncategorized':
            where_clauses.append('''NOT EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = DL.content_entries.id 
                AND ta.account_name = ''' + f"'{self.account_name}'" + '''
            )''')
        elif filter_type == 'categorized_undownloaded':
            # Content with topic assigned but not downloaded (pink items)
            where_clauses.append('''EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = DL.content_entries.id 
                AND ta.account_name = ''' + f"'{self.account_name}'" + '''
            )''')
            where_clauses.append("download_status NOT IN ('downloaded', 'completed', 're-downloaded', 'ignored')")
        elif filter_type == 'error':
            # Items with error or failed status (red items)
            where_clauses.append("download_status IN ('error', 'failed', 'success_with_issues')")
        elif filter_type == 'specific_topic_undownloaded':
            # Topic-assigned items that have not been downloaded yet
            where_clauses.append('''EXISTS (
                SELECT 1 FROM DL.topic_assignments ta 
                WHERE ta.content_id = DL.content_entries.id 
                AND ta.account_name = ''' + f"'{self.account_name}'" + '''
            )''')
            where_clauses.append("download_status NOT IN ('downloaded', 'completed', 're-downloaded', 'ignored')")
        
        # Topic filter support
        if topic_filter:
            # Get topic_id from topic name
            cursor.execute('SELECT id FROM DL.topics WHERE topic_name = ?', (topic_filter,))
            topic_row = cursor.fetchone()
            if topic_row:
                topic_id = topic_row[0]
                where_clauses.append(f'''EXISTS (
                    SELECT 1 FROM DL.topic_assignments ta 
                    WHERE ta.content_id = DL.content_entries.id 
                    AND ta.account_name = '{self.account_name}'
                    AND ta.topic_id = {topic_id}
                )''')
        
        sql = f"SELECT COUNT(*) FROM DL.content_entries WHERE {' AND '.join(where_clauses)}"
        cursor.execute(sql)
        return cursor.fetchone()[0]

    def get_thumbnail_scan_entries(self) -> List[Dict[str, Any]]:
        """Return lightweight entry rows for thumbnail scanning without heavy joins."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                ce.id,
                ce.account_name,
                ce.text,
                ce.type,
                CASE
                    WHEN ce.type = 'reel' THEN 'GraphVideo'
                    WHEN ce.type = 'carousel' THEN 'GraphSidecar'
                    ELSE 'GraphImage'
                END AS typename
            FROM DL.content_entries ce
            WHERE ce.account_name = ?
            ORDER BY ce.row_number ASC
        ''', (self.account_name,))

        rows = []
        for row in cursor.fetchall():
            entry_id = (row[0] or '').strip() if row[0] else ''
            if not entry_id:
                continue

            content_type = (row[3] or '').strip().lower() if row[3] else ''
            if content_type == 'reel':
                typename = 'GraphVideo'
            elif content_type == 'carousel':
                typename = 'GraphSidecar'
            else:
                typename = 'GraphImage'

            rows.append({
                'id': entry_id,
                'shortcode': entry_id,
                'account_name': row[1],
                'text': row[2] or '',
                'type': content_type,
                'typename': typename,
            })

        return rows

    def get_entries_missing_thumbnails(self) -> List[Dict[str, Any]]:
        """Return lightweight entries that do not yet have a thumbnail record."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                ce.id,
                ce.account_name,
                ce.text,
                ce.content_type,
                fhint.file_destination_path
            FROM DL.content_entries ce
            LEFT JOIN DL.thumbnails t
                ON t.content_id = ce.id
            OUTER APPLY (
                SELECT TOP 1 f.file_destination_path
                FROM DL.files f
                WHERE f.content_id = ce.id
                  AND f.file_destination_path IS NOT NULL
                  AND LTRIM(RTRIM(f.file_destination_path)) <> ''
                ORDER BY
                    CASE
                        WHEN f.file_download_status IN ('completed', 'downloaded', 're-downloaded') THEN 0
                        ELSE 1
                    END,
                    f.file_number ASC
            ) fhint
            WHERE ce.account_name = ?
              AND t.thumbnail_id IS NULL
            ORDER BY ce.row_number ASC
        ''', (self.account_name,))

        rows = []
        for row in cursor.fetchall():
            entry_id = (row[0] or '').strip() if row[0] else ''
            if not entry_id:
                continue

            content_type = (row[3] or '').strip().lower() if row[3] else ''
            if content_type == 'reel':
                typename = 'GraphVideo'
            elif content_type == 'carousel':
                typename = 'GraphSidecar'
            else:
                typename = 'GraphImage'

            rows.append({
                'id': entry_id,
                'shortcode': entry_id,
                'account_name': row[1],
                'text': row[2] or '',
                'type': content_type,
                'typename': typename,
                'local_media_path': row[4] or None,
            })

        return rows
    
    def bulk_update_download_status(self, entry_ids: List[str], status: str) -> int:
        """Bulk update download status."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            placeholders = ','.join(['?' for _ in entry_ids])
            cursor.execute(f'''
                UPDATE DL.content_entries 
                SET download_status = ?, updated_at = GETDATE()
                WHERE id IN ({placeholders})
            ''', [status] + entry_ids)
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to bulk update: {e}")
    
    def get_setting(self, key: str) -> Optional[str]:
        """Get a setting value. Automatically deserializes JSON strings and handles booleans."""
        import json
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT [value] FROM DL.settings WHERE [key] = ?', (key,))
        row = cursor.fetchone()
        if not row:
            return None
        
        value_str = row[0]
        
        # Handle boolean string representations
        if value_str in ('0', '1'):
            return value_str == '1'
        if value_str.lower() in ('true', 'false'):
            return value_str.lower() == 'true'
        
        # Try to deserialize JSON
        try:
            return json.loads(value_str)
        except:
            return value_str
    
    def get_settings(self):
        """Get all settings as dictionary."""
        import json
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT [key], [value] FROM DL.settings')
        rows = cursor.fetchall()
        
        settings = {}
        for row in rows:
            key, value_str = row[0], row[1]
            
            # Handle boolean string representations
            if value_str in ('0', '1'):
                settings[key] = value_str == '1'
            elif value_str.lower() in ('true', 'false'):
                settings[key] = value_str.lower() == 'true'
            else:
                # Try to deserialize JSON
                try:
                    settings[key] = json.loads(value_str)
                except:
                    settings[key] = value_str
        
        return settings
    
    def set_setting(self, key: str, value):
        """Set a setting value. Automatically serializes dicts/lists to JSON, booleans to '0'/'1'."""
        import json
        
        # Serialize complex types and booleans
        if isinstance(value, bool):
            value_str = '1' if value else '0'
        elif isinstance(value, (dict, list)):
            value_str = json.dumps(value)
        else:
            value_str = str(value) if value is not None else ''
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                MERGE DL.settings AS target
                USING (SELECT ? AS [key], ? AS [value]) AS source
                ON target.[key] = source.[key]
                WHEN MATCHED THEN
                    UPDATE SET [value] = source.[value], updated_at = GETDATE()
                WHEN NOT MATCHED THEN
                    INSERT ([key], [value]) VALUES (source.[key], source.[value]);
            ''', (key, value_str))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to set setting {key}: {e}")
    
    def get_topic(self, topic_id: int) -> Optional[Dict[str, Any]]:
        """Get a topic by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM DL.topics WHERE id = ?', (topic_id,))
        row = cursor.fetchone()
        
        if row:
            return self._dict_from_row(cursor, row)
        return None
    
    def get_all_topics(self) -> List[Dict[str, Any]]:
        """Get all topics ordered by parent and display_order."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM DL.topics 
            ORDER BY parent_topic_id, display_order, topic_name
        ''')
        
        return [self._dict_from_row(cursor, row) for row in cursor.fetchall()]

    def get_topics_with_undownloaded_counts(self, account_name: str = None) -> List[Dict[str, Any]]:
        """Get topics that have undownloaded items, ordered alphabetically by topic name."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if account_name is None:
            account_name = self.account_name

        cursor.execute('''
            SELECT
                t.id,
                t.topic_name,
                t.parent_topic_id,
                COUNT(DISTINCT ta.content_id) AS undownloaded_count
            FROM DL.topics t
            INNER JOIN DL.topic_assignments ta
                ON ta.topic_id = t.id
               AND ta.account_name = ?
            INNER JOIN DL.content_entries ce
                ON ce.id = ta.content_id
               AND ce.account_name = ?
            WHERE ce.download_status NOT IN ('downloaded', 'completed', 're-downloaded')
            GROUP BY t.id, t.topic_name, t.parent_topic_id
            HAVING COUNT(DISTINCT ta.content_id) > 0
            ORDER BY t.topic_name ASC
        ''', (account_name, account_name))

        topics = []
        for row in cursor.fetchall():
            topics.append({
                'id': row[0],
                'topic_name': row[1],
                'parent_topic_id': row[2],
                'undownloaded_count': row[3],
            })

        return topics
    
    def get_default_approval_topic(self) -> Optional[Dict[str, Any]]:
        """
        Get the default approval topic set by the user.
        
        Returns:
            Topic dict if default is set, None otherwise
        """
        settings = self.get_settings()
        topic_id = settings.get('default_approval_topic')
        
        if topic_id is not None:
            # Convert to int if it's a string
            try:
                topic_id = int(topic_id)
            except (ValueError, TypeError):
                return None
            return self.get_topic(topic_id)
        return None
    
    def set_default_approval_topic(self, topic_id: Optional[int]):
        """
        Set the default approval topic.
        
        Args:
            topic_id: Topic ID to set as default, or None to clear
        """
        if topic_id is None:
            # Clear default
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM DL.settings WHERE [key] = ?', ('default_approval_topic',))
            conn.commit()
        else:
            # Verify topic exists
            topic = self.get_topic(topic_id)
            if topic:
                self.set_setting('default_approval_topic', str(topic_id))
    
    def get_topic_item_counts(self, account_name: str = None) -> Dict[int, int]:
        """
        Get count of content items assigned to each topic.
        
        Args:
            account_name: Account to filter by (uses self.account_name if None)
        
        Returns:
            Dictionary of {topic_id: count}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if account_name is None:
            account_name = self.account_name
        
        cursor.execute('''
            SELECT topic_id, COUNT(*) as item_count
            FROM DL.content_entries
            WHERE account_name = ? AND topic_id IS NOT NULL
            GROUP BY topic_id
        ''', (account_name,))
        
        counts = {}
        for row in cursor.fetchall():
            topic_id = row[0]
            item_count = row[1]
            counts[topic_id] = item_count
        
        return counts
    
    def ensure_topic_assignments_table(self):
        """Create the topic_assignments table if it doesn't exist (many-to-many relationship)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.tables t 
                          JOIN sys.schemas s ON t.schema_id = s.schema_id 
                          WHERE s.name = 'DL' AND t.name = 'topic_assignments')
            BEGIN
                CREATE TABLE DL.topic_assignments (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    account_name NVARCHAR(100) NOT NULL,
                    content_id NVARCHAR(50) NOT NULL,
                    row_number INT NULL,
                    topic_id INT NOT NULL,
                    assigned_at DATETIME2 DEFAULT GETDATE(),
                    file_movement_status NVARCHAR(20) DEFAULT 'Pending' CHECK (file_movement_status IN ('Pending', 'In Process', 'Complete', 'Error')),
                    file_movement_error NVARCHAR(500) NULL,
                    file_movement_updated_at DATETIME2 NULL,
                    CONSTRAINT FK_topic_assignments_topics FOREIGN KEY (topic_id) REFERENCES DL.topics(id) ON DELETE CASCADE,
                    CONSTRAINT UQ_topic_assignment UNIQUE (account_name, content_id, topic_id)
                )
            END
        ''')
        conn.commit()
        
        # Add columns to existing table if they don't exist (one at a time to avoid syntax issues)
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'row_number')
            BEGIN
                ALTER TABLE DL.topic_assignments
                ADD row_number INT NULL
            END
        ''')
        conn.commit()

        # Backfill row_number from content_entries for existing assignments.
        cursor.execute('''
            UPDATE ta
            SET ta.row_number = ce.row_number
            FROM DL.topic_assignments ta
            INNER JOIN DL.content_entries ce
                ON ce.account_name = ta.account_name
               AND ce.id = ta.content_id
            WHERE ta.row_number IS NULL
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE object_id = OBJECT_ID('DL.topic_assignments')
                  AND name = 'IX_topic_assignments_account_row_topic'
            )
            BEGIN
                CREATE NONCLUSTERED INDEX IX_topic_assignments_account_row_topic
                ON DL.topic_assignments (account_name, row_number, topic_id)
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'file_movement_status')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD file_movement_status NVARCHAR(20) DEFAULT 'Pending'
            END
        ''')
        conn.commit()
        
        # Add check constraint if column exists but constraint doesn't
        try:
            cursor.execute('''
                IF EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'file_movement_status')
                AND NOT EXISTS (SELECT * FROM sys.check_constraints 
                               WHERE parent_object_id = OBJECT_ID('DL.topic_assignments')
                               AND name = 'CHK_file_movement_status')
                BEGIN
                    ALTER TABLE DL.topic_assignments 
                    ADD CONSTRAINT CHK_file_movement_status 
                    CHECK (file_movement_status IN ('Pending', 'In Process', 'Complete', 'Error'))
                END
            ''')
            conn.commit()
        except:
            pass  # Constraint might already exist with different name
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'file_movement_error')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD file_movement_error NVARCHAR(500) NULL
            END
        ''')
        conn.commit()
        
        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'file_movement_updated_at')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD file_movement_updated_at DATETIME2 NULL
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'TreeUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD TreeUpdated BIT NOT NULL CONSTRAINT DF_topic_assignments_TreeUpdated DEFAULT 0
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'SiteUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD SiteUpdated BIT NOT NULL CONSTRAINT DF_topic_assignments_SiteUpdated DEFAULT 0
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns 
                          WHERE object_id = OBJECT_ID('DL.topic_assignments') 
                          AND name = 'VidPrepUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments 
                ADD VidPrepUpdated BIT NOT NULL CONSTRAINT DF_topic_assignments_VidPrepUpdated DEFAULT 0
            END
        ''')
        conn.commit()

        # Upgrade flags to 3-state values (0=To-Do, 1=Done, 2=Ignored).
        cursor.execute('''
            IF EXISTS (
                SELECT 1
                FROM sys.columns c
                JOIN sys.types t ON c.user_type_id = t.user_type_id
                WHERE c.object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'TreeUpdated'
                  AND t.name = 'bit'
            )
            BEGIN
                DECLARE @df_name_tree NVARCHAR(128)
                SELECT @df_name_tree = dc.name
                FROM sys.default_constraints dc
                JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
                WHERE dc.parent_object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'TreeUpdated'

                IF @df_name_tree IS NOT NULL
                    EXEC('ALTER TABLE DL.topic_assignments DROP CONSTRAINT ' + QUOTENAME(@df_name_tree))

                ALTER TABLE DL.topic_assignments ALTER COLUMN TreeUpdated TINYINT NOT NULL
                ALTER TABLE DL.topic_assignments ADD CONSTRAINT DF_topic_assignments_TreeUpdated DEFAULT 0 FOR TreeUpdated
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF EXISTS (
                SELECT 1
                FROM sys.columns c
                JOIN sys.types t ON c.user_type_id = t.user_type_id
                WHERE c.object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'VidPrepUpdated'
                  AND t.name = 'bit'
            )
            BEGIN
                DECLARE @df_name_prep NVARCHAR(128)
                SELECT @df_name_prep = dc.name
                FROM sys.default_constraints dc
                JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
                WHERE dc.parent_object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'VidPrepUpdated'

                IF @df_name_prep IS NOT NULL
                    EXEC('ALTER TABLE DL.topic_assignments DROP CONSTRAINT ' + QUOTENAME(@df_name_prep))

                ALTER TABLE DL.topic_assignments ALTER COLUMN VidPrepUpdated TINYINT NOT NULL
                ALTER TABLE DL.topic_assignments ADD CONSTRAINT DF_topic_assignments_VidPrepUpdated DEFAULT 0 FOR VidPrepUpdated
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF EXISTS (
                SELECT 1
                FROM sys.columns c
                JOIN sys.types t ON c.user_type_id = t.user_type_id
                WHERE c.object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'SiteUpdated'
                  AND t.name = 'bit'
            )
            BEGIN
                DECLARE @df_name_site NVARCHAR(128)
                SELECT @df_name_site = dc.name
                FROM sys.default_constraints dc
                JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
                WHERE dc.parent_object_id = OBJECT_ID('DL.topic_assignments')
                  AND c.name = 'SiteUpdated'

                IF @df_name_site IS NOT NULL
                    EXEC('ALTER TABLE DL.topic_assignments DROP CONSTRAINT ' + QUOTENAME(@df_name_site))

                ALTER TABLE DL.topic_assignments ALTER COLUMN SiteUpdated TINYINT NOT NULL
                ALTER TABLE DL.topic_assignments ADD CONSTRAINT DF_topic_assignments_SiteUpdated DEFAULT 0 FOR SiteUpdated
            END
        ''')
        conn.commit()

        # Ensure values stay in 0/1/2 domain.
        cursor.execute('''
            IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CHK_topic_assignments_TreeUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments
                ADD CONSTRAINT CHK_topic_assignments_TreeUpdated CHECK (TreeUpdated IN (0, 1, 2))
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CHK_topic_assignments_SiteUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments
                ADD CONSTRAINT CHK_topic_assignments_SiteUpdated CHECK (SiteUpdated IN (0, 1, 2))
            END
        ''')
        conn.commit()

        cursor.execute('''
            IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CHK_topic_assignments_VidPrepUpdated')
            BEGIN
                ALTER TABLE DL.topic_assignments
                ADD CONSTRAINT CHK_topic_assignments_VidPrepUpdated CHECK (VidPrepUpdated IN (0, 1, 2))
            END
        ''')
        conn.commit()
        logger.info("Ensured DL.topic_assignments table exists with file movement tracking columns")

    def _resolve_content_row_number(self, content_id: Any, account_name: str = None) -> Optional[int]:
        """Resolve row_number for a content identifier (shortcode/id or row number)."""
        if account_name is None:
            account_name = self.account_name

        if content_id is None:
            return None

        # If caller already passed a row number, use it.
        if isinstance(content_id, int):
            return content_id

        content_id_str = str(content_id).strip()
        if not content_id_str:
            return None

        # Numeric string may already be a row number.
        if content_id_str.isdigit():
            try:
                return int(content_id_str)
            except ValueError:
                pass

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT row_number
                FROM DL.content_entries
                WHERE account_name = ? AND id = ?
            ''', (account_name, content_id_str))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        except Exception as e:
            logger.debug(f"Failed to resolve row_number for content_id {content_id}: {e}")

        return None

    def _resolve_content_shortcode(self, content_ref: Any, account_name: str = None) -> Optional[str]:
        """Resolve shortcode/id for a content reference (shortcode/id or row number)."""
        if account_name is None:
            account_name = self.account_name

        if content_ref is None:
            return None

        # If caller passed shortcode/id directly, use it as-is.
        if not isinstance(content_ref, int):
            content_ref_str = str(content_ref).strip()
            if not content_ref_str:
                return None
            if not content_ref_str.isdigit():
                return content_ref_str
            try:
                content_ref = int(content_ref_str)
            except ValueError:
                return content_ref_str

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id
                FROM DL.content_entries
                WHERE account_name = ? AND row_number = ?
            ''', (account_name, int(content_ref)))
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception as e:
            logger.debug(f"Failed to resolve shortcode for content_ref {content_ref}: {e}")

        return None
    
    def add_topic_assignment(self, content_id: str, topic_id: int, account_name: str = None) -> bool:
        """
        Assign a topic to content (many-to-many).
        
        Args:
            content_id: Content shortcode
            topic_id: Topic ID to assign
            account_name: Account name (uses self.account_name if None)
        
        Returns:
            True if successful
        """
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO DL.topic_assignments (account_name, content_id, row_number, topic_id, file_movement_status)
                VALUES (?, ?, ?, ?, 'Pending')
            ''', (account_name, content_id, row_number, topic_id))
            conn.commit()
            return True
        except Exception as e:
            # Duplicate assignment is fine (unique constraint)
            if 'UNIQUE' in str(e).upper() or 'duplicate' in str(e).lower():
                return True
            logger.error(f"Error adding topic assignment: {e}")
            return False
    
    def remove_topic_assignment(self, content_id: str, topic_id: int, account_name: str = None) -> bool:
        """Remove a topic assignment from content."""
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM DL.topic_assignments
                                WHERE account_name = ? AND topic_id = ?
                                    AND (
                                                (row_number IS NOT NULL AND row_number = ?)
                                         OR (content_id = ?)
                                    )
                        ''', (account_name, topic_id, row_number, content_shortcode))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing topic assignment: {e}")
            return False
    
    def get_content_topics(self, content_id: str, account_name: str = None) -> List[int]:
        """Get all topic IDs assigned to a content item."""
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT topic_id FROM DL.topic_assignments
                        WHERE account_name = ?
                            AND (
                                        (row_number IS NOT NULL AND row_number = ?)
                                 OR (content_id = ?)
                            )
            ORDER BY assigned_at
                ''', (account_name, row_number, content_shortcode))
        
        return [row[0] for row in cursor.fetchall()]
    
    def clear_content_topics(self, content_id: str, account_name: str = None) -> bool:
        """Remove all topic assignments from a content item."""
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM DL.topic_assignments
                                WHERE account_name = ?
                                    AND (
                                                (row_number IS NOT NULL AND row_number = ?)
                                         OR (content_id = ?)
                                    )
                        ''', (account_name, row_number, content_shortcode))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error clearing topic assignments: {e}")
            return False
    
    def get_topic_item_counts_v2(self, account_name: str = None) -> Dict[int, int]:
        """
        Get count of content items assigned to each topic (using many-to-many table).
        
        Args:
            account_name: Account to filter by (uses self.account_name if None)
        
        Returns:
            Dictionary of {topic_id: count}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if account_name is None:
            account_name = self.account_name
        
        cursor.execute('''
            SELECT topic_id,
                   COUNT(DISTINCT COALESCE(CAST(row_number AS NVARCHAR(50)), content_id)) as item_count
            FROM DL.topic_assignments
            WHERE account_name = ?
            GROUP BY topic_id
        ''', (account_name,))
        
        counts = {}
        for row in cursor.fetchall():
            topic_id = row[0]
            item_count = row[1]
            counts[topic_id] = item_count
        
        return counts
    
    def get_topic_pending_download_counts(self, account_name: str = None) -> Dict[int, int]:
        """
        Get count of content items awaiting download for each topic (using many-to-many table).
        Items with download_status != 'completed' are considered pending.
        
        Args:
            account_name: Account to filter by (uses self.account_name if None)
        
        Returns:
            Dictionary of {topic_id: pending_count}
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if account_name is None:
            account_name = self.account_name
        
        cursor.execute('''
            SELECT ta.topic_id,
                   COUNT(DISTINCT COALESCE(CAST(ta.row_number AS NVARCHAR(50)), ta.content_id)) as pending_count
            FROM DL.topic_assignments ta
            INNER JOIN DL.content_entries ce
                ON ta.account_name = ce.account_name
               AND (
                    (ta.row_number IS NOT NULL AND ta.row_number = ce.row_number)
                 OR (ta.row_number IS NULL AND ta.content_id = ce.id)
               )
            WHERE ta.account_name = ?
            AND ce.download_status != 'completed'
            GROUP BY ta.topic_id
        ''', (account_name,))
        
        counts = {}
        for row in cursor.fetchall():
            topic_id = row[0]
            pending_count = row[1]
            counts[topic_id] = pending_count
        
        return counts

    def get_topic_update_on_counts(self, account_name: str = None) -> Dict[int, Dict[str, int]]:
        """
        Get per-topic assignment counts and ON counts for Tree/Site/Video Prep flags.

        ON means TreeUpdated=1 or SiteUpdated=1 or VidPrepUpdated=1.

        Returns:
            {topic_id: {'total': int, 'on': int}}
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if account_name is None:
            account_name = self.account_name

        cursor.execute('''
            WITH item_flags AS (
                SELECT
                    topic_id,
                    COALESCE(CAST(row_number AS NVARCHAR(50)), content_id) AS item_key,
                    MAX(CASE WHEN TreeUpdated = 1 OR SiteUpdated = 1 OR VidPrepUpdated = 1 THEN 1 ELSE 0 END) AS is_on,
                    MAX(CASE WHEN TreeUpdated = 1 AND SiteUpdated = 1 AND VidPrepUpdated = 1 THEN 1 ELSE 0 END) AS is_both_done
                FROM DL.topic_assignments
                WHERE account_name = ?
                GROUP BY topic_id, COALESCE(CAST(row_number AS NVARCHAR(50)), content_id)
            )
            SELECT
                topic_id,
                COUNT(*) AS total_count,
                SUM(is_on) AS on_count,
                SUM(is_both_done) AS both_done_count
            FROM item_flags
            GROUP BY topic_id
        ''', (account_name,))

        stats = {}
        for row in cursor.fetchall():
            topic_id = int(row[0])
            total_count = int(row[1] or 0)
            on_count = int(row[2] or 0)
            both_done_count = int(row[3] or 0)
            stats[topic_id] = {
                'total': total_count,
                'on': on_count,
                'both_done': both_done_count,
            }

        return stats
    
    def update_file_movement_status(self, content_id: str, topic_id: int, status: str, 
                                    error_message: str = None, account_name: str = None) -> bool:
        """
        Update file movement status for a topic assignment.
        
        Args:
            content_id: Content shortcode
            topic_id: Topic ID
            status: Status value ('Pending', 'In Process', 'Complete', 'Error')
            error_message: Optional error message if status is 'Error'
            account_name: Account name (uses self.account_name if None)
        
        Returns:
            True if successful
        """
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        valid_statuses = ['Pending', 'In Process', 'Complete', 'Error']
        if status not in valid_statuses:
            logger.error(f"Invalid file movement status: {status}")
            return False
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE DL.topic_assignments
                SET file_movement_status = ?,
                    file_movement_error = ?,
                    file_movement_updated_at = GETDATE()
                WHERE account_name = ? AND topic_id = ?
                  AND (
                        (row_number IS NOT NULL AND row_number = ?)
                     OR (content_id = ?)
                  )
            ''', (status, error_message, account_name, topic_id, row_number, content_shortcode))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating file movement status: {e}")
            return False
    
    def get_content_topic_assignments(self, content_id: str, account_name: str = None) -> List[Dict]:
        """
        Get all topic assignments for a content item with their status.
        
        Args:
            content_id: Content shortcode
            account_name: Account name (uses self.account_name if None)
        
        Returns:
            List of dicts with topic_id, file_movement_status, file_movement_error
        """
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT topic_id, file_movement_status, file_movement_error, file_movement_updated_at
            FROM DL.topic_assignments
                        WHERE account_name = ?
                            AND (
                                        (row_number IS NOT NULL AND row_number = ?)
                                 OR (content_id = ?)
                            )
            ORDER BY assigned_at
                ''', (account_name, row_number, content_shortcode))
        
        assignments = []
        for row in cursor.fetchall():
            assignments.append({
                'topic_id': row[0],
                'file_movement_status': row[1],
                'file_movement_error': row[2],
                'file_movement_updated_at': row[3]
            })
        
        return assignments

    def get_topic_assignment_update_flags(self, content_id: str, topic_id: int,
                                          account_name: str = None) -> Optional[Dict[str, int]]:
        """Get TreeUpdated, SiteUpdated, and VidPrepUpdated flags for one topic assignment (0/1/2)."""
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
                        SELECT TOP 1 TreeUpdated, SiteUpdated, VidPrepUpdated
            FROM DL.topic_assignments
            WHERE account_name = ?
              AND topic_id = ?
              AND (
                    (row_number IS NOT NULL AND row_number = ?)
                 OR (content_id = ?)
              )
            ORDER BY
                CASE
                    WHEN row_number IS NOT NULL AND row_number = ? THEN 0
                    WHEN content_id = ? THEN 1
                    ELSE 2
                END,
                assigned_at DESC
        ''', (account_name, topic_id, row_number, content_shortcode, row_number, content_shortcode))

        row = cursor.fetchone()
        if not row:
            return None

        return {
            'TreeUpdated': int(row[0]),
            'SiteUpdated': int(row[1]),
            'VidPrepUpdated': int(row[2])
        }

    def get_topic_assignment_flags_for_topic(self, topic_id: int,
                                             account_name: str = None) -> Dict[str, Dict[Any, Dict[str, int]]]:
        """
        Get all tri-state assignment flags for a topic in one query.

        Returns:
            {
                'by_row_number': {row_number: {'TreeUpdated': int, 'SiteUpdated': int, 'VidPrepUpdated': int}},
                'by_content_id': {content_id: {'TreeUpdated': int, 'SiteUpdated': int, 'VidPrepUpdated': int}}
            }
        """
        if account_name is None:
            account_name = self.account_name

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT row_number, content_id, TreeUpdated, SiteUpdated, VidPrepUpdated
            FROM DL.topic_assignments
            WHERE account_name = ? AND topic_id = ?
            ORDER BY assigned_at DESC
        ''', (account_name, int(topic_id)))

        by_row_number: Dict[int, Dict[str, int]] = {}
        by_content_id: Dict[str, Dict[str, int]] = {}

        for row in cursor.fetchall():
            row_number = row[0]
            content_id = str(row[1]).strip() if row[1] is not None else ''

            flags = {
                'TreeUpdated': int(row[2]),
                'SiteUpdated': int(row[3]),
                'VidPrepUpdated': int(row[4]),
            }

            # Keep first row for each key (latest because query is DESC).
            if row_number is not None and int(row_number) not in by_row_number:
                by_row_number[int(row_number)] = flags
            if content_id and content_id not in by_content_id:
                by_content_id[content_id] = flags

        return {
            'by_row_number': by_row_number,
            'by_content_id': by_content_id,
        }

    def update_topic_assignment_update_flag(self, content_id: str, topic_id: int,
                                            field_name: str, state_value: int,
                                            account_name: str = None) -> bool:
        """Update one topic assignment tri-state flag: TreeUpdated, SiteUpdated, or VidPrepUpdated (0/1/2)."""
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)

        if field_name not in ('TreeUpdated', 'SiteUpdated', 'VidPrepUpdated'):
            logger.error(f"Invalid topic assignment flag field: {field_name}")
            return False

        if state_value not in (0, 1, 2):
            logger.error(f"Invalid topic assignment flag value for {field_name}: {state_value}")
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = f'''
                UPDATE DL.topic_assignments
                SET {field_name} = ?
                WHERE account_name = ? AND topic_id = ?
                  AND (
                        (row_number IS NOT NULL AND row_number = ?)
                   OR (content_id = ?)
                  )
            '''
            cursor.execute(query, (state_value, account_name, topic_id, row_number, content_shortcode))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating {field_name} for topic assignment: {e}")
            return False
    
    def has_pending_topic_movements(self, content_id: str, account_name: str = None) -> bool:
        """
        Check if content has any pending file movements.
        
        Args:
            content_id: Content shortcode
            account_name: Account name (uses self.account_name if None)
        
        Returns:
            True if any assignments have 'Pending' status
        """
        if account_name is None:
            account_name = self.account_name

        row_number = self._resolve_content_row_number(content_id, account_name)
        content_shortcode = self._resolve_content_shortcode(content_id, account_name)
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM DL.topic_assignments
                        WHERE account_name = ?
                            AND (
                                        (row_number IS NOT NULL AND row_number = ?)
                                 OR (content_id = ?)
                            )
            AND file_movement_status = 'Pending'
                ''', (account_name, row_number, content_shortcode))
        
        count = cursor.fetchone()[0]
        return count > 0
    
    def reseed_topics_identity(self) -> bool:
        """
        Reseed the topics table IDENTITY column to fix PRIMARY KEY constraint violations.
        Sets the IDENTITY seed to MAX(id) + 1.
        
        Returns:
            True if successful
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Get the maximum ID currently in the table
            cursor.execute('SELECT MAX(id) FROM DL.topics')
            max_id = cursor.fetchone()[0]
            
            if max_id is None:
                max_id = 0
            
            # Reseed the identity column
            cursor.execute(f'DBCC CHECKIDENT (\'DL.topics\', RESEED, {max_id})')
            conn.commit()
            logger.info(f"Reseeded DL.topics IDENTITY to {max_id}")
            return True
        except Exception as e:
            logger.error(f"Error reseeding topics identity: {e}")
            conn.rollback()
            return False
    
    # Account Management Methods
    
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        """Get all accounts from the accounts table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT account_name, ig_username, ig_password, root_folder, created_at, updated_at
            FROM DL.accounts
            ORDER BY account_name
        ''')
        
        accounts = []
        for row in cursor.fetchall():
            accounts.append({
                'account_name': row[0],
                'ig_username': row[1] or '',
                'ig_password': row[2] or '',
                'root_folder': row[3] or '',
                'created_at': row[4],
                'updated_at': row[5]
            })
        
        return accounts
    
    def get_account(self, account_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific account by name."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT account_name, ig_username, ig_password, root_folder, created_at, updated_at
            FROM DL.accounts
            WHERE account_name = ?
        ''', (account_name,))
        
        row = cursor.fetchone()
        if row:
            return {
                'account_name': row[0],
                'ig_username': row[1] or '',
                'ig_password': row[2] or '',
                'root_folder': row[3] or '',
                'created_at': row[4],
                'updated_at': row[5]
            }
        return None
    
    def add_or_update_account(self, account_name: str, ig_username: str = '', 
                              ig_password: str = '', root_folder: str = '') -> bool:
        """Add or update an account in the accounts table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                MERGE DL.accounts AS target
                USING (SELECT ? AS account_name, ? AS ig_username, ? AS ig_password, ? AS root_folder) AS source
                ON target.account_name = source.account_name
                WHEN MATCHED THEN
                    UPDATE SET 
                        ig_username = CASE WHEN source.ig_username != '' THEN source.ig_username ELSE target.ig_username END,
                        ig_password = CASE WHEN source.ig_password != '' THEN source.ig_password ELSE target.ig_password END,
                        root_folder = CASE WHEN source.root_folder != '' THEN source.root_folder ELSE target.root_folder END,
                        updated_at = GETDATE()
                WHEN NOT MATCHED THEN
                    INSERT (account_name, ig_username, ig_password, root_folder)
                    VALUES (source.account_name, source.ig_username, source.ig_password, source.root_folder);
            ''', (account_name, ig_username or '', ig_password or '', root_folder or ''))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error adding/updating account {account_name}: {e}")
            return False
    
    def delete_account(self, account_name: str) -> bool:
        """Delete an account from the accounts table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM DL.accounts WHERE account_name = ?', (account_name,))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error deleting account {account_name}: {e}")
            return False
    
    def add_file(self, content_id: str, file_info: Dict[str, Any]) -> int:
        """
        Add a file entry to the database.
        If file already exists (duplicate content_id + file_number), update it instead.
        
        Args:
            content_id: Parent content entry ID
            file_info: File information dictionary
            
        Returns:
            File ID (database row ID)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        file_number = file_info.get('FileNumber', 1)
        
        # Check if file already exists
        cursor.execute('SELECT id FROM DL.files WHERE content_id = ? AND file_number = ?', (content_id, file_number))
        existing = cursor.fetchone()
        
        if existing:
            # File exists, update it instead
            file_id = existing[0]
            cursor.execute('''
                UPDATE DL.files SET
                    cdn_url = ?, cdn_mechanism = ?,
                    file_name = ?, download_filename = ?, file_caption = ?, file_tags = ?,
                    file_type = ?, file_quality = ?, file_size_bytes = ?,
                    file_download_status = ?, file_download_date = ?,
                    file_segment_count = ?, file_assembly_status = ?, file_save_status = ?,
                    file_destination_path = ?, file_debug_path = ?,
                    has_audio = ?, audio_url = ?, audio_segment_count = ?, xpv_asset_id = ?,
                    url_source_issue = ?, url_auto_corrected = ?, url_correction_log = ?,
                    user_notes = ?,
                    updated_at = GETDATE()
                WHERE id = ?
            ''', (
                file_info.get('FileCDNUrl', ''),
                file_info.get('FileCDNURLFoundViaMechanism', ''),
                file_info.get('FileName', ''),
                file_info.get('DownloadFilename', ''),
                file_info.get('FileCaption', ''),
                file_info.get('FileTags', ''),
                file_info.get('FileType', ''),
                file_info.get('FileQuality', 'high'),
                file_info.get('FileSizeBytes', 0),
                file_info.get('FileDownloadStatus', 'awaiting'),
                file_info.get('FileDownloadDate'),
                file_info.get('FileSegmentCount', 0),
                file_info.get('FileAssemblyStatus', 'awaiting'),
                file_info.get('FileSaveStatus', 'awaiting'),
                file_info.get('FileDestinationPath', ''),
                file_info.get('FileDebugPath', ''),
                file_info.get('HasAudio', False),
                file_info.get('AudioUrl', ''),
                file_info.get('AudioSegmentCount', 0),
                file_info.get('XpvAssetId', ''),
                file_info.get('UrlSourceIssue', ''),
                file_info.get('UrlAutoCorrected', False),
                file_info.get('UrlCorrectionLog', ''),
                file_info.get('UserNotes', ''),
                file_id
            ))
            conn.commit()
            return file_id
        
        # File doesn't exist, insert it
        cursor.execute('''
            INSERT INTO DL.files (
                content_id, file_number, cdn_url, cdn_mechanism,
                file_name, download_filename, file_caption, file_tags,
                file_type, file_quality, file_size_bytes,
                file_download_status, file_download_date,
                file_segment_count, file_assembly_status, file_save_status,
                file_destination_path, file_debug_path,
                has_audio, audio_url, audio_segment_count, xpv_asset_id,
                url_source_issue, url_auto_corrected, url_correction_log, user_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            content_id,
            file_info.get('FileNumber', 1),
            file_info.get('FileCDNUrl', ''),
            file_info.get('FileCDNURLFoundViaMechanism', ''),
            file_info.get('FileName', ''),
            file_info.get('DownloadFilename', ''),
            file_info.get('FileCaption', ''),
            file_info.get('FileTags', ''),
            file_info.get('FileType', 'unknown'),
            file_info.get('FileQuality', 'high'),
            file_info.get('FileSizeBytes', 0),
            file_info.get('FileDownloadStatus', 'awaiting'),
            file_info.get('FileDownloadDate'),
            file_info.get('FileSegmentCount', 0),
            file_info.get('FileAssemblyStatus', 'awaiting'),
            file_info.get('FileSaveStatus', 'awaiting'),
            file_info.get('FileDestinationPath', ''),
            file_info.get('FileDebugPath'),
            1 if file_info.get('HasAudio', False) else 0,
            file_info.get('AudioURL'),
            file_info.get('AudioSegmentCount', 0),
            file_info.get('XpvAssetId'),
            file_info.get('URLSourceIssue'),
            1 if file_info.get('URLAutoCorrected', False) else 0,
            file_info.get('URLCorrectionLog'),
            file_info.get('UserNotes', '')
        ))
        
        # Get the inserted file ID
        cursor.execute('SELECT @@IDENTITY AS file_id')
        file_id = cursor.fetchone()[0]
        
        # Add CDN discovery attempts
        for order, attempt in enumerate(file_info.get('FileCDNDiscoveryAttempts', []), 1):
            self.add_cdn_discovery_attempt(file_id, attempt, order)
        
        # Add video segments
        for segment in file_info.get('FileSegmentsDetail', []):
            self.add_segment(file_id, segment)
        
        # Add audio segments
        for segment in file_info.get('AudioSegmentsDetail', []):
            self.add_segment(file_id, segment)
        
        conn.commit()
        return int(file_id) if file_id else 0
    
    def add_cdn_discovery_attempt(self, file_id: int, attempt: Dict[str, Any], order: int):
        """Add a CDN discovery attempt record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO DL.cdn_discovery_attempts (
                file_id, mechanism, success, cdn_url_result, failure_reason, attempt_order
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            file_id,
            attempt.get('Mechanism', ''),
            1 if attempt.get('Success', False) else 0,
            attempt.get('CDNURLResult'),
            attempt.get('FailureReason'),
            order
        ))
    
    def add_segment(self, file_id: int, segment: Dict[str, Any]):
        """Add a segment (video or audio) record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO DL.segments (
                file_id, segment_type, segment_url, segment_size_bytes,
                segment_order, segment_download_status
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            file_id,
            segment.get('segmentType', 'video'),
            segment.get('segmentURL', ''),
            segment.get('segmentSizeBytes', 0),
            segment.get('segmentOrder', 0),
            segment.get('segmentDownloadStatus', 'pending')
        ))
    
    def delete_files_for_entry(self, entry_id: str) -> int:
        """
        Delete all files associated with a content entry.
        Used when re-scanning to replace old file list.
        
        Args:
            entry_id: Content entry ID
            
        Returns:
            Number of files deleted
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Cascading delete will handle segments and cdn_discovery_attempts
        cursor.execute('DELETE FROM DL.files WHERE content_id = ?', (entry_id,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        return deleted_count
    
    def update_file_status(self, content_id: str, file_number: int, status_updates: Dict[str, Any]):
        """
        Update file status fields.
        
        Args:
            content_id: Content entry ID
            file_number: File number within content
            status_updates: Dictionary of status fields to update
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Get file_id
        cursor.execute('''
            SELECT id FROM DL.files WHERE content_id = ? AND file_number = ?
        ''', (content_id, file_number))
        
        row = cursor.fetchone()
        if not row:
            return
        
        file_id = row[0]
        
        # Build UPDATE query
        set_clauses = []
        values = []
        
        for key, value in status_updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        
        if not set_clauses:
            return
        
        values.append(file_id)
        
        query = f'''
            UPDATE DL.files 
            SET {', '.join(set_clauses)}, updated_at = GETDATE()
            WHERE id = ?
        '''
        
        cursor.execute(query, values)
        conn.commit()
    
    def update_file_download_name(self, content_id: str, file_number: int, download_filename: str, new_dest_path: str):
        """
        Update download filename and destination path for a specific file.
        Preserves original Instagram filename in FileName field.
        
        Args:
            content_id: Content entry ID
            file_number: File number within the entry
            download_filename: New download filename (local storage name)
            new_dest_path: New destination path (relative to user_dir)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE DL.files
            SET download_filename = ?, file_destination_path = ?, updated_at = GETDATE()
            WHERE content_id = ? AND file_number = ?
        ''', (download_filename, new_dest_path, content_id, file_number))
        
        conn.commit()
    
    def update_file_user_notes(self, content_id: str, file_number: int, user_notes: str):
        """
        Update user notes for a specific file.
        
        Args:
            content_id: Content entry ID (shortcode)
            file_number: File number within the entry (1-based)
            user_notes: User's notes for this file
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE DL.files
            SET user_notes = ?, updated_at = GETDATE()
            WHERE content_id = ? AND file_number = ?
        ''', (user_notes, content_id, file_number))
        
        conn.commit()
        logger.info(f"Updated user notes for {content_id} file #{file_number}")
    
    def add_rejected_url(self, content_id: str, url: str, reason: str, 
                        matched_patterns: Optional[List[str]] = None,
                        efg_data: Optional[Dict[str, Any]] = None) -> int:
        """
        Add a rejected URL to the database.
        
        Args:
            content_id: Content entry ID
            url: The rejected URL
            reason: Reason for rejection
            matched_patterns: List of matched ad patterns
            efg_data: Decoded efg parameter data
            
        Returns:
            ID of the inserted rejected URL record
        """
        import json
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO DL.rejected_urls (content_id, url, reason, matched_patterns, efg_data)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            content_id,
            url,
            reason,
            json.dumps(matched_patterns) if matched_patterns else None,
            json.dumps(efg_data) if efg_data else None
        ))
        
        # Get the inserted ID
        cursor.execute('SELECT @@IDENTITY AS rejected_id')
        rejected_id = cursor.fetchone()[0]
        conn.commit()
        return int(rejected_id) if rejected_id else 0
    
    def delete_rejected_urls_for_entry(self, content_id: str) -> int:
        """
        Delete all rejected URLs for a content entry.
        Used when re-scanning to replace old rejected URL list.
        
        Args:
            content_id: Content entry ID
            
        Returns:
            Number of rejected URLs deleted
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM DL.rejected_urls WHERE content_id = ?', (content_id,))
        deleted_count = cursor.rowcount
        
        conn.commit()
        return deleted_count
    
    # ==================== TEST CASE MANAGEMENT ====================
    
    def mark_as_test_case(self, content_id: str, test_notes: str = '') -> int:
        """
        Mark a content entry as a test case.
        
        Args:
            content_id: Content entry ID
            test_notes: Optional notes about this test case
            
        Returns:
            Test case ID if successful, None if failed
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if already a test case
        cursor.execute('SELECT test_case_id FROM DL.test_cases WHERE content_id = ?', (content_id,))
        existing = cursor.fetchone()
        
        if existing:
            return existing[0]  # Already a test case
        
        try:
            cursor.execute('''
                INSERT INTO DL.test_cases (content_id, account_name, test_notes)
                VALUES (?, ?, ?)
            ''', (content_id, self.account_name, test_notes))
            
            cursor.execute('SELECT @@IDENTITY AS test_case_id')
            test_case_id = cursor.fetchone()[0]
            
            conn.commit()
            return int(test_case_id)
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to mark as test case: {e}")
    
    def unmark_test_case(self, content_id: str) -> bool:
        """
        Remove test case marking from a content entry.
        
        Args:
            content_id: Content entry ID
            
        Returns:
            True if removed, False if not a test case
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM DL.test_cases WHERE content_id = ?', (content_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        
        return deleted
    
    def update_test_case_status(self, content_id: str, status: str, notes: str = None) -> bool:
        """
        Update overall test case status.
        
        Args:
            content_id: Content entry ID
            status: 'Success', 'Failure', or 'TBD'
            notes: Optional notes to append
            
        Returns:
            True if updated successfully
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        update_parts = ['overall_status = ?', 'last_tested_at = GETDATE()']
        params = [status]
        
        if notes:
            update_parts.append('test_notes = ISNULL(test_notes, \'\') + ?')
            params.append(f"\n{notes}")
        
        params.append(content_id)
        
        sql = f"UPDATE DL.test_cases SET {', '.join(update_parts)} WHERE content_id = ?"
        
        try:
            cursor.execute(sql, params)
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to update test case status: {e}")
    
    def get_test_case_info(self, content_id: str) -> Optional[Dict[str, Any]]:
        """
        Get test case information for a content entry.
        
        Args:
            content_id: Content entry ID
            
        Returns:
            Dictionary with test case info, or None if not a test case
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT test_case_id, overall_status, test_notes, 
                   marked_as_test_at, last_tested_at
            FROM DL.test_cases
            WHERE content_id = ?
        ''', (content_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            'test_case_id': row[0],
            'overall_status': row[1],
            'test_notes': row[2],
            'marked_as_test_at': row[3],
            'last_tested_at': row[4]
        }
    
    def is_test_case(self, content_id: str) -> bool:
        """Check if a content entry is marked as a test case."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM DL.test_cases WHERE content_id = ?', (content_id,))
        return cursor.fetchone() is not None
    
    def get_all_test_cases(self) -> List[Dict[str, Any]]:
        """
        Get all test cases for the current account.
        
        Returns:
            List of test case dictionaries
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT tc.test_case_id, tc.content_id, tc.overall_status,
                   tc.test_notes, tc.marked_as_test_at, tc.last_tested_at,
                   ce.row_number, ce.media_url, ce.content_type, ce.content_sub_type
            FROM DL.test_cases tc
            INNER JOIN DL.content_entries ce ON tc.content_id = ce.id
            WHERE tc.account_name = ?
            ORDER BY tc.marked_as_test_at DESC
        ''', (self.account_name,))
        
        test_cases = []
        for row in cursor.fetchall():
            test_cases.append({
                'test_case_id': row[0],
                'content_id': row[1],
                'overall_status': row[2],
                'test_notes': row[3],
                'marked_as_test_at': row[4],
                'last_tested_at': row[5],
                'row_number': row[6],
                'media_url': row[7],
                'content_type': row[8],
                'content_sub_type': row[9]
            })
        
        return test_cases
    
    def add_instagram_url(self, url: str, entry_type: str = 'post', source: str = 'Manual Entry') -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Add an Instagram URL as a new content entry if it doesn't already exist.
        
        Args:
            url: Instagram URL
            entry_type: Type of content ('post', 'reel', etc.)
            source: Source description
            
        Returns:
            Tuple of (is_new, content_id, row_number)
            - is_new: True if added as new entry, False if duplicate
            - content_id: The content entry ID (new or existing)
            - row_number: Row number (new or existing)
        """
        import re
        import time
        
        # Extract ID from URL
        # Format: https://www.instagram.com/p/ABC123xyz/ or /reel/ABC123xyz/
        match = re.search(r'instagram\.com/(p|reel)/([^/\?]+)', url)
        if not match:
            raise ValueError(f"Could not extract valid ID from URL: {url}")
        
        short_code = match.group(2)
        timestamp = str(int(time.time()))
        entry_id = f"{short_code}_{timestamp}"
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Check if already exists (check by URL pattern to catch duplicates)
        cursor.execute('''
            SELECT id, row_number 
            FROM DL.content_entries 
            WHERE account_name = ? AND media_url LIKE ?
        ''', (self.account_name, f'%{short_code}%'))
        existing = cursor.fetchone()
        
        if existing:
            return (False, existing[0], existing[1])
        
        # Get next row number
        cursor.execute('''
            SELECT ISNULL(MAX(row_number), 0) + 1 
            FROM DL.content_entries 
            WHERE account_name = ?
        ''', (self.account_name,))
        next_row_number = cursor.fetchone()[0]
        
        # Create new entry
        try:
            cursor.execute('''
                INSERT INTO DL.content_entries (
                    id, account_name, media_url, text, source, type, 
                    date_added, content_type, cdn_acquisition_status, 
                    download_status, review_state, row_number
                ) VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?, ?, ?)
            ''', (
                entry_id,
                self.account_name,
                url,
                '',  # No caption yet
                source,
                entry_type,
                entry_type,  # content_type
                'awaiting scan',
                'awaiting scan',
                'not yet reviewed',
                next_row_number
            ))
            
            conn.commit()
            return (True, entry_id, next_row_number)
        
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to add Instagram URL: {e}")
    
    def add_thumbnail(self, content_id: str, file_name: str, file_path: str, 
                      file_size_bytes: int = None, width: int = None, height: int = None) -> int:
        """
        Add or update thumbnail for a content entry.
        
        Args:
            content_id: Content entry ID (shortcode)
            file_name: Thumbnail filename
            file_path: Full path to thumbnail file
            file_size_bytes: File size in bytes
            width: Image width in pixels
            height: Image height in pixels
            
        Returns:
            Thumbnail ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if thumbnail already exists
            cursor.execute('SELECT thumbnail_id FROM DL.thumbnails WHERE content_id = ?', (content_id,))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing
                cursor.execute('''
                    UPDATE DL.thumbnails 
                    SET file_name = ?, file_path = ?, file_size_bytes = ?, 
                        width = ?, height = ?, created_at = GETDATE()
                    WHERE content_id = ?
                ''', (file_name, file_path, file_size_bytes, width, height, content_id))
                thumbnail_id = existing[0]
            else:
                # Insert new
                cursor.execute('''
                    INSERT INTO DL.thumbnails (content_id, file_name, file_path, file_size_bytes, width, height)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (content_id, file_name, file_path, file_size_bytes, width, height))
                cursor.execute('SELECT @@IDENTITY')
                thumbnail_id = cursor.fetchone()[0]
            
            conn.commit()
            return int(thumbnail_id) if thumbnail_id else 0
            
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to add thumbnail: {e}")
    
    def get_thumbnail(self, content_id: str) -> Optional[Dict[str, Any]]:
        """
        Get thumbnail information for a content entry.
        
        Args:
            content_id: Content entry ID (shortcode)
            
        Returns:
            Dictionary with thumbnail info or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT thumbnail_id, content_id, file_name, file_path, 
                   file_size_bytes, width, height, created_at
            FROM DL.thumbnails
            WHERE content_id = ?
        ''', (content_id,))
        
        row = cursor.fetchone()
        if row:
            return {
                'thumbnail_id': row[0],
                'content_id': row[1],
                'file_name': row[2],
                'file_path': row[3],
                'file_size_bytes': row[4],
                'width': row[5],
                'height': row[6],
                'created_at': row[7]
            }
        return None
    
    def delete_thumbnail(self, content_id: str) -> bool:
        """
        Delete thumbnail for a content entry.
        
        Args:
            content_id: Content entry ID (shortcode)
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM DL.thumbnails WHERE content_id = ?', (content_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to delete thumbnail: {e}")

    def _get_video_output_vidid_sql_type(self, cursor):
        cursor.execute('''
            SELECT TOP 1 TYPE_NAME(c.user_type_id)
            FROM sys.columns c
            INNER JOIN sys.tables t ON t.object_id = c.object_id
            INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = 'VIDEO' AND t.name = 'VideoOutput' AND c.name = 'VidID'
        ''')
        row = cursor.fetchone()
        if row and row[0]:
            return row[0].upper()
        return 'INT'

    def ensure_video_output_tables(self):
        """Ensure VIDEO.VideoOutput, VIDEO.AudioTracks, and VIDEO.FileAssembly tables exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'VIDEO')
                BEGIN
                    EXEC('CREATE SCHEMA VIDEO')
                END
            ''')
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = 'VIDEO' AND t.name = 'VideoOutput'
                )
                BEGIN
                    CREATE TABLE VIDEO.VideoOutput (
                        VidID INT IDENTITY(1,1) PRIMARY KEY,
                        AccountName NVARCHAR(255) NOT NULL,
                        OutputKind NVARCHAR(20) NOT NULL CONSTRAINT DF_VideoOutput_OutputKind DEFAULT 'video',
                        OutputPath NVARCHAR(1000) NOT NULL,
                        OutputFileName NVARCHAR(255) NULL,
                        VideoFileTitle NVARCHAR(500) NULL,
                        VideoFileDesc NVARCHAR(MAX) NULL,
                        SourcePath NVARCHAR(1000) NULL,
                        SourceShortcode NVARCHAR(100) NULL,
                        SelectedTopic NVARCHAR(255) NULL,
                        FilePrefix NVARCHAR(255) NULL,
                        FileIndex NVARCHAR(20) NULL,
                        Modifier NVARCHAR(50) NULL,
                        Separator NVARCHAR(10) NULL,
                        PrependTopic BIT NOT NULL CONSTRAINT DF_VideoOutput_PrependTopic DEFAULT 0,
                        OutputFolderMode NVARCHAR(50) NULL,
                        OutputFolderPath NVARCHAR(1000) NULL,
                        CodecPreset NVARCHAR(50) NULL,
                        CRF INT NULL,
                        ResolutionPreset NVARCHAR(50) NULL,
                        OutputWidth INT NULL,
                        OutputHeight INT NULL,
                        BackgroundMode NVARCHAR(50) NULL,
                        BackgroundColor NVARCHAR(50) NULL,
                        BackgroundImagePath NVARCHAR(1000) NULL,
                        AudioMode NVARCHAR(50) NULL,
                        AudioFilePath NVARCHAR(1000) NULL,
                        AudioStartSeconds FLOAT NULL,
                        AudioEndSeconds FLOAT NULL,
                        CropX INT NULL,
                        CropY INT NULL,
                        CropWidth INT NULL,
                        CropHeight INT NULL,
                        TrimStartFrame INT NULL,
                        TrimEndFrame INT NULL,
                        SourceFrameCount INT NULL,
                        SourceFps FLOAT NULL,
                        SourceDurationSeconds FLOAT NULL,
                        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_VideoOutput_CreatedAt DEFAULT GETDATE(),
                        UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_VideoOutput_UpdatedAt DEFAULT GETDATE()
                    )
                END
            ''')
            conn.commit()

            vidid_sql_type = self._get_video_output_vidid_sql_type(cursor)

            cursor.execute(f'''
                IF COL_LENGTH('VIDEO.AudioTracks', 'VidID') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD VidID {vidid_sql_type} NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'TrackOrder') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD TrackOrder INT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'TrackPath') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD TrackPath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'TrackName') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD TrackName NVARCHAR(255) NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'VolumePercent') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD VolumePercent FLOAT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'ClipStartSeconds') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD ClipStartSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'ClipEndSeconds') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD ClipEndSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'EnterFrame') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD EnterFrame INT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'ExitFrame') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD ExitFrame INT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'FadeInSeconds') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD FadeInSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'FadeOutSeconds') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD FadeOutSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.AudioTracks', 'Muted') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD Muted BIT NOT NULL CONSTRAINT DF_AudioTracks_Muted DEFAULT 0;
                IF COL_LENGTH('VIDEO.AudioTracks', 'CreatedAt') IS NULL
                    ALTER TABLE VIDEO.AudioTracks ADD CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_AudioTracks_CreatedAt DEFAULT GETDATE();
            ''')
            conn.commit()

            cursor.execute(f'''
                DECLARE @audioTracksNeedsRebuild BIT = 0;

                IF EXISTS (
                    SELECT 1
                    FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = 'VIDEO' AND t.name = 'AudioTracks'
                )
                BEGIN
                    IF COL_LENGTH('VIDEO.AudioTracks', 'AudioTrackID') IS NULL
                    BEGIN
                        SET @audioTracksNeedsRebuild = 1;
                    END
                    ELSE IF EXISTS (
                        SELECT 1
                        FROM sys.key_constraints kc
                        INNER JOIN sys.tables t ON t.object_id = kc.parent_object_id
                        INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                        INNER JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
                        INNER JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                        WHERE kc.type = 'PK'
                          AND s.name = 'VIDEO'
                          AND t.name = 'AudioTracks'
                        GROUP BY kc.name
                        HAVING SUM(CASE WHEN c.name = 'AudioTrackID' THEN 1 ELSE 0 END) = 0
                            OR COUNT(*) <> 1
                    )
                    BEGIN
                        SET @audioTracksNeedsRebuild = 1;
                    END
                END

                IF @audioTracksNeedsRebuild = 1
                BEGIN
                    IF OBJECT_ID('VIDEO.AudioTracks_Migrated', 'U') IS NOT NULL
                        DROP TABLE VIDEO.AudioTracks_Migrated;

                    CREATE TABLE VIDEO.AudioTracks_Migrated (
                        AudioTrackID INT IDENTITY(1,1) PRIMARY KEY,
                        VidID {vidid_sql_type} NOT NULL,
                        TrackOrder INT NOT NULL,
                        TrackPath NVARCHAR(1000) NOT NULL,
                        TrackName NVARCHAR(255) NULL,
                        VolumePercent FLOAT NULL,
                        ClipStartSeconds FLOAT NULL,
                        ClipEndSeconds FLOAT NULL,
                        EnterFrame INT NULL,
                        ExitFrame INT NULL,
                        FadeInSeconds FLOAT NULL,
                        FadeOutSeconds FLOAT NULL,
                        Muted BIT NOT NULL CONSTRAINT DF_AudioTracks_Migrated_Muted DEFAULT 0,
                        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_AudioTracks_Migrated_CreatedAt DEFAULT GETDATE(),
                        CONSTRAINT FK_AudioTracks_Migrated_VideoOutput FOREIGN KEY (VidID)
                            REFERENCES VIDEO.VideoOutput(VidID) ON DELETE CASCADE
                    );

                    INSERT INTO VIDEO.AudioTracks_Migrated (
                        VidID,
                        TrackOrder,
                        TrackPath,
                        TrackName,
                        VolumePercent,
                        ClipStartSeconds,
                        ClipEndSeconds,
                        EnterFrame,
                        ExitFrame,
                        FadeInSeconds,
                        FadeOutSeconds,
                        Muted,
                        CreatedAt
                    )
                    SELECT
                        CAST(ISNULL(VidID, 0) AS {vidid_sql_type}) AS VidID,
                        ROW_NUMBER() OVER (
                            PARTITION BY CAST(ISNULL(VidID, 0) AS {vidid_sql_type})
                            ORDER BY ISNULL(TrackOrder, 0), ISNULL(TrackName, ''), ISNULL(TrackPath, '')
                        ) AS TrackOrder,
                        CAST(ISNULL(TrackPath, '') AS NVARCHAR(1000)) AS TrackPath,
                        CAST(TrackName AS NVARCHAR(255)) AS TrackName,
                        TRY_CAST(VolumePercent AS FLOAT) AS VolumePercent,
                        TRY_CAST(ClipStartSeconds AS FLOAT) AS ClipStartSeconds,
                        TRY_CAST(ClipEndSeconds AS FLOAT) AS ClipEndSeconds,
                        TRY_CAST(EnterFrame AS INT) AS EnterFrame,
                        TRY_CAST(ExitFrame AS INT) AS ExitFrame,
                        TRY_CAST(FadeInSeconds AS FLOAT) AS FadeInSeconds,
                        TRY_CAST(FadeOutSeconds AS FLOAT) AS FadeOutSeconds,
                        CAST(ISNULL(Muted, 0) AS BIT) AS Muted,
                        ISNULL(CreatedAt, GETDATE()) AS CreatedAt
                    FROM VIDEO.AudioTracks
                    WHERE ISNULL(VidID, 0) > 0
                                            AND ISNULL(LTRIM(RTRIM(CAST(TrackPath AS NVARCHAR(1000)))), '') <> ''
                                            AND EXISTS (
                                                    SELECT 1
                                                    FROM VIDEO.VideoOutput vo
                                        WHERE vo.VidID = CAST(ISNULL(VIDEO.AudioTracks.VidID, 0) AS {vidid_sql_type})
                                            );

                    DROP TABLE VIDEO.AudioTracks;
                    EXEC sp_rename 'VIDEO.AudioTracks_Migrated', 'AudioTracks';
                END
            ''')
            conn.commit()

            # Migrate legacy VIDEO.VideoOutput schemas by adding any missing columns
            # required by current save/load logic.
            cursor.execute('''
                IF COL_LENGTH('VIDEO.VideoOutput', 'AccountName') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD AccountName NVARCHAR(255) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputKind') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputKind NVARCHAR(20) NOT NULL CONSTRAINT DF_VideoOutput_OutputKind DEFAULT 'video';
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputPath') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputPath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputFileName') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputFileName NVARCHAR(255) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'VideoFileTitle') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD VideoFileTitle NVARCHAR(500) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'VideoFileDesc') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD VideoFileDesc NVARCHAR(MAX) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SourcePath') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SourcePath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SourceShortcode') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SourceShortcode NVARCHAR(100) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SelectedTopic') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SelectedTopic NVARCHAR(255) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'FilePrefix') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD FilePrefix NVARCHAR(255) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'FileIndex') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD FileIndex NVARCHAR(20) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'Modifier') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD Modifier NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'Separator') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD Separator NVARCHAR(10) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'PrependTopic') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD PrependTopic BIT NOT NULL CONSTRAINT DF_VideoOutput_PrependTopic DEFAULT 0;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputFolderMode') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputFolderMode NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputFolderPath') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputFolderPath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CodecPreset') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CodecPreset NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CRF') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CRF INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'ResolutionPreset') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD ResolutionPreset NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputWidth') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputWidth INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'OutputHeight') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD OutputHeight INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'BackgroundMode') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD BackgroundMode NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'BackgroundColor') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD BackgroundColor NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'BackgroundImagePath') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD BackgroundImagePath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'AudioMode') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD AudioMode NVARCHAR(50) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'AudioFilePath') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD AudioFilePath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'AudioStartSeconds') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD AudioStartSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'AudioEndSeconds') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD AudioEndSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CropX') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CropX INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CropY') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CropY INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CropWidth') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CropWidth INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CropHeight') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CropHeight INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'TrimStartFrame') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD TrimStartFrame INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'TrimEndFrame') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD TrimEndFrame INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SourceFrameCount') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SourceFrameCount INT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SourceFps') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SourceFps FLOAT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'SourceDurationSeconds') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD SourceDurationSeconds FLOAT NULL;
                IF COL_LENGTH('VIDEO.VideoOutput', 'CreatedAt') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_VideoOutput_CreatedAt DEFAULT GETDATE();
                IF COL_LENGTH('VIDEO.VideoOutput', 'UpdatedAt') IS NULL
                    ALTER TABLE VIDEO.VideoOutput ADD UpdatedAt DATETIME2 NOT NULL CONSTRAINT DF_VideoOutput_UpdatedAt DEFAULT GETDATE();
            ''')
            conn.commit()

            # Backfill AccountName on legacy rows so account-scoped save/lookups work.
            cursor.execute(
                '''
                UPDATE VIDEO.VideoOutput
                SET AccountName = ?
                WHERE AccountName IS NULL OR LTRIM(RTRIM(AccountName)) = ''
                ''',
                (self.account_name or 'legacy',),
            )
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE object_id = OBJECT_ID('VIDEO.VideoOutput')
                      AND name = 'UX_VideoOutput_Account_OutputPath'
                )
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM VIDEO.VideoOutput
                        GROUP BY AccountName, OutputPath
                        HAVING COUNT(*) > 1
                    )
                    BEGIN
                        CREATE UNIQUE INDEX UX_VideoOutput_Account_OutputPath
                        ON VIDEO.VideoOutput(AccountName, OutputPath)
                    END
                END
            ''')
            conn.commit()

            cursor.execute(f'''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = 'VIDEO' AND t.name = 'AudioTracks'
                )
                BEGIN
                    CREATE TABLE VIDEO.AudioTracks (
                        AudioTrackID INT IDENTITY(1,1) PRIMARY KEY,
                        VidID {vidid_sql_type} NOT NULL,
                        TrackOrder INT NOT NULL,
                        TrackPath NVARCHAR(1000) NOT NULL,
                        TrackName NVARCHAR(255) NULL,
                        VolumePercent FLOAT NULL,
                        ClipStartSeconds FLOAT NULL,
                        ClipEndSeconds FLOAT NULL,
                        EnterFrame INT NULL,
                        ExitFrame INT NULL,
                        FadeInSeconds FLOAT NULL,
                        FadeOutSeconds FLOAT NULL,
                        Muted BIT NOT NULL CONSTRAINT DF_AudioTracks_Muted DEFAULT 0,
                        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_AudioTracks_CreatedAt DEFAULT GETDATE(),
                        CONSTRAINT FK_AudioTracks_VideoOutput FOREIGN KEY (VidID)
                            REFERENCES VIDEO.VideoOutput(VidID) ON DELETE CASCADE
                    )
                END
            ''')
            conn.commit()

            cursor.execute(f'''
                IF COL_LENGTH('VIDEO.FileAssembly', 'VidID') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD VidID {vidid_sql_type} NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'FileID') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD FileID INT NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'AssemblyOrder') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD AssemblyOrder INT NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'AssemblyStage') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD AssemblyStage NVARCHAR(100) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'InputPath') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD InputPath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'OutputPath') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD OutputPath NVARCHAR(1000) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'ToolName') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD ToolName NVARCHAR(100) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'CommandLine') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD CommandLine NVARCHAR(MAX) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'AssemblyPayload') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD AssemblyPayload NVARCHAR(MAX) NULL;
                IF COL_LENGTH('VIDEO.FileAssembly', 'CreatedAt') IS NULL
                    ALTER TABLE VIDEO.FileAssembly ADD CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_FileAssembly_CreatedAt DEFAULT GETDATE();
            ''')
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE object_id = OBJECT_ID('VIDEO.AudioTracks')
                      AND name = 'IX_AudioTracks_VidID_Order'
                )
                BEGIN
                    CREATE INDEX IX_AudioTracks_VidID_Order
                    ON VIDEO.AudioTracks(VidID, TrackOrder)
                END
            ''')
            conn.commit()

            cursor.execute(f'''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = 'VIDEO' AND t.name = 'FileAssembly'
                )
                BEGIN
                    CREATE TABLE VIDEO.FileAssembly (
                        FileAssemblyID INT IDENTITY(1,1) PRIMARY KEY,
                        VidID {vidid_sql_type} NOT NULL,
                        AssemblyOrder INT NOT NULL,
                        AssemblyStage NVARCHAR(100) NOT NULL,
                        InputPath NVARCHAR(1000) NULL,
                        OutputPath NVARCHAR(1000) NULL,
                        ToolName NVARCHAR(100) NULL,
                        CommandLine NVARCHAR(MAX) NULL,
                        AssemblyPayload NVARCHAR(MAX) NULL,
                        CreatedAt DATETIME2 NOT NULL CONSTRAINT DF_FileAssembly_CreatedAt DEFAULT GETDATE(),
                        CONSTRAINT FK_FileAssembly_VideoOutput FOREIGN KEY (VidID)
                            REFERENCES VIDEO.VideoOutput(VidID) ON DELETE CASCADE
                    )
                END
            ''')
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE object_id = OBJECT_ID('VIDEO.FileAssembly')
                      AND name = 'IX_FileAssembly_VidID_Order'
                )
                BEGIN
                    CREATE INDEX IX_FileAssembly_VidID_Order
                    ON VIDEO.FileAssembly(VidID, AssemblyOrder)
                END
            ''')
            conn.commit()

            cursor.execute(f'''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = 'VIDEO' AND t.name = 'Applications'
                )
                BEGIN
                    CREATE TABLE VIDEO.Applications (
                        VidAID BIGINT IDENTITY(1,1) PRIMARY KEY,
                        VidID {vidid_sql_type} NOT NULL,
                        TechniqueClassID INT NOT NULL,
                        TechniqueTypeID INT NOT NULL,
                        TSID BIGINT NULL,
                        AlternateTechniqueName NVARCHAR(512) NULL,
                        KeyTechnique BIT NULL,
                        FormationID BIGINT NULL,
                        PossessionStateID INT NULL,
                        PitchPositionID INT NULL,
                        ExerciseClassID BIGINT NULL,
                        MuscleGroupID BIGINT NULL,
                        EngagementMechanismID BIGINT NULL,
                        CONSTRAINT FK_Applications_VideoOutput FOREIGN KEY (VidID)
                            REFERENCES VIDEO.VideoOutput(VidID) ON DELETE CASCADE
                    )
                END
            ''')
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE object_id = OBJECT_ID('VIDEO.Applications')
                      AND name = 'IX_Applications_VidID'
                )
                BEGIN
                    CREATE INDEX IX_Applications_VidID
                    ON VIDEO.Applications(VidID, VidAID)
                END
            ''')
            conn.commit()

            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes
                    WHERE object_id = OBJECT_ID('VIDEO.Applications')
                      AND name = 'UX_Applications_Vid_Class_Type_TSID'
                )
                BEGIN
                    CREATE UNIQUE INDEX UX_Applications_Vid_Class_Type_TSID
                    ON VIDEO.Applications(VidID, TechniqueClassID, TechniqueTypeID, TSID)
                    WHERE TSID IS NOT NULL
                END
            ''')
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to ensure VIDEO tables: {e}")

    def save_video_output_record(
        self,
        video_output: Dict[str, Any],
        audio_tracks: Optional[List[Dict[str, Any]]] = None,
        file_assembly: Optional[List[Dict[str, Any]]] = None,
        delete_existing: bool = False,
    ) -> int:
        """Save VIDEO.VideoOutput row and its VIDEO.AudioTracks/FileAssembly rows.

        Args:
            video_output: Video output metadata dictionary.
            audio_tracks: List of track dictionaries.
            file_assembly: List of file assembly dictionaries documenting creation steps.
            delete_existing: Delete an existing row for same account/path before insert.

        Returns:
            Newly inserted VidID.
        """
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        output_path = str(video_output.get('output_path') or '').strip()
        if not output_path:
            raise ValueError("video_output.output_path is required")

        account_name = str(video_output.get('account_name') or self.account_name or '').strip()
        if not account_name:
            raise ValueError("account_name is required")

        try:
            cursor.execute(
                '''
                SELECT VidID
                FROM VIDEO.VideoOutput
                WHERE AccountName = ? AND OutputPath = ?
                ''',
                (account_name, output_path),
            )
            existing_row = cursor.fetchone()
            if existing_row:
                if not delete_existing:
                    raise ValueError(
                        f"Video output record already exists for account '{account_name}' and path '{output_path}'"
                    )
                cursor.execute(
                    '''
                    DELETE FROM VIDEO.VideoOutput
                    WHERE AccountName = ? AND OutputPath = ?
                    ''',
                    (account_name, output_path),
                )

            cursor.execute(
                '''
                INSERT INTO VIDEO.VideoOutput (
                    AccountName,
                    OutputKind,
                    OutputPath,
                    OutputFileName,
                    VideoFileTitle,
                    VideoFileDesc,
                    SourcePath,
                    SourceShortcode,
                    SelectedTopic,
                    FilePrefix,
                    FileIndex,
                    Modifier,
                    Separator,
                    PrependTopic,
                    OutputFolderMode,
                    OutputFolderPath,
                    CodecPreset,
                    CRF,
                    ResolutionPreset,
                    OutputWidth,
                    OutputHeight,
                    BackgroundMode,
                    BackgroundColor,
                    BackgroundImagePath,
                    AudioMode,
                    AudioFilePath,
                    AudioStartSeconds,
                    AudioEndSeconds,
                    CropX,
                    CropY,
                    CropWidth,
                    CropHeight,
                    TrimStartFrame,
                    TrimEndFrame,
                    SourceFrameCount,
                    SourceFps,
                    SourceDurationSeconds,
                    UpdatedAt
                )
                OUTPUT INSERTED.VidID
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                ''',
                (
                    account_name,
                    video_output.get('output_kind') or 'video',
                    output_path,
                    video_output.get('output_file_name'),
                    video_output.get('video_file_title'),
                    video_output.get('video_file_desc'),
                    video_output.get('source_path'),
                    video_output.get('source_shortcode'),
                    video_output.get('selected_topic'),
                    video_output.get('file_prefix'),
                    video_output.get('file_index'),
                    video_output.get('modifier'),
                    video_output.get('separator'),
                    1 if video_output.get('prepend_topic') else 0,
                    video_output.get('output_folder_mode'),
                    video_output.get('output_folder_path'),
                    video_output.get('codec_preset'),
                    video_output.get('crf'),
                    video_output.get('resolution_preset'),
                    video_output.get('output_width'),
                    video_output.get('output_height'),
                    video_output.get('background_mode'),
                    video_output.get('background_color'),
                    video_output.get('background_image_path'),
                    video_output.get('audio_mode'),
                    video_output.get('audio_file_path'),
                    video_output.get('audio_start_seconds'),
                    video_output.get('audio_end_seconds'),
                    video_output.get('crop_x'),
                    video_output.get('crop_y'),
                    video_output.get('crop_width'),
                    video_output.get('crop_height'),
                    video_output.get('trim_start_frame'),
                    video_output.get('trim_end_frame'),
                    video_output.get('source_frame_count'),
                    video_output.get('source_fps'),
                    video_output.get('source_duration_seconds'),
                ),
            )

            inserted_row = cursor.fetchone()
            if not inserted_row:
                raise Exception("Failed to obtain inserted VidID")
            vid_id = int(inserted_row[0])

            for order, track in enumerate(audio_tracks or [], start=1):
                track_path = str(track.get('track_path') or '').strip()
                if not track_path:
                    continue

                cursor.execute(
                    '''
                    INSERT INTO VIDEO.AudioTracks (
                        VidID,
                        TrackOrder,
                        TrackPath,
                        TrackName,
                        VolumePercent,
                        ClipStartSeconds,
                        ClipEndSeconds,
                        EnterFrame,
                        ExitFrame,
                        FadeInSeconds,
                        FadeOutSeconds,
                        Muted
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        vid_id,
                        int(track.get('track_order') or order),
                        track_path,
                        track.get('track_name') or os.path.basename(track_path),
                        track.get('volume_percent'),
                        track.get('clip_start_seconds'),
                        track.get('clip_end_seconds'),
                        track.get('enter_frame'),
                        track.get('exit_frame'),
                        track.get('fade_in_seconds'),
                        track.get('fade_out_seconds'),
                        1 if bool(track.get('muted')) else 0,
                    ),
                )

            for order, assembly_row in enumerate(file_assembly or [], start=1):
                assembly_stage = str(assembly_row.get('assembly_stage') or '').strip() or 'ffmpeg_export'
                input_path = str(assembly_row.get('input_path') or '').strip() or None
                output_path_for_row = str(assembly_row.get('output_path') or '').strip() or output_path
                tool_name = str(assembly_row.get('tool_name') or '').strip() or None
                command_line = assembly_row.get('command_line')
                payload = assembly_row.get('assembly_payload')

                if command_line is not None and not isinstance(command_line, str):
                    try:
                        command_line = json.dumps(command_line, ensure_ascii=False)
                    except Exception:
                        command_line = str(command_line)

                if payload is not None and not isinstance(payload, str):
                    try:
                        payload = json.dumps(payload, ensure_ascii=False)
                    except Exception:
                        payload = str(payload)

                cursor.execute(
                    '''
                    SELECT 1
                    FROM sys.columns
                    WHERE object_id = OBJECT_ID('VIDEO.FileAssembly')
                      AND name = 'FileID'
                    '''
                )
                has_file_id_col = cursor.fetchone() is not None

                file_id_value = assembly_row.get('file_id')
                if file_id_value is None:
                    file_id_value = assembly_row.get('FileID')
                if file_id_value is None:
                    # Legacy schema compatibility: some DBs require FileID NOT NULL.
                    file_id_value = vid_id

                if has_file_id_col:
                    cursor.execute(
                        '''
                        INSERT INTO VIDEO.FileAssembly (
                            VidID,
                            FileID,
                            AssemblyOrder,
                            AssemblyStage,
                            InputPath,
                            OutputPath,
                            ToolName,
                            CommandLine,
                            AssemblyPayload
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            vid_id,
                            int(file_id_value),
                            int(assembly_row.get('assembly_order') or order),
                            assembly_stage,
                            input_path,
                            output_path_for_row,
                            tool_name,
                            command_line,
                            payload,
                        ),
                    )
                else:
                    cursor.execute(
                    '''
                    INSERT INTO VIDEO.FileAssembly (
                        VidID,
                        AssemblyOrder,
                        AssemblyStage,
                        InputPath,
                        OutputPath,
                        ToolName,
                        CommandLine,
                        AssemblyPayload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        vid_id,
                        int(assembly_row.get('assembly_order') or order),
                        assembly_stage,
                        input_path,
                        output_path_for_row,
                        tool_name,
                        command_line,
                        payload,
                    ),
                )

            conn.commit()
            return vid_id
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to save video output record: {e}")

    def get_video_output_record(self, output_path: str, account_name: str = None) -> Optional[Dict[str, Any]]:
        """Get a saved VIDEO.VideoOutput row by output path."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        if account_name is None:
            account_name = self.account_name

        cursor.execute(
            '''
            SELECT TOP 1
                VidID,
                AccountName,
                OutputKind,
                OutputPath,
                OutputFileName,
                VideoFileTitle,
                VideoFileDesc,
                SourcePath,
                SourceShortcode,
                SelectedTopic,
                FilePrefix,
                FileIndex,
                Modifier,
                Separator,
                PrependTopic,
                OutputFolderMode,
                OutputFolderPath,
                CodecPreset,
                CRF,
                ResolutionPreset,
                OutputWidth,
                OutputHeight,
                BackgroundMode,
                BackgroundColor,
                BackgroundImagePath,
                AudioMode,
                AudioFilePath,
                AudioStartSeconds,
                AudioEndSeconds,
                CropX,
                CropY,
                CropWidth,
                CropHeight,
                TrimStartFrame,
                TrimEndFrame,
                SourceFrameCount,
                SourceFps,
                SourceDurationSeconds,
                CreatedAt,
                UpdatedAt
            FROM VIDEO.VideoOutput
            WHERE AccountName = ? AND OutputPath = ?
            ORDER BY VidID DESC
            ''',
            (account_name, str(output_path).strip()),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._dict_from_row(cursor, row)

    def get_video_audio_tracks(self, vid_id: int) -> List[Dict[str, Any]]:
        """Get audio tracks linked to a VIDEO.VideoOutput row."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT
                AudioTrackID,
                VidID,
                TrackOrder,
                TrackPath,
                TrackName,
                VolumePercent,
                ClipStartSeconds,
                ClipEndSeconds,
                EnterFrame,
                ExitFrame,
                FadeInSeconds,
                FadeOutSeconds,
                Muted,
                CreatedAt
            FROM VIDEO.AudioTracks
            WHERE VidID = ?
            ORDER BY TrackOrder ASC, AudioTrackID ASC
            ''',
            (int(vid_id),),
        )

        results = []
        for row in cursor.fetchall():
            results.append(self._dict_from_row(cursor, row))
        return results

    def get_video_file_assembly(self, vid_id: int) -> List[Dict[str, Any]]:
        """Get file assembly rows linked to a VIDEO.VideoOutput row."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT
                FileAssemblyID,
                VidID,
                AssemblyOrder,
                AssemblyStage,
                InputPath,
                OutputPath,
                ToolName,
                CommandLine,
                AssemblyPayload,
                CreatedAt
            FROM VIDEO.FileAssembly
            WHERE VidID = ?
            ORDER BY AssemblyOrder ASC, FileAssemblyID ASC
            ''',
            (int(vid_id),),
        )

        results = []
        for row in cursor.fetchall():
            results.append(self._dict_from_row(cursor, row))
        return results

    def get_video_output_bundle(self, output_path: str, account_name: str = None) -> Optional[Dict[str, Any]]:
        """Get a saved output record and its linked audio tracks."""
        record = self.get_video_output_record(output_path, account_name=account_name)
        if not record:
            return None

        record['audio_tracks'] = self.get_video_audio_tracks(record['VidID'])
        record['file_assembly'] = self.get_video_file_assembly(record['VidID'])
        record['applications'] = self.get_video_applications(record['VidID'])
        record['nodes'] = self.get_video_nodes(record['VidID'])
        return record

    def delete_video_output_record(self, output_path: str, account_name: str = None) -> bool:
        """Delete VIDEO.VideoOutput row by account/path. Dependent rows are removed via FK cascade."""
        self.ensure_video_output_tables()

        normalized_output = str(output_path or '').strip()
        if not normalized_output:
            return False

        target_account = str(account_name or self.account_name or '').strip()
        if not target_account:
            return False

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                DELETE FROM VIDEO.VideoOutput
                WHERE AccountName = ? AND OutputPath = ?
                ''',
                (target_account, normalized_output),
            )
            deleted = cursor.rowcount > 0
            conn.commit()
            return bool(deleted)
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to delete video output record: {e}")

    def get_vid_prep_count_for_shortcode(self, shortcode: str, account_name: str = None) -> int:
        """Count VIDEO.VideoOutput rows produced from a given source shortcode."""
        self.ensure_video_output_tables()

        clean_shortcode = str(shortcode or '').strip()
        if not clean_shortcode:
            return 0

        if account_name is None:
            account_name = self.account_name

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT COUNT(*)
            FROM VIDEO.VideoOutput
            WHERE AccountName = ?
              AND SourceShortcode = ?
            ''',
            (account_name, clean_shortcode),
        )
        row = cursor.fetchone()
        return int(row[0] if row and row[0] is not None else 0)

    def save_video_application(
        self,
        vid_id: int,
        technique_class_id: int,
        technique_type_id: int,
        tsid: Optional[int] = None,
        key_technique: Optional[bool] = None,
    ) -> int:
        """Insert a VIDEO.Applications row and return inserted VidAID."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''
                SELECT TOP 1 VidAID
                FROM VIDEO.Applications
                WHERE VidID = ?
                  AND TechniqueClassID = ?
                  AND TechniqueTypeID = ?
                  AND TSID = ?
                ''',
                (
                    int(vid_id),
                    int(technique_class_id),
                    int(technique_type_id),
                    int(tsid) if tsid is not None else None,
                ),
            )
            existing_row = cursor.fetchone()
            if existing_row:
                raise ValueError(
                    f"Application already exists for VidID={int(vid_id)}, "
                    f"TechniqueClassID={int(technique_class_id)}, "
                    f"TechniqueTypeID={int(technique_type_id)}, TSID={int(tsid) if tsid is not None else 'NULL'}"
                )

            cursor.execute(
                '''
                INSERT INTO VIDEO.Applications (
                    VidID,
                    TechniqueClassID,
                    TechniqueTypeID,
                    TSID,
                    AlternateTechniqueName,
                    KeyTechnique,
                    FormationID,
                    PossessionStateID,
                    PitchPositionID,
                    ExerciseClassID,
                    MuscleGroupID,
                    EngagementMechanismID
                )
                OUTPUT INSERTED.VidAID
                VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL)
                ''',
                (
                    int(vid_id),
                    int(technique_class_id),
                    int(technique_type_id),
                    int(tsid) if tsid is not None else None,
                    (1 if key_technique is True else 0) if key_technique is not None else None,
                ),
            )
            inserted_row = cursor.fetchone()
            if not inserted_row:
                raise Exception("Failed to obtain inserted VidAID")
            conn.commit()
            return int(inserted_row[0])
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to save video application: {e}")

    def replace_video_applications(self, vid_id: int, applications: List[Dict[str, Any]]) -> None:
        """Replace all VIDEO.Applications rows for a VidID with provided payload rows."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''
                DELETE FROM VIDEO.Applications
                WHERE VidID = ?
                ''',
                (int(vid_id),),
            )

            seen_keys = set()
            for row in applications or []:
                class_id = int(row.get('TechniqueClassID'))
                type_id = int(row.get('TechniqueTypeID'))
                tsid = int(row.get('TSID')) if row.get('TSID') is not None else None
                key_technique = row.get('KeyTechnique')

                dedupe_key = (class_id, type_id, tsid)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                cursor.execute(
                    '''
                    INSERT INTO VIDEO.Applications (
                        VidID,
                        TechniqueClassID,
                        TechniqueTypeID,
                        TSID,
                        AlternateTechniqueName,
                        KeyTechnique,
                        FormationID,
                        PossessionStateID,
                        PitchPositionID,
                        ExerciseClassID,
                        MuscleGroupID,
                        EngagementMechanismID
                    )
                    VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL)
                    ''',
                    (
                        int(vid_id),
                        class_id,
                        type_id,
                        tsid,
                        (1 if bool(key_technique) else 0) if key_technique is not None else None,
                    ),
                )

            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to replace video applications: {e}")

    def get_video_applications(self, vid_id: int) -> List[Dict[str, Any]]:
        """Get VIDEO.Applications rows for a VidID."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT
                VidAID,
                VidID,
                TechniqueClassID,
                TechniqueTypeID,
                TSID,
                AlternateTechniqueName,
                KeyTechnique,
                FormationID,
                PossessionStateID,
                PitchPositionID,
                ExerciseClassID,
                MuscleGroupID,
                EngagementMechanismID
            FROM VIDEO.Applications
            WHERE VidID = ?
            ORDER BY VidAID ASC
            ''',
            (int(vid_id),),
        )

        results = []
        for row in cursor.fetchall():
            results.append(self._dict_from_row(cursor, row))
        return results

    def delete_video_application(self, vid_aid: int) -> bool:
        """Delete a VIDEO.Applications row by VidAID."""
        self.ensure_video_output_tables()
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''
                DELETE FROM VIDEO.Applications
                WHERE VidAID = ?
                ''',
                (int(vid_aid),),
            )
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to delete video application: {e}")

    def ensure_video_node_tables(self):
        """Ensure VIDEO.NodeOutput exists in a multi-row capable form."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1 FROM sys.tables t
                    INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE s.name = \'VIDEO\' AND t.name = \'NodeOutput\'
                )
                BEGIN
                    CREATE TABLE VIDEO.NodeOutput (
                        VidNID BIGINT IDENTITY(1,1) NOT NULL,
                        VidID  BIGINT NOT NULL,
                        FlowID BIGINT NULL,
                        ParentNodeID BIGINT NULL,
                        NodeName NVARCHAR(256) NULL,
                        NodeDescription NVARCHAR(MAX) NULL,
                        CONSTRAINT PK_NodeOutput PRIMARY KEY CLUSTERED (VidNID ASC),
                        CONSTRAINT FK_NodeOutput_VideoOutput FOREIGN KEY (VidID)
                            REFERENCES VIDEO.VideoOutput(VidID) ON DELETE CASCADE
                    )
                END
            ''')
            conn.commit()
            cursor.execute('''
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE object_id = OBJECT_ID(\'VIDEO.NodeOutput\')
                      AND name = \'IX_NodeOutput_VidID\'
                )
                BEGIN
                    CREATE INDEX IX_NodeOutput_VidID
                    ON VIDEO.NodeOutput(VidID)
                END
            ''')
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to ensure VIDEO.NodeOutput table: {e}")

    def replace_video_nodes(self, vid_id: int, nodes: List[Dict[str, Any]]) -> None:
        """Replace all VIDEO.NodeOutput rows for a VidID with the provided list."""
        self.ensure_video_node_tables()
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'DELETE FROM VIDEO.NodeOutput WHERE VidID = ?',
                (int(vid_id),),
            )
            for node in nodes or []:
                node_name = (str(node.get('NodeName') or '')).strip() or None
                cursor.execute(
                    '''
                    INSERT INTO VIDEO.NodeOutput
                        (VidID, FlowID, ParentNodeID, NodeName, NodeDescription)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (
                        int(vid_id),
                        int(node['FlowID']) if node.get('FlowID') is not None else None,
                        int(node['ParentNodeID']) if node.get('ParentNodeID') is not None else None,
                        node_name,
                        (str(node.get('NodeDescription') or '')).strip() or None,
                    ),
                )
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to replace video nodes: {e}")

    def get_video_nodes(self, vid_id: int) -> List[Dict[str, Any]]:
        """Get VIDEO.NodeOutput rows for a VidID."""
        self.ensure_video_node_tables()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT VidID, FlowID, ParentNodeID, NodeName, NodeDescription
            FROM VIDEO.NodeOutput
            WHERE VidID = ?
            ORDER BY
                COALESCE(FlowID, 9223372036854775807),
                COALESCE(ParentNodeID, 9223372036854775807),
                COALESCE(NodeName, N''),
                COALESCE(NodeDescription, N'')
            ''',
            (int(vid_id),),
        )
        results = []
        for row in cursor.fetchall():
            results.append(self._dict_from_row(cursor, row))
        return results

    def ensure_queue_table(self):
        """Ensure download queue table exists."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if table exists
            cursor.execute("""
                SELECT * FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'DL' AND TABLE_NAME = 'download_queue'
            """)
            
            if not cursor.fetchone():
                # Create table
                cursor.execute("""
                    CREATE TABLE DL.download_queue (
                        queue_id INT IDENTITY(1,1) PRIMARY KEY,
                        account_name NVARCHAR(255) NOT NULL,
                        content_id NVARCHAR(50) NOT NULL,
                        row_number INT,
                        caption NVARCHAR(MAX),
                        target_directory NVARCHAR(500),
                        queue_status NVARCHAR(50) DEFAULT 'pending',
                        added_at DATETIME DEFAULT GETDATE(),
                        started_at DATETIME,
                        completed_at DATETIME,
                        error_message NVARCHAR(MAX),
                        CONSTRAINT UQ_queue_account_content UNIQUE (account_name, content_id)
                    )
                """)
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to ensure queue table: {e}")
    
    def add_to_queue(self, content_id: str, row_number: int = None, 
                     caption: str = None, target_directory: str = None) -> bool:
        """
        Add item to download queue.
        
        Args:
            content_id: Content shortcode
            row_number: Row number from content_entries
            caption: Post caption
            target_directory: Target download directory
            
        Returns:
            True if added, False if already in queue
        """
        self.ensure_queue_table()
        logger.info(f"add_to_queue() called: account={self.account_name}, content_id={content_id}, row_number={row_number}")
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO DL.download_queue 
                (account_name, content_id, row_number, caption, target_directory, queue_status)
                VALUES (?, ?, ?, ?, ?, 'pending')
            """, (self.account_name, content_id, row_number, caption, target_directory))
            conn.commit()
            logger.info(f"Successfully added {content_id} to queue for {self.account_name}")
            return True
        except pyodbc.IntegrityError:
            # Already in queue
            conn.rollback()
            logger.info(f"Item {content_id} already in queue for {self.account_name}")
            return False
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add {content_id} to queue: {e}")
            raise Exception(f"Failed to add to queue: {e}")
    
    def remove_from_queue(self, content_id: str) -> bool:
        """
        Remove item from download queue.
        
        Args:
            content_id: Content shortcode
            
        Returns:
            True if removed, False if not found
        """
        self.ensure_queue_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                DELETE FROM DL.download_queue 
                WHERE account_name = ? AND content_id = ?
            """, (self.account_name, content_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to remove from queue: {e}")
    
    def get_queue(self) -> List[Dict[str, Any]]:
        """
        Get all items in download queue for current account.
        
        Returns:
            List of queue items ordered by added_at
        """
        self.ensure_queue_table()
        logger.info(f"get_queue() called for account: {self.account_name}")
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT queue_id, account_name, content_id, row_number, caption, 
                   target_directory, queue_status, added_at, started_at, 
                   completed_at, error_message
            FROM DL.download_queue
            WHERE account_name = ?
            ORDER BY added_at ASC
        """, (self.account_name,))
        
        results = [self._dict_from_row(cursor, row) for row in cursor.fetchall()]
        logger.info(f"get_queue() returning {len(results)} item(s) for {self.account_name}")
        return results
    
    def clear_queue(self, status_filter: str = None) -> int:
        """
        Clear download queue for current account.
        
        Args:
            status_filter: Optional filter (e.g., 'failed', 'completed')
            
        Returns:
            Number of items removed
        """
        self.ensure_queue_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if status_filter:
                cursor.execute("""
                    DELETE FROM DL.download_queue 
                    WHERE account_name = ? AND queue_status = ?
                """, (self.account_name, status_filter))
            else:
                cursor.execute("""
                    DELETE FROM DL.download_queue 
                    WHERE account_name = ?
                """, (self.account_name,))
            
            count = cursor.rowcount
            conn.commit()
            return count
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to clear queue: {e}")
    
    def update_queue_status(self, content_id: str, status: str, 
                           error_message: str = None) -> bool:
        """
        Update queue item status.
        
        Args:
            content_id: Content shortcode
            status: New status ('pending', 'downloading', 'completed', 'failed')
            error_message: Optional error message for failed items
            
        Returns:
            True if updated
        """
        self.ensure_queue_table()
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            if status == 'downloading':
                cursor.execute("""
                    UPDATE DL.download_queue 
                    SET queue_status = ?, started_at = GETDATE()
                    WHERE account_name = ? AND content_id = ?
                """, (status, self.account_name, content_id))
            elif status in ['completed', 'failed']:
                cursor.execute("""
                    UPDATE DL.download_queue 
                    SET queue_status = ?, completed_at = GETDATE(), error_message = ?
                    WHERE account_name = ? AND content_id = ?
                """, (status, error_message, self.account_name, content_id))
            else:
                cursor.execute("""
                    UPDATE DL.download_queue 
                    SET queue_status = ?, error_message = ?
                    WHERE account_name = ? AND content_id = ?
                """, (status, error_message, self.account_name, content_id))
            
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            raise Exception(f"Failed to update queue status: {e}")
    
    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
