"""
GUI - Clean PyQt5 interface for Instagram Downloader

Simple, intuitive interface with three main tabs:
- Accounts: Login, switch accounts
- Browse: View saved posts
- Download: Manage downloads
"""
import sys
import os
import json
import pickle
import platform
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QLineEdit, QListWidget,
    QMessageBox, QProgressBar, QTextEdit, QFileDialog, QListWidgetItem,
    QGroupBox, QGridLayout, QInputDialog, QTableWidget, QTableWidgetItem,
    QSplitter, QHeaderView, QCheckBox, QDialog, QScrollArea, QFrame,
    QStackedWidget, QComboBox, QSpinBox, QToolTip, QSlider, QTreeWidget, QTreeWidgetItem,
    QSizePolicy, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QObject, QMetaObject, Q_ARG, QSize, QTimer, QPoint, QUrl, QMutex
from PyQt5.QtGui import QPixmap, QColor, QFont, QImage
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
import logging

import config
from account_manager import AccountManager
from instagram_manager import InstagramManager
from content_database_manager import ContentDatabaseManager

logger = logging.getLogger(__name__)


class HoverImageLabel(QLabel):
    """QLabel that shows full-size image tooltip on hover"""
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setMouseTracking(True)
    
    def enterEvent(self, event):
        """Show full-size tooltip when mouse enters"""
        if self.image_path and os.path.exists(self.image_path):
            # Load full image
            pixmap = QPixmap(self.image_path)
            if not pixmap.isNull():
                # Scale to reasonable size (max 800x800)
                scaled = pixmap.scaled(800, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                # Create HTML for tooltip
                # Save scaled pixmap temporarily for tooltip
                QToolTip.showText(event.globalPos(), f'<img src="{self.image_path}" width="{min(scaled.width(), 800)}" height="{min(scaled.height(), 800)}">')
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Hide tooltip when mouse leaves"""
        QToolTip.hideText()
        super().leaveEvent(event)


class QTextEditLogger(logging.Handler, QObject):
    """Logging handler that writes to a QTextEdit widget (thread-safe)"""
    log_signal = pyqtSignal(str)
    
    def __init__(self, text_edit):
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.text_edit = text_edit
        self._closed = False
        # Prevent Python's logging.shutdown() from flushing when Qt objects are deleted
        self.flushOnClose = False
        # Connect signal to slot with auto-scroll
        self.log_signal.connect(self._append_and_scroll)
    
    def _append_and_scroll(self, msg):
        """Append text and scroll to bottom"""
        try:
            self.text_edit.append(msg)
            # Auto-scroll to bottom
            scrollbar = self.text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except RuntimeError:
            self._closed = True
    
    def emit(self, record):
        """Emit log record - safely handle if widget is deleted"""
        if self._closed:
            return
        try:
            msg = self.format(record)
            
            # Color-code download mode indicators
            if '(authenticated)' in msg.lower() or 'authenticated session' in msg.lower():
                # Red for authenticated mode
                msg = msg.replace('(authenticated)', '<span style="color: #ff3333; font-weight: bold;">(AUTHENTICATED)</span>')
                msg = msg.replace('(Authenticated)', '<span style="color: #ff3333; font-weight: bold;">(AUTHENTICATED)</span>')
                # Handle "Using authenticated session" phrase
                if 'Using authenticated session' in msg:
                    msg = msg.replace('Using authenticated session', '<span style="color: #ff3333; font-weight: bold;">Using AUTHENTICATED session</span>')
            elif '(anonymous)' in msg.lower() or 'anonymous download' in msg.lower():
                # Blue for anonymous mode
                msg = msg.replace('(anonymous)', '<span style="color: #0066ff; font-weight: bold;">(ANONYMOUS)</span>')
                msg = msg.replace('(Anonymous)', '<span style="color: #0066ff; font-weight: bold;">(ANONYMOUS)</span>')
                # Handle "Attempting anonymous download" phrase
                if 'Attempting anonymous download' in msg:
                    msg = msg.replace('Attempting anonymous download', '<span style="color: #0066ff; font-weight: bold;">Attempting ANONYMOUS download</span>')
            
            # Check for C: drive paths in DOWNLOADS/FILES only (not working directory)
            # Ignore references to the script's working directory (C:\A7\qs\...)
            if ('C:' in msg or 'c:' in msg) and 'qs.python.instagram-downloader' not in msg:
                # Check if it's actually a file/download path (contains common patterns)
                if any(pattern in msg.lower() for pattern in ['download', 'path', 'directory', 'file', '.jpg', '.mp4', '.png', 'sassenheimer\\D', 'Instagram\\']):
                    # Add red HTML formatting for C: drive warnings
                    msg = f'<span style="color: #ff3333; font-weight: bold;">⚠️ C: DRIVE FILE PATH DETECTED</span> {msg}'
            
            # Emit signal instead of directly calling append()
            # This ensures thread-safe operation
            self.log_signal.emit(msg)
        except RuntimeError:
            # Qt object has been deleted
            self._closed = True
    
    def close(self):
        """Close handler - safely disconnect without accessing Qt objects"""
        if not self._closed:
            self._closed = True
            try:
                # Disconnect signal if Qt objects still exist
                self.log_signal.disconnect()
            except (RuntimeError, TypeError):
                # Qt object already deleted or signal not connected
                pass
        # Call parent close but don't flush (flushOnClose = False)
        super().close()


class LoginThread(QThread):
    """Background thread for login operation"""
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, manager, username, password, session_file):
        super().__init__()
        self.manager = manager
        self.username = username
        self.password = password
        self.session_file = session_file
    
    def run(self):
        try:
            success = self.manager.login(self.username, self.password, self.session_file)
            if success:
                self.finished.emit(True, f"Logged in as {self.username}")
            else:
                self.finished.emit(False, "Login failed. Check credentials.")
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")


class LoadSavedThread(QThread):
    """Background thread for loading saved posts"""
    post_loaded = pyqtSignal(dict)  # individual post
    finished = pyqtSignal(int)  # total count
    error = pyqtSignal(str)
    duplicate_found = pyqtSignal(str)  # shortcode of duplicate post
    progress = pyqtSignal(int, int, int, str)  # total_fetched, new_count, existing_count, current_shortcode
    
    def __init__(self, manager, content_db, stop_at_first_duplicate, existing_shortcodes=None):
        super().__init__()
        self.manager = manager
        self.content_db = content_db
        self.stop_at_first_duplicate = stop_at_first_duplicate
        self.existing_shortcodes = existing_shortcodes or set()
        self._stop_requested = False
    
    def run(self):
        try:
            new_count = 0  # Posts that don't exist in database
            existing_count = 0  # Posts that already exist in database
            skipped_ui = 0  # Posts already loaded in UI
            total_fetched = 0  # Total posts fetched from Instagram
            
            for post in self.manager.get_saved_posts():
                if self._stop_requested:
                    break
                
                total_fetched += 1
                shortcode = post.get('shortcode')
                
                # Skip if already loaded in UI
                if shortcode in self.existing_shortcodes:
                    skipped_ui += 1
                    continue
                
                # Check if exists in database (before saving)
                is_existing = False
                if self.content_db:
                    is_existing = self.content_db.is_duplicate(shortcode)
                    
                    # Stop at first duplicate if setting is enabled
                    if self.stop_at_first_duplicate and is_existing:
                        self.duplicate_found.emit(shortcode)
                        break
                
                if is_existing:
                    existing_count += 1
                    # Don't add to UI - it's already in database
                    # Just emit progress but skip UI update to avoid duplicates
                    self.progress.emit(total_fetched, new_count, existing_count, shortcode)
                    logger.debug(f"Skipping {shortcode} - already in database")
                    continue
                else:
                    new_count += 1
                
                # Emit progress update
                self.progress.emit(total_fetched, new_count, existing_count, shortcode)
                
                # Only emit to UI if it's NEW (not in database)
                self.post_loaded.emit(post)
            
            logger.info(f"Fetched {total_fetched} saved posts from Instagram:")
            logger.info(f"  - {new_count} new (added to UI + database)")
            logger.info(f"  - {existing_count} already in database (skipped)")
            logger.info(f"  - {skipped_ui} already in UI (skipped)")
            self.finished.emit(new_count)
        except Exception as e:
            self.error.emit(f"Failed to load posts: {str(e)}")
    
    def stop(self):
        """Request the thread to stop"""
        self._stop_requested = True


class LoadPageThread(QThread):
    """Background thread for loading a single page of entries on demand"""
    page_loaded = pyqtSignal(int, list)  # page_num, posts
    error = pyqtSignal(str)
    
    def __init__(self, content_db, page_num, items_per_page, search_filters=None):
        super().__init__()
        self.content_db = content_db
        self.page_num = page_num
        self.items_per_page = items_per_page
        self.search_filters = search_filters or {}
        self._stop_requested = False
    
    def run(self):
        try:
            offset = self.page_num * self.items_per_page
            logger.debug(f"[LoadPageThread] Loading page {self.page_num} (offset={offset}, limit={self.items_per_page})")
            
            # Check if stopped before starting
            if self._stop_requested:
                logger.debug(f"[LoadPageThread] Page {self.page_num} load cancelled before starting")
                return
            
            # Extract sort/filter parameters from search_filters
            sort_by_ui = self.search_filters.get('sort_by', 'Row Number')
            sort_direction = self.search_filters.get('sort_direction', 'DESC')
            filter_ui = self.search_filters.get('filter', 'All (Unfiltered)')
            topic_filter = self.search_filters.get('topic_filter', 'All Topics')
            
            logger.info(f"[LoadPageThread] Page {self.page_num}: sort_by_ui={sort_by_ui}, direction={sort_direction}")
            
            # Map UI dropdown text to database column names
            sort_by_map = {
                'Save Date': 'saved_time',
                'Post Date': 'posted_time',
                'Import Date': 'import_time',
                'Row Number': 'row_number'
            }
            sort_by_db = sort_by_map.get(sort_by_ui, 'row_number')
            
            logger.info(f"[LoadPageThread] Page {self.page_num}: Mapped '{sort_by_ui}' to database field '{sort_by_db}'")
            
            # Map filter dropdown to filter type
            filter_type = None
            if filter_ui == 'Only Ignored (Black) Items':
                filter_type = 'ignored'
            elif filter_ui == 'Only Uncategorized':
                filter_type = 'uncategorized'
            elif filter_ui == 'Only Categorized & Undownloaded':
                filter_type = 'categorized_undownloaded'
            elif filter_ui == 'Only Error Items':
                filter_type = 'error'
            elif filter_ui == 'Specific Topic-Undownloaded':
                filter_type = 'specific_topic_undownloaded'
            
            # Only apply topic criteria for the specific-topic filter mode.
            topic_name = None
            if filter_ui == 'Specific Topic-Undownloaded':
                topic_name = None if topic_filter == 'All Topics' else topic_filter
            
            logger.info(f"[LoadPageThread] Page {self.page_num}: Calling get_all_account_entries with sort_by={sort_by_db}, direction={sort_direction}")
            
            # Get entries for this page with sort/filter
            entries = self.content_db.get_all_account_entries(
                limit=self.items_per_page, 
                offset=offset,
                sort_by=sort_by_db,
                sort_direction=sort_direction,
                filter_type=filter_type,
                topic_filter=topic_name
            )
            
            logger.info(f"[LoadPageThread] Page {self.page_num}: Retrieved {len(entries)} entries from database")
            
            # Check if stopped after database query
            if self._stop_requested:
                logger.debug(f"Page {self.page_num} load cancelled after database query")
                return
            
            # Convert to posts
            posts = []
            for entry in entries:
                if self._stop_requested:
                    logger.debug(f"Page {self.page_num} load cancelled during conversion")
                    return
                post = self.content_db.convert_entry_to_post(entry)
                if post:
                    posts.append(post)
            
            # Only emit if not stopped
            if not self._stop_requested:
                logger.debug(f"Page {self.page_num} loaded: {len(posts)} posts")
                self.page_loaded.emit(self.page_num, posts)
            else:
                logger.debug(f"Page {self.page_num} load cancelled after conversion")
            
        except Exception as e:
            if not self._stop_requested:
                self.error.emit(f"Failed to load page {self.page_num}: {str(e)}")
    
    def stop(self):
        """Request the thread to stop"""
        self._stop_requested = True


class LoadDatabaseThread(QThread):
    """Background thread for getting database count and initializing lazy loading"""
    count_loaded = pyqtSignal(int, dict)  # total count, statistics
    error = pyqtSignal(str)
    
    def __init__(self, content_db):
        super().__init__()
        self.content_db = content_db
        self._stop_requested = False
    
    def run(self):
        try:
            logger.info("LoadDatabaseThread.run() started - getting count")
            # Get total count (fast query - no data loading)
            total = self.content_db.get_content_count()
            logger.info(f"Got total count: {total}")
            
            # Get statistics
            stats = self.content_db.get_statistics()
            logger.info(f"Got statistics: {stats}")
            
            logger.info(f"Database initialized: {total} entries total (lazy loading enabled)")
            self.count_loaded.emit(total, stats)
            logger.info("count_loaded signal emitted")
            
        except Exception as e:
            logger.error(f"LoadDatabaseThread error: {e}", exc_info=True)
            self.error.emit(f"Failed to initialize database: {str(e)}")
    
    def stop(self):
        """Request the thread to stop"""
        self._stop_requested = True


class DownloadThread(QThread):
    """Background thread for downloading posts with pause/resume/cancel support"""
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(int, int)  # success, failed
    status = pyqtSignal(str)
    download_complete = pyqtSignal(str, bool, str, str, list, dict)  # shortcode, success, file_path, error_msg, downloaded_files, metadata
    session_expired = pyqtSignal()  # Signal when session expires during download
    
    def __init__(self, manager, shortcodes, target_dir, process_id=None):
        super().__init__()
        self.manager = manager
        self.shortcodes = shortcodes
        self.target_dir = target_dir
        self.process_id = process_id
        
        # Control flags
        self._paused = False
        self._cancelled = False
        self._mutex = QMutex()
        
    def pause(self):
        """Pause the download"""
        logger.info(f"DownloadThread.pause() called for process {self.process_id}")
        self._mutex.lock()
        self._paused = True
        self._mutex.unlock()
        logger.info(f"DownloadThread paused flag set to True for process {self.process_id}")
        self.status.emit("Paused")
        
    def resume(self):
        """Resume the download"""
        logger.info(f"DownloadThread.resume() called for process {self.process_id}")
        self._mutex.lock()
        self._paused = False
        self._mutex.unlock()
        logger.info(f"DownloadThread paused flag set to False for process {self.process_id}")
        
    def cancel(self):
        """Cancel the download"""
        logger.info(f"DownloadThread.cancel() called for process {self.process_id}")
        self._mutex.lock()
        self._cancelled = True
        self._paused = False
        self._mutex.unlock()
        logger.info(f"DownloadThread cancelled flag set to True for process {self.process_id}")
        self.status.emit("Cancelled")
    
    def is_paused(self):
        """Check if paused"""
        self._mutex.lock()
        result = self._paused
        self._mutex.unlock()
        return result
    
    def is_cancelled(self):
        """Check if cancelled"""
        self._mutex.lock()
        result = self._cancelled
        self._mutex.unlock()
        return result
    
    def run(self):
        import os
        import time
        logger.info(f"DownloadThread.run() started for process {self.process_id}, {len(self.shortcodes)} shortcode(s)")
        success = 0
        failed = 0
        total = len(self.shortcodes)
        
        for i, shortcode in enumerate(self.shortcodes, 1):
            # Check for cancellation
            if self.is_cancelled():
                logger.info(f"DownloadThread detected cancellation at start of loop iteration {i}")
                self.status.emit("Cancelled")
                break
            
            # Wait while paused
            if self.is_paused():
                logger.info(f"DownloadThread detected pause at iteration {i}, entering pause loop")
            while self.is_paused() and not self.is_cancelled():
                time.sleep(0.1)
            
            # Check again after pause
            if self.is_cancelled():
                logger.info(f"DownloadThread detected cancellation after pause at iteration {i}")
                self.status.emit("Cancelled")
                break
            
            # Add delay between downloads to avoid Instagram rate limiting (except for first download)
            if i > 1:
                delay = 10  # 10 second delay between downloads to avoid detection
                logger.info(f"Waiting {delay} seconds before next download (avoiding Instagram detection)...")
                time.sleep(delay)
            elif i == 1:
                # Even before first download in a batch, add a small delay if not first ever download
                delay = 3
                logger.info(f"Initial {delay} second delay before starting batch download...")
                time.sleep(delay)
            
            self.status.emit(f"Downloading {shortcode}...")
            self.progress.emit(i, total)
            
            try:
                result, metadata = self.manager.download_post(shortcode, self.target_dir)
                
                if result:
                    success += 1
                    # Emit success with metadata (caption, tags, files, owner, typename)
                    self.download_complete.emit(
                        shortcode, True, str(self.target_dir), "", 
                        metadata.get('files', []), metadata
                    )
                else:
                    failed += 1
                    self.download_complete.emit(shortcode, False, "", "Download failed", [], {})
            except Exception as e:
                failed += 1
                error_msg = str(e)
                
                # Check if session expired or rate limited
                if "BadResponseException" in str(type(e).__name__) or "Fetching Post metadata failed" in error_msg:
                    self.session_expired.emit()
                
                # Check if rate limited (feedback_required)
                if "feedback_required" in error_msg.lower():
                    logger.warning(f"Instagram rate limit detected for {shortcode}. Try again in a few minutes or reduce download speed.")
                
                # Emit the actual exception message
                self.download_complete.emit(shortcode, False, "", error_msg, [], {})

            # Emit detailed action report after each processed item.
            completed = success + failed
            percent = int((completed * 100) / total) if total else 100
            if failed > 0:
                self.status.emit(f"{completed} / {total} ({percent}%, {failed} failures)")
            else:
                self.status.emit(f"{completed} / {total} ({percent}%)")
        
        self.finished.emit(success, failed)


class ProcessManager(QObject):
    """Manages background processes with pause/resume/cancel support"""
    process_added = pyqtSignal(str, str, str)  # process_id, process_type, description
    process_updated = pyqtSignal(str, str, int, int)  # process_id, status, current, total
    process_removed = pyqtSignal(str)  # process_id
    
    def __init__(self):
        super().__init__()
        self.processes = {}  # {process_id: {type, description, status, thread, current, total}}
        self.next_id = 1
        
    def add_process(self, process_type, description, thread=None):
        """Add a new process to track
        
        Args:
            process_type: Type of process ('batch_download', 'single_download', 'thumbnail_bulk')
            description: Human-readable description
            thread: Optional thread object (DownloadThread, etc.)
            
        Returns:
            process_id: Unique identifier for this process
        """
        process_id = f"proc_{self.next_id}"
        self.next_id += 1
        
        self.processes[process_id] = {
            'type': process_type,
            'description': description,
            'status': 'running',
            'thread': thread,
            'current': 0,
            'total': 0,
            'start_time': QTimer()  # Track how long it's been running
        }
        
        self.process_added.emit(process_id, process_type, description)
        logger.info(f"Process added: {process_id} - {description}")
        return process_id
    
    def update_process(self, process_id, status=None, current=None, total=None):
        """Update process status and progress"""
        if process_id not in self.processes:
            return
        
        process = self.processes[process_id]
        if status is not None:
            process['status'] = status
        if current is not None:
            process['current'] = current
        if total is not None:
            process['total'] = total
        
        self.process_updated.emit(
            process_id,
            process['status'],
            process['current'],
            process['total']
        )
    
    def remove_process(self, process_id):
        """Remove a completed/cancelled process"""
        if process_id in self.processes:
            del self.processes[process_id]
            self.process_removed.emit(process_id)
            logger.info(f"Process removed: {process_id}")
    
    def get_process(self, process_id):
        """Get process info"""
        return self.processes.get(process_id)
    
    def get_all_processes(self):
        """Get all processes"""
        return dict(self.processes)
    
    def pause_process(self, process_id):
        """Pause a process"""
        logger.info(f"ProcessManager.pause_process() called for {process_id}")
        process = self.processes.get(process_id)
        if not process:
            logger.warning(f"Process {process_id} not found in processes dict")
            return
        logger.info(f"Process found: type={process['type']}, status={process['status']}, has_thread={process['thread'] is not None}")
        if process and process['thread']:
            if hasattr(process['thread'], 'pause'):
                logger.info(f"Calling thread.pause() for {process_id}")
                process['thread'].pause()
                process['status'] = 'paused'
                self.process_updated.emit(process_id, 'paused', process['current'], process['total'])
                logger.info(f"Process paused: {process_id}")
            else:
                logger.warning(f"Thread for {process_id} does not have pause() method")
        else:
            logger.warning(f"No thread reference for process {process_id}")
    
    def resume_process(self, process_id):
        """Resume a paused process"""
        logger.info(f"ProcessManager.resume_process() called for {process_id}")
        process = self.processes.get(process_id)
        if not process:
            logger.warning(f"Process {process_id} not found in processes dict")
            return
        logger.info(f"Process found: type={process['type']}, status={process['status']}, has_thread={process['thread'] is not None}")
        if process and process['thread']:
            if hasattr(process['thread'], 'resume'):
                logger.info(f"Calling thread.resume() for {process_id}")
                process['thread'].resume()
                process['status'] = 'running'
                self.process_updated.emit(process_id, 'running', process['current'], process['total'])
                logger.info(f"Process resumed: {process_id}")
            else:
                logger.warning(f"Thread for {process_id} does not have resume() method")
        else:
            logger.warning(f"No thread reference for process {process_id}")
    
    def cancel_process(self, process_id):
        """Cancel a process"""
        logger.info(f"ProcessManager.cancel_process() called for {process_id}")
        process = self.processes.get(process_id)
        if not process:
            logger.warning(f"Process {process_id} not found in processes dict")
            return
        logger.info(f"Process found: type={process['type']}, status={process['status']}, has_thread={process['thread'] is not None}")
        if process and process['thread']:
            if hasattr(process['thread'], 'cancel'):
                logger.info(f"Calling thread.cancel() for {process_id}")
                process['thread'].cancel()
                process['status'] = 'cancelled'
                self.process_updated.emit(process_id, 'cancelled', process['current'], process['total'])
                logger.info(f"Process cancelled: {process_id}")
            else:
                logger.warning(f"Thread for {process_id} does not have cancel() method")
        else:
            logger.warning(f"No thread reference for process {process_id}")
    
    def restart_process(self, process_id):
        """Restart a cancelled/failed process (not implemented yet)"""
        logger.warning(f"Restart not yet implemented for {process_id}")
        # TODO: Implement restart logic


class InstagramDownloaderGUI(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.account_manager = AccountManager()
        self.instagram_manager = InstagramManager()
        self.content_db = None  # Will be initialized when user logs in
        self.current_username = None
        self.saved_posts = []  # Deprecated - kept for backward compatibility
        
        # === Lazy loading system ===
        self.total_items = 0  # Total count from database
        self.page_cache = {}  # {page_num: [posts]}
        self.cache_max_pages = 5  # Keep up to 5 pages in memory
        self.loading_pages = set()  # Track pages currently being loaded
        self.page_load_threads = {}  # {page_num: LoadPageThread}
        self.posts_added_since_pagination_update = 0  # Track when to update pagination
        
        # Fetch tracking for pagination adjustment
        self.fetch_in_progress = False
        self.fetch_initial_total_items = 0
        self.fetch_initial_page = 0
        
        self.db_load_thread = None  # Thread for loading database entries
        self.queued_shortcodes = set()  # Track shortcodes in download queue
        self.selected_tiles = set()  # Track selected tile shortcodes for batch operations
        self.carousel_indices = {}  # Track current index for carousel posts {shortcode: index}
        self.active_download_threads = []  # Track active download threads
        self.thumbnail_threads = []  # Track active thumbnail download threads
        self.stop_thumbnail_downloads = False  # Flag to stop thumbnail downloads
        
        # Path settings (loaded from account)
        self.thumbnails_path = None  # Will be set from account
        self.topics_root_path = None  # Will be set from account
        
        # Process manager for tracking background operations
        self.process_manager = ProcessManager()
        
        # View mode settings
        self.current_view_mode = 'tiles'  # Always use tiles (table view disabled)
        self.tiles_per_page = 20
        self.current_page = 0
        self.target_page = 0  # Target page to restore after data loads (from saved settings)
        self.filtered_posts = []  # Posts after filtering for pagination
        self.current_tile_data = {}  # Track currently displayed tiles: {(row, col): (shortcode, status_hash)}
        self.last_displayed_page = -1  # Track which page is currently displayed
        self.last_displayed_columns = 0  # Track column count for layout changes
        
        # Table pagination settings
        self.table_current_page = 0
        self.table_items_per_page = 100
        
        self.tile_size = 'medium'  # 'small', 'medium', 'large', 'xlarge'
        self.theme = 'light'  # 'light' or 'dark'
        self.inline_video = False  # Play videos inline (True) or in popup (False)
        self.tile_video_volume = 30  # Default volume for inline tile videos (0-100)
        self.resize_timer = QTimer()  # Timer for debouncing window resize
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.on_resize_complete)
        self._populating_tiles = False  # Flag to prevent concurrent populate_tiles calls
        
        # Qt multimedia availability check - load from settings
        saved_qt_available = self.account_manager.get_setting('qt_multimedia_available', 'auto')
        if saved_qt_available == 'auto':
            self.qt_multimedia_available = None  # Not checked yet
        else:
            self.qt_multimedia_available = saved_qt_available == 'true'
            if not self.qt_multimedia_available:
                logger.info("Qt multimedia previously detected as unavailable - will use alternate player")
        
        # VLC player availability (lazy check)
        self.vlc_available = None  # None=not checked, True/False=result
        self.vlc_instance = None
        
        # Force system player (skip all built-in players)
        self.force_system_player = self.account_manager.get_setting('force_system_player', 'false') == 'true'
        if self.force_system_player:
            logger.info("Force system player enabled - will skip built-in players")
        
        # Sort and filter settings
        self.current_sort_by = 'Row Number'  # Default sort field
        self.current_sort_direction = 'DESC'  # Default sort direction
        self.current_filter = 'All (Unfiltered)'  # Default filter
        self.current_topic_filter = 'All Topics'  # Default topic filter
        
        # Load settings BEFORE init_ui (which creates the checkboxes)
        self.auto_load_at_startup = self.account_manager.get_setting('auto_load_at_startup', 'true') == 'true'
        self.stop_at_first_duplicate = self.account_manager.get_setting('stop_at_first_duplicate', 'false') == 'true'
        self.auto_fetch_thumbnails = self.account_manager.get_setting('auto_fetch_thumbnails', 'false') == 'true'
        self.auto_fetch_new_thumbnails = self.account_manager.get_setting('auto_fetch_new_thumbnails', 'true') == 'true'
        
        self.init_ui()
        config.ensure_directories()
        
        # Auto-login with most recent account if available
        self.auto_login()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(config.APP_NAME)
        self.setGeometry(100, 100, 1400, config.WINDOW_HEIGHT)  # Wider for log panel
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Create splitter for main content and log panel
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Main content with tabs
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top toolbar with Exit button
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(5, 5, 5, 5)
        
        toolbar_layout.addStretch()
        
        exit_btn = QPushButton("🚪 Exit")
        exit_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; font-weight: bold; padding: 5px 15px; }")
        exit_btn.setToolTip("Close the application")
        exit_btn.clicked.connect(self.exit_application)
        toolbar_layout.addWidget(exit_btn)
        
        left_layout.addLayout(toolbar_layout)
        
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        left_layout.addWidget(self.tabs)
        
        # Create tabs (Browse and Download first, Accounts last)
        self.create_browse_tab()
        self.create_download_tab()
        self.create_topics_tab()
        self.create_settings_tab()
        self.create_account_tab()
        
        splitter.addWidget(left_widget)
        
        # Right side: Log console
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create vertical splitter for console log and process table
        right_splitter = QSplitter(Qt.Vertical)
        
        # Top half: Console Log
        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        console_layout.setContentsMargins(0, 0, 0, 0)
        
        log_label = QLabel("Console Log")
        log_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        console_layout.addWidget(log_label)
        
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setAcceptRichText(True)  # Enable HTML formatting for colored warnings
        self.log_console.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
            }
        """)
        console_layout.addWidget(self.log_console)
        
        # Console buttons
        console_buttons_layout = QHBoxLayout()
        
        copy_console_btn = QPushButton("📋 Copy Console Text")
        copy_console_btn.clicked.connect(self.copy_console_text)
        console_buttons_layout.addWidget(copy_console_btn)
        
        clear_btn = QPushButton("🗑 Clear Log")
        clear_btn.clicked.connect(self.log_console.clear)
        console_buttons_layout.addWidget(clear_btn)
        
        console_layout.addLayout(console_buttons_layout)
        
        right_splitter.addWidget(console_widget)
        
        # Bottom half: Process Manager
        process_widget = QWidget()
        process_layout = QVBoxLayout(process_widget)
        process_layout.setContentsMargins(0, 0, 0, 0)
        
        process_label = QLabel("Queued Processes")
        process_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        process_layout.addWidget(process_label)
        
        # Process table
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(6)
        self.process_table.setHorizontalHeaderLabels([
            "☑", "Process", "Status", "Progress", "Actions", "ID"
        ])
        self.process_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.process_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.process_table.horizontalHeader().setStretchLastSection(False)
        self.process_table.setColumnWidth(0, 30)  # Checkbox
        self.process_table.setColumnWidth(1, 200)  # Process name
        self.process_table.setColumnWidth(2, 80)  # Status
        self.process_table.setColumnWidth(3, 150)  # Progress
        self.process_table.setColumnWidth(4, 150)  # Actions
        self.process_table.setColumnHidden(5, True)  # ID column (hidden)
        process_layout.addWidget(self.process_table)
        
        # Bulk action buttons
        bulk_actions_layout = QHBoxLayout()
        
        self.select_all_processes_btn = QPushButton("Select All")
        self.select_all_processes_btn.clicked.connect(self.select_all_processes)
        bulk_actions_layout.addWidget(self.select_all_processes_btn)
        
        self.deselect_all_processes_btn = QPushButton("Deselect All")
        self.deselect_all_processes_btn.clicked.connect(self.deselect_all_processes)
        bulk_actions_layout.addWidget(self.deselect_all_processes_btn)
        
        bulk_actions_layout.addStretch()
        
        self.pause_selected_btn = QPushButton("⏸ Pause Selected")
        self.pause_selected_btn.clicked.connect(self.pause_selected_processes)
        bulk_actions_layout.addWidget(self.pause_selected_btn)
        
        self.resume_selected_btn = QPushButton("▶ Resume Selected")
        self.resume_selected_btn.clicked.connect(self.resume_selected_processes)
        bulk_actions_layout.addWidget(self.resume_selected_btn)
        
        self.cancel_selected_btn = QPushButton("⏹ Cancel Selected")
        self.cancel_selected_btn.clicked.connect(self.cancel_selected_processes)
        bulk_actions_layout.addWidget(self.cancel_selected_btn)
        
        self.clear_completed_btn = QPushButton("🗑 Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed_processes)
        bulk_actions_layout.addWidget(self.clear_completed_btn)
        
        process_layout.addLayout(bulk_actions_layout)
        
        right_splitter.addWidget(process_widget)
        
        # Set splitter to 50/50 split
        right_splitter.setSizes([300, 300])
        
        right_layout.addWidget(right_splitter)
        
        splitter.addWidget(right_widget)
        
        # Set splitter sizes (70% main content, 30% log+processes)
        splitter.setSizes([980, 420])
        
        main_layout.addWidget(splitter)
        
        # Setup logging to console
        self.setup_logging()
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def setup_logging(self):
        """Setup logging to GUI console"""
        # Create handler
        self.gui_handler = QTextEditLogger(self.log_console)
        self.gui_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))
        
        # Add to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.gui_handler)
        root_logger.setLevel(logging.INFO)
        
        # Initialize thumbnail cache
        self.thumbnail_cache = {}  # {shortcode: QPixmap}
        
        # Connect process manager signals
        self.process_manager.process_added.connect(self.on_process_added)
        self.process_manager.process_updated.connect(self.on_process_updated)
        self.process_manager.process_removed.connect(self.on_process_removed)
    
    # ========== PROCESS MANAGEMENT METHODS ==========
    
    def on_process_added(self, process_id, process_type, description):
        """Handle new process added"""
        row = 0  # Insert at top for newest-first ordering
        self.process_table.insertRow(row)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox_widget = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_widget)
        checkbox_layout.addWidget(checkbox)
        checkbox_layout.setAlignment(Qt.AlignCenter)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        self.process_table.setCellWidget(row, 0, checkbox_widget)
        
        # Process description
        self.process_table.setItem(row, 1, QTableWidgetItem(description))
        
        # Status
        status_item = QTableWidgetItem("Running")
        status_item.setForeground(QColor("#28a745"))  # Green
        self.process_table.setItem(row, 2, status_item)
        
        # Progress
        self.process_table.setItem(row, 3, QTableWidgetItem("0 / 0"))
        
        # Action buttons
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(2, 2, 2, 2)
        actions_layout.setSpacing(2)
        
        pause_btn = QPushButton("⏸")
        pause_btn.setMaximumWidth(30)
        pause_btn.setToolTip("Pause")
        pause_btn.clicked.connect(lambda: self.pause_process_by_id(process_id))
        actions_layout.addWidget(pause_btn)
        
        cancel_btn = QPushButton("⏹")
        cancel_btn.setMaximumWidth(30)
        cancel_btn.setToolTip("Cancel")
        cancel_btn.clicked.connect(lambda: self.cancel_process_by_id(process_id))
        actions_layout.addWidget(cancel_btn)
        
        clear_btn = QPushButton("🗑")
        clear_btn.setMaximumWidth(30)
        clear_btn.setToolTip("Clear")
        clear_btn.clicked.connect(lambda: self.clear_process_by_id(process_id))
        actions_layout.addWidget(clear_btn)
        
        actions_layout.addStretch()
        self.process_table.setCellWidget(row, 4, actions_widget)
        
        # Hidden ID column
        self.process_table.setItem(row, 5, QTableWidgetItem(process_id))
    
    def on_process_updated(self, process_id, status, current, total):
        """Handle process status/progress update"""
        # Find row with this process_id
        for row in range(self.process_table.rowCount()):
            id_item = self.process_table.item(row, 5)
            if id_item and id_item.text() == process_id:
                # Update status
                status_item = self.process_table.item(row, 2)
                if status_item:
                    # Format status text for display
                    status_display = status.replace('_', ' ').title()
                    status_item.setText(status_display)
                    # Color code status
                    if status == 'running':
                        status_item.setForeground(QColor("#28a745"))  # Green
                    elif status == 're-downloading':
                        status_item.setForeground(QColor("#17a2b8"))  # Cyan (distinct from regular running)
                    elif status == 'paused':
                        status_item.setForeground(QColor("#ffc107"))  # Yellow
                    elif status == 'cancelled':
                        status_item.setForeground(QColor("#dc3545"))  # Red
                    elif status == 'completed':
                        status_item.setForeground(QColor("#007bff"))  # Blue
                    elif status == 're-downloaded':
                        status_item.setForeground(QColor("#6610f2"))  # Purple (distinct from completed)
                    elif status == 'failed':
                        status_item.setForeground(QColor("#dc3545"))  # Red
                    elif status == 'completed_with_errors':
                        status_item.setForeground(QColor("#ff8c00"))  # Orange
                
                # Update progress
                progress_item = self.process_table.item(row, 3)
                if progress_item:
                    if total > 0:
                        percentage = int((current / total) * 100)
                        progress_item.setText(f"{current} / {total} ({percentage}%)")
                    else:
                        progress_item.setText(f"{current} / {total}")
                break
    
    def on_process_removed(self, process_id):
        """Handle process removal"""
        # Find and remove row with this process_id
        for row in range(self.process_table.rowCount()):
            id_item = self.process_table.item(row, 5)
            if id_item and id_item.text() == process_id:
                self.process_table.removeRow(row)
                break
    
    def pause_process_by_id(self, process_id):
        """Pause a specific process"""
        logger.info(f"UI: pause_process_by_id() called for {process_id}")
        self.process_manager.pause_process(process_id)
    
    def cancel_process_by_id(self, process_id):
        """Cancel a specific process"""
        logger.info(f"UI: cancel_process_by_id() called for {process_id}")
        self.process_manager.cancel_process(process_id)
    
    def clear_process_by_id(self, process_id):
        """Clear/remove a specific process from the list"""
        self.process_manager.remove_process(process_id)
    
    def get_selected_process_ids(self):
        """Get list of selected process IDs"""
        selected_ids = []
        for row in range(self.process_table.rowCount()):
            checkbox_widget = self.process_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    id_item = self.process_table.item(row, 5)
                    if id_item:
                        selected_ids.append(id_item.text())
        return selected_ids
    
    def select_all_processes(self):
        """Select all processes"""
        for row in range(self.process_table.rowCount()):
            checkbox_widget = self.process_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(True)
    
    def deselect_all_processes(self):
        """Deselect all processes"""
        for row in range(self.process_table.rowCount()):
            checkbox_widget = self.process_table.cellWidget(row, 0)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)
    
    def pause_selected_processes(self):
        """Pause all selected processes"""
        selected_ids = self.get_selected_process_ids()
        logger.info(f"UI: pause_selected_processes() called for {len(selected_ids)} process(es): {selected_ids}")
        for process_id in selected_ids:
            self.process_manager.pause_process(process_id)
    
    def resume_selected_processes(self):
        """Resume all selected processes"""
        selected_ids = self.get_selected_process_ids()
        logger.info(f"UI: resume_selected_processes() called for {len(selected_ids)} process(es): {selected_ids}")
        for process_id in selected_ids:
            self.process_manager.resume_process(process_id)
    
    def cancel_selected_processes(self):
        """Cancel all selected processes"""
        selected_ids = self.get_selected_process_ids()
        logger.info(f"UI: cancel_selected_processes() called for {len(selected_ids)} process(es): {selected_ids}")
        for process_id in selected_ids:
            self.process_manager.cancel_process(process_id)
    
    def clear_completed_processes(self):
        """Clear all completed/cancelled processes"""
        to_remove = []
        for process_id, process in self.process_manager.get_all_processes().items():
            if process['status'] in ['completed', 're-downloaded', 'cancelled', 'failed']:
                to_remove.append(process_id)
        
        for process_id in to_remove:
            self.process_manager.remove_process(process_id)
    
    # ========== END PROCESS MANAGEMENT METHODS ==========
    
    @staticmethod
    def sanitize_topic_path(topic_path):
        """
        Sanitize and validate a topic path to ensure it's safe.
        Supports both absolute paths (with drive letters) and relative paths.
        
        Args:
            topic_path: Path string from user input or database
        
        Returns:
            Tuple of (sanitized_path, is_absolute) or (None, False) if invalid
        """
        if not topic_path or not topic_path.strip():
            return None, False
        
        # Remove leading/trailing whitespace
        path = topic_path.strip()
        
        # Check if it's an absolute Windows path with drive letter (e.g., C:\, G:\)
        is_absolute = False
        if len(path) >= 2 and path[1] == ':':
            # It's an absolute path with drive letter - keep it
            is_absolute = True
            logger.info(f"Topic path is absolute: {path}")
        
        # Block UNC paths (\\server\share) - these are security risks
        if path.startswith('\\\\') or path.startswith('//'):
            logger.error(f"UNC paths not allowed in topic path: {topic_path}")
            return None, False
        
        # For relative paths, remove leading slashes
        if not is_absolute:
            path = path.lstrip('\\/')
        
        # Replace backslashes with forward slashes for consistency (but keep drive letter colon)
        if is_absolute and len(path) >= 2 and path[1] == ':':
            # Keep drive letter, convert rest
            drive = path[:2]
            rest = path[2:].replace('\\', '/')
            path = drive + rest
        else:
            path = path.replace('\\', '/')
        
        # Check for invalid characters that could cause issues
        invalid_chars = ['<', '>', '"', '|', '?', '*']
        for char in invalid_chars:
            if char in path:
                logger.error(f"Invalid character '{char}' in topic path: {topic_path}")
                return None, False
        
        # Don't allow parent directory references for security
        if '..' in path:
            logger.error(f"Parent directory references (..) not allowed in topic path: {topic_path}")
            return None, False
        
        return path if path else None, is_absolute
    
    def auto_login(self):
        """Automatically login with the most recent account if available"""
        logger.info("=" * 60)
        logger.info("AUTO-LOGIN STARTED")
        logger.info("=" * 60)
        try:
            accounts = self.account_manager.list_accounts()
            logger.info(f"Found {len(accounts)} account(s) in database")
            if not accounts:
                logger.info("No accounts found - auto-login skipped")
                return
            
            # Get most recent account (they're ordered by last_login DESC)
            account = accounts[0]
            username = account['username']
            ig_username = account.get('ig_username') or username  # Use IG username, fallback to account name
            session_file = Path(account['session_file'])
            
            logger.info(f"Most recent account: {username} (IG: {ig_username})")
            logger.info(f"Session file path: {session_file}")
            
            if not session_file.exists():
                logger.warning(f"Session file not found for {username}")
                return
            
            # Try to login with saved session (no need to re-login if session is valid)
            logger.info(f"Attempting login with {username} (IG: {ig_username})...")
            login_success = self.instagram_manager.login(ig_username, "", session_file)
            logger.info(f"Login result: {login_success}")
            
            if login_success:
                logger.info(f"✓ Login successful for {username}")
                self.current_username = username
                self.account_status.setText(f"✓ Logged in as {username}")
                self.account_status.setStyleSheet(
                    "font-weight: bold; padding: 10px; color: green;"
                )
                # Initialize content database manager
                self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
                self.statusBar().showMessage(f"Logged in as {username}")
                self.load_accounts()
                
                # Load account's download path
                download_path = account.get('download_path')
                logger.info(f"DEBUG auto_login: account data = {account}")
                logger.info(f"DEBUG auto_login: download_path from account = {download_path}")
                logger.info(f"DEBUG auto_login: Current download_path_input.text() = {self.download_path_input.text()}")
                if download_path:
                    self.download_path_input.setText(download_path)
                    logger.info(f"✓ Set download_path_input to: {download_path}")
                    logger.info(f"  Verify: download_path_input.text() now = {self.download_path_input.text()}")
                else:
                    logger.warning(f"No download_path in account data, keeping default: {self.download_path_input.text()}")
                
                # Load account's thumbnails path
                thumbnails_path = account.get('thumbnails_path')
                if thumbnails_path:
                    self.thumbnails_path = thumbnails_path
                    logger.info(f"Loaded thumbnails path: {thumbnails_path}")
                else:
                    # Calculate from download_path if available
                    if download_path:
                        dl_path = Path(download_path)
                        if dl_path.name == 'content':
                            self.thumbnails_path = str(dl_path.parent / ".thumbnails")
                        else:
                            self.thumbnails_path = str(dl_path / ".thumbnails")
                        logger.warning(f"No thumbnails_path in account data, calculated from download_path: {self.thumbnails_path}")
                    else:
                        logger.error("No download_path or thumbnails_path in database - cannot determine thumbnails location")
                        self.thumbnails_path = None
                
                # Load account's topics root path
                topics_root_path = account.get('topics_root_path')
                if topics_root_path:
                    self.topics_root_path = topics_root_path
                    logger.info(f"Loaded topics_root_path: {topics_root_path}")
                else:
                    if download_path:
                        self.topics_root_path = download_path
                        logger.warning(f"No topics_root_path in account data, using download_path: {self.topics_root_path}")
                    else:
                        logger.error("No download_path or topics_root_path in database - cannot determine topics location")
                        self.topics_root_path = None
                
                # Load UI settings for this account
                self.load_ui_settings()
                
                # Restore download queue from database
                self.restore_queue_from_database()
                
                # Refresh Settings tab with account paths
                self.refresh_settings_paths()
                logger.info("Settings tab paths refreshed after auto-login")
                
                # Load saved content entries from database (if enabled)
                if self.auto_load_at_startup:
                    # Load async in background - UI will appear immediately
                    self.load_database_entries_async()
                    logger.info(f"Auto-login successful for {username} - loading database in background")
                else:
                    logger.info(f"Auto-login successful for {username} (auto-load disabled)")
                    self.browse_status.setText("Click 'Load Database Entries' to view saved content")
                
                logger.info("=" * 60)
                logger.info("AUTO-LOGIN COMPLETED SUCCESSFULLY")
                logger.info("=" * 60)
            else:
                logger.warning(f"✗ Auto-login failed for {username} - session may have expired")
                logger.info("=" * 60)
                logger.info("AUTO-LOGIN FAILED")
                logger.info("=" * 60)
        except Exception as e:
            logger.error(f"Auto-login error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.info("=" * 60)
            logger.info("AUTO-LOGIN ERROR")
            logger.info("=" * 60)
    
    def create_account_tab(self):
        """Create the Account Management tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Login section
        login_group = QGroupBox("Login to Instagram")
        login_layout = QGridLayout()
        
        login_layout.addWidget(QLabel("Username:"), 0, 0)
        self.username_input = QLineEdit()
        login_layout.addWidget(self.username_input, 0, 1)
        
        login_layout.addWidget(QLabel("Password:"), 1, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        login_layout.addWidget(self.password_input, 1, 1)
        
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.login)
        login_layout.addWidget(self.login_btn, 2, 0, 1, 2)
        
        # Add separator and import button
        import_label = QLabel("─── Or ───")
        import_label.setAlignment(Qt.AlignCenter)
        import_label.setStyleSheet("color: gray; margin: 5px;")
        login_layout.addWidget(import_label, 3, 0, 1, 2)
        
        # Import from JSON file button
        self.import_json_btn = QPushButton("📁 Import from JSON File")
        self.import_json_btn.clicked.connect(self.import_session_from_json)
        self.import_json_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        login_layout.addWidget(self.import_json_btn, 4, 0, 1, 1)
        
        # Chrome extraction button (requires admin)
        self.extract_chrome_btn = QPushButton("🟢 Import from Chrome (Admin)")
        self.extract_chrome_btn.clicked.connect(self.extract_from_chrome)
        self.extract_chrome_btn.setStyleSheet("""
            QPushButton {
                background-color: #4285F4;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3367D6;
            }
        """)
        self.extract_chrome_btn.setToolTip("Extract cookies from Chrome (requires Admin rights on Windows)")
        login_layout.addWidget(self.extract_chrome_btn, 4, 1, 1, 1)
        
        # Firefox extraction button (requires admin)
        self.extract_firefox_btn = QPushButton("🦊 Import from Firefox (Admin)")
        self.extract_firefox_btn.clicked.connect(self.extract_from_firefox)
        self.extract_firefox_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF7139;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E66000;
            }
        """)
        self.extract_firefox_btn.setToolTip("Extract cookies from Firefox (requires Admin rights on Windows)")
        login_layout.addWidget(self.extract_firefox_btn, 5, 0, 1, 1)
        
        # Manual cookie import button
        self.manual_import_btn = QPushButton("🔧 Manual Import (F12)")
        self.manual_import_btn.clicked.connect(self.manual_import_session)
        self.manual_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.manual_import_btn.setToolTip("Manually paste cookies from browser F12 DevTools (no admin required)")
        login_layout.addWidget(self.manual_import_btn, 5, 1, 1, 1)
        
        login_group.setLayout(login_layout)
        layout.addWidget(login_group)
        
        # Saved accounts section
        accounts_group = QGroupBox("Saved Accounts")
        accounts_layout = QVBoxLayout()
        
        self.accounts_list = QListWidget()
        self.accounts_list.itemDoubleClicked.connect(self.switch_account)
        accounts_layout.addWidget(self.accounts_list)
        
        accounts_btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_accounts)
        accounts_btn_layout.addWidget(refresh_btn)
        
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete_account)
        accounts_btn_layout.addWidget(delete_btn)
        
        accounts_layout.addLayout(accounts_btn_layout)
        accounts_group.setLayout(accounts_layout)
        layout.addWidget(accounts_group)
        
        # Current status with session info
        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        
        self.account_status = QLabel("Not logged in")
        self.account_status.setStyleSheet("font-weight: bold; padding: 10px;")
        status_layout.addWidget(self.account_status)
        
        self.session_status = QLabel("")
        self.session_status.setStyleSheet("font-size: 9pt; color: gray; padding: 0 10px;")
        status_layout.addWidget(self.session_status)
        
        layout.addWidget(status_widget)
        
        # Session management buttons
        session_mgmt_layout = QHBoxLayout()
        
        test_session_btn = QPushButton("🔍 Test Session")
        test_session_btn.clicked.connect(self.test_session)
        test_session_btn.setToolTip("Check if your current session is still valid")
        session_mgmt_layout.addWidget(test_session_btn)
        
        refresh_session_btn = QPushButton("🔄 Refresh Session")
        refresh_session_btn.clicked.connect(self.prompt_session_refresh)
        refresh_session_btn.setToolTip("Open Manual Import dialog to refresh expired session")
        session_mgmt_layout.addWidget(refresh_session_btn)
        
        layout.addLayout(session_mgmt_layout)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Accounts")
        
        # Load saved accounts
        self.load_accounts()
    
    def create_browse_tab(self):
        """Create the Browse Saved Posts tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # View Mode Selector (at the very top)
        view_selector = QHBoxLayout()
        view_selector.addWidget(QLabel("View Mode:"))
        
        # Table view button - HIDDEN (table view disabled)
        self.table_view_btn = QPushButton("📋 Table View")
        self.table_view_btn.setCheckable(True)
        self.table_view_btn.setChecked(False)
        self.table_view_btn.clicked.connect(lambda: self.switch_view_mode('table'))
        self.table_view_btn.setStyleSheet("QPushButton:checked { background-color: #0078d4; color: white; font-weight: bold; }")
        self.table_view_btn.setVisible(False)  # Hide table view button
        view_selector.addWidget(self.table_view_btn)
        
        # Tile view button - always checked and HIDDEN (no need to toggle)
        self.tile_view_btn = QPushButton("🔲 Tile View")
        self.tile_view_btn.setCheckable(True)
        self.tile_view_btn.setChecked(True)
        self.tile_view_btn.clicked.connect(lambda: self.switch_view_mode('tiles'))
        self.tile_view_btn.setStyleSheet("QPushButton:checked { background-color: #0078d4; color: white; font-weight: bold; }")
        self.tile_view_btn.setVisible(False)  # Hide tile view button (only one mode now)
        view_selector.addWidget(self.tile_view_btn)
        
        # Tile size toggle button
        self.tile_size_btn = QPushButton("📐 Medium")
        self.tile_size_btn.setToolTip("Toggle tile size: Small (more tiles) / Medium / Large (fewer tiles)")
        self.tile_size_btn.clicked.connect(self.toggle_tile_size)
        view_selector.addWidget(self.tile_size_btn)
        
        # Theme toggle button
        self.theme_btn = QPushButton("☀️ Light")
        self.theme_btn.setToolTip("Toggle theme: Light / Dark")
        self.theme_btn.clicked.connect(self.toggle_theme)
        view_selector.addWidget(self.theme_btn)
        
        # Video mode toggle button
        self.video_mode_btn = QPushButton("🎬 Popup")
        self.video_mode_btn.setToolTip("Toggle inline/popup video playback")
        self.video_mode_btn.clicked.connect(self.toggle_video_mode)
        view_selector.addWidget(self.video_mode_btn)
        
        view_selector.addStretch()
        layout.addLayout(view_selector)
        
        # Data Operations Row - Load/Fetch/Import buttons
        data_ops = QHBoxLayout()
        
        load_db_btn = QPushButton("📁 Load Database Entries")
        load_db_btn.clicked.connect(self.load_database_entries)
        load_db_btn.setToolTip("Load saved content from local database")
        data_ops.addWidget(load_db_btn)
        
        fetch_btn = QPushButton("🔄 Fetch New Saved Posts")
        fetch_btn.clicked.connect(self.load_saved_posts)
        fetch_btn.setToolTip("Fetch saved posts from Instagram (adds new ones to database)")
        data_ops.addWidget(fetch_btn)
        
        import_btn = QPushButton("📥 Import from Export File")
        import_btn.clicked.connect(self.import_from_export)
        import_btn.setToolTip("Import saved posts from Instagram's exported data")
        data_ops.addWidget(import_btn)
        
        data_ops.addStretch()
        layout.addLayout(data_ops)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)
        
        # Controls Row - Sorting, Filtering, Thumbnails, URL input
        controls = QHBoxLayout()
        
        # Sort By dropdown
        controls.addWidget(QLabel("Sort By:"))
        self.sort_by_combo = QComboBox()
        self.sort_by_combo.addItems(["Save Date", "Post Date", "Import Date", "Row Number"])
        self.sort_by_combo.setCurrentText("Row Number")  # Default
        self.sort_by_combo.currentTextChanged.connect(self.apply_sort_and_filter)
        self.sort_by_combo.setToolTip("Choose field to sort by")
        controls.addWidget(self.sort_by_combo)
        
        # Sort Direction dropdown
        self.sort_direction_combo = QComboBox()
        self.sort_direction_combo.addItems(["DESC", "ASC"])
        self.sort_direction_combo.setCurrentText("DESC")  # Default descending
        self.sort_direction_combo.currentTextChanged.connect(self.apply_sort_and_filter)
        self.sort_direction_combo.setToolTip("Sort direction (DESC=newest first, ASC=oldest first)")
        controls.addWidget(self.sort_direction_combo)
        
        controls.addSpacing(20)
        
        # Filter dropdown
        controls.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All (Unfiltered)",
            "Only Ignored (Black) Items",
            "Only Uncategorized",
            "Only Categorized & Undownloaded",
            "Only Error Items",
            "Specific Topic-Undownloaded",
        ])
        self.filter_combo.setCurrentText("All (Unfiltered)")
        self.filter_combo.currentTextChanged.connect(self.apply_sort_and_filter)
        self.filter_combo.setToolTip("Filter posts by status:\n• Ignored (Black) Items - user marked as ignored\n• Uncategorized - no topic assigned\n• Categorized & Undownloaded - pink items with topic but not downloaded\n• Error Items - red items where download failed\n• Specific Topic-Undownloaded - pick a topic from the topic list")
        controls.addWidget(self.filter_combo)
        
        # Topic filter dropdown (dynamically populated)
        controls.addWidget(QLabel("Topic:"))
        self.topic_filter_combo = QComboBox()
        self.topic_filter_combo.setMinimumWidth(260)
        self.topic_filter_combo.addItem("All Topics", None)
        self.topic_filter_combo.setEnabled(False)
        self.topic_filter_combo.currentTextChanged.connect(self.apply_sort_and_filter)
        self.topic_filter_combo.setToolTip("Filter by specific topic")
        controls.addWidget(self.topic_filter_combo)
        
        controls.addSpacing(20)
        
        # Stop thumbnails button
        self.stop_thumbnails_btn = QPushButton("⏸️ Stop Thumbnails")
        self.stop_thumbnails_btn.clicked.connect(self.toggle_thumbnail_downloads)
        self.stop_thumbnails_btn.setToolTip("Stop/Resume background thumbnail downloads")
        self.stop_thumbnails_btn.setStyleSheet("background-color: #ffcccc;")
        self.stop_thumbnails_btn.setVisible(False)  # Hidden by default
        controls.addWidget(self.stop_thumbnails_btn)
        
        controls.addStretch()
        
        # Add URL textbox and button
        controls.addWidget(QLabel("Add URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.instagram.com/p/ABC123/ or /reel/ABC123/")
        self.url_input.setMinimumWidth(300)
        self.url_input.returnPressed.connect(self.add_url)
        controls.addWidget(self.url_input)
        
        add_url_btn = QPushButton("➕ Add")
        add_url_btn.clicked.connect(self.add_url)
        add_url_btn.setToolTip("Add a single Instagram post URL")
        controls.addWidget(add_url_btn)
        
        layout.addLayout(controls)
        
        # Batch operations row (for multi-select in tile view)
        batch_ops_layout = QHBoxLayout()
        
        # Selection counter
        self.selection_count_label = QLabel("Selected: 0")
        self.selection_count_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        batch_ops_layout.addWidget(self.selection_count_label)
        
        # Select All button
        select_all_btn = QPushButton("☑️ Select All")
        select_all_btn.clicked.connect(self.select_all_tiles)
        select_all_btn.setToolTip("Select all visible tiles on current page")
        batch_ops_layout.addWidget(select_all_btn)

        # Select Remaining button
        select_remaining_btn = QPushButton("✅ Select Remaining")
        select_remaining_btn.clicked.connect(self.select_remaining_tiles)
        select_remaining_btn.setToolTip("Select visible items that are not downloaded and not topic-assigned")
        batch_ops_layout.addWidget(select_remaining_btn)
        
        # Deselect All button
        deselect_all_btn = QPushButton("☐ Deselect All")
        deselect_all_btn.clicked.connect(self.deselect_all_tiles)
        deselect_all_btn.setToolTip("Clear all selections")
        batch_ops_layout.addWidget(deselect_all_btn)
        
        # Set Topic for Selected button
        self.batch_topic_btn = QPushButton("🏷️ Set Topic for Selected")
        self.batch_topic_btn.clicked.connect(self.set_topic_for_selected)
        self.batch_topic_btn.setToolTip("Assign topic to all selected posts")
        self.batch_topic_btn.setEnabled(False)
        batch_ops_layout.addWidget(self.batch_topic_btn)
        
        # Queue Selected button
        self.batch_queue_btn = QPushButton("➕ Queue Selected")
        self.batch_queue_btn.clicked.connect(self.queue_selected)
        self.batch_queue_btn.setToolTip("Add all selected posts to download queue")
        self.batch_queue_btn.setEnabled(False)
        batch_ops_layout.addWidget(self.batch_queue_btn)
        
        # Download Selected Now button
        self.batch_download_btn = QPushButton("⬇️ Download Selected Now")
        self.batch_download_btn.clicked.connect(self.download_selected_now)
        self.batch_download_btn.setToolTip("Download all selected posts immediately")
        self.batch_download_btn.setEnabled(False)
        self.batch_download_btn.setStyleSheet("QPushButton { background-color: #0078d4; color: white; font-weight: bold; }")
        batch_ops_layout.addWidget(self.batch_download_btn)

        # Ignore Selected button
        self.batch_ignore_btn = QPushButton("🚫 Ignore Selected")
        self.batch_ignore_btn.clicked.connect(self.ignore_selected)
        self.batch_ignore_btn.setToolTip("Mark all selected posts as ignored")
        self.batch_ignore_btn.setEnabled(False)
        self.batch_ignore_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; font-weight: bold; }")
        batch_ops_layout.addWidget(self.batch_ignore_btn)
        
        # Download Page button
        download_page_btn = QPushButton("📥 Download Page")
        download_page_btn.clicked.connect(self.download_page_now)
        download_page_btn.setToolTip("Download all posts on current page and copy files to assigned topic folders")
        download_page_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
        batch_ops_layout.addWidget(download_page_btn)
        
        # Download Topic-Assigned Items button
        self.download_topic_assigned_btn = QPushButton("🏷️ Download [0] Topic-Assigned")
        self.download_topic_assigned_btn.clicked.connect(self.download_topic_assigned_now)
        self.download_topic_assigned_btn.setToolTip("Download all items on current page that have topics assigned")
        self.download_topic_assigned_btn.setStyleSheet("QPushButton { background-color: #6610f2; color: white; font-weight: bold; }")
        batch_ops_layout.addWidget(self.download_topic_assigned_btn)
        
        batch_ops_layout.addStretch()
        layout.addLayout(batch_ops_layout)
        self.update_topic_assigned_download_button_text()
        
        # Settings row
        settings = QHBoxLayout()
        
        self.auto_load_check = QCheckBox("Auto-load at startup")
        self.auto_load_check.setChecked(self.auto_load_at_startup)
        self.auto_load_check.stateChanged.connect(self.toggle_auto_load)
        self.auto_load_check.setToolTip("Automatically load database entries when app starts")
        settings.addWidget(self.auto_load_check)
        
        self.stop_at_duplicate_check = QCheckBox("Stop at First Existing Post")
        self.stop_at_duplicate_check.setChecked(self.stop_at_first_duplicate)
        self.stop_at_duplicate_check.stateChanged.connect(self.toggle_stop_at_duplicate)
        self.stop_at_duplicate_check.setToolTip("When fetching from Instagram, stop at the first post that already exists in database")
        settings.addWidget(self.stop_at_duplicate_check)
        
        self.use_system_player_check = QCheckBox("Use System Video Player")
        # Check the box if force_system_player is enabled
        self.use_system_player_check.setChecked(self.force_system_player)
        self.use_system_player_check.stateChanged.connect(self.toggle_use_system_player)
        self.use_system_player_check.setToolTip("Skip built-in player (VLC/Qt) and always open videos in external system player")
        settings.addWidget(self.use_system_player_check)
        
        # Volume slider for inline tile videos
        settings.addWidget(QLabel("🔊 Volume:"))
        self.tile_volume_slider = QSlider(Qt.Horizontal)
        self.tile_volume_slider.setMinimum(0)
        self.tile_volume_slider.setMaximum(100)
        self.tile_volume_slider.setValue(self.tile_video_volume)
        self.tile_volume_slider.setMaximumWidth(100)
        self.tile_volume_slider.setToolTip("Volume for inline tile videos (0-100)")
        self.tile_volume_slider.valueChanged.connect(self.on_tile_volume_changed)
        settings.addWidget(self.tile_volume_slider)
        
        settings.addStretch()
        settings.addWidget(QLabel("Filter:"))
        filter_input = QLineEdit()
        filter_input.setPlaceholderText("Search by account, caption, shortcode, or Instagram URL...")
        filter_input.textChanged.connect(self.filter_posts)
        settings.addWidget(filter_input)
        layout.addLayout(settings)
        
        # Stacked widget to switch between table and tile views
        self.view_stack = QStackedWidget()
        
        # Horizontal split: Views on left, Details panel on right
        content_splitter = QHBoxLayout()
        
        # Create both views
        views_widget = QWidget()
        views_layout = QVBoxLayout(views_widget)
        views_layout.setContentsMargins(0, 0, 0, 0)
        
        # TABLE VIEW
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        
        self.posts_table = QTableWidget()
        self.posts_table.setColumnCount(13)  # Added columns for classify, thumbnail download, and reset
        self.posts_table.setHorizontalHeaderLabels(["Thumb", "Row #", "ID (Shortcode)", "Account", "Caption", "Type", "Status", "Open", "Copy URL", "Firefox", "Classify", "Get Thumb", "Reset"])
        self.posts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.posts_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.posts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.posts_table.verticalHeader().setVisible(False)
        
        # Enable sorting
        self.posts_table.setSortingEnabled(True)
        self.posts_table.horizontalHeader().setSortIndicatorShown(True)
        
        # Set column widths
        thumb_size = self.get_thumbnail_size()
        self.posts_table.setColumnWidth(0, thumb_size + 20)   # Thumbnail (dynamic)
        self.posts_table.setColumnWidth(1, 70)   # Row #
        self.posts_table.setColumnWidth(2, 120)  # ID (Shortcode)
        self.posts_table.setColumnWidth(3, 120)  # Account
        self.posts_table.setColumnWidth(4, 300)  # Caption
        self.posts_table.setColumnWidth(5, 100)  # Type
        self.posts_table.setColumnWidth(6, 140)  # Status
        self.posts_table.setColumnWidth(7, 70)   # Open
        self.posts_table.setColumnWidth(8, 50)   # Copy URL
        self.posts_table.setColumnWidth(9, 50)   # Firefox
        self.posts_table.setColumnWidth(10, 70)  # Classify
        self.posts_table.setColumnWidth(11, 70)  # Get Thumb
        self.posts_table.setColumnWidth(12, 70)  # Reset
        
        # Set row height for thumbnails (dynamic)
        self.posts_table.verticalHeader().setDefaultSectionSize(thumb_size + 10)
        
        table_layout.addWidget(self.posts_table)
        
        # Add pagination controls to table view
        table_pagination = QHBoxLayout()
        table_pagination.addWidget(QLabel("Items per page:"))
        self.table_items_per_page_spin = QSpinBox()
        self.table_items_per_page_spin.setRange(50, 500)
        self.table_items_per_page_spin.setValue(100)
        self.table_items_per_page_spin.setSingleStep(50)
        self.table_items_per_page_spin.valueChanged.connect(self.change_table_items_per_page)
        table_pagination.addWidget(self.table_items_per_page_spin)
        table_pagination.addStretch()
        
        self.table_prev_page_btn = QPushButton("⬅️ Previous")
        self.table_prev_page_btn.clicked.connect(self.table_prev_page)
        table_pagination.addWidget(self.table_prev_page_btn)
        
        self.table_page_label = QLabel("Page 1 of 1")
        self.table_page_label.setAlignment(Qt.AlignCenter)
        table_pagination.addWidget(self.table_page_label)
        
        self.table_next_page_btn = QPushButton("Next ➡️")
        self.table_next_page_btn.clicked.connect(self.table_next_page)
        table_pagination.addWidget(self.table_next_page_btn)
        
        table_layout.addLayout(table_pagination)
        
        # Connect table click to show details
        self.posts_table.itemClicked.connect(self.show_post_details)
        
        # Connect selection change to update Topics tab
        self.posts_table.itemSelectionChanged.connect(self.on_browse_item_selection_changed)
        
        # TILE VIEW with pagination
        tile_container = QWidget()
        tile_layout = QVBoxLayout(tile_container)
        tile_layout.setContentsMargins(0, 0, 0, 0)
        
        # Pagination controls at top
        pagination_top = QHBoxLayout()
        pagination_top.addWidget(QLabel("Items per page:"))
        self.items_per_page_spin = QSpinBox()
        self.items_per_page_spin.setRange(10, 100)
        self.items_per_page_spin.setValue(20)
        self.items_per_page_spin.setSingleStep(10)
        self.items_per_page_spin.valueChanged.connect(self.change_items_per_page)
        pagination_top.addWidget(self.items_per_page_spin)
        
        pagination_top.addSpacing(20)
        pagination_top.addWidget(QLabel("Current page:"))
        self.current_page_spin = QSpinBox()
        self.current_page_spin.setRange(1, 1)
        self.current_page_spin.setValue(1)
        self.current_page_spin.setSingleStep(1)
        self.current_page_spin.setMinimumWidth(80)
        self.current_page_spin.valueChanged.connect(self.jump_to_page)
        pagination_top.addWidget(self.current_page_spin)
        
        pagination_top.addStretch()
        tile_layout.addLayout(pagination_top)
        
        # Scroll area for tiles
        self.tiles_scroll = QScrollArea()
        self.tiles_scroll.setWidgetResizable(True)
        self.tiles_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.tiles_container_widget = QWidget()
        self.tiles_grid = QGridLayout(self.tiles_container_widget)
        self.tiles_grid.setSpacing(5)  # Reduced from 10 for tighter layout
        self.tiles_grid.setContentsMargins(5, 5, 5, 5)  # Reduced from 10
        
        self.tiles_scroll.setWidget(self.tiles_container_widget)
        tile_layout.addWidget(self.tiles_scroll)
        
        # Pagination controls at bottom
        pagination_bottom = QHBoxLayout()
        self.first_page_btn = QPushButton("⏮️ First")
        self.first_page_btn.clicked.connect(self.first_page)
        pagination_bottom.addWidget(self.first_page_btn)
        
        self.prev_page_btn = QPushButton("⬅️ Previous")
        self.prev_page_btn.clicked.connect(self.prev_page)
        pagination_bottom.addWidget(self.prev_page_btn)
        
        self.page_label = QLabel("Page 1 of 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        pagination_bottom.addWidget(self.page_label)
        
        self.next_page_btn = QPushButton("Next ➡️")
        self.next_page_btn.clicked.connect(self.next_page)
        pagination_bottom.addWidget(self.next_page_btn)
        
        self.last_page_btn = QPushButton("Last ⏭️")
        self.last_page_btn.clicked.connect(self.last_page)
        pagination_bottom.addWidget(self.last_page_btn)
        
        # Add Refresh Page button
        refresh_page_btn = QPushButton("🔄 Refresh")
        refresh_page_btn.clicked.connect(self.refresh_current_page)
        refresh_page_btn.setToolTip("Reload current page from database (fixes missing video controls)")
        refresh_page_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
        pagination_bottom.addWidget(refresh_page_btn)
        
        tile_layout.addLayout(pagination_bottom)
        
        # Add both views to stacked widget
        self.view_stack.addWidget(table_container)  # Index 0
        self.view_stack.addWidget(tile_container)   # Index 1
        
        views_layout.addWidget(self.view_stack)
        content_splitter.addWidget(views_widget, 3)  # Views take 3/4 of space
        
        # Details panel (right side)
        details_container = QVBoxLayout()
        
        details_label = QLabel("Details & Workflow")
        details_label.setStyleSheet("font-weight: bold; padding: 5px; background: #f0f0f0;")
        details_container.addWidget(details_label)
        
        self.details_panel = QTextEdit()
        self.details_panel.setReadOnly(True)
        self.details_panel.setMinimumWidth(350)
        self.details_panel.setMaximumWidth(450)
        self.details_panel.setMinimumHeight(200)  # Set minimum height
        self.details_panel.setMaximumHeight(300)  # Make details box shorter
        self.details_panel.setPlaceholderText("Click a post to view details...")
        self.details_panel.setStyleSheet("border: 1px solid #ccc; padding: 5px;")  # Removed hardcoded colors for theme support
        details_container.addWidget(self.details_panel)
        
        # Copy Caption and Edit Notes buttons side by side (left-aligned)
        buttons_row = QHBoxLayout()
        
        self.copy_caption_btn = QPushButton("📋 Copy")
        self.copy_caption_btn.clicked.connect(self.copy_caption_to_clipboard)
        self.copy_caption_btn.setEnabled(False)
        self.copy_caption_btn.setToolTip("Copy caption text (without tags) to clipboard")
        self.copy_caption_btn.setMaximumWidth(150)
        buttons_row.addWidget(self.copy_caption_btn)
        
        self.edit_notes_btn = QPushButton("📝 Notes")
        self.edit_notes_btn.clicked.connect(self.edit_file_notes)
        self.edit_notes_btn.setEnabled(False)
        self.edit_notes_btn.setToolTip("Add or edit notes for each file in this post")
        self.edit_notes_btn.setMaximumWidth(150)
        buttons_row.addWidget(self.edit_notes_btn)
        
        buttons_row.addStretch()  # Push buttons to the left
        
        details_container.addLayout(buttons_row)
        
        # Vertical Color Key
        color_key_label = QLabel("<b>Color Key:</b>")
        color_key_label.setStyleSheet("margin-top: 10px; padding: 5px;")  # No hardcoded color
        details_container.addWidget(color_key_label)
        
        # Create vertical color key with solid boxes
        color_key_layout = QVBoxLayout()
        color_key_layout.setSpacing(3)
        
        color_items = [
            ("#e0e0e0", "#000000", "Gray: Not categorized/downloaded"),
            ("#1a1a1a", "#ffffff", "Black: Ignored"),
            ("#c8e6c9", "#000000", "Green: Downloaded, not categorized"),
            ("#FF69B4", "#000000", "Pink: Categorized, not downloaded"),
            ("#4169E1", "#ffffff", "Blue: Complete (downloaded + categorized)"),
            ("#ff4444", "#ffffff", "Red: Error")
        ]
        
        for bg_color, text_color, label_text in color_items:
            item_layout = QHBoxLayout()
            item_layout.setContentsMargins(0, 0, 0, 0)
            
            color_box = QLabel()
            color_box.setStyleSheet(f"background-color: {bg_color}; border: 1px solid #999;")
            color_box.setFixedSize(20, 20)
            item_layout.addWidget(color_box)
            
            text_label = QLabel(label_text)
            text_label.setStyleSheet(f"padding-left: 5px; font-size: 10pt;")  # Removed hardcoded color for theme support
            item_layout.addWidget(text_label)
            item_layout.addStretch()
            
            color_key_layout.addLayout(item_layout)
        
        details_container.addLayout(color_key_layout)
        
        details_container.addStretch()  # Push color key to top, prevent expansion
        
        # Store current entry for copy button
        self.current_entry = None
        
        content_splitter.addLayout(details_container, 1)  # Details takes 1/4 of space
        
        layout.addLayout(content_splitter)
        
        # Action buttons
        actions = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.posts_table.selectAll)
        actions.addWidget(select_all_btn)
        
        clear_list_btn = QPushButton("🗑️ Clear List")
        clear_list_btn.clicked.connect(self.clear_browse_list)
        clear_list_btn.setToolTip("Clear the browse list (keeps database intact)")
        actions.addWidget(clear_list_btn)
        
        add_to_queue_btn = QPushButton("Add to Download Queue")
        add_to_queue_btn.clicked.connect(self.add_to_download_queue)
        actions.addWidget(add_to_queue_btn)
        
        # Queue Current Page button
        queue_page_btn = QPushButton("📄 Queue Undownloaded on Page")
        queue_page_btn.clicked.connect(self.queue_undownloaded_on_page)
        queue_page_btn.setToolTip("Add all undownloaded posts on the current page to download queue")
        queue_page_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; }")
        actions.addWidget(queue_page_btn)
        
        # Add thumbnail download button
        thumbnails_btn = QPushButton("🖼️ Download Missing Thumbnails")
        thumbnails_btn.clicked.connect(self.download_missing_thumbnails_bulk)
        thumbnails_btn.setToolTip("Download thumbnail images for posts that don't have them")
        actions.addWidget(thumbnails_btn)
        
        # Force re-download thumbnails for current page
        redownload_page_thumbs_btn = QPushButton("🔄 Redownload Thumbnails for this Page")
        redownload_page_thumbs_btn.clicked.connect(self.redownload_thumbnails_for_current_page)
        redownload_page_thumbs_btn.setToolTip("Force re-download thumbnail images for every item on the current page")
        redownload_page_thumbs_btn.setStyleSheet("QPushButton { background-color: #fd7e14; color: white; font-weight: bold; }")
        actions.addWidget(redownload_page_thumbs_btn)
        
        actions.addStretch()
        layout.addLayout(actions)
        
        # Status
        self.browse_status = QLabel("Load saved posts to begin")
        layout.addWidget(self.browse_status)
        
        self.tabs.addTab(tab, "Browse")
        
        # Initialize selection UI state (buttons disabled until tiles are selected)
        self.update_selection_ui()
    
    def create_download_tab(self):
        """Create the Download Queue tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Download directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Download to:"))
        self.download_path_input = QLineEdit("")  # Will be populated from database on login
        self.download_path_input.setPlaceholderText("Login to load download path from database")
        # Auto-save when user finishes editing the text field
        self.download_path_input.editingFinished.connect(self.on_download_path_changed)
        dir_layout.addWidget(self.download_path_input)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_download_dir)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)
        
        # Queue table
        layout.addWidget(QLabel("Download Queue:"))
        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(6)
        self.queue_table.setHorizontalHeaderLabels(["Row #", "ID (Shortcode)", "Caption", "File Name", "File Location", "Open"])
        self.queue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.queue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.queue_table.verticalHeader().setVisible(False)
        
        # Set column widths
        self.queue_table.setColumnWidth(0, 70)   # Row #
        self.queue_table.setColumnWidth(1, 120)  # ID
        self.queue_table.setColumnWidth(2, 250)  # Caption
        self.queue_table.setColumnWidth(3, 150)  # File Name
        self.queue_table.setColumnWidth(4, 200)  # File Location
        self.queue_table.setColumnWidth(5, 80)   # Open/Debug buttons (wider for two buttons)
        
        layout.addWidget(self.queue_table)
        
        # Queue controls
        queue_controls = QHBoxLayout()
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_from_queue)
        queue_controls.addWidget(remove_btn)
        
        clear_btn = QPushButton("Clear Queue")
        clear_btn.clicked.connect(self.clear_queue)
        queue_controls.addWidget(clear_btn)
        
        clear_failures_btn = QPushButton("Clear All Failures")
        clear_failures_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
        clear_failures_btn.clicked.connect(self.clear_all_failures)
        queue_controls.addWidget(clear_failures_btn)
        
        queue_controls.addStretch()
        layout.addLayout(queue_controls)
        
        # Progress
        self.download_progress = QProgressBar()
        layout.addWidget(self.download_progress)
        
        self.download_status = QLabel("Ready to download")
        layout.addWidget(self.download_status)
        
        # Download button
        self.download_btn = QPushButton("Start Download")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14pt;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        layout.addWidget(self.download_btn)
        
        self.tabs.addTab(tab, "Download")
    
    def create_topics_tab(self):
        """Create the Topics management tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Title
        title = QLabel("Topics Manager")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(title)
        
        # Info label
        info = QLabel("Organize your content by assigning items to topics. Topics are stored in the SQL Server database.")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Topic tree
        self.topics_tree = QTreeWidget()
        self.topics_tree.setHeaderLabels(["Topic Name", "Items", "Pending DL", "ID", "Content Path", "Display Order"])
        self.topics_tree.setColumnWidth(0, 300)
        self.topics_tree.setColumnWidth(1, 60)   # Items column
        self.topics_tree.setColumnWidth(2, 80)   # Pending downloads column
        self.topics_tree.setColumnWidth(3, 60)   # ID
        self.topics_tree.setColumnWidth(4, 200)  # Content Path
        self.topics_tree.setColumnWidth(5, 100)  # Display Order
        self.topics_tree.itemSelectionChanged.connect(self.on_topic_selection_changed)
        layout.addWidget(self.topics_tree)
        
        # Buttons row
        buttons = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 Refresh Topics")
        refresh_btn.clicked.connect(self.load_topics_tree)
        buttons.addWidget(refresh_btn)
        
        add_topic_btn = QPushButton("➕ Add Root Topic")
        add_topic_btn.clicked.connect(self.add_new_topic)
        buttons.addWidget(add_topic_btn)
        
        self.add_child_topic_btn = QPushButton("➕ Add Child Topic")
        self.add_child_topic_btn.clicked.connect(self.add_child_to_selected_topic)
        self.add_child_topic_btn.setEnabled(False)
        buttons.addWidget(self.add_child_topic_btn)
        
        edit_topic_btn = QPushButton("✏️ Edit Topic")
        edit_topic_btn.clicked.connect(self.edit_selected_topic)
        buttons.addWidget(edit_topic_btn)
        
        delete_topic_btn = QPushButton("🗑️ Delete Topic")
        delete_topic_btn.clicked.connect(self.delete_selected_topic)
        buttons.addWidget(delete_topic_btn)
        
        self.promote_topic_btn = QPushButton("⬆️ Promote")
        self.promote_topic_btn.setToolTip("Move topic to same level as its parent")
        self.promote_topic_btn.clicked.connect(self.promote_selected_topic)
        self.promote_topic_btn.setEnabled(False)
        buttons.addWidget(self.promote_topic_btn)
        
        self.demote_topic_btn = QPushButton("⬇️ Demote")
        self.demote_topic_btn.setToolTip("Move topic as child of previous sibling")
        self.demote_topic_btn.clicked.connect(self.demote_selected_topic)
        self.demote_topic_btn.setEnabled(False)
        buttons.addWidget(self.demote_topic_btn)
        
        self.move_up_topic_btn = QPushButton("🔼 Move Up")
        self.move_up_topic_btn.setToolTip("Move topic up in display order")
        self.move_up_topic_btn.clicked.connect(self.move_topic_up)
        self.move_up_topic_btn.setEnabled(False)
        buttons.addWidget(self.move_up_topic_btn)
        
        self.move_down_topic_btn = QPushButton("🔽 Move Down")
        self.move_down_topic_btn.setToolTip("Move topic down in display order")
        self.move_down_topic_btn.clicked.connect(self.move_topic_down)
        self.move_down_topic_btn.setEnabled(False)
        buttons.addWidget(self.move_down_topic_btn)
        
        self.move_to_top_btn = QPushButton("⏫ Move to Top")
        self.move_to_top_btn.setToolTip("Move topic to the top of its siblings")
        self.move_to_top_btn.clicked.connect(self.move_topic_to_top)
        self.move_to_top_btn.setEnabled(False)
        buttons.addWidget(self.move_to_top_btn)
        
        self.move_to_bottom_btn = QPushButton("⏬ Move to Bottom")
        self.move_to_bottom_btn.setToolTip("Move topic to the bottom of its siblings")
        self.move_to_bottom_btn.clicked.connect(self.move_topic_to_bottom)
        self.move_to_bottom_btn.setEnabled(False)
        buttons.addWidget(self.move_to_bottom_btn)
        
        self.alphabetize_selected_btn = QPushButton("🔤 Alphabetize Selected")
        self.alphabetize_selected_btn.setToolTip("Move selected topic to its alphabetical position among siblings")
        self.alphabetize_selected_btn.clicked.connect(self.alphabetize_selected_topic)
        self.alphabetize_selected_btn.setEnabled(False)
        buttons.addWidget(self.alphabetize_selected_btn)
        
        self.alphabetize_level_btn = QPushButton("🔤📁 Alphabetize Level")
        self.alphabetize_level_btn.setToolTip("Sort all siblings of selected topic alphabetically")
        self.alphabetize_level_btn.clicked.connect(self.alphabetize_level)
        self.alphabetize_level_btn.setEnabled(False)
        buttons.addWidget(self.alphabetize_level_btn)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Sunken)
        buttons.addWidget(separator)
        
        # Folder management buttons
        confirm_folders_btn = QPushButton("📁 Confirm All Folders")
        confirm_folders_btn.setToolTip("Create all topic folders in the file system if they don't exist")
        confirm_folders_btn.clicked.connect(self.confirm_all_topic_folders)
        buttons.addWidget(confirm_folders_btn)
        
        self.copy_files_for_topic_btn = QPushButton("📋 Copy Files For Topic")
        self.copy_files_for_topic_btn.setToolTip("Re-copy all files for all items assigned to the selected topic")
        self.copy_files_for_topic_btn.clicked.connect(self.manually_copy_files_to_topics)
        self.copy_files_for_topic_btn.setEnabled(False)
        buttons.addWidget(self.copy_files_for_topic_btn)
        
        buttons.addStretch()
        layout.addLayout(buttons)
        
        # Selected item section
        selected_group = QGroupBox("Manage Selected Browse Item")
        selected_layout = QVBoxLayout(selected_group)
        
        self.selected_item_label = QLabel("No item selected in Browse tab")
        self.selected_item_label.setWordWrap(True)
        selected_layout.addWidget(self.selected_item_label)
        
        item_buttons = QHBoxLayout()
        
        self.assign_topic_btn = QPushButton("📌 Assign Selected Topic to Item")
        self.assign_topic_btn.clicked.connect(self.assign_topic_to_selected_item)
        self.assign_topic_btn.setEnabled(False)
        item_buttons.addWidget(self.assign_topic_btn)
        
        self.unassign_topic_btn = QPushButton("❌ Remove Topic from Item")
        self.unassign_topic_btn.clicked.connect(self.unassign_topic_from_selected_item)
        self.unassign_topic_btn.setEnabled(False)
        item_buttons.addWidget(self.unassign_topic_btn)
        
        item_buttons.addStretch()
        selected_layout.addLayout(item_buttons)
        
        layout.addWidget(selected_group)
        
        # Status
        self.topics_status = QLabel("Load topics to begin")
        layout.addWidget(self.topics_status)
        
        self.tabs.addTab(tab, "Topics")
    
    def create_settings_tab(self):
        """Create the Settings tab for account-specific settings"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Title
        title = QLabel("⚙️ Account Settings")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Scrollable area for settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setSpacing(15)
        
        # === Application Settings ===
        app_group = QGroupBox("Application Settings")
        app_layout = QVBoxLayout()
        
        # Auto-load at startup (already exists)
        self.settings_auto_load_check = QCheckBox("Auto-load database entries at startup")
        self.settings_auto_load_check.setChecked(self.auto_load_at_startup)
        self.settings_auto_load_check.stateChanged.connect(self.toggle_auto_load)
        self.settings_auto_load_check.setToolTip("Automatically load saved content when app starts (can slow startup for large databases)")
        app_layout.addWidget(self.settings_auto_load_check)
        
        # Auto-fetch thumbnails
        self.settings_auto_fetch_thumbnails_check = QCheckBox("Auto-fetch missing thumbnails on startup")
        self.settings_auto_fetch_thumbnails_check.setChecked(self.auto_fetch_thumbnails)
        self.settings_auto_fetch_thumbnails_check.stateChanged.connect(self.toggle_auto_fetch_thumbnails)
        self.settings_auto_fetch_thumbnails_check.setToolTip("Automatically download thumbnails for downloaded posts that don't have them (can slow startup)")
        app_layout.addWidget(self.settings_auto_fetch_thumbnails_check)
        
        self.settings_auto_fetch_new_thumbnails_check = QCheckBox("Auto-fetch thumbnails for newly-added saved entries")
        self.settings_auto_fetch_new_thumbnails_check.setChecked(self.auto_fetch_new_thumbnails)
        self.settings_auto_fetch_new_thumbnails_check.stateChanged.connect(self.toggle_auto_fetch_new_thumbnails)
        self.settings_auto_fetch_new_thumbnails_check.setToolTip("Automatically download thumbnails when fetching new saved posts from Instagram")
        app_layout.addWidget(self.settings_auto_fetch_new_thumbnails_check)
        
        # Stop at first duplicate (existing setting)
        stop_duplicate_label = QLabel("Stop at first duplicate when loading from Instagram")
        app_layout.addWidget(stop_duplicate_label)
        self.settings_stop_duplicate_check = QCheckBox("Enable")
        stop_duplicate_saved = self.account_manager.get_setting('stop_at_first_duplicate', 'true')
        self.settings_stop_duplicate_check.setChecked(stop_duplicate_saved == 'true')
        self.settings_stop_duplicate_check.stateChanged.connect(self.toggle_stop_at_duplicate_from_settings)
        self.settings_stop_duplicate_check.setToolTip("Stop loading new posts from Instagram when encountering a post already in database")
        app_layout.addWidget(self.settings_stop_duplicate_check)
        
        app_group.setLayout(app_layout)
        settings_layout.addWidget(app_group)
        
        # === UI Settings ===
        ui_group = QGroupBox("UI Preferences")
        ui_layout = QVBoxLayout()
        
        # Theme
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.settings_theme_combo = QComboBox()
        self.settings_theme_combo.addItems(["Light", "Dark"])
        self.settings_theme_combo.setCurrentText("Light" if self.theme == 'light' else "Dark")
        self.settings_theme_combo.currentTextChanged.connect(self.change_theme_from_settings)
        theme_row.addWidget(self.settings_theme_combo)
        theme_row.addStretch()
        ui_layout.addLayout(theme_row)
        
        # Tile size
        tile_row = QHBoxLayout()
        tile_row.addWidget(QLabel("Tile Size:"))
        self.settings_tile_combo = QComboBox()
        self.settings_tile_combo.addItems(["Small", "Medium", "Large", "XLarge"])
        tile_map = {'small': 'Small', 'medium': 'Medium', 'large': 'Large', 'xlarge': 'XLarge'}
        self.settings_tile_combo.setCurrentText(tile_map.get(self.tile_size, 'Medium'))
        self.settings_tile_combo.currentTextChanged.connect(self.change_tile_size_from_settings)
        tile_row.addWidget(self.settings_tile_combo)
        tile_row.addStretch()
        ui_layout.addLayout(tile_row)
        
        # Video playback mode
        video_row = QHBoxLayout()
        video_row.addWidget(QLabel("Video Playback:"))
        self.settings_video_combo = QComboBox()
        self.settings_video_combo.addItems(["Popup", "Inline"])
        self.settings_video_combo.setCurrentText("Inline" if self.inline_video else "Popup")
        self.settings_video_combo.currentTextChanged.connect(self.change_video_mode_from_settings)
        video_row.addWidget(self.settings_video_combo)
        video_row.addStretch()
        ui_layout.addLayout(video_row)
        
        # Items per page
        items_row = QHBoxLayout()
        items_row.addWidget(QLabel("Items per Page:"))
        self.settings_items_spin = QSpinBox()
        self.settings_items_spin.setRange(10, 100)
        self.settings_items_spin.setSingleStep(10)
        self.settings_items_spin.setValue(self.tiles_per_page)
        self.settings_items_spin.valueChanged.connect(self.change_items_per_page)
        items_row.addWidget(self.settings_items_spin)
        items_row.addStretch()
        ui_layout.addLayout(items_row)
        
        ui_group.setLayout(ui_layout)
        settings_layout.addWidget(ui_group)
        
        # === Path Settings ===
        paths_group = QGroupBox("Account Paths (from Database)")
        paths_layout = QVBoxLayout()
        
        # Get current account's paths from database
        account_paths = None
        if self.current_username:
            account_paths = self.account_manager.get_account(self.current_username)
        
        # Root folder
        paths_layout.addWidget(QLabel("<b>Root Folder:</b>"))
        self.settings_root_folder = QLineEdit()
        self.settings_root_folder.setReadOnly(True)
        self.settings_root_folder.setStyleSheet("background-color: #f0f0f0; color: #000000;")
        self.settings_root_folder.setPlaceholderText("Not logged in")
        if account_paths:
            self.settings_root_folder.setText(account_paths.get('root_folder', '') or 'Not set')
        paths_layout.addWidget(self.settings_root_folder)
        
        # Debug path
        paths_layout.addWidget(QLabel("<b>Debug Path:</b>"))
        self.settings_debug_path = QLineEdit()
        self.settings_debug_path.setReadOnly(True)
        self.settings_debug_path.setStyleSheet("background-color: #f0f0f0; color: #000000;")
        self.settings_debug_path.setPlaceholderText("Not logged in")
        if account_paths:
            self.settings_debug_path.setText(account_paths.get('debug_path', '') or 'Not set')
        paths_layout.addWidget(self.settings_debug_path)
        
        # Download path
        paths_layout.addWidget(QLabel("<b>Download Path:</b>"))
        self.settings_download_path = QLineEdit()
        self.settings_download_path.setReadOnly(True)
        self.settings_download_path.setStyleSheet("background-color: #f0f0f0; color: #000000;")
        self.settings_download_path.setPlaceholderText("Not logged in")
        if account_paths:
            self.settings_download_path.setText(account_paths.get('download_path', '') or 'Not set')
        paths_layout.addWidget(self.settings_download_path)
        
        # Thumbnails path
        paths_layout.addWidget(QLabel("<b>Thumbnails Path:</b>"))
        self.settings_thumbnails_path = QLineEdit()
        self.settings_thumbnails_path.setReadOnly(True)
        self.settings_thumbnails_path.setStyleSheet("background-color: #f0f0f0; color: #000000;")
        self.settings_thumbnails_path.setPlaceholderText("Not logged in")
        if account_paths:
            self.settings_thumbnails_path.setText(account_paths.get('thumbnails_path', '') or 'Not set')
        paths_layout.addWidget(self.settings_thumbnails_path)
        
        # Topics root path
        paths_layout.addWidget(QLabel("<b>Topics Root Path:</b>"))
        self.settings_topics_root_path = QLineEdit()
        self.settings_topics_root_path.setReadOnly(True)
        self.settings_topics_root_path.setStyleSheet("background-color: #f0f0f0; color: #000000;")
        self.settings_topics_root_path.setPlaceholderText("Not logged in")
        if account_paths:
            self.settings_topics_root_path.setText(account_paths.get('topics_root_path', '') or 'Not set')
        paths_layout.addWidget(self.settings_topics_root_path)
        
        paths_group.setLayout(paths_layout)
        settings_layout.addWidget(paths_group)
        
        # === Account Info ===
        account_group = QGroupBox("Account Information")
        account_layout = QVBoxLayout()
        
        # Current account
        if self.current_username:
            account_info = QLabel(f"<b>Logged in as:</b> {self.current_username}")
            account_layout.addWidget(account_info)
            
            # Session info
            session_info_btn = QPushButton("View Session Details")
            session_info_btn.clicked.connect(self.show_session_info)
            account_layout.addWidget(session_info_btn)
        else:
            no_account = QLabel("<i>No account logged in</i>")
            account_layout.addWidget(no_account)
        
        account_group.setLayout(account_layout)
        settings_layout.addWidget(account_group)
        
        # Spacer
        settings_layout.addStretch()
        
        scroll.setWidget(settings_widget)
        layout.addWidget(scroll)
        
        # Status
        self.settings_status = QLabel("Settings will be saved automatically")
        self.settings_status.setStyleSheet("font-size: 9pt; color: gray; padding: 10px;")
        layout.addWidget(self.settings_status)
        
        self.tabs.addTab(tab, "Settings")
    
    def toggle_stop_at_duplicate_from_settings(self, state):
        """Toggle stop at first duplicate setting"""
        self.stop_at_first_duplicate = (state == Qt.Checked)
        self.account_manager.set_setting('stop_at_first_duplicate', 'true' if self.stop_at_first_duplicate else 'false')
        if hasattr(self, 'stop_at_duplicate_checkbox'):
            self.stop_at_duplicate_checkbox.setChecked(self.stop_at_first_duplicate)
        logger.info(f"Stop at first duplicate: {self.stop_at_first_duplicate}")
    
    def toggle_auto_fetch_thumbnails(self, state):
        """Toggle auto-fetch thumbnails setting"""
        self.auto_fetch_thumbnails = (state == Qt.Checked)
        self.account_manager.set_setting('auto_fetch_thumbnails', 'true' if self.auto_fetch_thumbnails else 'false')
        logger.info(f"Auto-fetch thumbnails: {self.auto_fetch_thumbnails}")
    
    def toggle_auto_fetch_new_thumbnails(self, state):
        """Toggle auto-fetch new thumbnails setting"""
        self.auto_fetch_new_thumbnails = (state == Qt.Checked)
        self.account_manager.set_setting('auto_fetch_new_thumbnails', 'true' if self.auto_fetch_new_thumbnails else 'false')
        logger.info(f"Auto-fetch new thumbnails: {self.auto_fetch_new_thumbnails}")
    
    def change_theme_from_settings(self, theme_text):
        """Change theme from settings dropdown"""
        self.theme = 'dark' if theme_text == 'Dark' else 'light'
        self.apply_theme()
        self.save_ui_setting('theme', self.theme)
        theme_icons = {'light': '☀️ Light', 'dark': '🌙 Dark'}
        if hasattr(self, 'theme_btn'):
            self.theme_btn.setText(theme_icons[self.theme])
    
    def change_tile_size_from_settings(self, size_text):
        """Change tile size from settings dropdown"""
        size_map = {'Small': 'small', 'Medium': 'medium', 'Large': 'large', 'XLarge': 'xlarge'}
        new_size = size_map.get(size_text, 'medium')
        if new_size != self.tile_size:
            self.tile_size = new_size
            self.save_ui_setting('tile_size', new_size)
            
            # Update button if it exists
            size_icons = {'small': '🔹', 'medium': '📐', 'large': '🔲', 'xlarge': '⬛'}
            if hasattr(self, 'tile_size_btn'):
                self.tile_size_btn.setText(f"{size_icons[self.tile_size]} {self.tile_size.capitalize()}")
            
            # Update table thumbnails
            thumb_size = self.get_thumbnail_size()
            self.posts_table.setColumnWidth(0, thumb_size + 20)
            self.posts_table.verticalHeader().setDefaultSectionSize(thumb_size + 10)
            
            # Refresh tiles if in tile mode
            if self.current_view_mode == 'tiles':
                self.last_displayed_page = -1  # Force rebuild
                self.populate_tiles()
    
    def change_video_mode_from_settings(self, mode_text):
        """Change video playback mode from settings dropdown"""
        self.inline_video = (mode_text == 'Inline')
        self.save_ui_setting('inline_video', 'true' if self.inline_video else 'false')
        mode_icons = {False: '🎬 Popup', True: '📺 Inline'}
        if hasattr(self, 'video_mode_btn'):
            self.video_mode_btn.setText(mode_icons[self.inline_video])
    
    def browse_download_path_from_settings(self):
        """Browse for download path from settings tab"""
        from PyQt5.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if path:
            self.settings_download_path.setText(path)
            if hasattr(self, 'download_path_input'):
                self.download_path_input.setText(path)
            # Save to account
            if self.current_username:
                self.account_manager.update_account_download_path(self.current_username, path)
                logger.info(f"Updated download path: {path}")
    
    def refresh_settings_paths(self):
        """Refresh the path fields in Settings tab with current account data"""
        logger.info(f"refresh_settings_paths() called - current_username={self.current_username}")
        
        if not self.current_username:
            # Clear all fields if no user logged in
            if hasattr(self, 'settings_root_folder'):
                self.settings_root_folder.setText('Not logged in')
                self.settings_debug_path.setText('Not logged in')
                self.settings_download_path.setText('Not logged in')
                self.settings_thumbnails_path.setText('Not logged in')
                self.settings_topics_root_path.setText('Not logged in')
                logger.info("No user logged in - set all fields to 'Not logged in'")
            else:
                logger.warning("Settings fields not yet created")
            return
        
        # Get current account data from database
        logger.info(f"Fetching account data for {self.current_username}")
        account_paths = self.account_manager.get_account(self.current_username)
        if not account_paths:
            logger.warning(f"Could not retrieve account data for {self.current_username}")
            if hasattr(self, 'settings_root_folder'):
                self.settings_root_folder.setText('Error: Account not found')
                self.settings_debug_path.setText('Error: Account not found')
                self.settings_download_path.setText('Error: Account not found')
                self.settings_thumbnails_path.setText('Error: Account not found')
                self.settings_topics_root_path.setText('Error: Account not found')
            return
        
        logger.info(f"Retrieved account_paths: {account_paths}")
        
        # Update all path fields
        if hasattr(self, 'settings_root_folder'):
            root = account_paths.get('root_folder', '') or 'Not set'
            debug = account_paths.get('debug_path', '') or 'Not set'
            download = account_paths.get('download_path', '') or 'Not set'
            thumbnails = account_paths.get('thumbnails_path', '') or 'Not set'
            topics = account_paths.get('topics_root_path', '') or 'Not set'
            
            # CRITICAL: Check for C: drive paths and log ERROR
            if 'C:' in root or 'c:' in root:
                logger.error(f"⚠️⚠️⚠️ CRITICAL: C: drive detected in root_folder: {root}")
            if 'C:' in debug or 'c:' in debug:
                logger.error(f"⚠️⚠️⚠️ CRITICAL: C: drive detected in debug_path: {debug}")
            if 'C:' in download or 'c:' in download:
                logger.error(f"⚠️⚠️⚠️ CRITICAL: C: drive detected in download_path: {download}")
            if 'C:' in thumbnails or 'c:' in thumbnails:
                logger.error(f"⚠️⚠️⚠️ CRITICAL: C: drive detected in thumbnails_path: {thumbnails}")
            if 'C:' in topics or 'c:' in topics:
                logger.error(f"⚠️⚠️⚠️ CRITICAL: C: drive detected in topics_root_path: {topics}")
            
            self.settings_root_folder.setText(root)
            self.settings_debug_path.setText(debug)
            self.settings_download_path.setText(download)
            self.settings_thumbnails_path.setText(thumbnails)
            self.settings_topics_root_path.setText(topics)
            
            logger.info(f"Updated Settings tab paths:")
            logger.info(f"  root_folder: {root}")
            logger.info(f"  debug_path: {debug}")
            logger.info(f"  download_path: {download}")
            logger.info(f"  thumbnails_path: {thumbnails}")
            logger.info(f"  topics_root_path: {topics}")
        else:
            logger.error("Settings fields do not exist - this should not happen!")
    
    def show_session_info(self):
        """Show detailed session information"""
        if not self.current_username:
            QMessageBox.information(self, "No Account", "No account is currently logged in")
            return
        
        account = self.account_manager.get_account(self.current_username)
        if not account:
            QMessageBox.warning(self, "Error", "Could not load account information")
            return
        
        info_text = f"""
<b>Account:</b> {account['username']}<br>
<b>Instagram Username:</b> {account.get('ig_username', 'N/A')}<br>
<b>Session File:</b> {account['session_file']}<br>
<b>Last Login:</b> {account.get('last_login', 'Unknown')}<br>
<b>Download Path:</b> {account.get('download_path', 'Not set')}<br>
        """
        
        QMessageBox.information(self, "Session Information", info_text)
    
    def login(self):
        """Handle login button click"""
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not username or not password:
            QMessageBox.warning(self, "Error", "Please enter username and password")
            return
        
        # Disable login button during operation
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging in...")
        self.statusBar().showMessage("Logging in...")
        
        # Create session file path
        session_file = config.SESSIONS_DIR / f"{username}.session"
        
        # Run login in background thread
        self.login_thread = LoginThread(
            self.instagram_manager,
            username,
            password,
            session_file
        )
        self.login_thread.finished.connect(self.login_finished)
        self.login_thread.start()
    
    def login_finished(self, success, message):
        """Handle login completion"""
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Login")
        
        if success:
            username = self.username_input.text().strip()
            session_file = str(config.SESSIONS_DIR / f"{username}.session")
            
            # Check if account already exists to preserve ALL its paths
            existing_account = self.account_manager.get_account(username)
            if existing_account:
                # Account exists - preserve all paths
                download_path = existing_account.get('download_path')
                debug_path = existing_account.get('debug_path')
                thumbnails_path = existing_account.get('thumbnails_path')
                topics_root_path = existing_account.get('topics_root_path')
                root_folder = existing_account.get('root_folder')
                logger.info(f"Account {username} exists, preserving all existing paths")
            else:
                # NEW account - all paths will be None, account_manager will use defaults
                download_path = None
                debug_path = None
                thumbnails_path = None
                topics_root_path = None
                root_folder = None
                logger.info(f"NEW account {username}, will use default paths")
            
            self.account_manager.save_account(
                username, 
                session_file, 
                download_path=download_path,
                debug_path=debug_path,
                ig_username=username,
                thumbnails_path=thumbnails_path,
                topics_root_path=topics_root_path
            )
            self.current_username = username
            
            # Initialize content database manager
            self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
            
            # Ensure topic assignments table exists
            if self.content_db and self.content_db.db:
                try:
                    self.content_db.db.ensure_topic_assignments_table()
                except Exception as e:
                    logger.error(f"Failed to create topic_assignments table: {e}")
            
            # Update UI
            self.account_status.setText(f"✓ Logged in as {username}")
            self.account_status.setStyleSheet(
                "font-weight: bold; padding: 10px; color: green;"
            )
            self.password_input.clear()
            self.load_accounts()
            
            # Set download path
            self.download_path_input.setText(download_path)
            
            # Load account's thumbnails path
            thumbnails_path = existing_account.get('thumbnails_path') if existing_account else None
            if thumbnails_path:
                self.thumbnails_path = thumbnails_path
                logger.info(f"Loaded thumbnails path: {thumbnails_path}")
            else:
                # Calculate default: if download_path ends with 'content', go up one level
                dl_path = Path(download_path)
                if dl_path.name == 'content':
                    self.thumbnails_path = str(dl_path.parent / ".thumbnails")
                else:
                    self.thumbnails_path = str(dl_path / ".thumbnails")
                logger.warning(f"No thumbnails_path in account data, using default: {self.thumbnails_path}")
            
            # Load UI settings for this account
            self.load_ui_settings()
            
            # Restore download queue from database
            self.restore_queue_from_database()
            
            # Refresh Settings tab with account paths
            self.refresh_settings_paths()
            logger.info("Settings tab paths refreshed after manual login")
            
            # Load saved content from database
            self.load_database_entries()
            
            QMessageBox.information(self, "Success", message)
            self.statusBar().showMessage(f"Logged in as {username}")
        else:
            QMessageBox.warning(self, "Login Failed", message)
            self.statusBar().showMessage("Login failed")
    
    def import_session_from_json(self):
        """Import Instagram session from browser cookies JSON file"""
        # Show info dialog first
        info_msg = QMessageBox()
        info_msg.setIcon(QMessageBox.Information)
        info_msg.setWindowTitle("Import Session from Browser")
        info_msg.setText("This feature imports Instagram cookies from your browser.")
        info_msg.setInformativeText(
            "How to export cookies:\n\n"
            "1. Install Cookie Editor extension (Chrome/Firefox)\n"
            "2. Login to Instagram in your browser\n"
            "3. Click Cookie Editor → Export → Export as JSON\n"
            "4. Save the JSON file\n"
            "5. Select that file in the next dialog\n\n"
            "See TROUBLESHOOTING.md for detailed instructions."
        )
        info_msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        
        if info_msg.exec_() != QMessageBox.Ok:
            return
        
        # Open file dialog to select JSON file
        json_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Instagram Cookies JSON File",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if not json_file:
            return
        
        # Ask for username
        username, ok = QInputDialog.getText(
            self,
            "Enter Username",
            "Enter your Instagram username:",
            QLineEdit.Normal,
            ""
        )
        
        if not ok or not username.strip():
            QMessageBox.warning(self, "Cancelled", "Username is required")
            return
        
        username = username.strip()
        
        try:
            # Read JSON file
            with open(json_file, 'r') as f:
                cookies = json.load(f)
            
            # Extract sessionid and csrftoken
            sessionid = None
            csrftoken = None
            for cookie in cookies:
                if isinstance(cookie, dict):
                    if cookie.get('name') == 'sessionid':
                        sessionid = cookie.get('value')
                    elif cookie.get('name') == 'csrftoken':
                        csrftoken = cookie.get('value')
            
            if not sessionid:
                QMessageBox.critical(
                    self,
                    "Error",
                    "Could not find 'sessionid' cookie in the JSON file.\n\n"
                    "Make sure you exported cookies from instagram.com"
                )
                return
            
            if not csrftoken:
                QMessageBox.critical(
                    self,
                    "Error",
                    "Could not find 'csrftoken' cookie in the JSON file.\n\n"
                    "Make sure you exported cookies from instagram.com"
                )
                return
            
            # Create session file with both required cookies
            session_data = {
                'sessionid': sessionid,
                'csrftoken': csrftoken
            }
            
            session_file = config.SESSIONS_DIR / f"{username}.session"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(session_file, 'wb') as f:
                pickle.dump(session_data, f)
            
            # Check if account already exists in database
            existing_account = self.account_manager.get_account(username)
            if existing_account:
                # Preserve existing paths from database
                logger.info(f"Account {username} exists - preserving paths from database")
                download_path = existing_account.get('download_path')
                thumbnails_path = existing_account.get('thumbnails_path')
                topics_root_path = existing_account.get('topics_root_path')
                root_folder = existing_account.get('root_folder')
                debug_path = existing_account.get('debug_path')
            else:
                # New account - no paths yet
                logger.info(f"New account {username} - user must set paths in Settings tab")
                download_path = None
                thumbnails_path = None
                topics_root_path = None
                root_folder = None
                debug_path = None
            
            # Save account (will preserve existing paths or use None for new)
            self.account_manager.save_account(
                username, 
                str(session_file), 
                download_path=download_path,
                ig_username=username, 
                thumbnails_path=thumbnails_path,
                topics_root_path=topics_root_path,
                root_folder=root_folder,
                debug_path=debug_path
            )
            
            # Try to login with the session
            if self.instagram_manager.login(username, "", session_file):
                self.current_username = username
                self.account_status.setText(f"✓ Logged in as {username}")
                self.account_status.setStyleSheet(
                    "font-weight: bold; padding: 10px; color: green;"
                )
                # Initialize content database manager
                self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
                
                # Load paths from database
                if download_path:
                    self.download_path_input.setText(download_path)
                    self.thumbnails_path = thumbnails_path
                    logger.info(f"Loaded existing paths from database")
                else:
                    self.download_path_input.setText("")
                    self.download_path_input.setPlaceholderText("⚠️ Set download path in Settings tab")
                    self.thumbnails_path = None
                    logger.warning(f"No paths configured - user must set in Settings tab")
                
                self.load_accounts()
                # Load saved content from database
                self.load_database_entries()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"Session imported successfully!\n\n"
                    f"Logged in as {username}\n"
                    f"Session saved to: {session_file.name}"
                )
                self.statusBar().showMessage(f"Session imported for {username}")
            else:
                QMessageBox.warning(
                    self,
                    "Session Invalid",
                    f"Session file created but login test failed.\n\n"
                    f"The cookies may be expired or invalid.\n"
                    f"Try logging into Instagram in your browser first."
                )
        
        except json.JSONDecodeError:
            QMessageBox.critical(
                self,
                "Error",
                "Invalid JSON file. Make sure you exported cookies correctly."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to import session:\n\n{str(e)}"
            )
    
    def _extract_from_specific_browser(self, browser_name: str, browser_func):
        """Helper method to extract cookies from a specific browser"""
        # Ask for username
        username, ok = QInputDialog.getText(
            self,
            f"Import from {browser_name}",
            f"Enter your Instagram username:\n\n"
            f"⚠️ Make sure {browser_name} is CLOSED before proceeding!",
            QLineEdit.Normal,
            ""
        )
        
        if not ok or not username.strip():
            return
        
        username = username.strip()
        
        try:
            import browser_cookie3
            
            self.statusBar().showMessage(f"Extracting cookies from {browser_name}...")
            
            # Try to extract cookies
            sessionid = None
            csrftoken = None
            
            try:
                cookies = browser_func(domain_name='instagram.com')
                for cookie in cookies:
                    if cookie.name == 'sessionid':
                        sessionid = cookie.value
                    elif cookie.name == 'csrftoken':
                        csrftoken = cookie.value
            except Exception as e:
                # Check for admin rights error
                if 'RequiresAdminError' in str(type(e).__name__) or 'admin' in str(e).lower():
                    QMessageBox.critical(
                        self,
                        "Administrator Rights Required",
                        f"❌ Cookie extraction from {browser_name} requires Administrator privileges.\n\n"
                        f"Steps to fix:\n\n"
                        f"1. Close this app\n"
                        f"2. Close VS Code\n"
                        f"3. Right-click VS Code → 'Run as Administrator'\n"
                        f"4. Open the app again and try again\n\n"
                        f"OR use the '🔧 Manual Import (F12)' button (no admin needed)!"
                    )
                    self.statusBar().showMessage(f"{browser_name} extraction requires admin rights")
                    return
                else:
                    raise
            
            if not sessionid or not csrftoken:
                missing = []
                if not sessionid:
                    missing.append('sessionid')
                if not csrftoken:
                    missing.append('csrftoken')
                
                QMessageBox.critical(
                    self,
                    "Missing Cookies",
                    f"Could not find required Instagram cookies in {browser_name}.\n\n"
                    f"Missing: {', '.join(missing)}\n\n"
                    f"Make sure:\n"
                    f"• You're logged into Instagram in {browser_name}\n"
                    f"• {browser_name} is completely closed (not just minimized)\n"
                    f"• Instagram cookies haven't been cleared\n\n"
                    f"Alternative: Try the '🔧 Manual Import (F12)' button instead."
                )
                self.statusBar().showMessage(f"No cookies found in {browser_name}")
                return
            
            # Create session file with both required cookies
            session_data = {
                'sessionid': sessionid,
                'csrftoken': csrftoken
            }
            
            session_file = config.SESSIONS_DIR / f"{username}.session"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(session_file, 'wb') as f:
                pickle.dump(session_data, f)
            
            # Check if account already exists in database
            existing_account = self.account_manager.get_account(username)
            if existing_account:
                # Preserve existing paths from database
                logger.info(f"Account {username} exists - preserving paths from database")
                download_path = existing_account.get('download_path')
                thumbnails_path = existing_account.get('thumbnails_path')
                topics_root_path = existing_account.get('topics_root_path')
                root_folder = existing_account.get('root_folder')
                debug_path = existing_account.get('debug_path')
            else:
                # New account - no paths yet
                logger.info(f"New account {username} - user must set paths in Settings tab")
                download_path = None
                thumbnails_path = None
                topics_root_path = None
                root_folder = None
                debug_path = None
            
            # Save account (will preserve existing paths or use None for new)
            self.account_manager.save_account(
                username, 
                str(session_file), 
                download_path=download_path,
                ig_username=username, 
                thumbnails_path=thumbnails_path,
                topics_root_path=topics_root_path,
                root_folder=root_folder,
                debug_path=debug_path
            )
            
            # Try to login with the session
            if self.instagram_manager.login(username, "", session_file):
                self.current_username = username
                self.account_status.setText(f"✓ Logged in as {username}")
                self.account_status.setStyleSheet(
                    "font-weight: bold; padding: 10px; color: green;"
                )
                # Initialize content database manager
                self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
                
                # Load paths from database
                if download_path:
                    self.download_path_input.setText(download_path)
                    self.thumbnails_path = thumbnails_path
                    logger.info(f"Loaded existing paths from database")
                else:
                    self.download_path_input.setText("")
                    self.download_path_input.setPlaceholderText("⚠️ Set download path in Settings tab")
                    self.thumbnails_path = None
                    logger.warning(f"No paths configured - user must set in Settings tab")
                
                self.load_accounts()
                # Load saved content from database
                self.load_database_entries()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"✅ Session imported successfully!\n\n"
                    f"Logged in as {username}\n"
                    f"Cookies extracted from: {browser_name}\n"
                    f"Session saved to: {session_file.name}\n\n"
                    f"You can now download posts!"
                )
                self.statusBar().showMessage(f"Session extracted from {browser_name}")
            else:
                QMessageBox.warning(
                    self,
                    "Session Invalid",
                    f"Session file created but login test failed.\n\n"
                    f"The cookies from {browser_name} may be expired or invalid.\n\n"
                    f"Try:\n"
                    f"• Logging into Instagram in {browser_name} again\n"
                    f"• Getting fresh cookies\n"
                    f"• Using the '🔧 Manual Import (F12)' button instead"
                )
                self.statusBar().showMessage(f"{browser_name} cookies invalid")
        
        except ImportError:
            QMessageBox.critical(
                self,
                "Missing Dependency",
                "The 'browser-cookie3' library is not installed.\n\n"
                "Install it with:\n"
                "pip install browser-cookie3\n\n"
                "Or use the '🔧 Manual Import (F12)' button instead."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to extract cookies from {browser_name}:\n\n{str(e)}\n\n"
                f"Try the '🔧 Manual Import (F12)' button instead."
            )
            logger.error(f"{browser_name} cookie extraction failed: {e}", exc_info=True)
            self.statusBar().showMessage(f"{browser_name} extraction failed")
    
    def extract_from_chrome(self):
        """Extract Instagram session from Chrome (requires admin)"""
        import browser_cookie3
        self._extract_from_specific_browser("Chrome", browser_cookie3.chrome)
    
    def extract_from_firefox(self):
        """Extract Instagram session from Firefox (requires admin)"""
        import browser_cookie3
        self._extract_from_specific_browser("Firefox", browser_cookie3.firefox)
    
    def manual_import_session(self):
        """Manually import session by pasting cookies from F12 DevTools"""
        # Create custom dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual Cookie Import (F12)")
        dialog.setMinimumWidth(600)
        dialog.setMinimumHeight(500)
        
        layout = QVBoxLayout(dialog)
        
        # Instructions
        instructions = QLabel(
            "<h3>📋 How to Copy Cookies from Browser</h3>"
            "<ol>"
            "<li><b>Open Instagram</b> in your browser and make sure you're logged in</li>"
            "<li>Press <b>F12</b> to open Developer Tools</li>"
            "<li>Go to the <b>'Application'</b> tab (Chrome/Edge) or <b>'Storage'</b> tab (Firefox)</li>"
            "<li>On the left sidebar, expand <b>'Cookies'</b></li>"
            "<li>Click on <b>'https://www.instagram.com'</b></li>"
            "<li>Find these two cookies in the list:"
            "<ul>"
            "<li><b>sessionid</b> - looks like a long string of numbers and letters</li>"
            "<li><b>csrftoken</b> - another string of random characters</li>"
            "</ul>"
            "</li>"
            "<li><b>Double-click</b> the VALUE column for each cookie to select it</li>"
            "<li>Press <b>Ctrl+C</b> to copy, then paste below</li>"
            "</ol>"
            "<p style='color: #F57C00;'><b>⚠️ Keep these values private - they give access to your account!</b></p>"
        )
        instructions.setWordWrap(True)
        instructions.setTextFormat(Qt.RichText)
        layout.addWidget(instructions)
        
        # Input fields
        form_layout = QGridLayout()
        
        form_layout.addWidget(QLabel("<b>Instagram Username:</b>"), 0, 0)
        username_input = QLineEdit()
        username_input.setPlaceholderText("your_username")
        form_layout.addWidget(username_input, 0, 1)
        
        form_layout.addWidget(QLabel("<b>sessionid Cookie:</b>"), 1, 0, Qt.AlignTop)
        sessionid_input = QTextEdit()
        sessionid_input.setPlaceholderText("Paste the sessionid value here...")
        sessionid_input.setMaximumHeight(80)
        form_layout.addWidget(sessionid_input, 1, 1)
        
        form_layout.addWidget(QLabel("<b>csrftoken Cookie:</b>"), 2, 0, Qt.AlignTop)
        csrftoken_input = QTextEdit()
        csrftoken_input.setPlaceholderText("Paste the csrftoken value here...")
        csrftoken_input.setMaximumHeight(80)
        form_layout.addWidget(csrftoken_input, 2, 1)
        
        layout.addLayout(form_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        import_btn = QPushButton("✅ Import Session")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        import_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(import_btn)
        
        layout.addLayout(button_layout)
        
        # Show dialog
        if dialog.exec_() != QDialog.Accepted:
            return
        
        # Get values
        username = username_input.text().strip()
        sessionid = sessionid_input.toPlainText().strip()
        csrftoken = csrftoken_input.toPlainText().strip()
        
        # Validate
        if not username:
            QMessageBox.warning(self, "Missing Username", "Please enter your Instagram username.")
            return
        
        if not sessionid:
            QMessageBox.warning(self, "Missing sessionid", "Please paste the sessionid cookie value.")
            return
        
        if not csrftoken:
            QMessageBox.warning(self, "Missing csrftoken", "Please paste the csrftoken cookie value.")
            return
        
        try:
            # Create session file
            session_data = {
                'sessionid': sessionid,
                'csrftoken': csrftoken
            }
            
            session_file = config.SESSIONS_DIR / f"{username}.session"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(session_file, 'wb') as f:
                pickle.dump(session_data, f)
            
            # Check if account already exists in database
            existing_account = self.account_manager.get_account(username)
            if existing_account:
                # Preserve existing paths from database
                logger.info(f"Account {username} exists - preserving paths from database")
                download_path = existing_account.get('download_path')
                thumbnails_path = existing_account.get('thumbnails_path')
                topics_root_path = existing_account.get('topics_root_path')
                root_folder = existing_account.get('root_folder')
                debug_path = existing_account.get('debug_path')
            else:
                # New account - no paths yet
                logger.info(f"New account {username} - user must set paths in Settings tab")
                download_path = None
                thumbnails_path = None
                topics_root_path = None
                root_folder = None
                debug_path = None
            
            # Save account (will preserve existing paths or use None for new)
            self.account_manager.save_account(
                username, 
                str(session_file), 
                download_path=download_path,
                ig_username=username, 
                thumbnails_path=thumbnails_path,
                topics_root_path=topics_root_path,
                root_folder=root_folder,
                debug_path=debug_path
            )
            
            # Try to login with the session
            if self.instagram_manager.login(username, "", session_file):
                self.current_username = username
                self.account_status.setText(f"✓ Logged in as {username}")
                self.account_status.setStyleSheet(
                    "font-weight: bold; padding: 10px; color: green;"
                )
                # Initialize content database manager
                self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
                
                # Load paths from database
                if download_path:
                    self.download_path_input.setText(download_path)
                    self.thumbnails_path = thumbnails_path
                    logger.info(f"Loaded existing paths from database")
                else:
                    self.download_path_input.setText("")
                    self.download_path_input.setPlaceholderText("⚠️ Set download path in Settings tab")
                    self.thumbnails_path = None
                    logger.warning(f"No paths configured - user must set in Settings tab")
                
                self.load_accounts()
                # Load saved content from database
                self.load_database_entries()
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"✅ Session imported successfully!\n\n"
                    f"Logged in as {username}\n"
                    f"Session saved to: {session_file.name}\n\n"
                    f"You can now download posts!"
                )
                self.statusBar().showMessage(f"Manually imported session for {username}")
                self.update_session_status()
            else:
                QMessageBox.warning(
                    self,
                    "Session Invalid",
                    f"Session file created but login test failed.\n\n"
                    f"The cookies may be expired or invalid.\n\n"
                    f"Try copying fresh cookies from your browser."
                )
        
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to import session:\n\n{str(e)}"
            )
    
    def test_session(self):
        """Test if the current session is valid"""
        if not self.instagram_manager.logged_in:
            QMessageBox.warning(
                self,
                "Not Logged In",
                "Please log in or import a session first."
            )
            return
        
        self.statusBar().showMessage("Testing session...")
        
        is_valid, message = self.instagram_manager.test_session()
        
        if is_valid:
            QMessageBox.information(
                self,
                "Session Valid ✓",
                f"Your session is active and working!\n\n"
                f"Account: {self.current_username}\n\n"
                f"You can download posts without issues."
            )
            self.statusBar().showMessage("Session is valid ✓")
            self.update_session_status()
        else:
            result = QMessageBox.critical(
                self,
                "Session Expired ❌",
                f"Your session is no longer valid.\n\n"
                f"Reason: {message}\n\n"
                f"You need to refresh your cookies to continue downloading.\n\n"
                f"Click 'OK' to open the Manual Import dialog.",
                QMessageBox.Ok | QMessageBox.Cancel
            )
            
            if result == QMessageBox.Ok:
                self.manual_import_session()
            
            self.statusBar().showMessage("Session expired - refresh needed")
    
    def prompt_session_refresh(self):
        """Prompt user to refresh their session"""
        if not self.instagram_manager.logged_in:
            QMessageBox.information(
                self,
                "Refresh Session",
                "No active session to refresh.\n\n"
                "Use the login or import buttons to create a session first."
            )
            return
        
        # Test session first
        is_valid, message = self.instagram_manager.test_session()
        
        if is_valid:
            result = QMessageBox.question(
                self,
                "Session Still Valid",
                f"Your current session is still working.\n\n"
                f"Do you still want to refresh it with new cookies?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if result == QMessageBox.Yes:
                self.manual_import_session()
        else:
            # Session expired, go straight to refresh
            QMessageBox.warning(
                self,
                "Session Expired",
                f"Your session has expired and needs to be refreshed.\n\n"
                f"Reason: {message}\n\n"
                f"Opening Manual Import dialog..."
            )
            self.manual_import_session()
    
    def update_session_status(self):
        """Update the session status label with age and validity"""
        if not self.instagram_manager.logged_in:
            self.session_status.setText("")
            return
        
        age = self.instagram_manager.get_session_age()
        
        if age is None:
            self.session_status.setText("Session info unavailable")
            return
        
        # Format age
        if age < 60:
            age_str = f"{int(age)} seconds ago"
        elif age < 3600:
            age_str = f"{int(age / 60)} minutes ago"
        elif age < 86400:
            age_str = f"{int(age / 3600)} hours ago"
        else:
            age_str = f"{int(age / 86400)} days ago"
        
        # Warn if old
        if age > 3600:  # > 1 hour
            self.session_status.setText(
                f"⚠️ Session created {age_str} - may need refresh"
            )
            self.session_status.setStyleSheet("font-size: 9pt; color: orange; padding: 0 10px;")
        else:
            self.session_status.setText(f"Session created {age_str}")
            self.session_status.setStyleSheet("font-size: 9pt; color: gray; padding: 0 10px;")
    
    def load_accounts(self):
        """Load saved accounts into the list"""
        self.accounts_list.clear()
        accounts = self.account_manager.list_accounts()
        
        for account in accounts:
            # Handle last_login as datetime or string
            last_login = account.get('last_login')
            if last_login:
                if isinstance(last_login, str):
                    login_str = last_login[:16]
                else:
                    # It's a datetime object
                    login_str = last_login.strftime('%Y-%m-%d %H:%M')
            else:
                login_str = 'Never'
            
            item = QListWidgetItem(
                f"{account['username']} (Last login: {login_str})"
            )
            item.setData(Qt.UserRole, account)
            self.accounts_list.addItem(item)
    
    def switch_account(self, item):
        """Switch to a different saved account"""
        account = item.data(Qt.UserRole)
        username = account['username']
        ig_username = account.get('ig_username') or username  # Use IG username, fallback to account name
        session_file = Path(account['session_file'])
        
        self.statusBar().showMessage(f"Switching to {username}...")
        
        # Try to login with saved session
        if self.instagram_manager.login(ig_username, "", session_file):
            self.current_username = username
            self.account_status.setText(f"✓ Logged in as {username}")
            self.account_status.setStyleSheet(
                "font-weight: bold; padding: 10px; color: green;"
            )
            # Initialize content database manager
            self.content_db = ContentDatabaseManager(str(config.DATA_DIR), username)
            self.statusBar().showMessage(f"Switched to {username}")
            
            # Load account's download path
            download_path = account.get('download_path')
            if download_path:
                self.download_path_input.setText(download_path)
                logger.info(f"Loaded download path: {download_path}")
            
            # Load account's thumbnails path
            thumbnails_path = account.get('thumbnails_path')
            if thumbnails_path:
                self.thumbnails_path = thumbnails_path
                logger.info(f"Loaded thumbnails path: {thumbnails_path}")
            else:
                # No thumbnails path set - user must configure in Settings
                if download_path:
                    # Try to calculate from download_path
                    dl_path = Path(download_path)
                    if dl_path.name == 'content':
                        self.thumbnails_path = str(dl_path.parent / ".thumbnails")
                    else:
                        self.thumbnails_path = str(dl_path / ".thumbnails")
                    logger.warning(f"No thumbnails_path in account data, calculated from download_path: {self.thumbnails_path}")
                else:
                    # No download_path either - leave as None
                    self.thumbnails_path = None
                    logger.error("⚠️ No thumbnails_path OR download_path set - user MUST configure paths in Settings tab")
            
            # Load UI settings for this account
            self.load_ui_settings()
            
            # Refresh Settings tab with account paths
            self.refresh_settings_paths()
            logger.info("Settings tab paths refreshed after account switch")
            
            # Load saved content from database
            self.load_database_entries()
        else:
            QMessageBox.warning(
                self,
                "Session Expired",
                f"Session expired for {username}. Please login again."
            )
            self.username_input.setText(username)
            self.tabs.setCurrentIndex(2)  # Switch to accounts tab
    
    def delete_account(self):
        """Delete selected account"""
        current = self.accounts_list.currentItem()
        if not current:
            return
        
        account = current.data(Qt.UserRole)
        username = account['username']
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete account {username}?\n\n(Downloaded files will not be deleted)",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.account_manager.delete_account(username)
            self.load_accounts()
            self.statusBar().showMessage(f"Deleted account: {username}")
    
    def load_database_entries(self):
        """Legacy synchronous load - now redirects to async version"""
        self.load_database_entries_async()
    
    def load_database_entries_async(self):
        """Load saved content entries from database asynchronously"""
        if not self.content_db:
            logger.warning("Cannot load database entries - not logged in")
            return
        
        logger.info("load_database_entries_async() called")
        
        # Show hourglass cursor for this blocking operation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Stop any existing load thread
        if self.db_load_thread and self.db_load_thread.isRunning():
            logger.info("Stopping existing database load thread")
            self.db_load_thread.stop()
            self.db_load_thread.wait()
        
        # Clear existing posts
        self.saved_posts.clear()
        self.posts_table.setRowCount(0)
        
        # Update status
        self.browse_status.setText("Initializing database (lazy loading)...")
        
        # Create and start thread to get count
        logger.info("Creating LoadDatabaseThread")
        self.db_load_thread = LoadDatabaseThread(self.content_db)
        logger.info("Connecting count_loaded signal")
        self.db_load_thread.count_loaded.connect(self.on_db_count_loaded)
        logger.info("Connecting error signal")
        self.db_load_thread.error.connect(self.on_db_load_error)
        logger.info("Starting LoadDatabaseThread")
        self.db_load_thread.start()
        
        logger.info("Started async database initialization (lazy loading)")
    
    def on_db_load_progress(self, current, total):
        """Update progress during database load"""
        self.browse_status.setText(f"Loading database entries: {current}/{total}...")
    
    def on_db_batch_loaded(self, posts):
        """Handle a batch of posts loaded from database"""
        # Temporarily disable sorting for faster insertion
        was_sorting = self.posts_table.isSortingEnabled()
        self.posts_table.setSortingEnabled(False)
        
        # Add posts to the list
        for i, post in enumerate(posts):
            self.add_post_to_list(post)
            
            # Process events every 10 posts to keep UI responsive
            if i % 10 == 0:
                QApplication.processEvents()
                
                # If in tile view, refresh tiles periodically to show progress
                if self.current_view_mode == 'tiles' and i % 20 == 0:
                    self.filtered_posts = self.saved_posts.copy()
                    self.populate_tiles()
        
        # Update filtered_posts after batch is loaded
        self.filtered_posts = self.saved_posts.copy()
        
        # Refresh tile view if showing tiles
        if self.current_view_mode == 'tiles':
            self.populate_tiles()
        
        # Re-enable sorting
        self.posts_table.setSortingEnabled(was_sorting)
        
        # Update table pagination after loading
        self.update_table_pagination()
    
    def on_db_initial_load_complete(self, initial_count):
        """Handle completion of initial fast load - UI is now usable"""
        # Sort the initial entries
        self.posts_table.sortItems(0, Qt.DescendingOrder)
        
        # Update status to show UI is ready
        self.browse_status.setText(f"✓ Loaded first {initial_count} most recent posts (loading rest in background...)")
        logger.info(f"UI ready with {initial_count} entries - continuing background load")
    
    def on_db_load_finished(self, total_count, stats):
        """Handle completion of database load"""
        # Restore cursor after operation completes
        QApplication.restoreOverrideCursor()
        
        # Final update to filtered_posts
        self.filtered_posts = self.saved_posts.copy()
        
        # Sort by Row number descending (most recent first)
        self.posts_table.sortItems(0, Qt.DescendingOrder)
        
        # Restore target page if it's now valid with full dataset
        if self.target_page >= 0 and self.filtered_posts:
            total_pages = (len(self.filtered_posts) + self.tiles_per_page - 1) // self.tiles_per_page
            logger.info(f"[PAGE RESTORE] target_page={self.target_page}, total_pages={total_pages}, view_mode={self.current_view_mode}")
            
            if self.target_page < total_pages:
                self.current_page = self.target_page
                logger.info(f"[PAGE RESTORE] SUCCESS: Restored to page {self.target_page}")
                
                # Refresh view to show the restored page
                if self.current_view_mode == 'tiles':
                    self.populate_tiles()
                elif self.current_view_mode == 'table':
                    # For table view, just update pagination display
                    self.update_table_pagination()
            else:
                logger.warning(f"[PAGE RESTORE] FAILED: Target page {self.target_page} exceeds total pages {total_pages}")
                self.current_page = max(0, total_pages - 1)
        else:
            logger.info(f"[PAGE RESTORE] Skipped: target_page={self.target_page}, filtered_posts count={len(self.filtered_posts)}")
        
        # Update status with statistics
        if stats:
            status_msg = (
                f"Loaded {total_count} posts from database | "
                f"Total: {stats['total']}, "
                f"Awaiting scan: {stats['awaiting_scan']}, "
                f"Downloaded: {stats['downloaded']}"
            )
        else:
            status_msg = f"Loaded {total_count} posts from database"
        
        self.browse_status.setText(status_msg)
        logger.info(f"Database load complete: {total_count} entries")
        
        # Update table pagination after database load complete
        self.update_table_pagination()
        
        
    def on_db_load_error(self, error_msg):
        """Handle error during database load"""
        logger.error(f"Database load error: {error_msg}")
        self.browse_status.setText(f"Error: {error_msg}")
        QMessageBox.critical(self, "Load Error", error_msg)
    
    def on_db_count_loaded(self, total_count, stats):
        """Handle database count loaded - now ready for lazy loading"""
        logger.info(f"on_db_count_loaded() called: total_count={total_count}, stats={stats}")
        self.total_items = total_count
        logger.info(f"Set self.total_items = {self.total_items}")
        
        # Restore cursor
        QApplication.restoreOverrideCursor()
        
        # Update status with statistics
        if stats:
            status_msg = (
                f"Database ready: {total_count} items (lazy loading) | "
                f"Total: {stats['total']}, "
                f"Awaiting scan: {stats['awaiting_scan']}, "
                f"Downloaded: {stats['downloaded']}"
            )
        else:
            status_msg = f"Database ready: {total_count} items (lazy loading)"
        
        self.browse_status.setText(status_msg)
        logger.info(f"Database initialized: {total_count} entries (lazy loading enabled)")
        
        # Load first page immediately
        if total_count > 0:
            logger.info(f"[PAGE RESTORE] Checking target_page: {self.target_page} (>= 0: {self.target_page >= 0})")
            if self.target_page >= 0:
                # Restore saved page
                total_pages = (total_count + self.tiles_per_page - 1) // self.tiles_per_page
                logger.info(f"[PAGE RESTORE] total_pages={total_pages}, target_page={self.target_page}, tiles_per_page={self.tiles_per_page}")
                if self.target_page < total_pages:
                    self.current_page = self.target_page
                    logger.info(f"[PAGE RESTORE] ✓ Restoring to page {self.target_page} (will display as 'Page {self.target_page + 1}' in UI)")
                else:
                    self.current_page = 0
                    logger.warning(f"[PAGE RESTORE] ✗ Target page {self.target_page} >= total pages {total_pages}, using page 0")
            else:
                self.current_page = 0
                logger.info(f"[PAGE RESTORE] target_page < 0, using page 0")
            
            logger.info(f"About to call load_page({self.current_page}) - will display as 'Page {self.current_page + 1}' in UI")
            # Load the initial page
            self.load_page(self.current_page)
            
            # Preload adjacent pages in background
            QTimer.singleShot(100, lambda: self.preload_adjacent_pages(self.current_page))
    
    def load_page(self, page_num):
        """Load a specific page of posts from database"""
        try:
            logger.debug(f"load_page called for page {page_num}")
            
            # Check if already in cache
            if page_num in self.page_cache:
                logger.debug(f"Page {page_num} already in cache")
                self.populate_tiles()
                return
            
            # Check if already loading
            if page_num in self.loading_pages:
                logger.debug(f"Page {page_num} already loading")
                return
            
            # Mark as loading
            self.loading_pages.add(page_num)
            
            # Update status
            self.browse_status.setText(f"Loading page {page_num + 1}...")
            
            # Build search filters from current sort/filter settings
            search_filters = {
                'sort_by': getattr(self, 'current_sort_by', 'Row Number'),
                'sort_direction': getattr(self, 'current_sort_direction', 'DESC'),
                'filter': getattr(self, 'current_filter', 'All (Unfiltered)'),
                'topic_filter': getattr(self, 'current_topic_filter', 'All Topics')
            }
            
            # Create and start page load thread
            thread = LoadPageThread(self.content_db, page_num, self.tiles_per_page, search_filters)
            thread.page_loaded.connect(self.on_page_loaded)
            thread.error.connect(self.on_page_load_error)
            self.page_load_threads[page_num] = thread
            thread.start()
            
            logger.debug(f"Started loading page {page_num}")
        except Exception as e:
            logger.error(f"Error in load_page for page {page_num}: {e}", exc_info=True)
            self.loading_pages.discard(page_num)
            self.browse_status.setText(f"Error loading page {page_num + 1}")
            QMessageBox.warning(self, "Page Load Error", f"Failed to load page {page_num + 1}:\n{str(e)}")
    
    def on_page_loaded(self, page_num, posts):
        """Handle a page of posts loaded from database"""
        # Check if this page load was cancelled (thread was stopped)
        if page_num not in self.loading_pages and page_num not in self.page_load_threads:
            logger.debug(f"Ignoring load result for cancelled page {page_num}")
            return
        
        # Add to cache
        self.page_cache[page_num] = posts
        
        # Remove from loading set
        self.loading_pages.discard(page_num)
        
        # Clean up thread
        if page_num in self.page_load_threads:
            thread = self.page_load_threads[page_num]
            del self.page_load_threads[page_num]
            # Schedule thread for deletion
            thread.deleteLater()
        
        logger.debug(f"Page {page_num} cached: {len(posts)} posts")
        
        # Update status
        total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
        self.browse_status.setText(f"Page {page_num + 1} of {total_pages} loaded ({len(posts)} items)")
        
        # Evict old pages if cache is full
        if len(self.page_cache) > self.cache_max_pages:
            # Keep current page and adjacent pages, remove furthest
            pages_to_keep = {
                self.current_page - 2,
                self.current_page - 1,
                self.current_page,
                self.current_page + 1,
                self.current_page + 2
            }
            
            for cached_page in list(self.page_cache.keys()):
                if cached_page not in pages_to_keep and len(self.page_cache) > self.cache_max_pages:
                    del self.page_cache[cached_page]
                    logger.debug(f"Evicted page {cached_page} from cache")
        
        # If this is the current page, display it
        if page_num == self.current_page:
            # Update filtered_posts for backward compatibility (needed for table view)
            self.filtered_posts = posts.copy()
            
            # Update the appropriate view
            if self.current_view_mode == 'tiles':
                self.populate_tiles()
            else:  # table view
                # For table view, populate table from cache
                # Clear existing table
                self.posts_table.setRowCount(0)
                
                # Add posts from current page to table
                for post in posts:
                    self.add_post_to_list(post, skip_db_save=True)
                
                # Sort by row number descending
                self.posts_table.sortItems(0, Qt.DescendingOrder)
    
    def on_page_load_error(self, error_msg):
        """Handle error loading a page"""
        logger.error(f"Page load error: {error_msg}")
        self.browse_status.setText(f"Error loading page: {error_msg}")
        QMessageBox.warning(self, "Page Load Error", f"Failed to load page:\n{error_msg}")
    
    def cancel_distant_page_loads(self, current_page):
        """Cancel page load threads for pages far from current page"""
        # Define which pages to keep (current +/- 2)
        pages_to_keep = {
            current_page - 2,
            current_page - 1,
            current_page,
            current_page + 1,
            current_page + 2
        }
        
        # Stop and remove threads for distant pages
        for page_num in list(self.page_load_threads.keys()):
            if page_num not in pages_to_keep:
                logger.info(f"Cancelling load for distant page {page_num}")
                thread = self.page_load_threads[page_num]
                
                # Disconnect all signals to prevent callbacks after deletion
                try:
                    thread.page_loaded.disconnect()
                except:
                    pass
                try:
                    thread.error.disconnect()
                except:
                    pass
                
                # Request thread to stop
                thread.stop()
                
                # Remove from tracking
                del self.page_load_threads[page_num]
                self.loading_pages.discard(page_num)
                
                # Schedule thread for deletion by Qt event loop (safe way to delete)
                thread.deleteLater()
    
    def preload_adjacent_pages(self, current_page):
        """Preload pages adjacent to current page in background"""
        total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
        
        # Preload previous page
        if current_page > 0:
            prev_page = current_page - 1
            if prev_page not in self.page_cache and prev_page not in self.loading_pages:
                logger.debug(f"Preloading previous page {prev_page}")
                self.load_page(prev_page)
        
        # Preload next page
        if current_page < total_pages - 1:
            next_page = current_page + 1
            if next_page not in self.page_cache and next_page not in self.loading_pages:
                logger.debug(f"Preloading next page {next_page}")
                self.load_page(next_page)
    
    def load_saved_posts(self):
        """Load saved posts from Instagram"""
        if not self.instagram_manager.logged_in:
            QMessageBox.warning(
                self,
                "Not Logged In",
                "Please login to an account first"
            )
            self.tabs.setCurrentIndex(2)  # Switch to accounts tab
            return
        
        # Show hourglass cursor for this blocking operation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Build set of already-loaded shortcodes for faster duplicate checking
        existing_shortcodes = {post.get('shortcode') for post in self.saved_posts}
        
        # Don't clear the list - keep existing posts and add new ones
        self.browse_status.setText(f"Fetching new saved posts (have {len(self.saved_posts)} already)...")
        
        # Track initial state for pagination adjustment
        self.fetch_in_progress = True
        self.fetch_initial_total_items = self.total_items
        self.fetch_initial_page = self.current_page
        logger.info(f"Starting fetch: initial_page={self.fetch_initial_page}, initial_total={self.fetch_initial_total_items}")
        
        # Reset pagination update counter
        self.posts_added_since_pagination_update = 0
        
        # Add process to Process Manager
        self.load_saved_process_id = self.process_manager.add_process(
            'load_saved',
            'Loading saved posts from Instagram',
            thread=None
        )
        
        # Run in background thread
        self.load_thread = LoadSavedThread(self.instagram_manager, self.content_db, self.stop_at_first_duplicate, existing_shortcodes)
        self.load_thread.post_loaded.connect(self.add_post_to_list)
        self.load_thread.progress.connect(self.update_load_progress)
        self.load_thread.finished.connect(self.load_posts_finished)
        self.load_thread.error.connect(self.load_posts_error)
        self.load_thread.duplicate_found.connect(self.handle_duplicate_stop)
        self.load_thread.start()
    
    def add_post_to_list(self, post, skip_db_save=False):
        """Add a post to the browse table
        
        Args:
            post: Post dictionary
            skip_db_save: If True, skip database save (used when loading from DB)
        """
        logger.info(f"add_post_to_list called for {post.get('shortcode', 'unknown')}")
        self.saved_posts.append(post)
        # Note: filtered_posts is updated separately in batch operations
        
        # Save to database if content_db is initialized (and not loading from DB)
        is_duplicate = False
        if not skip_db_save and self.content_db:
            try:
                is_duplicate = not self.content_db.save_post(post)
                
                # After saving, get the entry back from database to retrieve assigned row_number
                if not is_duplicate:
                    shortcode = post.get('shortcode')
                    if shortcode:
                        db_entry = self.content_db.db.get_content_entry(shortcode)
                        if db_entry:
                            content_info = db_entry.get('ContentInformation', {})
                            assigned_row = content_info.get('rowNumber', 0)
                            if assigned_row:
                                post['row_number'] = assigned_row
                    
                    # Increment total_items for new posts (not duplicates)
                    self.total_items += 1
                    self.posts_added_since_pagination_update += 1
                    logger.debug(f"Incremented total_items to {self.total_items}")
                    
                    # Update pagination every 10 posts for better responsiveness
                    if self.posts_added_since_pagination_update >= 10:
                        self.update_pagination_controls()
                        self.posts_added_since_pagination_update = 0
                        logger.debug(f"Updated pagination controls, total_items={self.total_items}")
            except Exception as e:
                logger.error(f"Error saving post to database: {e}")
        
        # Temporarily disable sorting for faster insertion
        was_sorting = self.posts_table.isSortingEnabled()
        self.posts_table.setSortingEnabled(False)
        
        # Add row to table
        row = self.posts_table.rowCount()
        self.posts_table.insertRow(row)
        
        # Column 0: Thumbnail
        shortcode = post.get('shortcode', 'unknown')
        thumbnail_label = self.create_thumbnail_widget(shortcode, post)
        self.posts_table.setCellWidget(row, 0, thumbnail_label)
        
        # Column 1: Row Number from database
        row_number = post.get('row_number', 0)
        row_item = QTableWidgetItem()
        row_item.setData(Qt.DisplayRole, row_number)  # Use int for proper sorting
        if is_duplicate:
            row_item.setForeground(Qt.gray)
        self.posts_table.setItem(row, 1, row_item)
        
        # Column 2: Shortcode (Instagram post ID)
        if is_duplicate:
            shortcode = "✓ " + shortcode  # Check mark for duplicates
        id_item = QTableWidgetItem(shortcode)
        if is_duplicate:
            id_item.setForeground(Qt.gray)
        self.posts_table.setItem(row, 2, id_item)
        
        # Column 3: Account
        account_item = QTableWidgetItem(post['owner_username'])
        if is_duplicate:
            account_item.setForeground(Qt.gray)
        self.posts_table.setItem(row, 3, account_item)
        
        # Column 4: Caption
        caption = post['caption'][:100] + "..." if len(post['caption']) > 100 else post['caption']
        caption_item = QTableWidgetItem(caption)
        caption_item.setData(Qt.UserRole, post)  # Store full post data
        if is_duplicate:
            caption_item.setForeground(Qt.gray)
        self.posts_table.setItem(row, 4, caption_item)
        
        # Column 5: Type
        if post['typename'] == "GraphImage":
            type_text = "� POST"
        elif post['typename'] == "GraphVideo":
            type_text = "🎥 VIDEO"
        else:
            type_text = "📸 CAROUSEL"
        type_item = QTableWidgetItem(type_text)
        if is_duplicate:
            type_item.setForeground(Qt.gray)
        self.posts_table.setItem(row, 5, type_item)
        
        # Column 6: Download Status (use status from post data to avoid extra DB query)
        status_text = "New"
        status_color = Qt.blue
        
        # Get status from post data (already loaded from database)
        download_status = post.get('download_status', 'awaiting scan')
        if download_status == 'completed':
            status_text = "✓ Downloaded"
            status_color = Qt.darkGreen
        elif download_status == 'failed':
            status_text = "✗ Failed"
            status_color = Qt.red
        elif download_status == 'skipped':
            status_text = "⊘ Skipped"
            status_color = QColor(255, 165, 0)  # Orange
        elif download_status == 'success_with_issues':
            status_text = "⚠️ SUCCESS/ISSUES"
            status_color = Qt.red
        elif download_status == 'in progress':
            status_text = "⏳ Downloading"
            status_color = Qt.darkYellow
        else:
            status_text = "⏸ Awaiting Scan"
            status_color = Qt.gray
        
        status_item = QTableWidgetItem(status_text)
        status_item.setForeground(status_color)
        self.posts_table.setItem(row, 6, status_item)
        
        # Apply row coloring based on priority: errors > topic assigned > downloaded > not downloaded
        shortcode_clean = post.get('shortcode', '').replace('✓ ', '').strip()
        content_info = post.get('ContentInformation', {})
        topic_id = content_info.get('topicID')
        bg_color, _ = self.get_item_background_color(shortcode_clean, post.get('download_status', 'not_downloaded'), topic_id)
        
        # Convert hex color to QColor for background
        bg_qcolor = QColor(bg_color)
        
        # Set background color for all columns
        for col in range(self.posts_table.columnCount()):
            item = self.posts_table.item(row, col)
            if item:
                item.setBackground(bg_qcolor)
        
        # Apply foreground text coloring for status emphasis
        if status_text == "✓ Downloaded":
            for col in range(1, 7):  # Color text in all columns except thumbnail and button columns
                item = self.posts_table.item(row, col)
                if item:
                    item.setForeground(Qt.darkGreen)
        elif status_text == "✗ Failed":
            for col in range(1, 7):  # Color text in all columns except thumbnail and button columns
                item = self.posts_table.item(row, col)
                if item:
                    item.setForeground(Qt.red)
        elif status_text == "⊘ Skipped":
            for col in range(1, 7):  # Color text in all columns except thumbnail and button columns
                item = self.posts_table.item(row, col)
                if item:
                    item.setForeground(QColor(255, 165, 0))  # Orange
        elif status_text == "⚠️ SUCCESS/ISSUES":
            for col in range(1, 7):  # Color text in all columns except thumbnail and button columns
                item = self.posts_table.item(row, col)
                if item:
                    item.setForeground(Qt.red)
        
        # Column 7: Open button for downloaded posts, Debug button for failed posts, Info for skipped
        if status_text == "✓ Downloaded":
            open_btn = QPushButton("📂 Open")
            open_btn.setMaximumWidth(60)
            open_btn.clicked.connect(lambda checked, sc=post['shortcode']: self.open_downloaded_file(sc))
            self.posts_table.setCellWidget(row, 7, open_btn)
        elif status_text == "✗ Failed":
            # For failed posts loaded from database, we can't access the original error
            # But we can still provide a button to check for debug files
            debug_btn = QPushButton("🐛 Debug")
            debug_btn.setMaximumWidth(60)
            debug_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
            debug_btn.clicked.connect(lambda checked, sc=post['shortcode']: self.find_and_open_debug_file(sc))
            self.posts_table.setCellWidget(row, 7, debug_btn)
        elif status_text == "⊘ Skipped":
            # Skipped posts - show info button
            info_btn = QPushButton("ℹ️ Info")
            info_btn.setMaximumWidth(60)
            info_btn.setStyleSheet("QPushButton { background-color: #FFA500; color: white; }")
            info_btn.setToolTip("No files downloaded - may already exist or unavailable")
            self.posts_table.setCellWidget(row, 7, info_btn)
        elif status_text == "⚠️ SUCCESS/ISSUES":
            # Success with issues - show warning button
            warn_btn = QPushButton("⚠️ Issues")
            warn_btn.setMaximumWidth(70)
            warn_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
            warn_btn.setToolTip("Download succeeded but no files created - may already exist or be unavailable")
            self.posts_table.setCellWidget(row, 7, warn_btn)
        
        # Column 8: Copy URL button
        copy_btn = QPushButton("📋")
        copy_btn.setMaximumWidth(40)
        copy_btn.setToolTip("Copy Instagram URL")
        copy_btn.clicked.connect(lambda checked, url=post['url']: self.copy_url_to_clipboard(url))
        self.posts_table.setCellWidget(row, 8, copy_btn)
        
        # Column 9: Open in Firefox button
        firefox_btn = QPushButton("🦊")
        firefox_btn.setMaximumWidth(40)
        firefox_btn.setToolTip("Open in Firefox")
        firefox_btn.clicked.connect(lambda checked, url=post['url']: self.open_in_firefox(url))
        self.posts_table.setCellWidget(row, 9, firefox_btn)
        
        # Column 10: Classify button
        classify_btn = QPushButton("📁")
        classify_btn.setMaximumWidth(70)
        classify_btn.setToolTip("Classify content into topic")
        classify_btn.clicked.connect(lambda checked, sc=shortcode: self.classify_content(sc))
        self.posts_table.setCellWidget(row, 10, classify_btn)
        
        # Column 11: Download Thumbnail button
        thumb_btn = QPushButton("🖼️")
        thumb_btn.setMaximumWidth(70)
        thumb_btn.setToolTip("Download missing thumbnail")
        thumb_btn.clicked.connect(lambda checked, sc=shortcode, p=post: self.download_single_thumbnail(sc, p))
        self.posts_table.setCellWidget(row, 11, thumb_btn)
        
        # Column 12: Reset button
        reset_btn = QPushButton("🔄")
        reset_btn.setMaximumWidth(70)
        reset_btn.setToolTip("Reset to undownloaded state (deletes files)")
        reset_btn.clicked.connect(lambda checked, sc=shortcode_clean: self.reset_post(sc))
        self.posts_table.setCellWidget(row, 12, reset_btn)
        
        # Re-enable sorting only at the end
        if was_sorting:
            self.posts_table.setSortingEnabled(True)
        
        # Download thumbnail asynchronously based on settings
        # 1. New posts (not from database load) - only if auto_fetch_new_thumbnails enabled
        # 2. Downloaded posts missing thumbnails - only if auto_fetch_thumbnails enabled
        should_download_thumbnail = False
        
        if not is_duplicate and not skip_db_save and self.auto_fetch_new_thumbnails:
            # New post being saved - download thumbnail if setting enabled
            should_download_thumbnail = True
            logger.debug(f"New post {shortcode} - will fetch thumbnail (auto_fetch_new_thumbnails enabled)")
        elif self.auto_fetch_thumbnails and download_status in ['completed', 'success_with_issues']:
            # Post is downloaded - check if thumbnail exists (only if auto-fetch enabled)
            if self.content_db and self.content_db.db:
                thumbnail = self.content_db.db.get_thumbnail(shortcode)
                if not thumbnail:
                    # Downloaded post but no thumbnail - download it
                    should_download_thumbnail = True
                    logger.info(f"Downloaded post {shortcode} missing thumbnail - will fetch (auto-fetch enabled)")
        
        if should_download_thumbnail:
            from threading import Thread
            thumbnail_thread = Thread(target=self.download_thumbnail_async, args=(shortcode, post), daemon=True)
            self.thumbnail_threads.append(thumbnail_thread)
            thumbnail_thread.start()
            
            # Show stop button if thumbnails are downloading
            if self.thumbnail_threads and not self.stop_thumbnail_downloads:
                self.stop_thumbnails_btn.setVisible(True)
        
        self.browse_status.setText(f"Loaded {len(self.saved_posts)} posts...")
    
    def update_load_progress(self, total_fetched, new_count, existing_count, current_shortcode):
        """Update Process Manager with loading progress"""
        if hasattr(self, 'load_saved_process_id'):
            # Get row number from database if available
            row_number = "?"
            if self.content_db:
                try:
                    entry = self.content_db.db.get_content_entry(current_shortcode)
                    if entry:
                        content_info = entry.get('ContentInformation', {})
                        row_number = content_info.get('rowNumber', '?')
                except:
                    pass
            
            # Update process with status showing progress
            status_msg = f"Adding #{total_fetched}, ID {row_number} ({new_count} new, {existing_count} existing)"
            self.process_manager.update_process(
                self.load_saved_process_id,
                status='running',
                current=total_fetched,
                total=0  # Unknown total
            )
            # Update process description dynamically
            if self.load_saved_process_id in self.process_manager.processes:
                self.process_manager.processes[self.load_saved_process_id]['description'] = status_msg
                # Emit update to refresh UI
                self.process_manager.process_updated.emit(
                    self.load_saved_process_id,
                    'running',
                    total_fetched,
                    0
                )
    
    def load_posts_finished(self, count):
        """Handle posts loading completion"""
        # Mark process as completed
        if hasattr(self, 'load_saved_process_id'):
            # Get final stats from the process
            process = self.process_manager.get_process(self.load_saved_process_id)
            if process:
                total_fetched = process.get('current', 0)
                self.process_manager.update_process(
                    self.load_saved_process_id,
                    status='completed',
                    current=total_fetched,
                    total=total_fetched
                )
                # Remove after 3 seconds
                QTimer.singleShot(3000, lambda: self.process_manager.remove_process(self.load_saved_process_id))
        
        # Clear fetch tracking flag
        self.fetch_in_progress = False
        
        # Final pagination update after all posts loaded
        if self.posts_added_since_pagination_update > 0:
            self.update_pagination_controls()
            self.posts_added_since_pagination_update = 0
            logger.info(f"Final pagination update: total_items={self.total_items}")
        
        # Restore cursor after operation completes
        QApplication.restoreOverrideCursor()
        
        # Update filtered posts after fetching from Instagram
        self.filtered_posts = self.saved_posts.copy()
        
        # Refresh tile view to show all loaded posts
        if self.current_view_mode == 'tiles':
            self.populate_tiles()
        
        # Update table pagination after loading Instagram posts
        self.update_table_pagination()
        
        # Show statistics if database is available
        if self.content_db:
            try:
                stats = self.content_db.get_statistics()
                self.browse_status.setText(
                    f"Loaded {count} saved posts  |  "
                    f"Database: {stats['total']} total, "
                    f"{stats['awaiting_scan']} awaiting scan, "
                    f"{stats['downloaded']} downloaded"
                )
                self.statusBar().showMessage(
                    f"Loaded {count} posts (Database: {stats['total']} total)"
                )
            except Exception as e:
                logger.error(f"Error getting statistics: {e}")
                self.browse_status.setText(f"Loaded {count} saved posts")
                self.statusBar().showMessage(f"Loaded {count} saved posts")
        else:
            self.browse_status.setText(f"Loaded {count} saved posts")
            self.statusBar().showMessage(f"Loaded {count} saved posts")
        
    def load_posts_error(self, error):
        """Handle posts loading error"""
        # Mark process as failed
        if hasattr(self, 'load_saved_process_id'):
            self.process_manager.update_process(
                self.load_saved_process_id,
                status='failed'
            )
            # Remove after 5 seconds
            QTimer.singleShot(5000, lambda: self.process_manager.remove_process(self.load_saved_process_id))
        
        # Clear fetch tracking flag
        self.fetch_in_progress = False
        
        # Final pagination update even on error
        if hasattr(self, 'posts_added_since_pagination_update') and self.posts_added_since_pagination_update > 0:
            self.update_pagination_controls()
            self.posts_added_since_pagination_update = 0
            logger.info(f"Final pagination update (error): total_items={self.total_items}")
        
        # Restore cursor
        QApplication.restoreOverrideCursor()
        
        self.browse_status.setText("Error loading posts")
        QMessageBox.critical(self, "Error", error)
    
    def import_from_export(self):
        """Import saved posts from Instagram's exported data file"""
        from PyQt5.QtWidgets import QFileDialog
        import json
        
        # Show info dialog
        info_msg = QMessageBox()
        info_msg.setIcon(QMessageBox.Information)
        info_msg.setWindowTitle("Import from Instagram Export")
        info_msg.setText("This imports saved posts from Instagram's exported data.")
        info_msg.setInformativeText(
            "To export your Instagram data:\n\n"
            "1. Go to Instagram → Settings → Privacy & Security\n"
            "2. Request Download → Data Download\n"
            "3. Select JSON format\n"
            "4. Wait for email (can take up to 48 hours)\n"
            "5. Download and extract the ZIP file\n"
            "6. Import the 'saved_posts.json' file here\n\n"
            "Note: This doesn't require Instagram login or API access!"
        )
        info_msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        
        if info_msg.exec_() != QMessageBox.Ok:
            return
        
        # File picker
        json_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Instagram Export File",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if not json_file:
            return
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Parse Instagram export format
            # Format can vary, try common structures
            posts_data = []
            
            if isinstance(data, list):
                posts_data = data
            elif isinstance(data, dict):
                # Try nested format: {"saved_saved_media": [{"string_map_data": {...}}]}
                if 'saved_saved_media' in data:
                    raw_data = data['saved_saved_media']
                    posts_data = []
                    # Convert nested format to simple format
                    for item in raw_data:
                        try:
                            string_map = item.get('string_map_data', {})
                            saved_on = string_map.get('Saved on', {})
                            if 'href' in saved_on:
                                posts_data.append({
                                    'href': saved_on['href'],
                                    'timestamp': saved_on.get('timestamp', ''),
                                    'owner': item.get('title', 'unknown')
                                })
                        except Exception as e:
                            logger.debug(f"Skipped malformed nested entry: {e}")
                            continue
                else:
                    # Try common keys for flat format
                    for key in ['saved_posts', 'saved', 'items', 'data']:
                        if key in data:
                            posts_data = data[key]
                            break
            
            if not posts_data:
                QMessageBox.warning(
                    self,
                    "Unsupported Format",
                    "Could not find saved posts in this file.\n\n"
                    "Please make sure you selected the 'saved_posts.json' "
                    "file from your Instagram export."
                )
                return
            
            # Clear existing table
            self.posts_table.setRowCount(0)
            self.saved_posts = []
            self.filtered_posts = []
            self.browse_status.setText("Importing posts...")
            
            # Import each post
            imported = 0
            for item in posts_data:
                try:
                    # Parse Instagram export format (varies by version)
                    post = {}
                    
                    # Extract shortcode (required)
                    if 'href' in item:
                        # Extract shortcode from URL like "https://www.instagram.com/p/ABC123/" or "/reel/ABC123/"
                        url = item['href']
                        parts = url.strip('/').split('/')
                        # Handle both /p/ (posts) and /reel/ (reels) URLs
                        if 'p' in parts:
                            shortcode_with_params = parts[parts.index('p') + 1]
                            # Remove query parameters (everything after ?)
                            post['shortcode'] = shortcode_with_params.split('?')[0]
                        elif 'reel' in parts:
                            shortcode_with_params = parts[parts.index('reel') + 1]
                            # Remove query parameters (everything after ?)
                            post['shortcode'] = shortcode_with_params.split('?')[0]
                        else:
                            continue
                    elif 'code' in item:
                        post['shortcode'] = item['code']
                    elif 'shortcode' in item:
                        post['shortcode'] = item['shortcode']
                    else:
                        continue  # Skip if no shortcode
                    
                    # Build post object
                    # Detect if it's a reel from URL
                    url = item.get('href', '')
                    if 'reel' in url:
                        post['url'] = f"https://www.instagram.com/reel/{post['shortcode']}/"
                        post['typename'] = 'GraphVideo'
                        post['is_video'] = True
                    else:
                        post['url'] = f"https://www.instagram.com/p/{post['shortcode']}/"
                        post['typename'] = item.get('media_type', 'GraphImage')  # Default to image
                        post['is_video'] = 'video' in item.get('media_type', '').lower()
                    
                    post['owner_username'] = item.get('owner', item.get('username', 'unknown'))
                    post['caption'] = item.get('caption', item.get('title', ''))
                    post['date'] = item.get('timestamp', item.get('taken_at', ''))
                    post['likes'] = None
                    post['comments'] = None
                    post['video_url'] = None
                    post['media_count'] = 1
                    post['thumbnail_url'] = None
                    
                    self.add_post_to_list(post)
                    imported += 1
                    
                except Exception as e:
                    logger.debug(f"Skipped malformed entry: {e}")
                    continue
            
            # Update filtered posts after all imports
            self.filtered_posts = self.saved_posts.copy()
            
            self.browse_status.setText(f"Imported {imported} posts from export file")
            self.statusBar().showMessage(f"Imported {imported} posts")
            
            QMessageBox.information(
                self,
                "Import Complete",
                f"Successfully imported {imported} saved posts!\n\n"
                f"You can now select and download them."
            )
            
        except json.JSONDecodeError:
            QMessageBox.critical(
                self,
                "Invalid File",
                "This is not a valid JSON file."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Failed to import posts:\n\n{str(e)}"
            )
    
    def add_url(self):
        """Add a single Instagram post URL to the list"""
        url = self.url_input.text().strip()
        if not url:
            return
        
        try:
            shortcode = None
            url = url.strip('/')
            parts = url.split('/')
            
            if 'p' in parts:
                idx = parts.index('p')
                if idx + 1 < len(parts):
                    shortcode = parts[idx + 1].split('?')[0]
            elif 'reel' in parts:
                idx = parts.index('reel')
                if idx + 1 < len(parts):
                    shortcode = parts[idx + 1].split('?')[0]
            elif 'instagram.com' not in url.lower() and len(url) > 5:
                shortcode = url.split('?')[0]
            
            if not shortcode:
                QMessageBox.warning(self, "Invalid URL", "Could not extract shortcode")
                return
            
            for post in self.saved_posts:
                if post.get('shortcode') == shortcode:
                    QMessageBox.information(self, "Already Added", f"{shortcode} already in list")
                    self.url_input.clear()
                    return
            
            # Detect if it's a reel from URL
            if 'reel' in parts:
                post = {'shortcode': shortcode, 'url': f"https://www.instagram.com/reel/{shortcode}/",
                       'owner_username': 'unknown', 'caption': f'URL: {shortcode}',
                       'typename': 'GraphVideo', 'is_video': True, 'date': '',
                       'likes': None, 'comments': None, 'video_url': None,
                       'media_count': 1, 'thumbnail_url': None, 'row_number': 0}
            else:
                post = {'shortcode': shortcode, 'url': f"https://www.instagram.com/p/{shortcode}/",
                       'owner_username': 'unknown', 'caption': f'URL: {shortcode}',
                       'typename': 'GraphImage', 'is_video': False, 'date': '',
                       'likes': None, 'comments': None, 'video_url': None,
                       'media_count': 1, 'thumbnail_url': None, 'row_number': 0}
            
            self.add_post_to_list(post)
            self.filtered_posts = self.saved_posts.copy()  # Update filtered list for single add
            self.browse_status.setText(f"Added {shortcode}")
            self.url_input.clear()
            
            # Jump to the page where the newly added item appears
            if self.total_items > 0 and self.current_view_mode == 'tiles':
                # Calculate which page the new item is on (last item)
                last_item_index = self.total_items - 1
                target_page = last_item_index // self.tiles_per_page
                logger.info(f"Jumping to page {target_page + 1} to show newly added item {shortcode}")
                self.jump_to_page(target_page + 1)  # jump_to_page expects 1-indexed
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed: {str(e)}")
    
    def filter_posts(self, text):
        """Filter posts table/tiles by search text"""
        # If text looks like an Instagram URL, extract the shortcode
        search_text = text
        if text.strip():
            try:
                url_text = text.strip().strip('/')
                parts = url_text.split('/')
                
                # Check if it's an Instagram URL with /p/ or /reel/
                if 'p' in parts:
                    idx = parts.index('p')
                    if idx + 1 < len(parts):
                        # Extract shortcode from URL
                        search_text = parts[idx + 1].split('?')[0]
                elif 'reel' in parts:
                    idx = parts.index('reel')
                    if idx + 1 < len(parts):
                        # Extract shortcode from URL
                        search_text = parts[idx + 1].split('?')[0]
            except:
                # If extraction fails, just use original text
                search_text = text
        
        # Filter table view
        for row in range(self.posts_table.rowCount()):
            # Check if text matches account, caption, or shortcode (Column 2=Shortcode, 3=Account, 4=Caption)
            shortcode = self.posts_table.item(row, 2).text().replace('✓ ', '')  # Remove duplicate marker
            account = self.posts_table.item(row, 3).text()
            caption = self.posts_table.item(row, 4).text()
            
            match = (search_text.lower() in shortcode.lower() or
                    search_text.lower() in account.lower() or 
                    search_text.lower() in caption.lower())
            
            self.posts_table.setRowHidden(row, not match)
        
        # Filter tile view
        if search_text.strip():
            self.filtered_posts = [
                post for post in self.saved_posts
                if search_text.lower() in post.get('shortcode', '').lower() or
                   search_text.lower() in post.get('owner_username', '').lower() or
                   search_text.lower() in post.get('caption', '').lower()
            ]
        else:
            self.filtered_posts = self.saved_posts.copy()
        
        # Refresh tiles if in tile view
        if self.current_view_mode == 'tiles':
            self.current_page = 0
            self.last_displayed_page = -1  # Force full rebuild on filter change
            self.populate_tiles()
    
    def toggle_auto_load(self, state):
        """Toggle auto-load at startup setting"""
        self.auto_load_at_startup = (state == Qt.Checked)
        self.account_manager.set_setting('auto_load_at_startup', 'true' if self.auto_load_at_startup else 'false')
        logger.info(f"Auto-load at startup: {self.auto_load_at_startup}")
    
    def toggle_stop_at_duplicate(self, state):
        """Toggle stop at first duplicate setting"""
        self.stop_at_first_duplicate = (state == Qt.Checked)
        self.account_manager.set_setting('stop_at_first_duplicate', 'true' if self.stop_at_first_duplicate else 'false')
        logger.info(f"Stop at first duplicate: {self.stop_at_first_duplicate}")
    
    def toggle_use_system_player(self, state):
        """Toggle use system video player setting"""
        self.force_system_player = (state == Qt.Checked)
        self.account_manager.set_setting('force_system_player', 'true' if self.force_system_player else 'false')
        if self.force_system_player:
            logger.info("Force system player enabled - will skip VLC and Qt players")
        else:
            logger.info("Built-in players enabled - will try VLC/Qt before system player")
    
    def apply_sort_and_filter(self):
        """Apply current sort and filter settings to the view"""
        if not hasattr(self, 'sort_by_combo'):
            return  # UI not initialized yet
        
        # Get current settings
        self.current_sort_by = self.sort_by_combo.currentText()
        self.current_sort_direction = self.sort_direction_combo.currentText()
        self.current_filter = self.filter_combo.currentText()
        self.current_topic_filter = self.topic_filter_combo.currentData() or 'All Topics'
        self.current_topic_filter_display = self.topic_filter_combo.currentText()

        # Refresh the topic dropdown to match the active filter mode.
        specific_topic_mode = self.current_filter == 'Specific Topic-Undownloaded'
        self.topic_filter_combo.setEnabled(specific_topic_mode)
        self.update_topic_filter_dropdown(specific_topic_mode)
        self.current_topic_filter = self.topic_filter_combo.currentData() or 'All Topics'
        self.current_topic_filter_display = self.topic_filter_combo.currentText()
        
        logger.info(f"=" * 60)
        logger.info(f"APPLY SORT AND FILTER")
        logger.info(f"  sort_by: {self.current_sort_by}")
        logger.info(f"  direction: {self.current_sort_direction}")
        logger.info(f"  filter: {self.current_filter}")
        logger.info(f"  topic: {self.current_topic_filter}")
        logger.info(f"=" * 60)
        
        # Show hourglass cursor for filter operation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        try:
            # Clear page cache since sorting/filtering changes the data
            self.page_cache.clear()
            self.current_page = 0
            self.last_displayed_page = -1
            logger.info("Cleared page cache and reset to page 0")
            
            # Get new total count with filter applied
            if self.content_db and self.content_db.db:
                # Map filter UI to filter type
                filter_type = None
                if self.current_filter == 'Only Ignored (Black) Items':
                    filter_type = 'ignored'
                elif self.current_filter == 'Only Uncategorized':
                    filter_type = 'uncategorized'
                elif self.current_filter == 'Only Categorized & Undownloaded':
                    filter_type = 'categorized_undownloaded'
                elif self.current_filter == 'Only Error Items':
                    filter_type = 'error'
                elif self.current_filter == 'Specific Topic-Undownloaded':
                    filter_type = 'specific_topic_undownloaded'
                
                # Only apply topic criteria for the specific-topic filter mode.
                topic_name = None
                if self.current_filter == 'Specific Topic-Undownloaded':
                    topic_name = None if self.current_topic_filter == 'All Topics' else self.current_topic_filter
                
                logger.info(f"Getting filtered count (filter_type={filter_type}, topic={topic_name})")
                
                # Get filtered count
                filtered_count = self.content_db.db.get_content_count(
                    filters=None,
                    filter_type=filter_type,
                    topic_filter=topic_name
                )
                
                self.total_items = filtered_count
                logger.info(f"Filtered total count: {filtered_count}")
                
                # Update pagination controls
                total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
                self.current_page_spin.setMaximum(max(1, total_pages))
                self.current_page_spin.setValue(1)  # Reset to page 1
                self.page_label.setText(f"/ {total_pages}")
                logger.info(f"Updated pagination: {total_pages} total pages")
                
                # Update status
                self.browse_status.setText(f"Showing {filtered_count} items (filtered)")
                
                # Reload first page with new filter
                logger.info("Loading page 0 with new sort/filter")
                self.load_page(0)
                self.preload_adjacent_pages(0)
                
                # Update the view
                if self.current_view_mode == 'tiles':
                    logger.info("Populating tiles with new data")
                    self.populate_tiles()
            else:
                logger.warning("content_db not available")
        except Exception as e:
            logger.error(f"Error in apply_sort_and_filter: {e}", exc_info=True)
        finally:
            QApplication.restoreOverrideCursor()
            logger.info("=" * 60)
    
    def update_topic_filter_dropdown(self, specific_undownloaded_only=False):
        """Update the topic filter dropdown with current topics"""
        if not hasattr(self, 'topic_filter_combo'):
            return  # UI not initialized yet
        
        current_selection = self.topic_filter_combo.currentData()
        
        # Block signals while updating
        self.topic_filter_combo.blockSignals(True)
        self.topic_filter_combo.clear()
        
        try:
            if self.content_db and self.content_db.db:
                if specific_undownloaded_only:
                    topics = self.content_db.db.get_topics_with_undownloaded_counts()
                    for topic in topics:
                        topic_name = topic.get('topic_name', '')
                        count = topic.get('undownloaded_count', 0)
                        if topic_name and count > 0:
                            self.topic_filter_combo.addItem(f"{topic_name} ({count})", topic_name)

                    if self.topic_filter_combo.count() == 0:
                        self.topic_filter_combo.addItem("No Topics With Undownloaded Items", '__NO_TOPICS__')
                    else:
                        index = self.topic_filter_combo.findData(current_selection)
                        if index < 0:
                            index = 0
                        self.topic_filter_combo.setCurrentIndex(index)
                else:
                    self.topic_filter_combo.addItem("All Topics", None)
                    topics = self.content_db.db.get_all_topics()
                    for topic in topics:
                        topic_name = topic.get('topic_name', '')
                        if topic_name:
                            self.topic_filter_combo.addItem(topic_name, topic_name)

                    index = self.topic_filter_combo.findData(current_selection)
                    if index >= 0:
                        self.topic_filter_combo.setCurrentIndex(index)
            else:
                self.topic_filter_combo.addItem("All Topics", None)
        except Exception as e:
            logger.error(f"Error loading topics for filter: {e}")
            self.topic_filter_combo.addItem("All Topics", None)
        
        self.topic_filter_combo.blockSignals(False)
    
    def download_thumbnail_async(self, shortcode, post, process_id=None, force_redownload=False):
        """Download thumbnail in background thread
        
        Args:
            shortcode: Content shortcode
            post: Post data dict
            process_id: Optional process ID for tracking (if None, no process tracking)
            force_redownload: If True, overwrite/remove existing thumbnail before download
        """
        import os
        from pathlib import Path
        from threading import current_thread
        
        # Update process status if tracking
        if process_id:
            self.process_manager.update_process(process_id, status='running', current=0, total=1)
        
        # Check if thumbnails are stopped
        if self.stop_thumbnail_downloads:
            logger.debug(f"Thumbnail download stopped for {shortcode}")
            if process_id:
                self.process_manager.update_process(process_id, status='cancelled')
                self.process_manager.remove_process(process_id)
            # Remove this thread from tracking
            try:
                self.thumbnail_threads.remove(current_thread())
            except ValueError:
                pass
            return
        
        if not self.instagram_manager or not self.content_db:
            if process_id:
                self.process_manager.update_process(process_id, status='failed')
                self.process_manager.remove_process(process_id)
            # Remove this thread from tracking
            try:
                self.thumbnail_threads.remove(current_thread())
            except ValueError:
                pass
            return
        
        # Strip any prefix markers (✓, etc.)
        clean_shortcode = shortcode.replace('✓ ', '').strip()
        
        # Use thumbnails_path from account if available, otherwise calculate default
        if hasattr(self, 'thumbnails_path') and self.thumbnails_path:
            thumbnails_dir = Path(self.thumbnails_path)
        else:
            # Fallback: Calculate based on download path and current username
            account_name = self.current_username if self.current_username else "unknown"
            download_path_text = self.download_path_input.text().strip()
            
            # CRITICAL: Check if download path is blank
            if not download_path_text:
                error_msg = f"Cannot fetch thumbnail: Download path is blank!\n\nShortcode: {clean_shortcode}"
                logger.error(f"⚠️⚠️⚠️ CRITICAL: {error_msg}")
                QMessageBox.critical(
                    self,
                    "Download Path Not Set",
                    error_msg + "\n\nPlease set a download path in the Settings tab."
                )
                if process_id:
                    self.process_manager.update_process(process_id, status='failed')
                    self.process_manager.remove_process(process_id)
                try:
                    self.thumbnail_threads.remove(current_thread())
                except ValueError:
                    pass
                return
            
            account_dir = Path(download_path_text)
            thumbnails_dir = account_dir / ".thumbnails"
        
        # Create thumbnails directory
        thumbnails_dir.mkdir(parents=True, exist_ok=True)
        
        # Thumbnail filename
        thumbnail_filename = f"{clean_shortcode}.jpg"
        thumbnail_path = thumbnails_dir / thumbnail_filename
        
        # If force re-download, remove any old DB/file state first
        if force_redownload:
            try:
                existing_thumbnail = self.content_db.db.get_thumbnail(clean_shortcode)
                if existing_thumbnail:
                    old_path = existing_thumbnail.get('file_path')
                    if old_path and os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except OSError as e:
                            logger.debug(f"Could not remove old thumbnail file {old_path}: {e}")
                    self.content_db.db.delete_thumbnail(clean_shortcode)
                
                # Also remove standard thumbnail file location if present
                if thumbnail_path.exists():
                    try:
                        thumbnail_path.unlink()
                    except OSError as e:
                        logger.debug(f"Could not remove thumbnail file {thumbnail_path}: {e}")
                
                # Clear in-memory cache so UI won't reuse stale pixmap
                self.thumbnail_cache.pop(clean_shortcode, None)
            except Exception as e:
                logger.warning(f"Failed preparing force thumbnail re-download for {clean_shortcode}: {e}")
        
        # Skip if already exists
        if thumbnail_path.exists() and not force_redownload:
            logger.debug(f"Thumbnail already exists: {thumbnail_path}")
            if process_id:
                self.process_manager.update_process(process_id, status='completed', current=1, total=1)
                # Auto-remove after brief delay
                QTimer.singleShot(2000, lambda: self.process_manager.remove_process(process_id))
            return
        
        # Download thumbnail
        try:
            success, dimensions = self.instagram_manager.download_thumbnail(clean_shortcode, thumbnail_path)
            
            if success and dimensions:
                width, height = dimensions
                file_size = thumbnail_path.stat().st_size
                
                # Save to database (use clean shortcode for database)
                self.content_db.db.add_thumbnail(
                    content_id=clean_shortcode,
                    file_name=thumbnail_filename,
                    file_path=str(thumbnail_path),
                    file_size_bytes=file_size,
                    width=width,
                    height=height
                )
                
                logger.info(f"Thumbnail downloaded and saved: {clean_shortcode}")
                
                # Update process status
                if process_id:
                    self.process_manager.update_process(process_id, status='completed', current=1, total=1)
                    # Auto-remove after brief delay
                    QTimer.singleShot(2000, lambda: self.process_manager.remove_process(process_id))
                
                # Load and cache the pixmap (use clean shortcode for cache key)
                from PyQt5.QtGui import QPixmap
                pixmap = QPixmap(str(thumbnail_path))
                if not pixmap.isNull():
                    self.thumbnail_cache[clean_shortcode] = pixmap
                    
                    # Schedule UI update on main thread (thread-safe)
                    QMetaObject.invokeMethod(self, "_update_thumbnail_widget_on_main_thread",
                                           Qt.QueuedConnection,
                                           Q_ARG(str, clean_shortcode))
            else:
                # Download failed
                if process_id:
                    self.process_manager.update_process(process_id, status='failed')
                    QTimer.singleShot(5000, lambda: self.process_manager.remove_process(process_id))
        except Exception as e:
            logger.error(f"Failed to download thumbnail for {clean_shortcode}: {e}")
            if process_id:
                self.process_manager.update_process(process_id, status='failed')
                QTimer.singleShot(5000, lambda: self.process_manager.remove_process(process_id))
        finally:
            # Remove this thread from tracking when complete
            from threading import current_thread
            try:
                self.thumbnail_threads.remove(current_thread())
            except ValueError:
                pass
            
            # Hide stop button if no more active threads
            if not self.thumbnail_threads:
                QMetaObject.invokeMethod(self, "_hide_stop_thumbnails_btn",
                                       Qt.QueuedConnection)
    
    @pyqtSlot(str)
    def _update_thumbnail_widget_on_main_thread(self, clean_shortcode: str):
        """Update thumbnail widget on main thread (called via QMetaObject.invokeMethod)"""
        try:
            # Update the thumbnail widget in the table
            for row in range(self.posts_table.rowCount()):
                shortcode_item = self.posts_table.item(row, 2)
                if shortcode_item and shortcode_item.text().replace('✓ ', '') == clean_shortcode:
                    # Get post data from the table
                    caption_item = self.posts_table.item(row, 4)
                    if caption_item:
                        post = caption_item.data(Qt.UserRole)
                        if post:
                            thumbnail_label = self.create_thumbnail_widget(clean_shortcode, post)
                            self.posts_table.setCellWidget(row, 0, thumbnail_label)
                    break
            
            # Refresh tile in tile view; update_tile_appearance will rebuild only when needed.
            if self.current_view_mode == 'tiles':
                self.refresh_single_item(clean_shortcode)
        except Exception as e:
            logger.error(f"Failed to update thumbnail widget for {clean_shortcode}: {e}")
    
    @pyqtSlot()
    def _hide_stop_thumbnails_btn(self):
        """Hide the stop thumbnails button when all threads complete (called on main thread)"""
        self.stop_thumbnails_btn.setVisible(False)
    
    def toggle_thumbnail_downloads(self):
        """Toggle thumbnail downloads on/off"""
        self.stop_thumbnail_downloads = not self.stop_thumbnail_downloads
        
        if self.stop_thumbnail_downloads:
            # Stopping thumbnails
            self.stop_thumbnails_btn.setText("▶️ Resume Thumbnails")
            self.stop_thumbnails_btn.setStyleSheet("background-color: #ccffcc;")
            self.stop_thumbnails_btn.setToolTip("Resume background thumbnail downloads")
            logger.info("Thumbnail downloads stopped by user")
            self.browse_status.setText("Thumbnail downloads paused")
        else:
            # Resuming thumbnails
            self.stop_thumbnails_btn.setText("⏸️ Stop Thumbnails")
            self.stop_thumbnails_btn.setStyleSheet("background-color: #ffcccc;")
            self.stop_thumbnails_btn.setToolTip("Stop background thumbnail downloads")
            logger.info("Thumbnail downloads resumed by user")
            self.browse_status.setText("Thumbnail downloads resumed")
    
    def get_thumbnail_size(self):
        """Get thumbnail size based on current tile_size setting"""
        sizes = {'small': 50, 'medium': 70, 'large': 100, 'xlarge': 140}
        return sizes[self.tile_size]
    
    def refresh_table_thumbnails(self):
        """Refresh all thumbnails in the table with new size"""
        thumb_size = self.get_thumbnail_size()
        
        # Update all thumbnail widgets in the table
        for row in range(self.posts_table.rowCount()):
            # Get existing widget
            widget = self.posts_table.cellWidget(row, 0)
            if widget:
                # Find the label inside the widget
                label = widget.findChild(QLabel)
                if label:
                    label.setMaximumSize(thumb_size, thumb_size)
                    label.setMinimumSize(thumb_size, thumb_size)
                    
                    # Re-scale cached pixmap if exists
                    caption_item = self.posts_table.item(row, 4)
                    if caption_item:
                        post = caption_item.data(Qt.UserRole)
                        if post:
                            shortcode = post.get('shortcode', '')
                            if shortcode in self.thumbnail_cache:
                                pixmap = self.thumbnail_cache[shortcode]
                                if not pixmap.isNull():
                                    label.setPixmap(pixmap.scaled(
                                        thumb_size, thumb_size, 
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation
                                    ))
    
    def create_thumbnail_widget(self, shortcode, post):
        """Create thumbnail widget with image or placeholder (cached and clickable)"""
        from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget
        from PyQt5.QtGui import QPixmap, QCursor
        from PyQt5.QtCore import Qt
        import os
        
        # Create container widget
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        thumb_size = self.get_thumbnail_size()
        
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("border: 1px solid #ccc;")
        label.setScaledContents(True)
        label.setMaximumSize(thumb_size, thumb_size)
        label.setMinimumSize(thumb_size, thumb_size)
        
        # Check cache first
        if shortcode in self.thumbnail_cache:
            pixmap = self.thumbnail_cache[shortcode]
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(label)
                return container
        
        # Try to load thumbnail from database
        has_thumbnail = False
        if self.content_db and self.content_db.db:
            thumbnail = self.content_db.db.get_thumbnail(shortcode)
            logger.info(f"Thumbnail lookup for {shortcode}: {thumbnail is not None}")
            if thumbnail:
                logger.info(f"  Path: {thumbnail.get('file_path')}")
                logger.info(f"  Exists: {os.path.exists(thumbnail['file_path'])}")
            if thumbnail and os.path.exists(thumbnail['file_path']):
                pixmap = QPixmap(thumbnail['file_path'])
                logger.info(f"  QPixmap null: {pixmap.isNull()}, size: {pixmap.width()}x{pixmap.height()}")
                if not pixmap.isNull():
                    # Cache the pixmap
                    self.thumbnail_cache[shortcode] = pixmap
                    label.setPixmap(pixmap.scaled(thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    has_thumbnail = True
        else:
            logger.warning(f"content_db not ready when creating thumbnail for {shortcode}")
        
        # No thumbnail yet - show clickable placeholder
        if not has_thumbnail:
            typename = post.get('typename', '')
            if typename == "GraphImage":
                label.setText("📄")
            elif typename == "GraphVideo":
                label.setText("🎥")
            else:
                label.setText("📸")
            label.setStyleSheet("border: 1px solid #ccc; font-size: 24px;")
            label.setCursor(QCursor(Qt.PointingHandCursor))
            label.setToolTip("Click to download thumbnail")
            
            # Make clickable
            label.mousePressEvent = lambda event: self.download_single_thumbnail(shortcode, post)
        
        layout.addWidget(label)
        return container
    
    def download_single_thumbnail(self, shortcode, post):
        """Download thumbnail for a single post (triggered by clicking placeholder)"""
        from threading import Thread
        
        logger.info(f"Manual thumbnail download requested for {shortcode}")
        
        # Create process entry for individual thumbnail download
        process_id = self.process_manager.add_process(
            'thumbnail_single',
            f'Thumbnail: {shortcode}',
            None
        )
        
        # Start download in background with process tracking
        thumbnail_thread = Thread(target=self.download_thumbnail_async, args=(shortcode, post, process_id), daemon=True)
        self.thumbnail_threads.append(thumbnail_thread)
        thumbnail_thread.start()
        
        # Show stop button if thumbnails are downloading
        if self.thumbnail_threads and not self.stop_thumbnail_downloads:
            self.stop_thumbnails_btn.setVisible(True)
    
    def download_missing_thumbnails_bulk(self):
        """Download thumbnails for all posts that don't have one"""
        from threading import Thread
        import time
        import os
        from PyQt5.QtGui import QPixmap
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        def has_usable_thumbnail(shortcode):
            """Return True only when thumbnail exists and can be loaded as a valid image."""
            # Cached pixmap is already validated at load time
            cached = self.thumbnail_cache.get(shortcode)
            if cached is not None and not cached.isNull():
                return True
            
            thumbnail = self.content_db.db.get_thumbnail(shortcode)
            if not thumbnail:
                return False
            
            thumb_path = thumbnail.get('file_path')
            if not thumb_path or not os.path.exists(thumb_path):
                return False
            
            try:
                if os.path.getsize(thumb_path) <= 0:
                    return False
            except OSError:
                return False
            
            test_pixmap = QPixmap(thumb_path)
            return not test_pixmap.isNull()
        
        # Build candidate posts from current data source.
        # In tiles-only mode, table rows may be empty, so prefer current page cache.
        candidate_posts = {}
        if self.current_view_mode == 'tiles' and self.current_page in self.page_cache:
            for post in self.page_cache[self.current_page]:
                shortcode = (post.get('shortcode') or '').strip()
                if shortcode:
                    candidate_posts[shortcode] = post
        
        # Fallback to table rows when cache is unavailable
        if not candidate_posts:
            for row in range(self.posts_table.rowCount()):
                shortcode_item = self.posts_table.item(row, 2)
                if not shortcode_item:
                    continue
                shortcode = shortcode_item.text().replace('✓ ', '').strip()
                if not shortcode:
                    continue
                caption_item = self.posts_table.item(row, 4)
                post = caption_item.data(Qt.UserRole) if caption_item else None
                if post:
                    candidate_posts[shortcode] = post
        
        # Last fallback for backward compatibility
        if not candidate_posts:
            for post in self.saved_posts:
                shortcode = (post.get('shortcode') or '').strip()
                if shortcode:
                    candidate_posts[shortcode] = post
        
        # Count posts without usable thumbnails
        posts_to_download = []
        for shortcode, post in candidate_posts.items():
            if not has_usable_thumbnail(shortcode):
                posts_to_download.append((shortcode, post))
        
        missing_count = len(posts_to_download)
        logger.info(f"[THUMBNAIL_BULK] candidates={len(candidate_posts)}, missing={missing_count}, page={self.current_page + 1}")
        
        if missing_count == 0:
            QMessageBox.information(
                self,
                "All Thumbnails Present",
                "No missing/corrupt thumbnails were found in the current dataset."
            )
            return
        
        # Confirm bulk download
        reply = QMessageBox.question(
            self, "Bulk Thumbnail Download",
            f"Download thumbnails for {missing_count} posts?\\n\\n"
            f"This will download preview images from Instagram.\\n"
            f"Downloads will happen in the background.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'thumbnail_bulk',
            f'Thumbnail Download ({missing_count} items)',
            None
        )
        
        # Download in background with rate limiting
        def bulk_download():
            logger.info(f"Starting bulk thumbnail download for {len(posts_to_download)} posts")
            self.process_manager.update_process(process_id, total=len(posts_to_download))
            
            for i, (shortcode, post) in enumerate(posts_to_download):
                try:
                    self.download_thumbnail_async(shortcode, post)
                    # Update progress
                    self.process_manager.update_process(process_id, current=i+1)
                    # Rate limit: 1 thumbnail per second to avoid hammering Instagram
                    if i < len(posts_to_download) - 1:
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Bulk download error for {shortcode}: {e}")
            
            logger.info(f"Bulk thumbnail download complete: {len(posts_to_download)} thumbnails")
            self.process_manager.update_process(process_id, status='completed')
            
            try:
                self.statusBar().showMessage(f"Downloaded {len(posts_to_download)} thumbnails", 5000)
            except RuntimeError:
                pass  # GUI was closed while thread was running
        
        # Start bulk download thread
        bulk_thread = Thread(target=bulk_download, daemon=True)
        bulk_thread.start()
        
        self.statusBar().showMessage(f"Downloading {missing_count} thumbnails in background...", 3000)
    
    def redownload_thumbnails_for_current_page(self):
        """Force re-download thumbnails for every post on the current page."""
        from threading import Thread
        import time
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        if self.current_page not in self.page_cache:
            QMessageBox.warning(self, "No Page Loaded", "Current page is not loaded yet.")
            return
        
        page_posts = self.page_cache.get(self.current_page, [])
        if not page_posts:
            QMessageBox.information(self, "No Posts", "Current page has no posts.")
            return
        
        posts_to_download = []
        for post in page_posts:
            shortcode = (post.get('shortcode') or '').strip()
            if shortcode:
                posts_to_download.append((shortcode, post))
        
        if not posts_to_download:
            QMessageBox.information(self, "No Valid Posts", "No valid shortcodes found on current page.")
            return
        
        reply = QMessageBox.question(
            self,
            "Redownload Thumbnails for this Page",
            f"Force re-download thumbnails for all {len(posts_to_download)} items on page {self.current_page + 1}?\n\n"
            f"This replaces existing thumbnail files/records and refreshes tile previews.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        process_id = self.process_manager.add_process(
            'thumbnail_redownload_page',
            f'Thumbnail Re-download (Page {self.current_page + 1}, {len(posts_to_download)} items)',
            None
        )
        
        # If thumbnail downloads are paused, resume automatically for this explicit action
        if self.stop_thumbnail_downloads:
            self.stop_thumbnail_downloads = False
            self.stop_thumbnails_btn.setText("⏸️ Stop Thumbnails")
            self.stop_thumbnails_btn.setStyleSheet("background-color: #ffcccc;")
            self.stop_thumbnails_btn.setToolTip("Stop background thumbnail downloads")
        self.stop_thumbnails_btn.setVisible(True)
        
        def redownload_worker():
            logger.info(f"[THUMBNAIL_REDOWNLOAD_PAGE] Starting page {self.current_page + 1} for {len(posts_to_download)} posts")
            self.process_manager.update_process(process_id, status='running', current=0, total=len(posts_to_download))
            
            completed = 0
            for i, (shortcode, post) in enumerate(posts_to_download):
                try:
                    self.download_thumbnail_async(shortcode, post, force_redownload=True)
                    completed += 1
                except Exception as e:
                    logger.error(f"Error re-downloading thumbnail for {shortcode}: {e}")
                finally:
                    self.process_manager.update_process(process_id, current=i + 1, total=len(posts_to_download))
                
                # Rate limit requests to avoid hammering Instagram
                if i < len(posts_to_download) - 1:
                    time.sleep(0.5)
            
            self.process_manager.update_process(process_id, status='completed', current=len(posts_to_download), total=len(posts_to_download))
            QTimer.singleShot(3000, lambda: self.process_manager.remove_process(process_id))
            
            try:
                self.statusBar().showMessage(
                    f"Re-downloaded thumbnails for page {self.current_page + 1}: {completed}/{len(posts_to_download)}",
                    5000
                )
            except RuntimeError:
                pass
            
            logger.info(f"[THUMBNAIL_REDOWNLOAD_PAGE] Completed page {self.current_page + 1}: {completed}/{len(posts_to_download)}")
        
        worker_thread = Thread(target=redownload_worker, daemon=True)
        self.thumbnail_threads.append(worker_thread)
        worker_thread.start()
        
        self.statusBar().showMessage(
            f"Re-downloading thumbnails for page {self.current_page + 1} ({len(posts_to_download)} items)...",
            3000
        )
    
    def show_post_details(self, item):
        """Show detailed information about the selected post"""
        try:
            row = item.row()
            shortcode_item = self.posts_table.item(row, 2)  # Column 2 now has shortcode
            if not shortcode_item:
                return
            
            shortcode = shortcode_item.text().replace('✓ ', '')
            
            # Get post details from database
            if not self.content_db:
                self.details_panel.setPlainText("No database connection")
                return
            
            entry = self.content_db.db.get_content_entry(shortcode)
            if not entry:
                self.details_panel.setPlainText(f"No details found for {shortcode}")
                self.current_entry = None
                self.copy_caption_btn.setEnabled(False)
                self.edit_notes_btn.setEnabled(False)
                return
            
            # Store entry for copy button
            self.current_entry = entry
            self.copy_caption_btn.setEnabled(True)
            self.edit_notes_btn.setEnabled(True)
            
            # Format details
            details = []
            details.append(f"═══ POST DETAILS: {shortcode} ═══\n")
            
            # Basic info
            details.append(f"URL: https://www.instagram.com/p/{shortcode}/")
            details.append(f"Account: {entry.get('account_name', 'Unknown')}")
            details.append(f"Type: {entry.get('typename', 'Unknown')}")
            details.append(f"Row Number: {entry.get('row_number', 'N/A')}")
            details.append(f"Status: {entry.get('download_status', 'Unknown')}")
            details.append("")
            
            # Caption
            caption = entry.get('text', '')
            if caption:
                details.append(f"Caption: {caption[:200]}{'...' if len(caption) > 200 else ''}")
                details.append("")
            
            # Tags (from validation_log)
            validation_log = entry.get('validation_log', '')
            if validation_log and validation_log.startswith('Tags: '):
                tags = validation_log.replace('Tags: ', '')
                details.append(f"Tags: {tags}")
                details.append("")
            
            # Files
            files_info = entry.get('FilesInformation', {})
            file_list = files_info.get('FileList', [])
            
            if file_list:
                details.append(f"Files ({len(file_list)}):")
                for i, file_info in enumerate(file_list, 1):
                    file_name = file_info.get('DownloadFilename', file_info.get('FileName', 'Unknown'))
                    file_type = file_info.get('FileType', 'unknown')
                    file_status = file_info.get('FileDownloadStatus', 'unknown')
                    file_path = file_info.get('FileDestinationPath', '')
                    file_caption = file_info.get('FileCaption', '')
                    file_tags = file_info.get('FileTags', '')
                    user_notes = file_info.get('UserNotes', '')
                    
                    details.append(f"  {i}. {file_name}")
                    details.append(f"     Type: {file_type} | Status: {file_status}")
                    if file_path:
                        details.append(f"     Path: {file_path}")
                    if file_caption:
                        details.append(f"     Caption: {file_caption[:100]}{'...' if len(file_caption) > 100 else ''}")
                    if file_tags:
                        details.append(f"     Tags: {file_tags}")
                    if user_notes:
                        details.append(f"     📝 Notes: {user_notes}")
                details.append("")
            else:
                details.append("No files downloaded yet")
                details.append("")
            
            # Metadata
            created = entry.get('created_at', '')
            if created:
                details.append(f"Added: {str(created)[:19]}")
            
            updated = entry.get('updated_at', '')
            if updated:
                details.append(f"Updated: {str(updated)[:19]}")
            
            self.details_panel.setPlainText('\n'.join(details))
            
        except Exception as e:
            logger.error(f"Error showing post details: {e}")
            self.details_panel.setPlainText(f"Error loading details: {str(e)}")
            self.current_entry = None
            self.copy_caption_btn.setEnabled(False)
            self.edit_notes_btn.setEnabled(False)
    
    def copy_console_text(self):
        """Copy all console text to clipboard"""
        try:
            console_text = self.log_console.toPlainText()
            if not console_text:
                QMessageBox.information(self, "Empty Console", "Console log is empty.")
                return
            
            clipboard = QApplication.clipboard()
            clipboard.setText(console_text)
            
            # Show confirmation in status bar
            self.statusBar().showMessage(f"Copied {len(console_text)} characters to clipboard", 3000)
            logger.info(f"Console text copied to clipboard: {len(console_text)} chars")
            
        except Exception as e:
            logger.error(f"Error copying console text: {e}")
            QMessageBox.warning(self, "Error", f"Failed to copy console text: {str(e)}")
    
    def copy_caption_to_clipboard(self):
        """Copy caption text (without tags) to clipboard"""
        try:
            if not self.current_entry:
                QMessageBox.warning(self, "No Caption", "No post selected or no caption available.")
                return
            
            # Get caption from entry
            caption = self.current_entry.get('text', '')
            
            if not caption:
                QMessageBox.information(self, "No Caption", "This post has no caption.")
                return
            
            # Remove tags (everything after #)
            # Find first hashtag position
            hashtag_pos = caption.find('#')
            if hashtag_pos > 0:
                # Only take the part before the first hashtag
                caption_without_tags = caption[:hashtag_pos].strip()
            else:
                # No hashtags, use full caption
                caption_without_tags = caption.strip()
            
            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(caption_without_tags)
            
            # Show confirmation
            self.browse_status.setText(f"Caption copied to clipboard ({len(caption_without_tags)} chars)")
            logger.info(f"Copied caption to clipboard: {len(caption_without_tags)} chars")
            
        except Exception as e:
            logger.error(f"Error copying caption: {e}")
            QMessageBox.warning(self, "Error", f"Failed to copy caption: {str(e)}")
    
    def edit_file_notes(self):
        """Open dialog to edit notes for each file in the current post"""
        try:
            if not self.current_entry:
                QMessageBox.warning(self, "No Post Selected", "Please select a post first.")
                return
            
            shortcode = self.current_entry.get('id', '')
            if not shortcode:
                QMessageBox.warning(self, "Error", "Could not determine post ID.")
                return
            
            # Get files from entry
            files_info = self.current_entry.get('FilesInformation', {})
            file_list = files_info.get('FileList', [])
            
            if not file_list:
                QMessageBox.information(self, "No Files", "This post has no files to add notes to.")
                return
            
            # Create dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Edit Notes - {shortcode}")
            dialog.setMinimumWidth(600)
            dialog.setMinimumHeight(400)
            
            layout = QVBoxLayout(dialog)
            
            # Instructions
            info_label = QLabel("Add notes for each file below. Notes are saved to the database.")
            info_label.setWordWrap(True)
            layout.addWidget(info_label)
            
            # Scroll area for file notes
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll_widget = QWidget()
            scroll_layout = QVBoxLayout(scroll_widget)
            
            # Store text edits for each file
            notes_editors = []
            
            for i, file_info in enumerate(file_list, 1):
                file_number = file_info.get('FileNumber', i)
                file_name = file_info.get('DownloadFilename', file_info.get('FileName', f'File {i}'))
                file_type = file_info.get('FileType', 'unknown')
                current_notes = file_info.get('UserNotes', '')
                
                # File label
                file_label = QLabel(f"<b>File {file_number}: {file_name}</b> ({file_type})")
                scroll_layout.addWidget(file_label)
                
                # Notes editor
                notes_edit = QTextEdit()
                notes_edit.setPlaceholderText(f"Enter notes for file {file_number}...")
                notes_edit.setText(current_notes)
                notes_edit.setMaximumHeight(100)
                scroll_layout.addWidget(notes_edit)
                
                # Store reference
                notes_editors.append({
                    'file_number': file_number,
                    'editor': notes_edit
                })
                
                # Spacer
                scroll_layout.addSpacing(10)
            
            scroll_layout.addStretch()
            scroll.setWidget(scroll_widget)
            layout.addWidget(scroll)
            
            # Buttons
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            
            save_btn = QPushButton("💾 Save")
            save_btn.clicked.connect(lambda: self.save_file_notes(shortcode, notes_editors, dialog))
            button_layout.addWidget(save_btn)
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            layout.addLayout(button_layout)
            
            dialog.exec_()
            
        except Exception as e:
            logger.error(f"Error opening notes editor: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open notes editor: {str(e)}")
    
    def save_file_notes(self, shortcode, notes_editors, dialog):
        """Save notes for all files in the post"""
        try:
            if not self.content_db:
                QMessageBox.warning(self, "Error", "No database connection.")
                return
            
            # Save notes for each file
            for notes_info in notes_editors:
                file_number = notes_info['file_number']
                notes_text = notes_info['editor'].toPlainText().strip()
                
                # Update in database
                self.content_db.db.update_file_user_notes(shortcode, file_number, notes_text)
            
            # Success message
            QMessageBox.information(self, "Notes Saved", f"Notes saved for {len(notes_editors)} file(s).")
            logger.info(f"Saved notes for {shortcode}, {len(notes_editors)} files")
            
            # Refresh the details panel to show updated notes
            self.current_entry = self.content_db.db.get_content_entry(shortcode)
            if self.current_entry:
                # Trigger details refresh by simulating a click on the current row
                current_row = self.posts_table.currentRow()
                if current_row >= 0:
                    item = self.posts_table.item(current_row, 0)
                    if item:
                        self.show_post_details(item)
            
            # Close dialog
            dialog.accept()
            
        except Exception as e:
            logger.error(f"Error saving notes: {e}")
            QMessageBox.warning(self, "Error", f"Failed to save notes: {str(e)}")
    
    def reset_post(self, shortcode):
        """Reset post to undownloaded state - deletes files and database records"""
        try:
            # Confirm with user
            reply = QMessageBox.question(
                self,
                "Confirm Reset",
                f"Reset post {shortcode} to undownloaded state?\n\n"
                f"This will:\n"
                f"• Delete all downloaded files from disk\n"
                f"• Remove file records from database\n"
                f"• Reset download status to 'awaiting scan'\n\n"
                f"This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
            
            if not self.content_db or not self.content_db.db:
                QMessageBox.warning(self, "Error", "No database connection")
                return
            
            # Get entry to find files
            entry = self.content_db.db.get_content_entry(shortcode)
            if not entry:
                QMessageBox.warning(self, "Error", f"Post {shortcode} not found in database")
                return
            
            deleted_files = []
            failed_deletes = []
            
            # Get files from entry's FilesInformation structure
            files_info = entry.get('FilesInformation', {})
            file_list = files_info.get('FileList', [])
            
            # Delete physical files from disk
            if file_list:
                for file_entry in file_list:
                    file_path = file_entry.get('FileDestinationPath', '')
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            deleted_files.append(os.path.basename(file_path))
                            logger.info(f"Deleted file: {file_path}")
                        except Exception as e:
                            failed_deletes.append(f"{os.path.basename(file_path)}: {str(e)}")
                            logger.error(f"Failed to delete file {file_path}: {e}")
            
            # Delete file records from database
            try:
                deleted_count = self.content_db.db.delete_files_for_entry(shortcode)
                logger.info(f"Deleted {deleted_count} file records from database for {shortcode}")
            except Exception as e:
                logger.error(f"Failed to delete file records: {e}")
                QMessageBox.warning(self, "Error", f"Failed to delete file records from database: {str(e)}")
                return
            
            # Reset download status
            try:
                success = self.content_db.db.update_content_entry(shortcode, {
                    'download_status': 'awaiting scan'
                })
                if not success:
                    raise Exception("Update returned False")
                logger.info(f"Reset download status for {shortcode}")
            except Exception as e:
                logger.error(f"Failed to reset download status: {e}")
                QMessageBox.warning(self, "Error", f"Failed to reset download status: {str(e)}")
                return
            
            # Show summary
            summary = f"Reset complete for {shortcode}\n\n"
            if deleted_files:
                summary += f"Deleted {len(deleted_files)} file(s):\n"
                for f in deleted_files[:5]:
                    summary += f"  • {f}\n"
                if len(deleted_files) > 5:
                    summary += f"  ... and {len(deleted_files) - 5} more\n"
            else:
                summary += "No files found on disk\n"
            
            summary += f"\nDeleted {deleted_count} database record(s)\n"
            summary += "Status reset to 'awaiting scan'"
            
            if failed_deletes:
                summary += f"\n\n⚠️ Failed to delete {len(failed_deletes)} file(s):\n"
                for f in failed_deletes[:3]:
                    summary += f"  • {f}\n"
            
            QMessageBox.information(self, "Reset Complete", summary)
            
            # Refresh the display by reloading saved posts
            self.load_saved_posts()
            
        except Exception as e:
            logger.error(f"Error resetting post {shortcode}: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to reset post:\n{str(e)}")
    
    def handle_duplicate_stop(self, shortcode):
        """Handle when fetching stops due to duplicate"""
        # Mark process as completed (stopped early)
        if hasattr(self, 'load_saved_process_id'):
            process = self.process_manager.get_process(self.load_saved_process_id)
            if process:
                total_fetched = process.get('current', 0)
                self.process_manager.update_process(
                    self.load_saved_process_id,
                    status='completed',
                    current=total_fetched,
                    total=total_fetched
                )
                # Remove after 3 seconds
                QTimer.singleShot(3000, lambda: self.process_manager.remove_process(self.load_saved_process_id))
        
        # Clear fetch tracking flag
        self.fetch_in_progress = False
        
        # Final pagination update after stopping early
        if self.posts_added_since_pagination_update > 0:
            self.update_pagination_controls()
            self.posts_added_since_pagination_update = 0
            logger.info(f"Final pagination update (stopped early): total_items={self.total_items}")
        
        # Restore cursor when fetching stops early
        QApplication.restoreOverrideCursor()
        
        logger.info(f"Stopped fetching at duplicate post: {shortcode}")
        self.browse_status.setText(f"Stopped at first existing post ({shortcode})")
        QMessageBox.information(
            self,
            "Fetch Stopped",
            f"Stopped fetching at first existing post.\n\n"
            f"Post: {shortcode}\n\n"
            f"All newer posts have been added to your database."
        )

    def show_auto_close_download_failed_dialog(self, shortcode, error_msg, timeout_ms=5000):
        """Show a non-blocking download error dialog that closes automatically."""
        if not hasattr(self, '_transient_dialogs'):
            self._transient_dialogs = []

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Critical)
        dialog.setWindowTitle("Download Failed")
        dialog.setText(f"Download failed for {shortcode}")
        dialog.setInformativeText(error_msg or "Unknown error")
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.setDefaultButton(QMessageBox.Ok)
        dialog.setWindowModality(Qt.NonModal)
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()

        # Keep a reference so the dialog and timer remain alive until closed.
        self._transient_dialogs.append(dialog)

        # Use a dialog-owned timer for reliable auto-close behavior.
        timer = QTimer(dialog)
        timer.setSingleShot(True)

        def _close_and_cleanup():
            try:
                if dialog.isVisible():
                    dialog.accept()
            finally:
                if dialog in self._transient_dialogs:
                    self._transient_dialogs.remove(dialog)

        timer.timeout.connect(_close_and_cleanup)
        timer.start(timeout_ms)
    
    def handle_download_complete(self, shortcode, success, file_path, error_msg, downloaded_files, metadata):
        """Handle individual download completion - update database and table"""
        # Save debug info if failed
        debug_file = None
        if not success and error_msg:
            debug_file = self.save_debug_info(shortcode, error_msg)
        
        # CRITICAL: If no files were downloaded, don't mark as completed
        actual_success = success and len(downloaded_files) > 0

        # Show non-blocking error dialog that auto-closes after 5 seconds.
        if not success:
            self.show_auto_close_download_failed_dialog(shortcode, error_msg, timeout_ms=5000)
        
        if success and not downloaded_files:
            warning_msg = (
                f"Download reported success for {shortcode} but NO FILES were created.\n"
                f"Marking as 'success_with_issues' - may already exist or be unavailable."
            )
            logger.warning(warning_msg)
        
        try:
            # Update database status
            if self.content_db:
                # Get the specific entry by shortcode (avoid loading all entries)
                entry = self.content_db.db.get_content_entry(shortcode)
                
                if entry:
                    # Determine status based on actual file creation
                    updates = {}
                    
                    if actual_success:
                        updates['download_status'] = 'completed'
                        
                        # Extract caption and tags from metadata
                        caption = ''
                        tags = ''
                        if metadata:
                            caption = metadata.get('caption', '')
                            tags = metadata.get('tags', '')
                            
                            if caption:
                                updates['text'] = caption
                                logger.info(f"Saved caption for {shortcode}: {caption[:50]}...")
                            
                            # Save tags to validation_log column
                            if tags:
                                updates['validation_log'] = f"Tags: {tags}"
                                logger.info(f"Saved tags for {shortcode}: {tags}")
                        
                        # Save file information to database (with caption and tags at file level)
                        for i, filename in enumerate(downloaded_files):
                            full_file_path = os.path.join(file_path, filename)
                            file_info = {
                                'FileNumber': i + 1,
                                'FileName': filename,
                                'DownloadFilename': filename,
                                'FileDestinationPath': full_file_path,
                                'FileDownloadStatus': 'completed',
                                'FileType': 'video' if filename.endswith('.mp4') else 'image',
                                'FileSaveStatus': 'completed',
                                'FileCaption': caption,  # Save caption at file level too
                                'FileTags': tags  # Save tags at file level too
                            }
                            
                            # Add file to database
                            try:
                                file_id = self.content_db.db.add_file(shortcode, file_info)
                                logger.info(f"Saved file {i+1}/{len(downloaded_files)} to database: {filename} (file_id: {file_id})")
                            except Exception as e:
                                logger.error(f"Error saving file to database: {e}")
                    
                    elif not success:
                        updates['download_status'] = 'failed'
                    else:
                        updates['download_status'] = 'success_with_issues'  # Success reported but no files created
                    
                    self.content_db.db.update_content_entry(shortcode, updates)
                    logger.info(f"Updated database status for {shortcode} to '{updates.get('download_status')}'")
                    
                    # Update page cache and tile appearance (for tile view)
                    new_status = updates.get('download_status')
                    if new_status:
                        # Update page cache for all pages containing this shortcode
                        # Create snapshot to prevent concurrent modification issues
                        cache_snapshot = list(self.page_cache.items())
                        for page_num, posts in cache_snapshot:
                            for i, post in enumerate(posts):
                                if post.get('shortcode') == shortcode:
                                    post['download_status'] = new_status
                                    logger.info(f"[DOWNLOAD_COMPLETE] Updated page cache for {shortcode}: status -> {new_status}")
                                    
                                    # If this is the current page, update the tile appearance
                                    if page_num == self.current_page and self.current_view_mode == 'tiles':
                                        columns = self.calculate_tile_columns()
                                        row = i // columns
                                        col = i % columns
                                        item = self.tiles_grid.itemAtPosition(row, col)
                                        if item and item.widget():
                                            tile_widget = item.widget()
                                            self.update_tile_appearance(tile_widget, post, shortcode)
                                            logger.info(f"[DOWNLOAD_COMPLETE] Updated tile appearance for {shortcode} at ({row}, {col})")
                                    break
                else:
                    logger.warning(f"Entry not found for {shortcode} - skipping database update")
                
                # Update in-memory saved_posts to match database
                for post in self.saved_posts:
                    if post.get('shortcode') == shortcode:
                        if actual_success:
                            post['download_status'] = 'completed'
                        elif not success:
                            post['download_status'] = 'failed'
                        else:
                            post['download_status'] = 'success_with_issues'
                        logger.info(f"Updated saved_posts for {shortcode}: status -> {post['download_status']}")
                        break
            
            # Update browse table row
            for row in range(self.posts_table.rowCount()):
                id_item = self.posts_table.item(row, 2)  # Column 2 now has shortcode
                if id_item:
                    # Remove checkmark prefix if present
                    row_shortcode = id_item.text().replace('✓ ', '')
                    if row_shortcode == shortcode:
                        # Update status column (column 6)
                        status_item = self.posts_table.item(row, 6)
                        if status_item:
                            if actual_success:
                                status_item.setText("✓ Downloaded")
                                status_item.setForeground(Qt.darkGreen)
                            elif success and not downloaded_files:
                                status_item.setText("⚠️ SUCCESS/ISSUES")
                                status_item.setForeground(Qt.red)
                            else:
                                status_item.setText("✗ Failed")
                                status_item.setForeground(Qt.red)
                        
                        # Color entire row based on result
                        if actual_success:
                            color = Qt.darkGreen
                        elif success and not downloaded_files:
                            color = Qt.red  # Red for success with issues
                        else:
                            color = Qt.red
                        
                        for col in range(1, 7):  # Don't color thumbnail column (0) or button columns (7, 8, 9)
                            item = self.posts_table.item(row, col)
                            if item:
                                item.setForeground(color)
                        
                        # Add button based on success/failure
                        if actual_success:
                            open_btn = QPushButton("📂 Open")
                            open_btn.setMaximumWidth(60)
                            open_btn.clicked.connect(lambda checked, sc=shortcode, fp=file_path: self.open_downloaded_file(sc, fp))
                            self.posts_table.setCellWidget(row, 7, open_btn)
                        elif success and not downloaded_files:
                            # Success with issues - show warning button
                            warn_btn = QPushButton("⚠️ Issues")
                            warn_btn.setMaximumWidth(70)
                            warn_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
                            warn_btn.setToolTip("Download succeeded but no files created - may already exist or be unavailable")
                            self.posts_table.setCellWidget(row, 7, warn_btn)
                        elif debug_file:
                            debug_btn = QPushButton("🐛 Debug")
                            debug_btn.setMaximumWidth(60)
                            debug_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
                            debug_btn.clicked.connect(lambda checked, df=debug_file: self.open_debug_file(df))
                            self.posts_table.setCellWidget(row, 7, debug_btn)
                        
                        logger.info(f"Updated browse table row for {shortcode}")
                        break
        
        except Exception as e:
            logger.error(f"Error updating browse table for {shortcode}: {e}")
        
        # Also update the queue table if this item is in the queue
        try:
            for queue_row in range(self.queue_table.rowCount()):
                id_item = self.queue_table.item(queue_row, 1)
                if id_item and id_item.text() == shortcode:
                    if actual_success:
                        # Update File Name column with actual downloaded files
                        filename_item = self.queue_table.item(queue_row, 3)
                        if filename_item:
                            # Show first file or file count if multiple
                            if len(downloaded_files) == 1:
                                filename_item.setText(downloaded_files[0])
                            else:
                                filename_item.setText(f"{len(downloaded_files)} files")
                            filename_item.setForeground(Qt.darkGreen)
                        
                        # Update queue status in database as downloading (will be completed later)
                        if self.content_db and self.content_db.db:
                            try:
                                self.content_db.db.update_queue_status(shortcode, 'downloading')
                                logger.info(f"Updated queue status to 'downloading' for {shortcode}")
                            except Exception as e:
                                logger.error(f"Failed to update queue status in database: {e}")
                    elif success and not downloaded_files:
                        # Success but no files - keep in queue with red status
                        filename_item = self.queue_table.item(queue_row, 3)
                        if filename_item:
                            filename_item.setText("⚠️ SUCCESS/ISSUES (no files)")
                            filename_item.setForeground(Qt.red)
                        
                        # Update File Location column color to red
                        location_item = self.queue_table.item(queue_row, 4)
                        if location_item:
                            location_item.setForeground(Qt.red)
                        
                        # Color other columns red to indicate issue
                        for col in range(5):
                            item = self.queue_table.item(queue_row, col)
                            if item:
                                item.setForeground(Qt.red)
                        
                        # DO NOT remove from queue - keep it visible for investigation
                        logger.info(f"Keeping {shortcode} in queue with SUCCESS/ISSUES status")
                    else:
                        # Update File Name column to show failure
                        filename_item = self.queue_table.item(queue_row, 3)
                        if filename_item:
                            filename_item.setText("✗ FAILED")
                            filename_item.setForeground(Qt.red)
                        
                        # Update queue status in database
                        if self.content_db and self.content_db.db:
                            try:
                                error_msg = error if error else "Download failed"
                                self.content_db.db.update_queue_status(shortcode, 'failed', error_msg)
                                logger.info(f"Updated queue status to 'failed' for {shortcode}")
                            except Exception as e:
                                logger.error(f"Failed to update queue status in database: {e}")
                        
                        # Add Debug and Remove buttons in column 5 if we have debug file
                        if debug_file:
                            # Create a widget to hold both buttons
                            button_widget = QWidget()
                            button_layout = QHBoxLayout(button_widget)
                            button_layout.setContentsMargins(2, 2, 2, 2)
                            button_layout.setSpacing(2)
                            
                            # Debug button
                            debug_btn = QPushButton("🐛")
                            debug_btn.setMaximumWidth(30)
                            debug_btn.setToolTip("View debug info")
                            debug_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; }")
                            debug_btn.clicked.connect(lambda checked, df=debug_file: self.open_debug_file(df))
                            button_layout.addWidget(debug_btn)
                            
                            # Remove button - store shortcode in property for lookup
                            remove_btn = QPushButton("✕")
                            remove_btn.setMaximumWidth(30)
                            remove_btn.setToolTip("Remove from queue")
                            remove_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; font-weight: bold; }")
                            remove_btn.setProperty("shortcode", shortcode)  # Store shortcode for lookup
                            remove_btn.clicked.connect(lambda checked, sc=shortcode: self.remove_queue_item_by_shortcode(sc))
                            button_layout.addWidget(remove_btn)
                            
                            self.queue_table.setCellWidget(queue_row, 5, button_widget)
                        
                        # Color all columns red
                        for col in range(5):
                            item = self.queue_table.item(queue_row, col)
                            if item:
                                item.setForeground(Qt.red)
                    
                    logger.info(f"Updated queue table row for {shortcode}")
                    break
        except Exception as e:
            logger.error(f"Error updating queue table for {shortcode}: {e}")
        
        # Check for topic assignments and copy files if download was successful
        # Do this regardless of whether files were just downloaded or already existed
        if actual_success:
            try:
                self.process_pending_topic_assignments(shortcode)
            except Exception as e:
                logger.error(f"Error processing topic assignments for {shortcode}: {e}")
            
            # Handle filter recalculation if filter is active (single download)
            try:
                self.handle_post_download_filter_update()
            except Exception as e:
                logger.error(f"Error handling post-download filter update: {e}")
    
    def open_downloaded_file(self, shortcode, file_path=None):
        """Open downloaded content in file explorer, selecting a concrete file when possible."""
        import subprocess
        import os
        
        try:
            target_file = None
            target_dir = None

            # If caller passed an explicit path, respect it.
            if file_path:
                if os.path.isfile(file_path):
                    target_file = file_path
                    target_dir = os.path.dirname(file_path)
                elif os.path.isdir(file_path):
                    target_dir = file_path
            else:
                # Prefer selecting the real media file for this shortcode.
                downloaded_files = self.get_downloaded_files(shortcode)
                if downloaded_files:
                    selected_index = self.carousel_indices.get(shortcode, 0)
                    if selected_index < 0 or selected_index >= len(downloaded_files):
                        selected_index = 0

                    candidate = downloaded_files[selected_index].get('path')
                    if candidate and os.path.isfile(candidate):
                        target_file = candidate
                        target_dir = os.path.dirname(candidate)

                # Fallback to download directory when no concrete file is available.
                if not target_dir:
                    target_dir = self.download_path_input.text()

            if target_file and os.path.exists(target_file):
                if sys.platform == 'win32':
                    # Select the exact file in Explorer.
                    subprocess.Popen(['explorer', f'/select,{os.path.normpath(target_file)}'])
                elif sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', '-R', target_file])
                else:  # Linux (most file managers don't support selection via xdg-open)
                    subprocess.Popen(['xdg-open', os.path.dirname(target_file)])
                logger.info(f"Opened explorer selecting file for {shortcode}: {target_file}")
            elif target_dir and os.path.exists(target_dir):
                if sys.platform == 'win32':
                    os.startfile(target_dir)
                elif sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', target_dir])
                else:  # Linux
                    subprocess.Popen(['xdg-open', target_dir])
                logger.info(f"Opened directory for {shortcode}: {target_dir}")
            else:
                QMessageBox.warning(
                    self,
                    "Directory Not Found",
                    f"Download path not found:\n{target_dir or file_path}"
                )
        except Exception as e:
            logger.error(f"Error opening directory: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open directory:\n{str(e)}"
            )
    
    def copy_url_to_clipboard(self, url):
        """Copy Instagram URL to clipboard"""
        try:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.statusBar().showMessage(f"Copied URL to clipboard: {url}", 3000)
            logger.info(f"Copied URL to clipboard: {url}")
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to copy URL:\n{str(e)}"
            )
    
    def open_post(self, shortcode):
        """Open Instagram post in default browser"""
        import webbrowser
        url = f"https://www.instagram.com/p/{shortcode}/"
        try:
            webbrowser.open(url)
            self.statusBar().showMessage(f"Opened {url}", 2000)
            logger.info(f"Opened post in browser: {url}")
        except Exception as e:
            logger.error(f"Error opening browser: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open browser:\n{str(e)}"
            )
    
    def open_in_firefox(self, url):
        """Open Instagram URL in Firefox"""
        import subprocess
        import os
        
        try:
            if sys.platform == 'win32':
                # Try common Firefox installation paths on Windows
                firefox_paths = [
                    r"C:\Program Files\Mozilla Firefox\firefox.exe",
                    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                    os.path.expandvars(r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
                    os.path.expandvars(r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe")
                ]
                
                firefox_exe = None
                for path in firefox_paths:
                    if os.path.exists(path):
                        firefox_exe = path
                        break
                
                if firefox_exe:
                    subprocess.Popen([firefox_exe, url])
                    logger.info(f"Opened URL in Firefox: {url}")
                else:
                    # Fallback to default browser
                    import webbrowser
                    webbrowser.open(url)
                    logger.warning("Firefox not found, opened in default browser")
                    self.statusBar().showMessage("Firefox not found, opened in default browser", 3000)
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(['open', '-a', 'Firefox', url])
                logger.info(f"Opened URL in Firefox: {url}")
            else:  # Linux
                subprocess.Popen(['firefox', url])
                logger.info(f"Opened URL in Firefox: {url}")
            
            self.statusBar().showMessage(f"Opened in Firefox: {url}", 3000)
        except Exception as e:
            logger.error(f"Error opening Firefox: {e}")
            # Fallback to default browser
            try:
                import webbrowser
                webbrowser.open(url)
                self.statusBar().showMessage("Firefox failed, opened in default browser", 3000)
            except:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open URL:\n{str(e)}"
                )
    
    def open_in_chrome(self, url):
        """Open Instagram URL in Chrome"""
        import subprocess
        import os
        
        try:
            if sys.platform == 'win32':
                # Try common Chrome installation paths on Windows
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
                ]
                
                chrome_exe = None
                for path in chrome_paths:
                    if os.path.exists(path):
                        chrome_exe = path
                        break
                
                if chrome_exe:
                    subprocess.Popen([chrome_exe, url])
                    logger.info(f"Opened URL in Chrome: {url}")
                else:
                    # Fallback to default browser
                    import webbrowser
                    webbrowser.open(url)
                    logger.warning("Chrome not found, opened in default browser")
                    self.statusBar().showMessage("Chrome not found, opened in default browser", 3000)
            elif sys.platform == 'darwin':  # macOS
                subprocess.Popen(['open', '-a', 'Google Chrome', url])
                logger.info(f"Opened URL in Chrome: {url}")
            else:  # Linux
                subprocess.Popen(['google-chrome', url])
                logger.info(f"Opened URL in Chrome: {url}")
            
            self.statusBar().showMessage(f"Opened in Chrome: {url}", 3000)
        except Exception as e:
            logger.error(f"Error opening Chrome: {e}")
            # Fallback to default browser
            try:
                import webbrowser
                webbrowser.open(url)
                self.statusBar().showMessage("Chrome failed, opened in default browser", 3000)
            except:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open URL:\n{str(e)}"
                )
    
    def ignore_content(self, shortcode):
        """Mark content as ignored"""
        try:
            if not self.content_db or not self.content_db.db:
                QMessageBox.warning(self, "No Database", "No database is loaded.")
                return
            
            # Show hourglass cursor for long operations
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            try:
                # Update download_status to 'ignored'
                updates = {'download_status': 'ignored'}
                success = self.content_db.db.update_content_entry(shortcode, updates)
                
                if success:
                    # Update in-memory post in saved_posts
                    for post in self.saved_posts:
                        if post.get('shortcode') == shortcode:
                            post['download_status'] = 'ignored'
                            break
                    
                    # Also update in page cache if present
                    # Create snapshot to prevent concurrent modification issues
                    cache_snapshot = list(self.page_cache.items())
                    for page_num, posts in cache_snapshot:
                        for post in posts:
                            if post.get('shortcode') == shortcode:
                                post['download_status'] = 'ignored'
                                logger.info(f"[IGNORE] Updated page cache for {shortcode}: status -> ignored")
                                break
                    
                    logger.info(f"Content {shortcode} marked as ignored")
                    self.statusBar().showMessage(f"Content marked as ignored", 2000)
                    
                    # Efficiently update just this item without full refresh
                    if self.current_view_mode == 'table':
                        # Update just the specific row's background color
                        for row in range(self.posts_table.rowCount()):
                            shortcode_item = self.posts_table.item(row, 2)
                            if shortcode_item:
                                shortcode_clean = shortcode_item.text().replace('✓ ', '').strip()
                                if shortcode_clean == shortcode:
                                    # Get ignored color
                                    bg_color, _ = self.get_item_background_color(shortcode, 'ignored')
                                    bg_qcolor = QColor(bg_color)
                                    # Update all columns in this row
                                    for col in range(self.posts_table.columnCount()):
                                        item = self.posts_table.item(row, col)
                                        if item:
                                            item.setBackground(bg_qcolor)
                                    break
                    else:
                        # For tile view, we need to refresh tiles (they're complex widgets)
                        self.populate_tiles()
                else:
                    QMessageBox.warning(self, "Update Failed", "Failed to update content status.")
            finally:
                # Always restore cursor
                QApplication.restoreOverrideCursor()
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.error(f"Error ignoring content {shortcode}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to ignore content:\n{str(e)}")
    
    def remove_from_view(self, shortcode):
        """Remove ignored content from view"""
        try:
            # Remove from saved_posts
            self.saved_posts = [p for p in self.saved_posts if p.get('shortcode') != shortcode]
            
            logger.info(f"Content {shortcode} removed from view")
            self.statusBar().showMessage(f"Content removed from view", 2000)
            
            # Refresh view
            self.refresh_current_view()
        except Exception as e:
            logger.error(f"Error removing content {shortcode} from view: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove content:\n{str(e)}")
    
    def restore_to_active(self, shortcode):
        """Restore ignored content back to active status (pre-download state)"""
        try:
            if not self.content_db or not self.content_db.db:
                QMessageBox.warning(self, "No Database", "No database is loaded.")
                return
            
            # Show hourglass cursor for long operations
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            try:
                # Delete all downloaded files from database (returns to pre-download state)
                deleted_count = self.content_db.db.delete_files_for_entry(shortcode)
                logger.info(f"Deleted {deleted_count} file record(s) for {shortcode}")
                
                # Update download_status to 'awaiting scan' (default active state)
                updates = {'download_status': 'awaiting scan'}
                success = self.content_db.db.update_content_entry(shortcode, updates)
                
                if success:
                    # Update in-memory post in saved_posts
                    for post in self.saved_posts:
                        if post.get('shortcode') == shortcode:
                            post['download_status'] = 'awaiting scan'
                            break
                    
                    # Also update in page cache if present
                    # Create snapshot to prevent concurrent modification issues
                    cache_snapshot = list(self.page_cache.items())
                    for page_num, posts in cache_snapshot:
                        for post in posts:
                            if post.get('shortcode') == shortcode:
                                post['download_status'] = 'awaiting scan'
                                logger.info(f"[RESTORE] Updated page cache for {shortcode}: status -> awaiting scan")
                                break
                    
                    logger.info(f"Content {shortcode} restored to active (pre-download state)")
                    self.statusBar().showMessage(f"Content restored to active ({deleted_count} file(s) cleared)", 3000)
                    
                    # Refresh just this item
                    self.refresh_single_item(shortcode)
                else:
                    QMessageBox.warning(self, "Update Failed", "Failed to update content status.")
            finally:
                # Always restore cursor
                QApplication.restoreOverrideCursor()
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.error(f"Error restoring content {shortcode}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to restore content:\n{str(e)}")
    
    def classify_content(self, shortcode):
        """Classify content by assigning it to multiple topics"""
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        try:
            # Get all topics from database
            topics = self.content_db.db.get_all_topics()
            
            if not topics:
                reply = QMessageBox.question(
                    self, "No Topics",
                    "No topics found in database. Topics are used to organize your content.\n\n"
                    "Would you like to create topics in the SQL Server database?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    QMessageBox.information(
                        self, "Create Topics",
                        "Please use the Topics tab to create and manage topics."
                    )
                return
            
            # Get currently assigned topics for this content
            current_topic_ids = self.content_db.db.get_content_topics(shortcode)
            
            # Create classification dialog
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Classify Content: {shortcode}")
            dialog.setMinimumWidth(500)
            dialog.setMinimumHeight(600)
            
            layout = QVBoxLayout(dialog)
            
            # === Radio buttons: Existing vs New Topic ===
            mode_group = QGroupBox("Topic Assignment Mode")
            mode_layout = QVBoxLayout()
            
            existing_radio = QRadioButton("Add to existing topic(s)")
            existing_radio.setChecked(True)
            mode_layout.addWidget(existing_radio)
            
            new_radio = QRadioButton("Create and add to new topic")
            mode_layout.addWidget(new_radio)
            
            mode_group.setLayout(mode_layout)
            layout.addWidget(mode_group)
            
            mode_group.setLayout(mode_layout)
            layout.addWidget(mode_group)
            
            # === Panel for EXISTING topics ===
            existing_panel = QWidget()
            existing_layout = QVBoxLayout(existing_panel)
            existing_layout.setContentsMargins(0, 0, 0, 0)
            
            # Info label
            info_label = QLabel("Select one or more topics for this content.\nFiles will be copied to each selected topic folder.")
            info_label.setWordWrap(True)
            info_label.setStyleSheet("padding: 5px; color: #0066cc;")
            existing_layout.addWidget(info_label)
            
            # Topic tree with checkboxes
            topic_tree = QTreeWidget()
            topic_tree.setHeaderLabels(["Topic Name", "Path"])
            topic_tree.setColumnWidth(0, 300)
            topic_tree.setColumnWidth(1, 150)
            
            # Build hierarchical topic display
            topic_map = {}
            for topic in topics:
                topic_map[topic['id']] = topic
            
            # Build parent-child relationships
            children_map = {}
            root_topics = []
            for topic in topics:
                parent_id = topic.get('parent_topic_id')
                if parent_id is None:
                    root_topics.append(topic)
                else:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(topic)
            
            # Recursively add topics to tree with checkboxes
            def add_topic_to_tree(topic, parent_item=None):
                item = QTreeWidgetItem()
                item.setText(0, topic['topic_name'])
                item.setText(1, topic.get('content_path', ''))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                
                # Check if this topic is currently assigned
                if topic['id'] in current_topic_ids:
                    item.setCheckState(0, Qt.Checked)
                else:
                    item.setCheckState(0, Qt.Unchecked)
                
                item.setData(0, Qt.UserRole, topic)  # Store full topic data
                
                if parent_item:
                    parent_item.addChild(item)
                else:
                    topic_tree.addTopLevelItem(item)
                
                # Add children
                topic_id = topic['id']
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_to_tree(child_topic, item)
                
                return item
            
            # Add all root topics and their children
            for root_topic in root_topics:
                add_topic_to_tree(root_topic)

            self._restore_topic_tree_expansion_state(topic_tree)
            # Restore scroll position after tree is built (use QTimer to ensure UI is ready)
            QTimer.singleShot(0, lambda: self._restore_topic_tree_scroll_position(topic_tree))
            
            topic_tree.itemExpanded.connect(lambda _item: self._save_topic_tree_expansion_state(topic_tree))
            topic_tree.itemCollapsed.connect(lambda _item: self._save_topic_tree_expansion_state(topic_tree))
            
            # Save both expansion state and scroll position when dialog closes
            def save_all_state(result):
                self._save_topic_tree_expansion_state(topic_tree)
                self._save_topic_tree_scroll_position(topic_tree)
            dialog.finished.connect(save_all_state)
            
            existing_layout.addWidget(topic_tree)
            
            layout.addWidget(existing_panel)
            
            # === Panel for NEW topic creation ===
            new_panel = QWidget()
            new_layout = QVBoxLayout(new_panel)
            new_layout.setContentsMargins(0, 0, 0, 0)
            
            new_info_label = QLabel("Create a new topic and assign this content to it.")
            new_info_label.setWordWrap(True)
            new_info_label.setStyleSheet("padding: 5px; color: #0066cc;")
            new_layout.addWidget(new_info_label)
            
            # Topic name
            name_layout = QHBoxLayout()
            name_layout.addWidget(QLabel("Topic Name:"))
            name_input = QLineEdit()
            name_input.setPlaceholderText("Enter topic name...")
            name_layout.addWidget(name_input)
            new_layout.addLayout(name_layout)
            
            # Content path
            path_layout = QHBoxLayout()
            path_layout.addWidget(QLabel("Content Path:"))
            path_input = QLineEdit()
            path_input.setPlaceholderText("Path where files will be copied...")
            path_layout.addWidget(path_input)
            new_layout.addLayout(path_layout)
            
            # Track if user manually edited content path
            path_manually_edited = [False]
            def on_path_edited():
                path_manually_edited[0] = True
            path_input.textEdited.connect(on_path_edited)
            
            # Update content path based on selected parent and topic name
            def update_path_from_parent():
                if path_manually_edited[0]:
                    return
                
                selected_items = parent_tree.selectedItems()
                if not selected_items:
                    path_input.setText(name_input.text())
                    return
                
                parent_id = selected_items[0].data(0, Qt.UserRole)
                if parent_id is None:
                    # Root parent - just use topic name
                    path_input.setText(name_input.text())
                else:
                    # Get parent's content_path
                    try:
                        conn = self.content_db.db._get_connection()
                        cursor = conn.cursor()
                        cursor.execute('SELECT content_path FROM DL.topics WHERE id = ?', (parent_id,))
                        result = cursor.fetchone()
                        parent_path = result[0] if result and result[0] else ''
                        if parent_path and not parent_path.endswith('/'):
                            parent_path += '/'
                        path_input.setText(parent_path + name_input.text())
                    except Exception as e:
                        logger.error(f"Error getting parent path: {e}")
                        path_input.setText(name_input.text())
            
            # Sync topic name to content path
            def on_name_changed(text):
                update_path_from_parent()
            name_input.textChanged.connect(on_name_changed)
            
            # Display order
            order_layout = QHBoxLayout()
            order_layout.addWidget(QLabel("Display Order:"))
            order_input = QSpinBox()
            order_input.setMinimum(0)
            order_input.setMaximum(9999)
            order_input.setValue(0)
            order_layout.addWidget(order_input)
            order_layout.addStretch()
            new_layout.addLayout(order_layout)
            
            # Parent topic selection (as tree widget)
            parent_label = QLabel("Parent Topic (optional):")
            new_layout.addWidget(parent_label)
            
            parent_tree = QTreeWidget()
            parent_tree.setHeaderLabels(["Topic Name"])
            parent_tree.setMaximumHeight(350)
            parent_tree.setSelectionMode(QTreeWidget.SingleSelection)
            
            # Add Root node
            root_item = QTreeWidgetItem()
            root_item.setText(0, "(Root - No Parent)")
            root_item.setData(0, Qt.UserRole, None)  # Store None for root
            root_item.setExpanded(True)
            parent_tree.addTopLevelItem(root_item)
            
            # Recursively add topics to parent tree
            def add_topic_to_parent_tree(topic, parent_item):
                item = QTreeWidgetItem()
                item.setText(0, topic['topic_name'])
                item.setData(0, Qt.UserRole, topic['id'])  # Store topic ID
                parent_item.addChild(item)
                item.setExpanded(True)
                
                # Add children
                topic_id = topic['id']
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_to_parent_tree(child_topic, item)
                
                return item
            
            # Add all root topics under Root node
            for root_topic in root_topics:
                add_topic_to_parent_tree(root_topic, root_item)
            
            # Select Root by default
            parent_tree.setCurrentItem(root_item)
            
            # Update path when parent selection changes
            def on_parent_changed():
                update_path_from_parent()
            parent_tree.itemSelectionChanged.connect(on_parent_changed)
            
            new_layout.addWidget(parent_tree)
            new_layout.addStretch()
            
            new_panel.setVisible(False)  # Hidden by default
            layout.addWidget(new_panel)
            
            # Radio button switching logic
            def on_mode_changed():
                is_existing = existing_radio.isChecked()
                existing_panel.setVisible(is_existing)
                new_panel.setVisible(not is_existing)
                
                # Update button text and tooltips
                if is_existing:
                    save_btn.setText("Save & Copy Files")
                    save_btn.setToolTip("Save topic assignment(s) and copy files to topic folder(s)")
                else:
                    save_btn.setText("Create Topic & Save")
                    save_btn.setToolTip("Create new topic and assign this content to it")
            
            existing_radio.toggled.connect(on_mode_changed)
            new_radio.toggled.connect(on_mode_changed)
            
            # Buttons
            button_layout = QHBoxLayout()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            clear_all_btn = QPushButton("Clear All Topics")
            clear_all_btn.setToolTip("Remove all topic classifications")
            clear_all_btn.clicked.connect(lambda: self.apply_multi_topic_classification(shortcode, [], topic_tree, dialog))
            button_layout.addWidget(clear_all_btn)
            
            save_enqueue_btn = QPushButton("Save Topic & Enqueue")
            save_enqueue_btn.setToolTip("Save topic assignment and add to download queue")
            save_enqueue_btn.clicked.connect(lambda: self.save_topic_and_enqueue(shortcode, topic_tree, dialog))
            button_layout.addWidget(save_enqueue_btn)
            
            save_btn = QPushButton("Save & Copy Files")
            save_btn.setDefault(True)
            save_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; }")
            save_btn.clicked.connect(lambda: self.save_multi_topic_selection(
                shortcode, topic_tree, dialog, existing_radio, 
                name_input, path_input, order_input, parent_tree
            ))
            button_layout.addWidget(save_btn)
            
            layout.addLayout(button_layout)
            
            dialog.exec_()
            
        except Exception as e:
            logger.error(f"Error classifying content {shortcode}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to classify content:\n{str(e)}")
    
    def save_multi_topic_selection(self, shortcode, topic_tree, dialog, existing_radio, 
                                   name_input, path_input, order_input, parent_tree):
        """Collect checked topics and apply classification, OR create new topic first"""
        
        # Check which mode is active
        if existing_radio.isChecked():
            # === Mode A: Add to existing topic(s) ===
            checked_topics = []
            
            def collect_checked_items(item):
                if item.checkState(0) == Qt.Checked:
                    topic = item.data(0, Qt.UserRole)
                    checked_topics.append(topic)
                
                for i in range(item.childCount()):
                    collect_checked_items(item.child(i))
            
            # Iterate through all top-level items
            for i in range(topic_tree.topLevelItemCount()):
                collect_checked_items(topic_tree.topLevelItem(i))
            
            # Apply the classification
            self.apply_multi_topic_classification(shortcode, checked_topics, topic_tree, dialog)
            
        else:
            # === Mode B: Create new topic and assign ===
            topic_name = name_input.text().strip()
            content_path = path_input.text().strip()
            display_order = order_input.value()
            
            # Get selected parent from tree widget
            selected_items = parent_tree.selectedItems()
            if selected_items:
                parent_id = selected_items[0].data(0, Qt.UserRole)
            else:
                parent_id = None  # Default to Root if nothing selected
            
            # Validate
            if not topic_name:
                QMessageBox.warning(dialog, "Invalid Input", "Topic name is required.")
                return
            
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                # Calculate alphabetic insertion position
                if parent_id is None:
                    cursor.execute('SELECT id, topic_name, display_order FROM DL.topics WHERE parent_topic_id IS NULL ORDER BY topic_name')
                else:
                    cursor.execute('SELECT id, topic_name, display_order FROM DL.topics WHERE parent_topic_id = ? ORDER BY topic_name', (parent_id,))
                
                siblings = cursor.fetchall()
                
                # Find alphabetic position and calculate display_order
                insert_position = 0
                for i, (sibling_id, sibling_name, sibling_order) in enumerate(siblings):
                    if topic_name.lower() < sibling_name.lower():
                        insert_position = i
                        break
                    insert_position = i + 1
                
                # Use insert_position as display_order
                display_order = insert_position
                
                # Insert the new topic
                try:
                    cursor.execute('''
                        INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                        VALUES (?, ?, ?, ?)
                    ''', (topic_name, content_path or None, display_order, parent_id))
                    
                    # Get the new topic ID
                    cursor.execute('SELECT @@IDENTITY')
                    new_topic_id = cursor.fetchone()[0]
                    
                    conn.commit()
                    logger.info(f"Created new topic: {topic_name} (ID: {new_topic_id}) at alphabetic position {insert_position}")
                except Exception as insert_error:
                    error_str = str(insert_error)
                    if 'PRIMARY KEY constraint' in error_str or 'duplicate key' in error_str.lower():
                        logger.warning(f"PRIMARY KEY violation detected, reseeding identity column")
                        conn.rollback()
                        
                        if self.content_db.db.reseed_topics_identity():
                            cursor.execute('''
                                INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                                VALUES (?, ?, ?, ?)
                            ''', (topic_name, content_path or None, display_order, parent_id))
                            cursor.execute('SELECT @@IDENTITY')
                            new_topic_id = cursor.fetchone()[0]
                            conn.commit()
                            logger.info("Successfully inserted topic after reseeding")
                        else:
                            raise insert_error
                    else:
                        raise insert_error
                
                # Update display_order for topics that come after the new one
                if parent_id is None:
                    cursor.execute('''
                        UPDATE DL.topics 
                        SET display_order = display_order + 1 
                        WHERE parent_topic_id IS NULL 
                        AND id != ? 
                        AND display_order >= ?
                    ''', (new_topic_id, display_order))
                else:
                    cursor.execute('''
                        UPDATE DL.topics 
                        SET display_order = display_order + 1 
                        WHERE parent_topic_id = ? 
                        AND id != ? 
                        AND display_order >= ?
                    ''', (parent_id, new_topic_id, display_order))
                
                conn.commit()
                
                # Get the full topic object
                new_topic = self.content_db.db.get_topic(new_topic_id)
                
                if not new_topic:
                    raise Exception("Failed to retrieve newly created topic")
                
                # Assign content to the new topic
                self.content_db.db.clear_content_topics(shortcode)
                self.content_db.db.add_topic_assignment(shortcode, new_topic_id)
                
                # Check if files are already downloaded
                downloaded_files = self.get_downloaded_files(shortcode)
                
                if downloaded_files:
                    # Copy files to the new topic folder
                    self.copy_files_to_multiple_topic_folders(shortcode, [new_topic])
                    
                    QMessageBox.information(
                        dialog,
                        "Topic Created & Assigned",
                        f"New topic '{topic_name}' created and content assigned.\n"
                        f"Files copied to topic folder."
                    )
                else:
                    QMessageBox.information(
                        dialog,
                        "Topic Created & Assigned",
                        f"New topic '{topic_name}' created and content assigned.\n"
                        f"Files will be copied when content is downloaded."
                    )
                
                QApplication.restoreOverrideCursor()
                
                # Refresh topics tab if it exists
                if hasattr(self, 'topics_table'):
                    self.load_topics()
                
                # Refresh current view to show updated status
                self.refresh_current_view()
                
                dialog.accept()
                
            except Exception as e:
                QApplication.restoreOverrideCursor()
                logger.error(f"Error creating new topic: {e}")
                QMessageBox.critical(dialog, "Error", f"Failed to create topic:\n{str(e)}")
    
    def save_topic_and_enqueue(self, shortcode, topic_tree, dialog):
        """Collect checked topics, apply classification, and add to download queue"""
        # First collect checked topics
        checked_topics = []
        
        def collect_checked_items(item):
            if item.checkState(0) == Qt.Checked:
                topic = item.data(0, Qt.UserRole)
                checked_topics.append(topic)
            
            for i in range(item.childCount()):
                collect_checked_items(item.child(i))
        
        # Iterate through all top-level items
        for i in range(topic_tree.topLevelItemCount()):
            collect_checked_items(topic_tree.topLevelItem(i))
        
        # Apply the classification without closing dialog (pass copy_files=False)
        self.apply_multi_topic_classification_and_enqueue(shortcode, checked_topics, topic_tree, dialog)
    
    def apply_multi_topic_classification_and_enqueue(self, shortcode, selected_topics, topic_tree, dialog):
        """Apply topic classification and add to download queue"""
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Clear existing assignments
            self.content_db.db.clear_content_topics(shortcode)
            
            # Add new assignments (defaults to 'Pending' status)
            for topic in selected_topics:
                self.content_db.db.add_topic_assignment(shortcode, topic['id'])
            
            logger.info(f"Content {shortcode} classified with {len(selected_topics)} topic(s)")
            
            # Check if files are already downloaded
            downloaded_files = self.get_downloaded_files(shortcode)
            
            if selected_topics:
                topic_names = [t['topic_name'] for t in selected_topics]
                if downloaded_files:
                    # Files exist - copy them now
                    self.copy_files_to_multiple_topic_folders(shortcode, selected_topics)
                    logger.info(f"Files copied to {len(selected_topics)} topic(s)")
                else:
                    # No files yet - assignments saved, will auto-copy after download
                    logger.info(f"No files to copy yet for {shortcode} - assignments saved for post-download copy")
                    logger.info(f"Topics: {', '.join(topic_names)}")
            else:
                logger.info(f"No topics selected - classifications cleared")
            
            # Find the post in page_cache (or saved_posts for backward compatibility) to add to queue
            post = None
            # First check page_cache (current system)
            for page_num, posts in self.page_cache.items():
                for p in posts:
                    if p.get('shortcode') == shortcode:
                        post = p
                        break
                if post:
                    break
            
            # Fallback to saved_posts for backward compatibility
            if not post:
                for p in self.saved_posts:
                    if p.get('shortcode') == shortcode:
                        post = p
                        break
            
            if post:
                # Check if already in queue
                if shortcode not in self.queued_shortcodes:
                    # Add to queue
                    target_dir = self.download_path_input.text()
                    
                    if target_dir:
                        # Add to database queue if available
                        if self.content_db and self.content_db.db:
                            try:
                                row_num = post.get('row_number', 0)
                                caption = post.get('caption', '')
                                self.content_db.db.add_to_queue(
                                    content_id=shortcode,
                                    row_number=row_num,
                                    caption=caption,
                                    target_directory=target_dir
                                )
                            except Exception as e:
                                logger.error(f"Failed to add {shortcode} to database queue: {e}")
                        
                        # Add to UI queue
                        self.add_post_to_queue(post)
                        
                        # Show appropriate message based on file status
                        if selected_topics:
                            topic_names = [t['topic_name'] for t in selected_topics]
                            if downloaded_files:
                                msg = f"✓ {shortcode} queued. Topics assigned and files copied: {', '.join(topic_names[:2])}"
                            else:
                                msg = f"💾 {shortcode} queued with {len(selected_topics)} topic(s). Files will AUTO-COPY after download"
                        else:
                            msg = f"{shortcode} added to download queue"
                        
                        self.statusBar().showMessage(msg, 5000)
                    else:
                        QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
                        QApplication.restoreOverrideCursor()
                        return
                else:
                    self.statusBar().showMessage(
                        f"Topic saved ({shortcode} already in queue)", 3000
                    )
            else:
                logger.warning(f"Post {shortcode} not found in page_cache or saved_posts")
            
            QApplication.restoreOverrideCursor()
            dialog.accept()
            
            # Refresh view to show updated background color
            self.refresh_current_view()
            self.update_topic_assigned_download_button_text()
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.error(f"Error applying classification and enqueueing {shortcode}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save and enqueue:\n{str(e)}")
    
    def apply_multi_topic_classification(self, shortcode, selected_topics, topic_tree, dialog):
        """Update content entry with multiple topic classifications and copy files to topic folders"""
        try:
            logger.info(f"=== apply_multi_topic_classification for {shortcode} with {len(selected_topics)} topic(s) ===")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Clear existing assignments
            logger.info(f"Clearing existing topic assignments for {shortcode}")
            self.content_db.db.clear_content_topics(shortcode)
            
            # Add new assignments (defaults to 'Pending' status)
            for topic in selected_topics:
                logger.info(f"Adding topic assignment: {shortcode} -> topic {topic['id']} ('{topic.get('topic_name', 'Unknown')}')")
                self.content_db.db.add_topic_assignment(shortcode, topic['id'])
            
            logger.info(f"Content {shortcode} classified with {len(selected_topics)} topic(s)")
            
            # Check if files are already downloaded
            downloaded_files = self.get_downloaded_files(shortcode)
            logger.info(f"Downloaded files check: {len(downloaded_files)} file(s) found")
            
            if selected_topics:
                if downloaded_files:
                    # Files exist - copy them now
                    logger.info(f"Files exist - calling copy_files_to_multiple_topic_folders")
                    self.copy_files_to_multiple_topic_folders(shortcode, selected_topics)
                    topic_names = [t['topic_name'] for t in selected_topics]
                    self.statusBar().showMessage(
                        f"✓ Classified with {len(selected_topics)} topic(s) and files copied: {', '.join(topic_names[:2])}" +
                        (f" (+{len(topic_names)-2} more)" if len(topic_names) > 2 else ""),
                        5000
                    )
                else:
                    # No files yet - assignments saved, will auto-copy after ANY download method completes
                    topic_names = [t['topic_name'] for t in selected_topics]
                    logger.info(f"No files to copy yet for {shortcode} - assignments saved for post-download copy")
                    logger.info(f"Topics: {', '.join(topic_names)}")
                    self.statusBar().showMessage(
                        f"💾 Classified with {len(selected_topics)} topic(s). Files will AUTO-COPY after download: {', '.join(topic_names[:2])}" +
                        (f" (+{len(topic_names)-2} more)" if len(topic_names) > 2 else ""),
                        8000  # Show longer since this is important info
                    )
            else:
                self.statusBar().showMessage(f"All topic classifications removed", 3000)
            
            QApplication.restoreOverrideCursor()
            dialog.accept()
            
            # Update cache and tile appearance
            logger.info(f"[CLASSIFY] Updating cache and tile for shortcode {shortcode}")
            if self.current_page in self.page_cache:
                updated_entry = self.content_db.db.get_content_entry(shortcode)
                if updated_entry:
                    # Find the post in cache - use single pass to avoid index corruption
                    target_post = None
                    post_index = None
                    for i, post in enumerate(self.page_cache[self.current_page]):
                        if post.get('shortcode') == shortcode:
                            target_post = post
                            post_index = i
                            break
                    
                    if target_post:
                        # Update ContentInformation fields (topic_id is the key change)
                        if 'ContentInformation' not in target_post:
                            target_post['ContentInformation'] = {}
                        if 'ContentInformation' in updated_entry:
                            target_post['ContentInformation']['topicID'] = updated_entry['ContentInformation'].get('topicID')
                        logger.info(f"[CLASSIFY] Cache updated for {shortcode} - topicID={target_post['ContentInformation'].get('topicID')}")
                        
                        # Update tile appearance using the found index
                        if post_index is not None:
                            columns = self.calculate_tile_columns()
                            row = post_index // columns
                            col = post_index % columns
                            layout_item = self.tiles_grid.itemAtPosition(row, col)
                            if layout_item:
                                tile_widget = layout_item.widget()
                                if tile_widget:
                                    self.update_tile_appearance(tile_widget, target_post, shortcode)
                                    logger.info(f"[CLASSIFY] Tile appearance updated for {shortcode}")
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.error(f"Error applying classification: {e}")
            QMessageBox.critical(dialog, "Error", f"Failed to save classification:\n{str(e)}")
    
    def copy_files_to_multiple_topic_folders(self, shortcode, topics):
        """Copy all files for a shortcode to multiple topic folders"""
        import shutil
        
        logger.info(f"=== copy_files_to_multiple_topic_folders called for {shortcode} with {len(topics)} topic(s) ===")
        
        try:
            # CRITICAL: Check if download path is blank before proceeding
            download_path_text = self.download_path_input.text().strip()
            if not download_path_text:
                error_msg = f"Cannot copy files to topics: Download path is blank!\n\nShortcode: {shortcode}\nTopics: {len(topics)}"
                logger.error(f"⚠️⚠️⚠️ CRITICAL: {error_msg}")
                QMessageBox.critical(
                    self,
                    "Download Path Not Set",
                    error_msg + "\n\nPlease set a download path in the Settings tab."
                )
                # Mark all topics as Error
                for topic in topics:
                    self.content_db.db.update_file_movement_status(
                        shortcode, topic['id'], 'Error', 'Download path is blank'
                    )
                return
            
            # Get downloaded files for this shortcode
            downloaded_files = self.get_downloaded_files(shortcode)
            logger.info(f"Found {len(downloaded_files)} downloaded file(s) for {shortcode}")
            
            if not downloaded_files:
                logger.info(f"No files to copy for {shortcode}")
                # Update all topics to Complete since there are no files
                for topic in topics:
                    self.content_db.db.update_file_movement_status(
                        shortcode, topic['id'], 'Complete'
                    )
                return
            
            base_path = Path(download_path_text)
            logger.info(f"Base download path: {base_path}")
            total_copied = 0
            
            for topic in topics:
                topic_id = topic['id']
                topic_name = topic.get('topic_name', 'Unknown')
                topic_path = topic.get('content_path') or topic.get('topic_name')
                
                logger.info(f"Processing topic {topic_id} ('{topic_name}'): content_path='{topic_path}'")
                
                if not topic_path:
                    error_msg = f"Topic '{topic_name}' has no content path defined!\\n\\nShortcode: {shortcode}\\nTopic ID: {topic_id}"
                    logger.error(f"⚠️⚠️⚠️ CRITICAL: {error_msg}")
                    QMessageBox.critical(
                        self,
                        "Topic Path Not Set",
                        error_msg + "\\n\\nPlease edit this topic in the Topics tab and set a valid content path."
                    )
                    self.content_db.db.update_file_movement_status(
                        shortcode, topic_id, 'Error', 'No content path defined'
                    )
                    continue
                
                # Sanitize path to ensure it's safe
                sanitized_path, is_absolute = self.sanitize_topic_path(topic_path)
                logger.info(f"Sanitized path: '{topic_path}' -> '{sanitized_path}' (absolute={is_absolute})")
                
                if not sanitized_path:
                    logger.error(f"Topic {topic_id} has invalid content_path, skipping")
                    self.content_db.db.update_file_movement_status(
                        shortcode, topic_id, 'Error', 'Invalid content path'
                    )
                    continue
                
                # Update status to In Process
                logger.info(f"Updating status to 'In Process' for topic {topic_id}")
                self.content_db.db.update_file_movement_status(
                    shortcode, topic_id, 'In Process'
                )
                
                try:
                    # Build destination folder: use absolute path directly or combine with download_path
                    if is_absolute:
                        topic_folder = Path(sanitized_path)
                    else:
                        topic_folder = base_path / Path(sanitized_path)
                    logger.info(f"Destination folder: {topic_folder}")
                    topic_folder.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created directory (if not exists): {topic_folder}")
                    
                    # Copy each file (skip if already exists)
                    files_copied = 0
                    files_skipped = 0
                    errors = []
                    for file_info in downloaded_files:
                        source_path = Path(file_info['path'])
                        logger.info(f"  Checking source file: {source_path}")
                        
                        if source_path.exists():
                            dest_path = topic_folder / source_path.name
                            logger.info(f"  Destination: {dest_path}")
                            
                            # Skip if destination file already exists and has same size
                            if dest_path.exists():
                                if dest_path.stat().st_size == source_path.stat().st_size:
                                    files_skipped += 1
                                    logger.info(f"  Skipped (already exists): {dest_path.name}")
                                    continue
                                else:
                                    logger.info(f"  File exists but size differs, re-copying: {dest_path.name}")
                            
                            try:
                                shutil.copy2(source_path, dest_path)
                                files_copied += 1
                                total_copied += 1
                                logger.info(f"  ✓ Copied: {source_path.name} ({files_copied}/{len(downloaded_files)})")
                            except Exception as e:
                                error_msg = f"Failed to copy {source_path.name}: {str(e)}"
                                logger.error(f"  ✗ {error_msg}")
                                errors.append(error_msg)
                        else:
                            error_msg = f"Source file not found: {source_path}"
                            logger.warning(f"  ✗ {error_msg}")
                            errors.append(error_msg)
                    
                    # Update status based on results
                    if errors:
                        error_summary = f"{files_copied}/{len(downloaded_files)} copied, {files_skipped} skipped. Errors: {'; '.join(errors[:3])}"
                        logger.error(f"Completed with errors for topic {topic_id}: {error_summary}")
                        self.content_db.db.update_file_movement_status(
                            shortcode, topic_id, 'Error', error_summary[:500]
                        )
                    else:
                        # Success if files were copied or already existed
                        status_msg = f"Complete ({files_copied} copied, {files_skipped} existed)" if files_skipped > 0 else None
                        logger.info(f"✓ Successfully completed for topic {topic_id}: {files_copied} copied, {files_skipped} existed")
                        self.content_db.db.update_file_movement_status(
                            shortcode, topic_id, 'Complete', status_msg
                        )
                    
                    logger.info(f"Copied {files_copied} file(s) for {shortcode} to topic folder: {topic_folder}")
                    
                except Exception as e:
                    error_msg = f"Failed to copy files to topic folder: {str(e)}"
                    logger.error(f"Exception for topic {topic_id}: {error_msg}")
                    logger.exception(e)
                    self.content_db.db.update_file_movement_status(
                        shortcode, topic_id, 'Error', error_msg[:500]
                    )
            
            if total_copied > 0:
                logger.info(f"=== TOTAL: Copied {total_copied} file(s) for {shortcode} to {len(topics)} topic folder(s) ===")
            elif len(topics) > 0:
                # Only warn if there were topics expecting files
                logger.warning(f"=== TOTAL: 0 files copied for {shortcode} (expected {len(topics)} topic folder(s)) ===")
            else:
                logger.debug(f"=== TOTAL: 0 files copied for {shortcode} (no topics assigned) ===")
        except Exception as e:
            logger.error(f"Error in copy_files_to_multiple_topic_folders: {e}")
            logger.exception(e)
    
    def process_pending_topic_assignments(self, shortcode):
        """Copy files to ALL assigned topic folders (not just pending ones)
        
        This is called after a download completes to ensure files are copied to
        all topic folders, whether the assignment was made before or after download.
        
        Returns:
            bool: True if all files were successfully copied to all assigned topic folders
        """
        try:
            logger.info(f"=== process_pending_topic_assignments called for {shortcode} ===")
            
            if not self.content_db or not self.content_db.db:
                logger.warning("No content database available")
                return False
            
            # Get ALL topic assignments (not just pending)
            # This handles both pre-download assignments and post-download "re-copy" scenarios
            assignments = self.content_db.db.get_content_topic_assignments(shortcode)
            logger.info(f"Found {len(assignments)} total topic assignment(s) for {shortcode}")
            
            if not assignments:
                logger.info(f"No topic assignments for {shortcode}")
                return True  # No assignments = success
            
            # Get all topics (need full topic objects with paths)
            all_topics = self.content_db.db.get_all_topics()
            logger.info(f"Loaded {len(all_topics)} total topics")
            
            # Get topic IDs from all assignments
            topic_ids = [a['topic_id'] for a in assignments]
            logger.info(f"Topic IDs to copy to: {topic_ids}")
            
            # Filter to topics that match the assignments
            topics_to_copy = [t for t in all_topics if t['id'] in topic_ids]
            logger.info(f"Found {len(topics_to_copy)} topic(s) to copy to")
            
            if topics_to_copy:
                topic_names = [t['topic_name'] for t in topics_to_copy]
                logger.info(f"Copying files to {len(topics_to_copy)} topic folder(s) for {shortcode}")
                logger.info(f"Topic names: {', '.join(topic_names)}")
                
                # Show user-visible status message
                self.statusBar().showMessage(
                    f"📋 Copying {shortcode} to {len(topics_to_copy)} topic folder(s)...", 
                    2000
                )
                
                # Perform the copy
                self.copy_files_to_multiple_topic_folders(shortcode, topics_to_copy)
                
                # Verify files were copied to all topic folders
                all_copied = self.verify_topic_folder_copies(shortcode, topics_to_copy)
                
                if all_copied:
                    # Show completion message
                    self.statusBar().showMessage(
                        f"✓ Copied {shortcode} to topic(s): {', '.join(topic_names[:3])}" + 
                        (f" (+{len(topic_names)-3} more)" if len(topic_names) > 3 else ""),
                        5000
                    )
                    logger.info(f"✓ Successfully copied and verified files to topic folders")
                    return True
                else:
                    logger.warning(f"⚠️ Files copied but verification failed for some topic folders")
                    return False
            else:
                logger.warning(f"No topics found matching assignment IDs: {topic_ids}")
                self.statusBar().showMessage(
                    f"⚠️ No topics found for {shortcode} assignments",
                    3000
                )
                return False
        except Exception as e:
            logger.error(f"Error processing topic assignments for {shortcode}: {e}")
            self.statusBar().showMessage(
                f"✗ Error copying {shortcode} to topics: {str(e)}",
                5000
            )
            import traceback
            traceback.print_exc()
            return False
    
    def verify_downloaded_files(self, shortcode):
        """Verify that all files for a shortcode actually exist on disk
        
        Returns:
            tuple: (all_exist: bool, existing_files: list, missing_count: int)
        """
        try:
            target_dir_str = self.download_path_input.text()
            if not target_dir_str:
                return (False, [], 0)
            
            target_dir = Path(target_dir_str)
            if not target_dir.exists():
                logger.warning(f"Download directory does not exist: {target_dir}")
                return (False, [], 0)
            
            # Get files for this shortcode from the directory
            import os
            all_files = os.listdir(target_dir) if target_dir.exists() else []
            shortcode_files = [f for f in all_files if shortcode in f]
            
            if not shortcode_files:
                logger.warning(f"No files found for {shortcode} in {target_dir}")
                return (False, [], 0)
            
            # Verify each file exists and is accessible
            existing_files = []
            for filename in shortcode_files:
                file_path = target_dir / filename
                if file_path.exists() and file_path.is_file():
                    existing_files.append(filename)
            
            missing_count = len(shortcode_files) - len(existing_files)
            all_exist = missing_count == 0
            
            logger.info(f"[VERIFY] {shortcode}: {len(existing_files)} files exist, {missing_count} missing")
            return (all_exist, existing_files, missing_count)
            
        except Exception as e:
            logger.error(f"Error verifying files for {shortcode}: {e}")
            return (False, [], 0)
    
    def verify_topic_folder_copies(self, shortcode, topics):
        """Verify that files have been copied to all assigned topic folders
        
        Args:
            shortcode: Content shortcode
            topics: List of topic dicts with 'content_path' keys
            
        Returns:
            bool: True if files exist in all topic folders
        """
        try:
            # Get source files
            all_exist, source_files, _ = self.verify_downloaded_files(shortcode)
            if not all_exist or not source_files:
                logger.warning(f"[VERIFY_TOPICS] Source files not found for {shortcode}")
                return False
            
            # Check each topic folder
            all_copied = True
            for topic in topics:
                topic_path = topic.get('content_path', '')
                if not topic_path:
                    logger.warning(f"[VERIFY_TOPICS] Topic '{topic.get('topic_name')}' has no content_path")
                    all_copied = False
                    continue
                
                topic_dir = Path(topic_path)
                if not topic_dir.exists():
                    logger.warning(f"[VERIFY_TOPICS] Topic folder does not exist: {topic_path}")
                    all_copied = False
                    continue
                
                # Check if all source files exist in this topic folder
                import os
                topic_files = set(os.listdir(topic_dir)) if topic_dir.exists() else set()
                missing_in_topic = [f for f in source_files if f not in topic_files]
                
                if missing_in_topic:
                    logger.warning(f"[VERIFY_TOPICS] Topic '{topic.get('topic_name')}' missing {len(missing_in_topic)} file(s): {missing_in_topic[:3]}")
                    all_copied = False
                else:
                    logger.info(f"[VERIFY_TOPICS] Topic '{topic.get('topic_name')}' has all {len(source_files)} file(s)")
            
            return all_copied
            
        except Exception as e:
            logger.error(f"Error verifying topic folder copies for {shortcode}: {e}")
            return False
    
    def recopy_to_topics(self, shortcode):
        """Re-copy files to all assigned topic folders"""
        try:
            if not self.content_db or not self.content_db.db:
                QMessageBox.warning(self, "Database Error", "Database not available")
                return
            
            # Get all topics assigned to this content
            topic_ids = self.content_db.db.get_content_topics(shortcode)
            if not topic_ids:
                QMessageBox.information(self, "No Topics", f"Content {shortcode} has no topic assignments")
                return
            
            # Check if files exist
            downloaded_files = self.get_downloaded_files(shortcode)
            if not downloaded_files:
                QMessageBox.warning(
                    self, 
                    "No Files", 
                    f"Content {shortcode} has not been downloaded yet.\n\n"
                    "Files will be copied to topic folders automatically when downloaded."
                )
                return
            
            # Get full topic objects
            all_topics = self.content_db.db.get_all_topics()
            topics_to_copy = [t for t in all_topics if t['id'] in topic_ids]
            
            if not topics_to_copy:
                QMessageBox.warning(self, "Topic Error", "Could not find assigned topics")
                return
            
            # Show progress cursor
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            try:
                # Copy files to all assigned topics
                self.copy_files_to_multiple_topic_folders(shortcode, topics_to_copy)
                
                QApplication.restoreOverrideCursor()
                
                # Show success message
                self.statusBar().showMessage(
                    f"Files re-copied to {len(topics_to_copy)} topic folder(s)", 3000
                )
                logger.info(f"Re-copied files for {shortcode} to {len(topics_to_copy)} topic folder(s)")
            except Exception as e:
                QApplication.restoreOverrideCursor()
                logger.error(f"Error re-copying files: {e}")
                QMessageBox.critical(self, "Copy Error", f"Failed to copy files:\n{str(e)}")
        
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.error(f"Error in recopy_to_topics: {e}")
            QMessageBox.critical(self, "Error", f"Failed to re-copy files:\n{str(e)}")
            # Update all topics to Error
            for topic in topics:
                self.content_db.db.update_file_movement_status(
                    shortcode, topic['id'], 'Error', str(e)[:500]
                )
    
    def copy_files_to_topic_folder(self, shortcode, topic_id):
        """Copy all files for a shortcode to the topic's subfolder (legacy single-topic version)"""
        import shutil
        
        try:
            # Get topic details
            topic = self.content_db.db.get_topic(topic_id)
            if not topic:
                logger.error(f"Topic {topic_id} not found")
                return
            
            topic_path = topic.get('content_path') or topic.get('topic_name')
            if not topic_path:
                logger.error(f"Topic {topic_id} has no content_path")
                return
            
            # Sanitize path to ensure it's safe
            topic_path, is_absolute = self.sanitize_topic_path(topic_path)
            if not topic_path:
                logger.error(f"Topic {topic_id} has invalid content_path")
                return
            
            # Get downloaded files for this shortcode
            downloaded_files = self.get_downloaded_files(shortcode)
            if not downloaded_files:
                logger.info(f"No files to copy for {shortcode}")
                return
            
            # Build destination folder: use absolute path directly or combine with download_path
            if is_absolute:
                topic_folder = Path(topic_path)
            else:
                base_path = Path(self.download_path_input.text())
                topic_folder = base_path / Path(topic_path)
            topic_folder.mkdir(parents=True, exist_ok=True)
            
            # Copy each file
            copied_count = 0
            for file_info in downloaded_files:
                source_path = Path(file_info['path'])
                if source_path.exists():
                    dest_path = topic_folder / source_path.name
                    try:
                        shutil.copy2(source_path, dest_path)
                        logger.info(f"Copied {source_path.name} to {topic_folder}")
                        copied_count += 1
                    except Exception as e:
                        logger.error(f"Failed to copy {source_path.name}: {e}")
                else:
                    logger.warning(f"Source file not found: {source_path}")
            
            if copied_count > 0:
                logger.info(f"Copied {copied_count} file(s) for {shortcode} to topic folder: {topic_folder}")
                self.statusBar().showMessage(f"Copied {copied_count} file(s) to topic folder", 3000)
        except Exception as e:
            logger.error(f"Error copying files to topic folder: {e}")
            # Don't show error dialog - classification still succeeded
    
    def save_debug_info(self, shortcode, error_msg):
        """Save debug information to a file and return the file path"""
        from datetime import datetime
        import json
        
        try:
            # Get debug path from current account
            debug_path = None
            if self.current_username:
                account = self.account_manager.get_account(self.current_username)
                if account and account.get('debug_path'):
                    debug_path = Path(account['debug_path'])
            
            # If no debug path configured, warn and skip debug file creation
            if not debug_path:
                logger.warning(f"⚠️ No debug_path configured for {self.current_username} - cannot create debug file for {shortcode}")
                return  # Skip debug file creation
            
            # Create debug directory
            debug_path.mkdir(parents=True, exist_ok=True)
            
            # Create debug file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            debug_file = debug_path / f"{shortcode}_{timestamp}_error.txt"
            
            # Gather debug information
            debug_info = {
                "shortcode": shortcode,
                "timestamp": datetime.now().isoformat(),
                "username": self.current_username,
                "error_message": error_msg,
                "download_path": self.download_path_input.text(),
                "debug_path": str(debug_path)
            }
            
            # Write debug file
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"INSTAGRAM DOWNLOAD ERROR - {shortcode}\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Timestamp: {debug_info['timestamp']}\n")
                f.write(f"Account: {debug_info['username']}\n")
                f.write(f"Shortcode: {debug_info['shortcode']}\n")
                f.write(f"Instagram URL: https://www.instagram.com/p/{shortcode}/\n")
                f.write(f"Download Path: {debug_info['download_path']}\n")
                f.write(f"Debug Path: {debug_info['debug_path']}\n")
                f.write("\n" + "=" * 80 + "\n")
                f.write("ERROR MESSAGE\n")
                f.write("=" * 80 + "\n\n")
                f.write(error_msg)
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("DEBUG INFO (JSON)\n")
                f.write("=" * 80 + "\n\n")
                f.write(json.dumps(debug_info, indent=2))
            
            logger.info(f"Debug info saved to: {debug_file}")
            return str(debug_file)
            
        except Exception as e:
            logger.error(f"Failed to save debug info for {shortcode}: {e}")
            return None
    
    def open_debug_file(self, debug_file_path):
        """Open debug file in default text editor"""
        import subprocess
        import os
        
        try:
            if os.path.exists(debug_file_path):
                if sys.platform == 'win32':
                    os.startfile(debug_file_path)
                elif sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', debug_file_path])
                else:  # Linux
                    subprocess.Popen(['xdg-open', debug_file_path])
                logger.info(f"Opened debug file: {debug_file_path}")
            else:
                QMessageBox.warning(
                    self,
                    "File Not Found",
                    f"Debug file not found:\n{debug_file_path}"
                )
        except Exception as e:
            logger.error(f"Error opening debug file: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to open debug file:\n{str(e)}"
            )
    
    def find_and_open_debug_file(self, shortcode):
        """Find the most recent debug file for a shortcode and open it"""
        import os
        import glob
        
        try:
            # Get debug path from current account
            debug_path = None
            if self.current_username:
                account = self.account_manager.get_account(self.current_username)
                if account and account.get('debug_path'):
                    debug_path = Path(account['debug_path'])
            
            # If no debug path configured, show message
            if not debug_path:
                QMessageBox.information(
                    self,
                    "No Debug Path",
                    f"No debug_path is configured for {self.current_username}.\n\n"
                    f"Set the debug path in the Settings tab to enable debug file creation."
                )
                return
            
            if not debug_path.exists():
                QMessageBox.information(
                    self,
                    "No Debug Files",
                    f"No debug files found for {shortcode}.\n\n"
                    f"Debug files are created when downloads fail."
                )
                return
            
            # Find debug files matching this shortcode
            pattern = str(debug_path / f"{shortcode}_*_error.txt")
            debug_files = sorted(glob.glob(pattern), reverse=True)  # Most recent first
            
            if debug_files:
                # Open the most recent debug file
                self.open_debug_file(debug_files[0])
            else:
                QMessageBox.information(
                    self,
                    "No Debug Files",
                    f"No debug files found for {shortcode}.\n\n"
                    f"Debug Path: {debug_path}"
                )
        except Exception as e:
            logger.error(f"Error finding debug file: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to find debug file:\n{str(e)}"
            )
    
    def add_to_download_queue(self):
        """Add selected posts to download queue"""
        selected_rows = self.posts_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        added = 0
        target_dir = self.download_path_input.text()
        
        for index in selected_rows:
            row = index.row()
            # Get post data from caption column (which stores it) - column 4
            caption_item = self.posts_table.item(row, 4)
            post = caption_item.data(Qt.UserRole)
            if not post:
                logger.warning(f"No post data found for row {row}")
                continue
            shortcode = post['shortcode']
            
            # Check if already in queue
            already_in_queue = False
            for i in range(self.queue_table.rowCount()):
                queue_id_item = self.queue_table.item(i, 1)
                if queue_id_item and queue_id_item.text() == shortcode:
                    already_in_queue = True
                    break
            
            if not already_in_queue:
                # Add to database first
                if self.content_db and self.content_db.db:
                    try:
                        row_num = post.get('row_number', 0)
                        caption = post.get('caption', '')
                        success = self.content_db.db.add_to_queue(
                            content_id=shortcode,
                            row_number=row_num,
                            caption=caption,
                            target_directory=target_dir
                        )
                        if not success:
                            logger.warning(f"Queue item {shortcode} already in database queue")
                    except Exception as e:
                        logger.error(f"Failed to add {shortcode} to database queue: {e}")
                
                # Add row to queue table
                queue_row = self.queue_table.rowCount()
                self.queue_table.insertRow(queue_row)
                
                # Column 0: Row Number
                row_num = post.get('row_number', 0)
                row_item = QTableWidgetItem()
                row_item.setData(Qt.DisplayRole, row_num)
                self.queue_table.setItem(queue_row, 0, row_item)
                
                # Column 1: ID (Shortcode) - store post data here
                id_item = QTableWidgetItem(shortcode)
                id_item.setData(Qt.UserRole, post)  # Store full post data
                self.queue_table.setItem(queue_row, 1, id_item)
                
                # Column 2: Caption
                caption = post.get('caption', '')[:80] + "..." if len(post.get('caption', '')) > 80 else post.get('caption', '')
                caption_item = QTableWidgetItem(caption)
                self.queue_table.setItem(queue_row, 2, caption_item)
                
                # Column 3: File Name (will be set after download)
                filename_item = QTableWidgetItem("Pending...")
                filename_item.setForeground(Qt.gray)
                self.queue_table.setItem(queue_row, 3, filename_item)
                
                # Column 4: File Location
                location_item = QTableWidgetItem(target_dir)
                location_item.setForeground(Qt.gray)
                self.queue_table.setItem(queue_row, 4, location_item)
                
                # Column 5: Open button (will be added after download)
                # Leave empty for now
                
                added += 1
        
        self.statusBar().showMessage(f"Added {added} posts to download queue")
    
    def add_post_to_queue(self, post):
        """Add a single post to download queue (called from tile)"""
        if not post:
            return
        
        shortcode = post.get('shortcode', '')
        target_dir = self.download_path_input.text()
        
        # Check if already in queue
        for i in range(self.queue_table.rowCount()):
            queue_id_item = self.queue_table.item(i, 1)
            if queue_id_item and queue_id_item.text() == shortcode:
                self.statusBar().showMessage(f"{shortcode} is already in download queue")
                return
        
        # Add to queued shortcodes set
        self.queued_shortcodes.add(shortcode)
        
        # Update Download tab styling
        self.update_download_tab_style()
        
        # Add row to queue table
        queue_row = self.queue_table.rowCount()
        self.queue_table.insertRow(queue_row)
        
        # Column 0: Row Number
        row_num = post.get('row_number', 0)
        row_item = QTableWidgetItem()
        row_item.setData(Qt.DisplayRole, row_num)
        self.queue_table.setItem(queue_row, 0, row_item)
        
        # Column 1: ID (Shortcode) - store post data here
        id_item = QTableWidgetItem(shortcode)
        id_item.setData(Qt.UserRole, post)  # Store full post data
        self.queue_table.setItem(queue_row, 1, id_item)
        
        # Column 2: Caption
        caption = post.get('caption', '')[:80] + "..." if len(post.get('caption', '')) > 80 else post.get('caption', '')
        caption_item = QTableWidgetItem(caption)
        self.queue_table.setItem(queue_row, 2, caption_item)
        
        # Column 3: File Name (will be set after download)
        filename_item = QTableWidgetItem("Pending...")
        filename_item.setForeground(Qt.gray)
        self.queue_table.setItem(queue_row, 3, filename_item)
        
        # Column 4: File Location
        location_item = QTableWidgetItem(target_dir)
        location_item.setForeground(Qt.gray)
        self.queue_table.setItem(queue_row, 4, location_item)
        
        self.statusBar().showMessage(f"Added {shortcode} to download queue")
    
    def queue_undownloaded_on_page(self):
        """Queue all undownloaded posts on the current page"""
        if not self.filtered_posts:
            QMessageBox.information(self, "No Posts", "No posts to queue.")
            return
        
        # Determine which view mode we're in and get current page posts
        if self.current_view_mode == 'table':
            # For table view, use table pagination
            start_idx = self.table_current_page * self.table_items_per_page
            end_idx = min(start_idx + self.table_items_per_page, len(self.filtered_posts))
        else:
            # For tile view, use tile pagination
            start_idx = self.current_page * self.tiles_per_page
            end_idx = min(start_idx + self.tiles_per_page, len(self.filtered_posts))
        
        current_page_posts = self.filtered_posts[start_idx:end_idx]
        
        # Filter for undownloaded posts
        undownloaded_posts = []
        for post in current_page_posts:
            download_status = post.get('download_status', 'not_downloaded')
            shortcode = post.get('shortcode', '')
            
            # Skip if already downloaded or already in queue
            if download_status in ['downloaded', 'completed', 're-downloaded']:
                continue
            if shortcode in self.queued_shortcodes:
                continue
            
            undownloaded_posts.append(post)
        
        if not undownloaded_posts:
            QMessageBox.information(
                self, 
                "No Posts to Queue", 
                "All posts on this page are either already downloaded or already in the queue."
            )
            return
        
        # Confirm with user
        reply = QMessageBox.question(
            self,
            "Queue Undownloaded Posts",
            f"Queue {len(undownloaded_posts)} undownloaded post(s) from this page?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Add each post to queue
        target_dir = self.download_path_input.text()
        added = 0
        
        for post in undownloaded_posts:
            shortcode = post.get('shortcode', '')
            
            # Add to database queue if available
            if self.content_db and self.content_db.db:
                try:
                    row_num = post.get('row_number', 0)
                    caption = post.get('caption', '')
                    self.content_db.db.add_to_queue(
                        content_id=shortcode,
                        row_number=row_num,
                        caption=caption,
                        target_directory=target_dir
                    )
                except Exception as e:
                    logger.error(f"Failed to add {shortcode} to database queue: {e}")
            
            # Add to UI queue
            self.add_post_to_queue(post)
            added += 1
        
        # Refresh the view to show updated queue status (color changes)
        if self.current_view_mode == 'table':
            # Update table row colors
            for row in range(self.posts_table.rowCount()):
                caption_item = self.posts_table.item(row, 4)
                if caption_item:
                    post = caption_item.data(Qt.UserRole)
                    if post:
                        shortcode_clean = post.get('shortcode', '')
                        content_info = post.get('ContentInformation', {})
                        topic_id = content_info.get('topicID')
                        bg_color, _ = self.get_item_background_color(shortcode_clean, post.get('download_status', 'not_downloaded'), topic_id)
                        bg_qcolor = QColor(bg_color)
                        for col in range(self.posts_table.columnCount()):
                            item = self.posts_table.item(row, col)
                            if item:
                                item.setBackground(bg_qcolor)
        else:
            # Refresh tile view to show aqua background for queued items
            self.populate_tiles()
        
        self.statusBar().showMessage(f"Added {added} post(s) to download queue from current page")
        logger.info(f"Queued {added} undownloaded posts from current page")
        
        # Refresh views to update color
        self.refresh_current_view()
    
    # ========== MULTI-SELECT BATCH OPERATIONS ==========
    
    def toggle_tile_selection(self, shortcode, state):
        """Toggle selection state for a tile"""
        if state == Qt.Checked:
            self.selected_tiles.add(shortcode)
        else:
            self.selected_tiles.discard(shortcode)
        
        self.update_selection_ui()
    
    def update_selection_ui(self):
        """Update UI elements based on selection count"""
        count = len(self.selected_tiles)
        self.selection_count_label.setText(f"Selected: {count}")
        
        # Enable/disable batch operation buttons
        has_selection = count > 0
        self.batch_topic_btn.setEnabled(has_selection)
        self.batch_queue_btn.setEnabled(has_selection)
        self.batch_download_btn.setEnabled(has_selection)
        self.batch_ignore_btn.setEnabled(has_selection)
    
    def sync_selected_tiles_from_visible_checkboxes(self):
        """Sync selected_tiles with currently visible tile checkboxes on current page."""
        if self.current_view_mode != 'tiles' or self.current_page not in self.page_cache:
            return
        
        current_page_posts = self.page_cache[self.current_page]
        columns = self.calculate_tile_columns()
        
        # Update only items on current page based on visible checkbox state.
        for i, post in enumerate(current_page_posts):
            shortcode = (post.get('shortcode') or '').strip()
            if not shortcode:
                continue
            
            row = i // columns
            col = i % columns
            layout_item = self.tiles_grid.itemAtPosition(row, col)
            if not layout_item:
                continue
            tile_widget = layout_item.widget()
            if not tile_widget:
                continue
            
            checkbox = tile_widget.findChild(QCheckBox)
            if not checkbox:
                continue
            
            if checkbox.isChecked():
                self.selected_tiles.add(shortcode)
            else:
                self.selected_tiles.discard(shortcode)
        
        self.update_selection_ui()
    
    def select_all_tiles(self):
        """Select all visible tiles on current page"""
        if self.current_view_mode != 'tiles':
            QMessageBox.information(self, "Tile View Only", "Multi-select only works in Tile View mode.")
            return
        
        # Get posts on current page from cache
        if self.current_page not in self.page_cache:
            logger.warning("Current page not in cache, cannot select all")
            return
        
        current_page_posts = self.page_cache[self.current_page]
        
        # Add all to selected set and update checkboxes
        for i, post in enumerate(current_page_posts):
            shortcode = post.get('shortcode', '')
            if shortcode:
                self.selected_tiles.add(shortcode)
                
                # Update checkbox for this tile
                columns = self.calculate_tile_columns()
                row = i // columns
                col = i % columns
                layout_item = self.tiles_grid.itemAtPosition(row, col)
                if layout_item:
                    tile_widget = layout_item.widget()
                    if tile_widget:
                        # Find checkbox in tile and check it
                        for child in tile_widget.findChildren(QCheckBox):
                            child.setChecked(True)
        
        self.update_selection_ui()
        logger.info(f"Selected all {len(current_page_posts)} tiles on current page")

    def select_remaining_tiles(self):
        """Select visible tiles that are not downloaded and not topic-assigned."""
        if self.current_view_mode != 'tiles':
            QMessageBox.information(self, "Tile View Only", "Multi-select only works in Tile View mode.")
            return

        # Get posts on current page from cache
        if self.current_page not in self.page_cache:
            logger.warning("Current page not in cache, cannot select remaining")
            return

        current_page_posts = self.page_cache[self.current_page]

        # Replace current selection with only the qualifying remaining items
        selected_count = 0
        for i, post in enumerate(current_page_posts):
            shortcode = (post.get('shortcode') or '').strip()
            if not shortcode:
                continue

            download_status = post.get('download_status', 'not_downloaded')
            is_downloaded = self._is_downloaded_status(download_status)
            has_topic_assignment = self._post_is_topic_assigned_and_needs_download(post, allow_db_lookup=True)
            should_select = (not is_downloaded) and (not has_topic_assignment)

            columns = self.calculate_tile_columns()
            row = i // columns
            col = i % columns
            layout_item = self.tiles_grid.itemAtPosition(row, col)
            if layout_item:
                tile_widget = layout_item.widget()
                if tile_widget:
                    for child in tile_widget.findChildren(QCheckBox):
                        child.setChecked(should_select)

            if should_select:
                self.selected_tiles.add(shortcode)
                selected_count += 1
            else:
                self.selected_tiles.discard(shortcode)

        self.update_selection_ui()
        logger.info(f"Selected {selected_count} remaining tile(s) on current page")
    
    def deselect_all_tiles(self):
        """Clear all tile selections"""
        # Create snapshot to avoid modification during iteration
        selected_snapshot = list(self.selected_tiles)
        self.selected_tiles.clear()
        
        # Update checkbox states for all tiles that were selected (avoid full repopulate)
        if self.current_view_mode == 'tiles' and self.current_page in self.page_cache:
            for shortcode in selected_snapshot:
                # Find the tile and update its checkbox
                for i, post in enumerate(self.page_cache[self.current_page]):
                    if post.get('shortcode') == shortcode:
                        columns = self.calculate_tile_columns()
                        row = i // columns
                        col = i % columns
                        layout_item = self.tiles_grid.itemAtPosition(row, col)
                        if layout_item:
                            tile_widget = layout_item.widget()
                            if tile_widget:
                                # Find checkbox in tile and uncheck it
                                for child in tile_widget.findChildren(QCheckBox):
                                    child.setChecked(False)
                        break
        
        self.update_selection_ui()
        logger.info("Cleared all tile selections")
    
    def set_topic_for_selected(self):
        """Assign topics to all selected posts using the full classification dialog"""
        if not self.selected_tiles:
            return
        
        if not self.content_db:
            QMessageBox.warning(self, "No Database", "Database not initialized.")
            return
        
        # Get list of topics
        topics = self.content_db.db.get_all_topics()
        if not topics:
            QMessageBox.warning(self, "No Topics", "No topics found. Create topics in the Topics tab first.")
            return
        
        # Create a snapshot of selected tiles to avoid modification during iteration
        selected_shortcodes = list(self.selected_tiles)
        logger.info(f"[BATCH_TOPIC] Starting batch topic assignment for {len(selected_shortcodes)} items: {selected_shortcodes}")
        
        try:
            # Create classification dialog (simplified version for batch operations)
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Assign Topics to {len(selected_shortcodes)} Selected Items")
            dialog.setMinimumWidth(500)
            dialog.setMinimumHeight(500)
            
            layout = QVBoxLayout(dialog)
            
            # Info label
            info_label = QLabel(f"Select one or more topics to assign to all {len(selected_shortcodes)} selected items.\nFiles will be copied to each selected topic folder.")
            info_label.setWordWrap(True)
            info_label.setStyleSheet("padding: 10px; background-color: #e7f3ff; color: #0066cc; border: 1px solid #0066cc; border-radius: 4px;")
            layout.addWidget(info_label)
            
            # Topic tree with checkboxes
            topic_tree = QTreeWidget()
            topic_tree.setHeaderLabels(["Topic Name", "Path"])
            topic_tree.setColumnWidth(0, 300)
            topic_tree.setColumnWidth(1, 150)
            
            # Build hierarchical topic display
            topic_map = {}
            for topic in topics:
                topic_map[topic['id']] = topic
            
            # Build parent-child relationships
            children_map = {}
            root_topics = []
            for topic in topics:
                parent_id = topic.get('parent_topic_id')
                if parent_id is None:
                    root_topics.append(topic)
                else:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(topic)
            
            # Recursively add topics to tree with checkboxes
            def add_topic_to_tree(topic, parent_item=None):
                item = QTreeWidgetItem()
                item.setText(0, topic['topic_name'])
                item.setText(1, topic.get('content_path', ''))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)  # Start unchecked for batch operations
                item.setData(0, Qt.UserRole, topic)  # Store full topic data
                
                if parent_item:
                    parent_item.addChild(item)
                else:
                    topic_tree.addTopLevelItem(item)
                
                # Add children
                topic_id = topic['id']
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_to_tree(child_topic, item)
                
                return item
            
            # Add all root topics and their children
            for root_topic in root_topics:
                add_topic_to_tree(root_topic)

            self._restore_topic_tree_expansion_state(topic_tree)
            # Restore scroll position after tree is built (use QTimer to ensure UI is ready)
            QTimer.singleShot(0, lambda: self._restore_topic_tree_scroll_position(topic_tree))
            
            topic_tree.itemExpanded.connect(lambda _item: self._save_topic_tree_expansion_state(topic_tree))
            topic_tree.itemCollapsed.connect(lambda _item: self._save_topic_tree_expansion_state(topic_tree))
            
            # Save both expansion state and scroll position when dialog closes
            def save_all_state(result):
                self._save_topic_tree_expansion_state(topic_tree)
                self._save_topic_tree_scroll_position(topic_tree)
            dialog.finished.connect(save_all_state)
            
            layout.addWidget(topic_tree)
            
            # Buttons
            button_layout = QHBoxLayout()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(dialog.reject)
            button_layout.addWidget(cancel_btn)
            
            button_layout.addStretch()
            
            save_btn = QPushButton(f"Assign Topics to {len(selected_shortcodes)} Items")
            save_btn.setDefault(True)
            save_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; padding: 8px; }")
            save_btn.clicked.connect(lambda: self.apply_batch_topic_assignment(selected_shortcodes, topic_tree, dialog))
            button_layout.addWidget(save_btn)
            
            layout.addLayout(button_layout)
            
            dialog.exec_()
            
        except Exception as e:
            logger.error(f"[BATCH_TOPIC] Error showing dialog: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to show topic assignment dialog:\n{str(e)}")
    
    def apply_batch_topic_assignment(self, shortcodes, topic_tree, dialog):
        """Apply selected topics to all shortcodes in batch"""
        try:
            # Get selected topics from tree
            selected_topics = []
            
            def get_checked_topics(item):
                if item.checkState(0) == Qt.Checked:
                    topic_data = item.data(0, Qt.UserRole)
                    if topic_data:
                        selected_topics.append(topic_data)
                
                # Check children
                for i in range(item.childCount()):
                    get_checked_topics(item.child(i))
            
            # Check all top-level items
            for i in range(topic_tree.topLevelItemCount()):
                get_checked_topics(topic_tree.topLevelItem(i))
            
            if not selected_topics:
                QMessageBox.warning(dialog, "No Topics Selected", "Please select at least one topic.")
                return
            
            logger.info(f"[BATCH_TOPIC] Assigning {len(selected_topics)} topic(s) to {len(shortcodes)} items")
            
            # Apply topics to all selected shortcodes
            success_count = 0
            error_count = 0
            
            for shortcode in shortcodes:
                try:
                    logger.info(f"[BATCH_TOPIC] Processing {shortcode}...")
                    
                    # Assign each selected topic
                    for topic in selected_topics:
                        topic_id = topic['id']
                        self.content_db.db.add_topic_assignment(shortcode, topic_id)
                        logger.info(f"[BATCH_TOPIC] Assigned topic {topic_id} ({topic['topic_name']}) to {shortcode}")
                    
                    success_count += 1
                    
                    # Update cache for this shortcode (only if on current page)
                    if self.current_page in self.page_cache:
                        updated_entry = self.content_db.db.get_content_entry(shortcode)
                        if updated_entry:
                            # Find the post in cache
                            target_post = None
                            post_index = None
                            for i, post in enumerate(self.page_cache[self.current_page]):
                                if post.get('shortcode') == shortcode:
                                    target_post = post
                                    post_index = i
                                    break
                            
                            if target_post:
                                # Update ContentInformation fields
                                if 'ContentInformation' not in target_post:
                                    target_post['ContentInformation'] = {}
                                if 'ContentInformation' in updated_entry:
                                    target_post['ContentInformation']['topicID'] = updated_entry['ContentInformation'].get('topicID')
                                logger.info(f"[BATCH_TOPIC] Cache updated for {shortcode}")
                                
                                # Update tile appearance
                                if post_index is not None and self.current_view_mode == 'tiles':
                                    try:
                                        columns = self.calculate_tile_columns()
                                        row = post_index // columns
                                        col = post_index % columns
                                        layout_item = self.tiles_grid.itemAtPosition(row, col)
                                        if layout_item and layout_item.widget():
                                            self.update_tile_appearance(layout_item.widget(), target_post, shortcode)
                                            logger.info(f"[BATCH_TOPIC] Tile appearance updated for {shortcode}")
                                    except Exception as tile_error:
                                        logger.error(f"[BATCH_TOPIC] Error updating tile for {shortcode}: {tile_error}")
                    
                    # Copy files to topic folders
                    if len(selected_topics) > 0:
                        try:
                            self.copy_files_to_multiple_topic_folders(shortcode, selected_topics)
                        except Exception as copy_error:
                            logger.error(f"[BATCH_TOPIC] Error copying files for {shortcode}: {copy_error}")
                    
                except Exception as e:
                    error_count += 1
                    logger.error(f"[BATCH_TOPIC] Failed to process {shortcode}: {e}", exc_info=True)
            
            # Close dialog
            dialog.accept()
            
            # Show results
            topic_names = ", ".join([t['topic_name'] for t in selected_topics])
            if error_count > 0:
                QMessageBox.warning(
                    self, "Batch Assignment Complete", 
                    f"Assigned topics ({topic_names}) to {success_count} of {len(shortcodes)} items.\n\n"
                    f"{error_count} error(s) occurred. Check console log for details."
                )
            else:
                QMessageBox.information(
                    self, "Topics Assigned", 
                    f"Successfully assigned topics ({topic_names}) to all {success_count} selected items."
                )

            self.update_topic_assigned_download_button_text()
            
            # Clear selection
            self.deselect_all_tiles()
            logger.info(f"[BATCH_TOPIC] Batch topic assignment complete: {success_count} success, {error_count} errors")
            
        except Exception as e:
            logger.error(f"[BATCH_TOPIC] Error in apply_batch_topic_assignment: {e}", exc_info=True)
            QMessageBox.critical(dialog, "Error", f"Failed to apply topic assignments:\n{str(e)}")
    
    def queue_selected(self):
        """Add all selected posts to download queue"""
        # Ensure selection set matches visible checkboxes before processing
        self.sync_selected_tiles_from_visible_checkboxes()
        
        if not self.selected_tiles:
            QMessageBox.information(self, "No Selection", "Select one or more tiles first.")
            return
        
        target_dir = self.download_path_input.text()
        if not target_dir:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        # Find posts by shortcode (use page_cache first; saved_posts is deprecated)
        selected_posts = []
        seen = set()
        
        cache_snapshot = list(self.page_cache.items())
        for page_num, posts in cache_snapshot:
            for post in posts:
                shortcode = post.get('shortcode')
                if shortcode in self.selected_tiles and shortcode not in seen:
                    # Skip already downloaded or queued
                    if post.get('download_status') in ['downloaded', 'completed', 're-downloaded']:
                        continue
                    if shortcode in self.queued_shortcodes:
                        continue
                    selected_posts.append(post)
                    seen.add(shortcode)
        
        # Backward compatibility fallback
        if len(seen) < len(self.selected_tiles):
            for post in self.saved_posts:
                shortcode = post.get('shortcode')
                if shortcode in self.selected_tiles and shortcode not in seen:
                    if post.get('download_status') in ['downloaded', 'completed', 're-downloaded']:
                        continue
                    if shortcode in self.queued_shortcodes:
                        continue
                    selected_posts.append(post)
                    seen.add(shortcode)
        
        if not selected_posts:
            QMessageBox.information(
                self, "Nothing to Queue", 
                "Selected posts are either already downloaded or already in queue."
            )
            return
        
        # Add to queue
        added = 0
        for post in selected_posts:
            shortcode = post.get('shortcode', '')
            
            # Add to database queue
            if self.content_db and self.content_db.db:
                try:
                    row_num = post.get('row_number', 0)
                    caption = post.get('caption', '')
                    self.content_db.db.add_to_queue(
                        content_id=shortcode,
                        row_number=row_num,
                        caption=caption,
                        target_directory=target_dir
                    )
                except Exception as e:
                    logger.error(f"Failed to add {shortcode} to database queue: {e}")
            
            # Add to UI queue
            self.add_post_to_queue(post)
            added += 1
        
        QMessageBox.information(self, "Queued", f"Added {added} posts to download queue.")
        
        # Clear selection and refresh
        self.deselect_all_tiles()
        self.refresh_current_view()
        logger.info(f"Queued {added} selected posts")
    
    def download_selected_now(self):
        """Download all selected posts immediately"""
        # Ensure selection set matches visible checkboxes before processing
        self.sync_selected_tiles_from_visible_checkboxes()
        
        if not self.selected_tiles:
            QMessageBox.information(self, "No Selection", "Select one or more tiles first.")
            return
        
        if not self.instagram_manager:
            QMessageBox.warning(self, "Not Logged In", "Please log in first.")
            return
        
        target_dir_str = self.download_path_input.text()
        if not target_dir_str:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        # Find posts by shortcode (use page_cache first; saved_posts is deprecated)
        selected_posts = []
        seen = set()
        
        cache_snapshot = list(self.page_cache.items())
        for page_num, posts in cache_snapshot:
            for post in posts:
                shortcode = post.get('shortcode')
                if shortcode in self.selected_tiles and shortcode not in seen:
                    selected_posts.append(post)
                    seen.add(shortcode)
        
        # Backward compatibility fallback
        if len(seen) < len(self.selected_tiles):
            for post in self.saved_posts:
                shortcode = post.get('shortcode')
                if shortcode in self.selected_tiles and shortcode not in seen:
                    selected_posts.append(post)
                    seen.add(shortcode)
        
        if not selected_posts:
            QMessageBox.information(self, "No Posts", "Selected tiles were not found in loaded page data.")
            return
        
        # Confirm download
        reply = QMessageBox.question(
            self, "Download Selected", 
            f"Download {len(selected_posts)} selected posts immediately?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Get shortcodes
        shortcodes = [p.get('shortcode', '') for p in selected_posts if p.get('shortcode')]
        
        # Start download in background thread
        target_dir = Path(target_dir_str)
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'batch_download',
            f'Download Selected ({len(shortcodes)} posts)',
            None
        )
        
        # Create download thread
        download_thread = DownloadThread(self.instagram_manager, shortcodes, target_dir, process_id)
        
        # Update process with thread reference
        process = self.process_manager.get_process(process_id)
        if process:
            process['thread'] = download_thread
            process['total'] = len(shortcodes)
        
        download_thread.progress.connect(lambda c, t: self.process_manager.update_process(process_id, current=c, total=t))
        download_thread.status.connect(lambda msg: self.statusBar().showMessage(msg))
        download_thread.download_complete.connect(self.handle_single_download_complete)
        download_thread.finished.connect(lambda s, f: self.on_download_thread_finished(download_thread, process_id))
        
        # Store thread
        self.active_download_threads.append(download_thread)
        
        download_thread.start()
        
        QMessageBox.information(self, "Download Started", f"Downloading {len(shortcodes)} posts in background.")
        
        # Clear selection and refresh
        self.deselect_all_tiles()
        self.refresh_current_view()

    def ignore_selected(self):
        """Mark all selected posts as ignored in a single batch operation."""
        # Ensure selection set matches visible checkboxes before processing
        self.sync_selected_tiles_from_visible_checkboxes()

        if not self.selected_tiles:
            QMessageBox.information(self, "No Selection", "Select one or more tiles first.")
            return

        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return

        selected_shortcodes = [s for s in self.selected_tiles if s]
        reply = QMessageBox.question(
            self,
            "Ignore Selected",
            f"Mark {len(selected_shortcodes)} selected item(s) as ignored?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        success_count = 0
        failed_count = 0

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)

            # Update DB status first
            for shortcode in selected_shortcodes:
                try:
                    success = self.content_db.db.update_content_entry(shortcode, {'download_status': 'ignored'})
                    if success:
                        success_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(f"[IGNORE_SELECTED] Failed to ignore {shortcode}: {e}")

            # Update in-memory saved_posts
            selected_set = set(selected_shortcodes)
            for post in self.saved_posts:
                shortcode = post.get('shortcode')
                if shortcode in selected_set:
                    post['download_status'] = 'ignored'

            # Update in-memory page cache
            cache_snapshot = list(self.page_cache.items())
            for _page_num, posts in cache_snapshot:
                for post in posts:
                    shortcode = post.get('shortcode')
                    if shortcode in selected_set:
                        post['download_status'] = 'ignored'

            logger.info(f"[IGNORE_SELECTED] Ignored {success_count} selected items (failed: {failed_count})")

        finally:
            QApplication.restoreOverrideCursor()

        # Clear selection and refresh once
        self.deselect_all_tiles()
        self.refresh_current_view()

        if failed_count > 0:
            QMessageBox.warning(
                self,
                "Ignore Selected Completed",
                f"Ignored {success_count} item(s). {failed_count} item(s) failed."
            )
        else:
            self.statusBar().showMessage(f"Ignored {success_count} selected item(s)", 3000)
    
    def download_page_now(self):
        """Download all posts on current page immediately"""
        if not self.instagram_manager:
            QMessageBox.warning(self, "Not Logged In", "Please log in first.")
            return
        
        target_dir_str = self.download_path_input.text()
        if not target_dir_str:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        # Get posts from current page cache
        if self.current_page not in self.page_cache:
            QMessageBox.warning(self, "No Posts", "Current page has no posts loaded.")
            return
        
        page_posts = self.page_cache[self.current_page]
        
        if not page_posts:
            QMessageBox.information(self, "No Posts", "Current page has no posts.")
            return
        
        # Get shortcodes from page
        shortcodes = [p.get('shortcode', '') for p in page_posts if p.get('shortcode')]
        
        if not shortcodes:
            QMessageBox.warning(self, "No Valid Posts", "No valid posts found on current page.")
            return
        
        # Confirm download
        reply = QMessageBox.question(
            self, "Download Page", 
            f"Download all {len(shortcodes)} posts on page {self.current_page + 1}?\n\nFiles will be copied to assigned topic folders.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        logger.info(f"[DOWNLOAD_PAGE] Starting download of {len(shortcodes)} posts from page {self.current_page + 1}")
        
        # Start download in background thread
        target_dir = Path(target_dir_str)
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'page_download',
            f'Download Page {self.current_page + 1} ({len(shortcodes)} posts)',
            None
        )
        
        # Create download thread
        download_thread = DownloadThread(self.instagram_manager, shortcodes, target_dir, process_id)
        
        # Update process with thread reference
        process = self.process_manager.get_process(process_id)
        if process:
            process['thread'] = download_thread
            process['total'] = len(shortcodes)
        
        download_thread.progress.connect(lambda c, t: self.process_manager.update_process(process_id, current=c, total=t))
        download_thread.status.connect(lambda msg: self.statusBar().showMessage(msg))
        download_thread.download_complete.connect(lambda shortcode, success, target_dir, error_msg, files, metadata: 
            self.handle_single_download_complete(shortcode, success, target_dir, error_msg, files, metadata, process_id))
        download_thread.finished.connect(lambda s, f: self.on_download_thread_finished(download_thread, process_id, s, f))
        
        # Store thread
        self.active_download_threads.append(download_thread)
        
        download_thread.start()
        
        QMessageBox.information(self, "Download Started", f"Downloading {len(shortcodes)} posts from page {self.current_page + 1} in background.")
        logger.info(f"[DOWNLOAD_PAGE] Download thread started for page {self.current_page + 1}")
        logger.info(f"Started download of {len(shortcodes)} selected posts")
    
    def download_topic_assigned_now(self):
        """Download all topic-assigned posts on current page immediately"""
        if not self.instagram_manager:
            QMessageBox.warning(self, "Not Logged In", "Please log in first.")
            return
        
        target_dir_str = self.download_path_input.text()
        if not target_dir_str:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        # Get posts from current page cache
        if self.current_page not in self.page_cache:
            QMessageBox.warning(self, "No Posts", "Current page has no posts loaded.")
            return

        page_posts = self.page_cache[self.current_page]

        if not page_posts:
            QMessageBox.information(self, "No Posts", "Current page has no posts.")
            return

        topic_assigned_posts = self.get_topic_assigned_download_candidates_for_current_page(allow_db_lookup=True)
        
        if not topic_assigned_posts:
            QMessageBox.information(
                self, 
                "No Topic-Assigned Posts", 
                "No undownloaded posts with topic assignments found on current page."
            )
            return
        
        # Get shortcodes
        shortcodes = [p.get('shortcode', '') for p in topic_assigned_posts if p.get('shortcode')]
        
        if not shortcodes:
            QMessageBox.warning(self, "No Valid Posts", "No valid topic-assigned posts found.")
            return
        
        # Confirm download
        reply = QMessageBox.question(
            self, "Download Topic-Assigned Items", 
            f"Download {len(shortcodes)} topic-assigned posts from page {self.current_page + 1}?\n\nFiles will be copied to their assigned topic folders.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        logger.info(f"[DOWNLOAD_TOPIC_ASSIGNED] Starting download of {len(shortcodes)} topic-assigned posts from page {self.current_page + 1}")
        
        # Start download in background thread
        target_dir = Path(target_dir_str)
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'topic_assigned_download',
            f'Download Topic-Assigned (Page {self.current_page + 1}, {len(shortcodes)} posts)',
            None
        )
        
        # Create download thread
        download_thread = DownloadThread(self.instagram_manager, shortcodes, target_dir, process_id)
        
        # Update process with thread reference
        process = self.process_manager.get_process(process_id)
        if process:
            process['thread'] = download_thread
            process['total'] = len(shortcodes)
        
        download_thread.progress.connect(lambda c, t: self.process_manager.update_process(process_id, current=c, total=t))
        download_thread.status.connect(lambda msg: self.statusBar().showMessage(msg))
        download_thread.download_complete.connect(lambda shortcode, success, target_dir, error_msg, files, metadata: 
            self.handle_single_download_complete(shortcode, success, target_dir, error_msg, files, metadata, process_id))
        download_thread.finished.connect(lambda s, f: self.on_download_thread_finished(download_thread, process_id, s, f))
        
        # Store thread
        self.active_download_threads.append(download_thread)
        
        download_thread.start()
        
        QMessageBox.information(self, "Download Started", f"Downloading {len(shortcodes)} topic-assigned posts in background.")
        logger.info(f"[DOWNLOAD_TOPIC_ASSIGNED] Download thread started for {len(shortcodes)} posts")

    def _is_downloaded_status(self, download_status):
        """Return True if status indicates the content is already downloaded."""
        return download_status in ['downloaded', 'completed', 're-downloaded']

    def _is_error_status(self, download_status):
        """Return True if status indicates previous download failure/issues."""
        return download_status in ['error', 'failed', 'success_with_issues']

    def _post_is_topic_assigned_and_needs_download(self, post, allow_db_lookup=False):
        """Return True if post has a topic assignment, needs download, and is not an error item."""
        shortcode = (post.get('shortcode') or '').strip()
        if not shortcode:
            return False

        download_status = post.get('download_status', 'not_downloaded')
        if self._is_downloaded_status(download_status):
            return False

        # Skip items that previously failed; do not retry these in bulk topic-assigned downloads.
        if self._is_error_status(download_status):
            return False

        content_info = post.get('ContentInformation', {})
        topic_id = content_info.get('topicID')

        if topic_id is None and allow_db_lookup and self.content_db and self.content_db.db:
            try:
                entry = self.content_db.db.get_content_entry(shortcode)
                if entry:
                    db_content_info = entry.get('ContentInformation', {})
                    topic_id = db_content_info.get('topicID')
            except Exception as e:
                logger.debug(f"Error checking topic assignment for {shortcode}: {e}")

            # Fallback: check topic assignment tables directly.
            if topic_id is None:
                try:
                    topic_ids = self.content_db.db.get_content_topics(shortcode)
                    if topic_ids:
                        topic_id = topic_ids[0]
                except Exception as e:
                    logger.debug(f"Error checking topic assignment list for {shortcode}: {e}")

        return topic_id is not None

    def get_topic_assigned_download_candidates_for_current_page(self, allow_db_lookup=False):
        """Get current-page posts that are topic-assigned and still need download."""
        if not hasattr(self, 'page_cache') or not hasattr(self, 'current_page'):
            return []

        if self.current_page not in self.page_cache:
            return []

        page_posts = self.page_cache[self.current_page]
        if not page_posts:
            return []

        return [
            post for post in page_posts
            if self._post_is_topic_assigned_and_needs_download(post, allow_db_lookup=allow_db_lookup)
        ]

    def update_topic_assigned_download_button_text(self):
        """Update the Download Topic-Assigned button label with current-page eligible count."""
        if not hasattr(self, 'download_topic_assigned_btn'):
            return

        count = len(self.get_topic_assigned_download_candidates_for_current_page(allow_db_lookup=True))
        self.download_topic_assigned_btn.setText(f"🏷️ Download [{count}] Topic-Assigned")
    
    # ========== END MULTI-SELECT BATCH OPERATIONS ==========
    
    def download_post_now(self, post):
        """Download a single post immediately in a background thread"""
        if not post or not self.instagram_manager:
            return
        
        shortcode = post.get('shortcode', '')
        target_dir_str = self.download_path_input.text()
        
        logger.info("=" * 60)
        logger.info(f"DOWNLOAD POST NOW: {shortcode}")
        logger.info(f"  download_path_input.text() = {target_dir_str}")
        logger.info("=" * 60)
        
        if not target_dir_str:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        # Convert to Path object (instagram_manager expects Path, not string)
        target_dir = Path(target_dir_str)
        
        logger.info(f"  Using target_dir: {target_dir}")
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'single_download',
            f'Download: {shortcode}',
            None
        )
        
        # Create thread for single download
        download_thread = DownloadThread(self.instagram_manager, [shortcode], target_dir, process_id)
        
        # Update process with thread reference
        process = self.process_manager.get_process(process_id)
        if process:
            process['thread'] = download_thread
            process['total'] = 1
        
        download_thread.progress.connect(lambda c, t: self.process_manager.update_process(process_id, current=c, total=t))
        download_thread.download_complete.connect(lambda shortcode, success, target_dir, error_msg, files, metadata: 
            self.handle_single_download_complete(shortcode, success, target_dir, error_msg, files, metadata, process_id))
        download_thread.finished.connect(lambda s, f: self.on_download_thread_finished(download_thread, process_id, s, f))
        
        # Store thread to prevent garbage collection
        self.active_download_threads.append(download_thread)
        
        download_thread.start()
        self.statusBar().showMessage(f"Downloading {shortcode}...", 2000)
    
    def on_download_thread_finished(self, thread, process_id=None, success_count=0, failed_count=0):
        """Clean up finished download thread"""
        if thread in self.active_download_threads:
            self.active_download_threads.remove(thread)
        
        # Update process status based on success/failure
        if process_id:
            if failed_count > 0 and success_count == 0:
                # All downloads failed
                self.process_manager.update_process(process_id, status='failed')
            elif failed_count > 0:
                # Some failed, some succeeded
                self.process_manager.update_process(process_id, status='completed_with_errors')
            else:
                # All succeeded
                self.process_manager.update_process(process_id, status='completed')
        
        if failed_count > 0:
            self.statusBar().showMessage(f"Download failed ({failed_count} error(s))", 3000)
        else:
            self.statusBar().showMessage("Download complete", 3000)
    
    def handle_single_download_complete(self, shortcode, success, target_dir, error_msg, files, metadata, process_id=None):
        """Handle completion of a single 'Download Now' operation"""
        if success:
            # Determine if this was a re-download (files existed but database said downloaded)
            was_redownload = False
            existing_entry = None
            if self.content_db:
                try:
                    existing_entry = self.content_db.db.get_content_entry(shortcode)
                    if existing_entry:
                        old_status = existing_entry.get('download_status', '')
                        # Check if it was marked as downloaded but files were missing
                        if old_status in ['downloaded', 'completed', 're-downloaded']:
                            all_exist, existing_files, missing = self.verify_downloaded_files(shortcode)
                            if not all_exist or len(files) > len(existing_files):
                                was_redownload = True
                                logger.info(f"[DOWNLOAD] {shortcode} was a re-download (old status: {old_status})")
                except Exception as e:
                    logger.error(f"Error checking if re-download: {e}")
            
            # Update post in saved_posts
            final_status = 're-downloaded' if was_redownload else 'completed'
            for post in self.saved_posts:
                if post.get('shortcode') == shortcode:
                    post['download_status'] = final_status
                    break
            
            # Also update in page cache if present
            cache_snapshot = list(self.page_cache.items())
            for page_num, posts in cache_snapshot:
                for post in posts:
                    if post.get('shortcode') == shortcode:
                        post['download_status'] = final_status
                        logger.info(f"[SINGLE_DOWNLOAD] Updated page cache for {shortcode}: status -> {final_status}")
                        break
            
            # Update database with file information
            if self.content_db and files:
                try:
                    entry_exists = existing_entry is not None
                    
                    if not entry_exists:
                        # Create entry first using metadata
                        post_data = {
                            'shortcode': shortcode,
                            'typename': metadata.get('typename', 'Unknown'),
                            'owner': metadata.get('owner', ''),
                            'text': metadata.get('caption', ''),
                            'download_status': final_status
                        }
                        self.content_db.save_post(post_data)
                        logger.info(f"Created database entry for {shortcode}")
                    
                    # Update status and caption
                    updates = {
                        'download_status': final_status,
                        'text': metadata.get('caption', '')
                    }
                    
                    # Save tags to validation_log
                    tags = metadata.get('tags', '')
                    if tags:
                        updates['validation_log'] = f"Tags: {tags}"
                        logger.info(f"Saved tags for {shortcode}: {tags}")
                    
                    self.content_db.db.update_content_entry(shortcode, updates)
                    
                    # Save each file to database
                    caption = metadata.get('caption', '')
                    for i, filename in enumerate(files):
                        file_path = os.path.join(target_dir, filename)
                        file_info = {
                            'FileNumber': i + 1,
                            'FileName': filename,
                            'DownloadFilename': filename,
                            'FileDestinationPath': file_path,
                            'FileDownloadStatus': 'downloaded',
                            'FileType': 'video' if filename.endswith('.mp4') else 'image',
                            'FileSaveStatus': 'completed',
                            'FileCaption': caption,
                            'FileTags': tags
                        }
                        
                        try:
                            file_id = self.content_db.db.add_file(shortcode, file_info)
                            logger.info(f"Saved file {i+1}/{len(files)} to database: {filename} (file_id: {file_id})")
                        except Exception as e:
                            logger.error(f"Error saving file to database: {e}")
                    
                    logger.info(f"Updated database with {len(files)} file(s) for {shortcode}")
                    
                except Exception as e:
                    logger.error(f"Error updating database for {shortcode}: {e}")
            
            # Verify files exist before proceeding to topic assignments
            all_exist, existing_files, missing = self.verify_downloaded_files(shortcode)
            if not all_exist:
                logger.warning(f"[DOWNLOAD] {shortcode} completed but {missing} file(s) are missing!")
            
            # Check for topic assignments and copy files
            topics_success = False
            if self.content_db:
                topics_success = self.process_pending_topic_assignments(shortcode)
                if not topics_success:
                    logger.warning(f"[DOWNLOAD] {shortcode} topic folder copying incomplete")
            
            # Refresh only the specific tile/row for this shortcode
            self.refresh_single_item(shortcode)
            
            # Show appropriate message
            if len(files) > 0:
                status_msg = "Re-downloaded" if was_redownload else "Downloaded"
                logger.info(f"{status_msg} {shortcode}: {len(files)} files")
                topics_msg = " and copied to topics" if topics_success else ""
                self.statusBar().showMessage(f"{status_msg} {shortcode}: {len(files)} file(s){topics_msg}", 3000)
            else:
                logger.info(f"Post {shortcode} already downloaded (files exist, database updated)")
                self.statusBar().showMessage(f"{shortcode} already downloaded (entry updated)", 3000)
        else:
            # Handle failure - update status to 'error' for visibility
            logger.error(f"Download Now failed for {shortcode}: {error_msg}")
            
            # Update post in saved_posts
            for post in self.saved_posts:
                if post.get('shortcode') == shortcode:
                    post['download_status'] = 'error'
                    break
            
            # Update in page cache
            cache_snapshot = list(self.page_cache.items())
            for page_num, posts in cache_snapshot:
                for i, post in enumerate(posts):
                    if post.get('shortcode') == shortcode:
                        post['download_status'] = 'error'
                        logger.info(f"[SINGLE_DOWNLOAD] Updated page cache for {shortcode}: status -> error")
                        
                        # If this is the current page, update the tile appearance to show RED
                        if page_num == self.current_page and self.current_view_mode == 'tiles':
                            columns = self.calculate_tile_columns()
                            row = i // columns
                            col = i % columns
                            item = self.tiles_grid.itemAtPosition(row, col)
                            if item and item.widget():
                                tile_widget = item.widget()
                                self.update_tile_appearance(tile_widget, post, shortcode)
                                logger.info(f"[SINGLE_DOWNLOAD] Updated tile appearance for {shortcode} at ({row}, {col}) - should be RED")
                        break
            
            # Update database
            if self.content_db:
                try:
                    existing_entry = self.content_db.db.get_content_entry(shortcode)
                    if existing_entry:
                        self.content_db.db.update_content_entry(shortcode, {'download_status': 'error'})
                        logger.info(f"Updated database status for {shortcode} to 'error'")
                except Exception as e:
                    logger.error(f"Error updating database for failed download {shortcode}: {e}")
            
            # Show non-blocking error dialog that auto-closes
            self.show_auto_close_download_failed_dialog(
                shortcode,
                f"{error_msg}\n\nThe tile should now be RED. You can retry the download.",
                timeout_ms=5000,
            )
    
    def refresh_single_item(self, shortcode):
        """Refresh display for a single item (avoids race conditions with concurrent downloads)"""
        if self.current_view_mode == 'table':
            # Find and update the specific row
            for row in range(self.posts_table.rowCount()):
                shortcode_item = self.posts_table.item(row, 2)
                if shortcode_item:
                    shortcode_clean = shortcode_item.text().replace('✓ ', '').strip()
                    if shortcode_clean == shortcode:
                        caption_item = self.posts_table.item(row, 4)
                        if caption_item:
                            post = caption_item.data(Qt.UserRole)
                            if post:
                                content_info = post.get('ContentInformation', {})
                                topic_id = content_info.get('topicID')
                                bg_color, _ = self.get_item_background_color(shortcode, post.get('download_status', 'not_downloaded'), topic_id)
                                bg_qcolor = QColor(bg_color)
                                for col in range(self.posts_table.columnCount()):
                                    item = self.posts_table.item(row, col)
                                    if item:
                                        item.setBackground(bg_qcolor)
                        break
        else:
            # Find and update the specific tile IN-PLACE without recreating it
            if self.current_page not in self.page_cache:
                # Page not loaded yet, can't refresh - this is expected if post is on different page
                logger.debug(f"[REFRESH] Page {self.current_page} not in cache for {shortcode}, skipping refresh")
                return
            
            current_page_posts = self.page_cache[self.current_page]
            columns = self.calculate_tile_columns()
            
            for i, post in enumerate(current_page_posts):
                if post.get('shortcode') == shortcode:
                    row = i // columns
                    col = i % columns
                    
                    # Find the existing tile widget at this position
                    layout_item = self.tiles_grid.itemAtPosition(row, col)
                    if not layout_item:
                        logger.debug(f"[REFRESH] No tile found at position ({row}, {col}) for {shortcode}")
                        return
                    
                    tile_widget = layout_item.widget()
                    if not tile_widget:
                        logger.debug(f"[REFRESH] No widget in tile at position ({row}, {col}) for {shortcode}")
                        return
                    
                    # Update the tile's background color without recreating it
                    self.update_tile_appearance(tile_widget, post, shortcode)
                    
                    logger.debug(f"[REFRESH] Updated tile for {shortcode} at ({row}, {col})")
                    return  # Exit after finding and updating
            
            # Post not on current page - this is normal, not an error
            logger.debug(f"[REFRESH] Shortcode {shortcode} not on current page (page {self.current_page}), skipping refresh")
    
    def update_tile_appearance(self, tile_widget, post, shortcode):
        """Update a tile's visual appearance and content if needed"""
        # Get current and expected status
        status = post.get('download_status', 'not_downloaded')
        content_info = post.get('ContentInformation', {})
        topic_id = content_info.get('topicID')
        
        # Check if tile has old status stored
        old_status = getattr(tile_widget, 'download_status', None)
        downloaded_files = self.get_downloaded_files(shortcode)
        has_media = len(downloaded_files) > 0
        
        # Thumbnail refresh case: status unchanged, but a cached thumbnail is now available.
        # Rebuild this specific tile so placeholder thumbnail is replaced immediately.
        thumbnail_needs_refresh = False
        if not has_media and shortcode in self.thumbnail_cache:
            for label in tile_widget.findChildren(QLabel):
                if hasattr(label, 'is_placeholder_thumbnail'):
                    pix = label.pixmap()
                    if pix is None or pix.isNull():
                        thumbnail_needs_refresh = True
                    break
        
        # Rebuild conditions:
        # 1. Status changed from old_status and now has files
        # 2. Status is completed/re-downloaded with files but old_status was None or different (ensures video controls appear)
        # 3. Thumbnail became available
        needs_rebuild = (
            (old_status and old_status != status and has_media) or  # Status changed and now has files
            (status in ['completed', 're-downloaded'] and has_media and 
             (not old_status or old_status not in ['completed', 're-downloaded'])) or  # Completed download, ensure rebuild
            thumbnail_needs_refresh
        )
        
        if needs_rebuild:
            logger.info(f"[UPDATE_TILE] {shortcode}: Download status changed ({old_status} -> {status}), rebuilding tile with {len(downloaded_files)} files")
            # Find tile position and rebuild it
            if self.current_page in self.page_cache:
                current_page_posts = self.page_cache[self.current_page]
                columns = self.calculate_tile_columns()
                
                for i, p in enumerate(current_page_posts):
                    if p.get('shortcode') == shortcode:
                        row = i // columns
                        col = i % columns
                        start_idx = self.current_page * self.tiles_per_page
                        row_number = start_idx + i + 1
                        
                        # Save scroll position
                        scrollbar = self.tiles_scroll.verticalScrollBar()
                        scroll_pos = scrollbar.value()
                        
                        # Remove old tile
                        old_item = self.tiles_grid.itemAtPosition(row, col)
                        if old_item:
                            old_widget = old_item.widget()
                            if old_widget:
                                self.tiles_grid.removeWidget(old_widget)
                                old_widget.deleteLater()
                        
                        # Create new tile with updated data
                        new_tile = self.create_tile_widget(post, row_number)
                        self.tiles_grid.addWidget(new_tile, row, col)
                        
                        # Restore scroll position
                        scrollbar.setValue(scroll_pos)
                        logger.info(f"[UPDATE_TILE] {shortcode}: Tile rebuilt at ({row}, {col})")
                        return
        
        # Otherwise, just update colors (fast path)
        bg_color, hover_color = self.get_item_background_color(shortcode, status, topic_id)
        
        # Save scroll position and block signals to prevent automatic scrolling
        scrollbar = self.tiles_scroll.verticalScrollBar()
        scroll_pos = scrollbar.value()
        scrollbar.blockSignals(True)
        
        # Disable updates on scroll area to prevent repaints during modification
        self.tiles_scroll.setUpdatesEnabled(False)
        
        # Update the tile's stylesheet with new colors
        tile_widget.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid #aaa;
                border-radius: 3px;
                padding: 3px;
            }}
            QFrame:hover {{
                border: 2px solid #0078d4;
                background-color: {hover_color};
            }}
        """)
        
        # Update the stored post data and status
        tile_widget.post_data = post
        tile_widget.download_status = status
        
        # Re-enable updates
        self.tiles_scroll.setUpdatesEnabled(True)
        
        # Restore scroll position and unblock signals
        scrollbar.setValue(scroll_pos)
        scrollbar.blockSignals(False)
        
        logger.debug(f"[UPDATE_TILE] {shortcode}: Updated colors to bg={bg_color}, hover={hover_color}, topic_id={topic_id}, scroll={scroll_pos}")
    
    def refresh_single_item_old(self, shortcode):
        """OLD VERSION - Recreates the entire tile (causes flashing)"""
        if self.current_view_mode == 'table':
            # Table mode code stays the same...
            pass
        else:
            # Find and update the specific tile - use page_cache since that's what tiles display
            if self.current_page not in self.page_cache:
                # Page not loaded yet, can't refresh
                return
            
            current_page_posts = self.page_cache[self.current_page]
            columns = self.calculate_tile_columns()
            
            for i, post in enumerate(current_page_posts):
                if post.get('shortcode') == shortcode:
                    row = i // columns
                    col = i % columns
                    start_idx = self.current_page * self.tiles_per_page
                    row_number = start_idx + i + 1
                    
                    # Remove old tile at this position
                    old_widget = self.tiles_grid.itemAtPosition(row, col)
                    if old_widget:
                        widget = old_widget.widget()
                        if widget:
                            self.tiles_grid.removeWidget(widget)
                            widget.deleteLater()
                    
                    # Create and insert new tile with updated data
                    tile = self.create_tile_widget(post, row_number)
                    self.tiles_grid.addWidget(tile, row, col)
                    
                    # Update tracking
                    status_hash = (
                        shortcode,
                        post.get('download_status', ''),
                        shortcode in self.queued_shortcodes,
                        post.get('typename', ''),
                    )
                    self.current_tile_data[(row, col)] = status_hash
                    
                    logger.debug(f"Refreshed tile for {shortcode} at ({row}, {col})")
                    break
    
    def refresh_current_view(self):
        """Refresh the current view (table or tiles) to reflect updated data"""
        # Note: We don't reload all entries from database here to avoid UI blocking.
        # The post data is already updated in saved_posts by the caller.
        # Just refresh the visual display.
        
        logger.info(f"[REFRESH] refresh_current_view() called - view_mode={self.current_view_mode}")
        
        # Recalculate total_items based on current filters after data changes (e.g., downloads)
        if self.content_db and self.content_db.db:
            try:
                # Map filter UI to filter type
                filter_type = None
                if hasattr(self, 'current_filter'):
                    if self.current_filter == 'Only Ignored (Black) Items':
                        filter_type = 'ignored'
                    elif self.current_filter == 'Only Uncategorized':
                        filter_type = 'uncategorized'
                    elif self.current_filter == 'Only Categorized & Undownloaded':
                        filter_type = 'categorized_undownloaded'
                    elif self.current_filter == 'Only Error Items':
                        filter_type = 'error'
                    elif self.current_filter == 'Specific Topic-Undownloaded':
                        filter_type = 'specific_topic_undownloaded'
                
                # Use topic name or None
                topic_name = None
                if self.current_filter == 'Specific Topic-Undownloaded' and hasattr(self, 'current_topic_filter') and self.current_topic_filter != 'All Topics':
                    topic_name = self.current_topic_filter
                
                # Get filtered count
                filtered_count = self.content_db.db.get_content_count(
                    filters=None,
                    filter_type=filter_type,
                    topic_filter=topic_name
                )
                
                old_total = self.total_items
                self.total_items = filtered_count
                logger.info(f"[REFRESH] Updated total_items: {old_total} -> {filtered_count}")
                
                # Validate and clamp current_page after total_items update
                total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
                if total_pages > 0 and self.current_page >= total_pages:
                    old_page = self.current_page
                    self.current_page = total_pages - 1
                    logger.info(f"[REFRESH] Clamped current_page: {old_page} -> {self.current_page} (total_pages={total_pages})")
            except Exception as e:
                logger.error(f"[REFRESH] Error updating total_items: {e}")
        
        # Now refresh the view with updated data
        if self.current_view_mode == 'table':
            # Refresh table colors
            for row in range(self.posts_table.rowCount()):
                shortcode_item = self.posts_table.item(row, 2)
                if shortcode_item:
                    shortcode_clean = shortcode_item.text().replace('✓ ', '').strip()
                    caption_item = self.posts_table.item(row, 4)
                    if caption_item:
                        post = caption_item.data(Qt.UserRole)
                        if post:
                            content_info = post.get('ContentInformation', {})
                            topic_id = content_info.get('topicID')
                            bg_color, _ = self.get_item_background_color(shortcode_clean, post.get('download_status', 'not_downloaded'), topic_id)
                            bg_qcolor = QColor(bg_color)
                            for col in range(self.posts_table.columnCount()):
                                item = self.posts_table.item(row, col)
                                if item:
                                    item.setBackground(bg_qcolor)
        else:
            # Refresh tile view - clear cache so tiles reload with updated data
            logger.info(f"[REFRESH] Clearing cache for tile view refresh")
            self.page_cache.clear()
            self.loading_pages.discard(self.current_page)  # Allow reload
            self.populate_tiles()
        
        # Update table pagination after refreshing view
        self.update_table_pagination()
        self.update_topic_assigned_download_button_text()
    
    def clear_browse_list(self):
        """Clear the browse list (but keep database intact)"""
        if self.posts_table.rowCount() == 0:
            return
        
        reply = QMessageBox.question(
            self,
            "Clear Browse List",
            f"Clear all {self.posts_table.rowCount()} posts from the browse list?\\n\\n"
            "Note: This only clears the display. Posts remain in the database.\\n"
            "Use 'Load Database Entries' to reload them.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.posts_table.setRowCount(0)
            self.saved_posts = []
            self.filtered_posts = []
            self.last_displayed_page = -1  # Reset page tracking
            self.current_tile_data = {}  # Clear tile tracking
            self.browse_status.setText("Browse list cleared")
            self.statusBar().showMessage("Browse list cleared")
            # Clear tiles if in tile view
            if self.current_view_mode == 'tiles':
                self.populate_tiles()
            # Update table pagination after clearing
            self.update_table_pagination()
    
    def remove_from_queue(self):
        """Remove selected items from download queue"""
        selected_rows = self.queue_table.selectionModel().selectedRows()
        
        # Get shortcodes before removing rows
        shortcodes_to_remove = []
        for index in selected_rows:
            id_item = self.queue_table.item(index.row(), 1)
            if id_item:
                shortcodes_to_remove.append(id_item.text())
        
        # Remove from database
        if self.content_db and self.content_db.db:
            for shortcode in shortcodes_to_remove:
                try:
                    self.content_db.db.remove_from_queue(shortcode)
                    logger.info(f"Removed {shortcode} from database queue")
                except Exception as e:
                    logger.error(f"Failed to remove {shortcode} from database queue: {e}")
        
        # Remove from UI in reverse order to avoid index shifting
        for index in sorted(selected_rows, reverse=True):
            self.queue_table.removeRow(index.row())
        
        # Update Download tab styling
        self.update_download_tab_style()
    
    def clear_queue(self):
        """Clear the entire download queue"""
        if self.queue_table.rowCount() > 0:
            reply = QMessageBox.question(
                self,
                "Confirm Clear",
                "Clear entire download queue?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # Clear from database
                if self.content_db and self.content_db.db:
                    try:
                        count = self.content_db.db.clear_queue()
                        logger.info(f"Cleared {count} items from database queue")
                    except Exception as e:
                        logger.error(f"Failed to clear database queue: {e}")
                
                # Clear from UI
                self.queue_table.setRowCount(0)
                
                # Update Download tab styling
                self.update_download_tab_style()
    
    def clear_all_failures(self):
        """Remove all failed items from download queue"""
        rows_to_remove = []
        shortcodes_to_remove = []
        for row in range(self.queue_table.rowCount()):
            filename_item = self.queue_table.item(row, 3)
            if filename_item and filename_item.text() == "✗ FAILED":
                rows_to_remove.append(row)
                # Get shortcode
                id_item = self.queue_table.item(row, 1)
                if id_item:
                    shortcodes_to_remove.append(id_item.text())
        
        if not rows_to_remove:
            QMessageBox.information(
                self,
                "No Failures",
                "There are no failed downloads in the queue."
            )
            return
        
        # Remove from database
        if self.content_db and self.content_db.db:
            for shortcode in shortcodes_to_remove:
                try:
                    self.content_db.db.remove_from_queue(shortcode)
                    logger.info(f"Removed failed {shortcode} from database queue")
                except Exception as e:
                    logger.error(f"Failed to remove {shortcode} from database queue: {e}")
        
        # Remove in reverse order to avoid index shifting
        for row in reversed(rows_to_remove):
            self.queue_table.removeRow(row)
        
        # Update Download tab styling
        self.update_download_tab_style()
        
        self.statusBar().showMessage(f"Removed {len(rows_to_remove)} failed item(s) from queue")
        
        # Update status if queue is now empty
        if self.queue_table.rowCount() == 0:
            self.download_status.setText("Ready to download")
    
    def restore_queue_from_database(self):
        """Restore download queue from database on startup"""
        logger.info("=== restore_queue_from_database called ===")
        if not self.content_db or not self.content_db.db:
            logger.warning("No content database available for queue restoration")
            return
        
        logger.info(f"Current account: {self.current_username}")
        logger.info(f"Database account: {self.content_db.account_name}")
        
        try:
            # Get queued items from database
            queue_items = self.content_db.db.get_queue()
            logger.info(f"get_queue() returned {len(queue_items)} item(s)")
            
            if not queue_items:
                logger.info("No queued items to restore")
                return
            
            restored_count = 0
            failed_count = 0
            
            for item in queue_items:
                shortcode = item.get('content_id')
                row_number = item.get('row_number', 0)
                caption = item.get('caption', '')
                target_dir = item.get('target_directory', '')
                queue_status = item.get('queue_status', 'pending')
                
                logger.info(f"Processing queue item: {shortcode} (row {row_number}, status: {queue_status})")
                
                # Get full post data from database
                try:
                    entry = self.content_db.db.get_content_entry(shortcode)
                    if not entry:
                        logger.warning(f"Queue item {shortcode} not found in content_entries")
                        failed_count += 1
                        continue
                    
                    logger.info(f"Found content entry for {shortcode}")
                    
                    # Build post dict for UI
                    post = {
                        'shortcode': shortcode,
                        'row_number': row_number,
                        'caption': entry.get('text', caption),
                        'typename': entry.get('typename', 'Unknown'),
                        'owner_username': entry.get('account_name', ''),
                        'url': f"https://www.instagram.com/p/{shortcode}/"
                    }
                    
                    # Add to UI queue table
                    queue_row = self.queue_table.rowCount()
                    self.queue_table.insertRow(queue_row)
                    
                    # Column 0: Row Number
                    row_item = QTableWidgetItem()
                    row_item.setData(Qt.DisplayRole, row_number)
                    self.queue_table.setItem(queue_row, 0, row_item)
                    
                    # Column 1: ID (Shortcode)
                    id_item = QTableWidgetItem(shortcode)
                    id_item.setData(Qt.UserRole, post)
                    self.queue_table.setItem(queue_row, 1, id_item)
                    
                    # Column 2: Caption
                    caption_display = caption[:80] + "..." if len(caption) > 80 else caption
                    caption_item = QTableWidgetItem(caption_display)
                    self.queue_table.setItem(queue_row, 2, caption_item)
                    
                    # Column 3: File Name - show status
                    if queue_status == 'completed':
                        filename_item = QTableWidgetItem("✓ Completed")
                        filename_item.setForeground(Qt.darkGreen)
                    elif queue_status == 'failed':
                        filename_item = QTableWidgetItem("✗ FAILED")
                        filename_item.setForeground(Qt.red)
                    else:
                        filename_item = QTableWidgetItem("Pending...")
                        filename_item.setForeground(Qt.gray)
                    self.queue_table.setItem(queue_row, 3, filename_item)
                    
                    # Column 4: File Location
                    location_item = QTableWidgetItem(target_dir or self.download_path_input.text())
                    location_item.setForeground(Qt.gray)
                    self.queue_table.setItem(queue_row, 4, location_item)
                    
                    # Add to queued_shortcodes set to track it
                    self.queued_shortcodes.add(shortcode)
                    
                    logger.info(f"Successfully restored {shortcode} to queue table (row {queue_row})")
                    restored_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to restore queue item {shortcode}: {e}")
                    failed_count += 1
            
            if restored_count > 0:
                logger.info(f"Restored {restored_count} items to download queue from database")
                logger.info(f"queued_shortcodes now contains {len(self.queued_shortcodes)} item(s): {self.queued_shortcodes}")
                self.download_status.setText(f"Restored {restored_count} items to queue from previous session")
            else:
                logger.info("No items were restored to the queue")
            
            # Update Download tab styling based on queue count
            self.update_download_tab_style()
        
        except Exception as e:
            logger.error(f"Failed to restore queue from database: {e}")
            import traceback
            traceback.print_exc()
    
    def update_download_tab_style(self):
        """Update Download tab appearance based on queue count"""
        queue_count = self.queue_table.rowCount()
        download_tab_index = 1  # Download is the 2nd tab (0-indexed)
        
        if queue_count > 0:
            # Blue background with white text when items are queued
            self.tabs.tabBar().setTabTextColor(download_tab_index, Qt.white)
            self.tabs.tabBar().setStyleSheet(
                f"QTabBar::tab:nth-child({download_tab_index + 1}) {{"
                "    background-color: #17a2b8;"
                "    color: white;"
                "    font-weight: bold;"
                "}"
                f"QTabBar::tab:nth-child({download_tab_index + 1}):selected {{"
                "    background-color: #138496;"
                "    color: white;"
                "}"
            )
        else:
            # Normal appearance when queue is empty
            self.tabs.tabBar().setTabTextColor(download_tab_index, Qt.black)
            self.tabs.tabBar().setStyleSheet(
                f"QTabBar::tab:nth-child({download_tab_index + 1}) {{"
                "    background-color: palette(button);"
                "    color: palette(buttonText);"
                "    font-weight: normal;"
                "}"
                f"QTabBar::tab:nth-child({download_tab_index + 1}):selected {{"
                "    background-color: palette(base);"
                "    color: palette(text);"
                "}"
            )
    
    def handle_session_expired(self):
        """Handle session expiration during downloads"""
        QMessageBox.critical(
            self,
            "Session Expired During Download",
            "❌ Your Instagram session expired while downloading.\n\n"
            "Downloads have been paused.\n\n"
            "Click 'Refresh Session' in the Accounts tab to get new cookies, then try again.",
            QMessageBox.Ok
        )
        self.statusBar().showMessage("Session expired - please refresh")
        self.update_session_status()
    
    def remove_queue_item_by_shortcode(self, shortcode):
        """Remove a queue item by finding its row via shortcode"""
        try:
            for row in range(self.queue_table.rowCount()):
                shortcode_item = self.queue_table.item(row, 1)
                if shortcode_item and shortcode_item.text() == shortcode:
                    # Remove from database first
                    if self.content_db and self.content_db.db:
                        try:
                            self.content_db.db.remove_from_queue(shortcode)
                            logger.info(f"Removed {shortcode} from database queue")
                        except Exception as e:
                            logger.error(f"Failed to remove {shortcode} from database queue: {e}")
                    
                    # Remove from UI table
                    self.queue_table.removeRow(row)
                    # Remove from queued shortcodes set
                    self.queued_shortcodes.discard(shortcode)
                    logger.info(f"Removed {shortcode} from queue")
                    self.statusBar().showMessage(f"Removed {shortcode} from queue")
                    
                    # Update Download tab styling
                    self.update_download_tab_style()
                    
                    # Update status if queue is now empty
                    if self.queue_table.rowCount() == 0:
                        self.download_status.setText("Ready to download")
                    break
        except Exception as e:
            logger.error(f"Error removing queue item {shortcode}: {e}")
    
    def remove_queue_row(self, row):
        """Remove a specific row from the queue by row index"""
        try:
            if 0 <= row < self.queue_table.rowCount():
                shortcode_item = self.queue_table.item(row, 1)
                shortcode = shortcode_item.text() if shortcode_item else "Unknown"
                
                # Remove from database first
                if shortcode != "Unknown" and self.content_db and self.content_db.db:
                    try:
                        self.content_db.db.remove_from_queue(shortcode)
                        logger.info(f"Removed {shortcode} from database queue")
                    except Exception as e:
                        logger.error(f"Failed to remove {shortcode} from database queue: {e}")
                
                # Remove from UI table
                self.queue_table.removeRow(row)
                # Remove from queued shortcodes set
                if shortcode != "Unknown":
                    self.queued_shortcodes.discard(shortcode)
                logger.info(f"Removed {shortcode} from queue")
                self.statusBar().showMessage(f"Removed {shortcode} from queue")
                
                # Update Download tab styling
                self.update_download_tab_style()
                
                # Update status if queue is now empty
                if self.queue_table.rowCount() == 0:
                    self.download_status.setText("Ready to download")
        except Exception as e:
            logger.error(f"Error removing queue row {row}: {e}")
    
    def toggle_post_in_queue(self, post, button):
        """Toggle a post in/out of queue and update button state"""
        if not post:
            return
        
        shortcode = post.get('shortcode', '')
        
        # Check if already in queue
        if shortcode in self.queued_shortcodes:
            # Remove from queue
            self.remove_queue_item_by_shortcode(shortcode)
            # Update button to "Queue" state
            button.setText("➕")
            button.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; }")
            button.setToolTip("Add to download queue")
        else:
            # Add to database queue first
            target_dir = self.download_path_input.text()
            if self.content_db and self.content_db.db and target_dir:
                try:
                    row_num = post.get('row_number', 0)
                    caption = post.get('caption', '')
                    self.content_db.db.add_to_queue(
                        content_id=shortcode,
                        row_number=row_num,
                        caption=caption,
                        target_directory=target_dir
                    )
                    logger.info(f"Added {shortcode} to database queue from toggle button")
                except Exception as e:
                    logger.error(f"Failed to add {shortcode} to database queue: {e}")
            
            # Add to UI queue
            self.add_post_to_queue(post)
            # Update button to "Unqueue" state
            button.setText("➖")
            button.setStyleSheet("QPushButton { background-color: #FFB6C1; color: #333; font-weight: bold; }")
            button.setToolTip("Remove from download queue")
    
    def browse_download_dir(self):
        """Browse for download directory and save to account settings"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Download Directory",
            self.download_path_input.text()
        )
        if dir_path:
            self.download_path_input.setText(dir_path)
            logger.info(f"DEBUG browse_download_dir: User selected path: {dir_path}")
            
            # Save the new download path to account settings
            if self.current_username:
                try:
                    account = self.account_manager.get_account(self.current_username)
                    logger.info(f"DEBUG browse_download_dir: Current account data: {account}")
                    if account:
                        session_file = account.get('session_file', '')
                        debug_path = account.get('debug_path')
                        ig_username = account.get('ig_username')
                        thumbnails_path = account.get('thumbnails_path')
                        topics_root_path = account.get('topics_root_path')
                        root_folder = account.get('root_folder')
                        logger.info(f"DEBUG browse_download_dir: Calling save_account with download_path={dir_path}")
                        self.account_manager.save_account(
                            self.current_username,
                            session_file,
                            download_path=dir_path,
                            debug_path=debug_path,
                            ig_username=ig_username,
                            thumbnails_path=thumbnails_path,
                            topics_root_path=topics_root_path,
                            root_folder=root_folder
                        )
                        logger.info(f"Saved download path '{dir_path}' for account {self.current_username}")
                        QMessageBox.information(
                            self,
                            "Download Path Saved",
                            f"Download path has been saved for account '{self.current_username}'."
                        )
                except Exception as e:
                    logger.error(f"Failed to save download path: {e}")
                    QMessageBox.warning(
                        self,
                        "Save Failed",
                        f"Failed to save download path: {str(e)}"
                    )
    
    def on_download_path_changed(self):
        """Save download path when user manually edits the text field - with confirmation"""
        if self.current_username:
            new_path = self.download_path_input.text()
            if new_path:
                try:
                    account = self.account_manager.get_account(self.current_username)
                    if account:
                        old_path = account.get('download_path', '')
                        
                        # Require confirmation if path is actually changing
                        if old_path and new_path != old_path:
                            reply = QMessageBox.question(
                                self,
                                "Confirm Path Change",
                                f"You are about to change the download path:\n\n"
                                f"From: {old_path}\n"
                                f"To: {new_path}\n\n"
                                f"This will affect where new downloads are saved.\n\n"
                                f"Continue?",
                                QMessageBox.Yes | QMessageBox.No
                            )
                            
                            if reply != QMessageBox.Yes:
                                # Revert to old path
                                self.download_path_input.setText(old_path)
                                logger.info(f"Download path change cancelled by user")
                                return
                        
                        session_file = account.get('session_file', '')
                        debug_path = account.get('debug_path')
                        ig_username = account.get('ig_username')
                        thumbnails_path = account.get('thumbnails_path')
                        topics_root_path = account.get('topics_root_path')
                        
                        self.account_manager.save_account(
                            self.current_username,
                            session_file,
                            download_path=new_path,
                            debug_path=debug_path,
                            ig_username=ig_username,
                            thumbnails_path=thumbnails_path,
                            topics_root_path=topics_root_path
                        )
                        logger.info(f"Auto-saved download path: {new_path}")
                        self.statusBar().showMessage(f"Download path saved: {new_path}", 2000)
                except Exception as e:
                    logger.error(f"Failed to auto-save download path: {e}")
    
    def start_download(self):
        """Start downloading queued posts"""
        if self.queue_table.rowCount() == 0:
            QMessageBox.information(self, "Empty Queue", "No posts in download queue")
            return
        
        if not self.instagram_manager.logged_in:
            QMessageBox.warning(self, "Not Logged In", "Please login first")
            self.tabs.setCurrentIndex(2)  # Switch to accounts tab
            return
        
        # CRITICAL: Check if download path is blank
        download_path_text = self.download_path_input.text().strip()
        if not download_path_text:
            QMessageBox.critical(
                self,
                "Download Path Not Set",
                "Cannot start download: Download path is blank!\n\n"
                "Please set a download path in the Settings tab or by selecting a download directory."
            )
            logger.error("⚠️⚠️⚠️ CRITICAL: Attempted to start download with blank download path!")
            return
        
        # Show hourglass cursor for this blocking operation
        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # Gather shortcodes from column 1 (ID column)
        shortcodes = []
        for i in range(self.queue_table.rowCount()):
            id_item = self.queue_table.item(i, 1)
            if id_item:
                shortcodes.append(id_item.text())
        
        target_dir = Path(download_path_text)
        logger.info(f"Starting download of {len(shortcodes)} posts to: {target_dir}")
        logger.info(f"Target directory exists: {target_dir.exists()}")
        logger.info(f"Target directory is writable: {os.access(target_dir.parent, os.W_OK) if target_dir.parent.exists() else 'parent does not exist'}")
        
        # Disable controls
        self.download_btn.setEnabled(False)
        self.download_btn.setText("Downloading...")
        
        # Create process entry
        process_id = self.process_manager.add_process(
            'batch_download',
            f'Batch Download ({len(shortcodes)} items)',
            None  # Will set thread below
        )
        
        # Start download thread
        self.dl_thread = DownloadThread(
            self.instagram_manager,
            shortcodes,
            target_dir,
            process_id
        )
        
        # Update process with thread reference
        process = self.process_manager.get_process(process_id)
        if process:
            process['thread'] = self.dl_thread
            process['total'] = len(shortcodes)
        
        self.dl_thread.progress.connect(lambda c, t: self.update_download_progress(c, t, process_id))
        self.dl_thread.status.connect(self.download_status.setText)
        self.dl_thread.download_complete.connect(self.handle_download_complete)
        self.dl_thread.session_expired.connect(self.handle_session_expired)
        self.dl_thread.finished.connect(lambda s, f: self.download_finished(s, f, process_id))
        self.dl_thread.start()
    
    def update_download_progress(self, current, total, process_id=None):
        """Update download progress bar and process table"""
        self.download_progress.setMaximum(total)
        self.download_progress.setValue(current)
        
        # Update process manager
        if process_id:
            self.process_manager.update_process(process_id, current=current, total=total)
    
    def handle_post_download_filter_update(self):
        """
        Handle filter recalculation after downloads complete.
        
        If a filter is active and items were downloaded:
        - Recalculate filtered item count
        - Adjust current page if needed (e.g., last page now empty)
        - Reset to "All" filter if no items remain
        """
        # Check if we're on the Browse tab and a filter is active
        if not hasattr(self, 'filter_combo') or not hasattr(self, 'content_db'):
            return
        
        current_filter = self.filter_combo.currentText()
        
        # If "All (Unfiltered)", no special handling needed
        if current_filter == 'All (Unfiltered)':
            return
        
        logger.info(f"[FILTER_UPDATE] Active filter: {current_filter}, checking post-download state")
        
        try:
            specific_topic_mode = current_filter == 'Specific Topic-Undownloaded'
            self.update_topic_filter_dropdown(specific_topic_mode)

            current_topic_name = None
            if hasattr(self, 'topic_filter_combo'):
                current_topic_name = self.topic_filter_combo.currentData() or 'All Topics'

            # Map filter UI to filter type
            filter_type = None
            if current_filter == 'Only Ignored (Black) Items':
                filter_type = 'ignored'
            elif current_filter == 'Only Uncategorized':
                filter_type = 'uncategorized'
            elif current_filter == 'Only Categorized & Undownloaded':
                filter_type = 'categorized_undownloaded'
            elif current_filter == 'Only Error Items':
                filter_type = 'error'
            elif current_filter == 'Specific Topic-Undownloaded':
                filter_type = 'specific_topic_undownloaded'
            
            # Only apply topic criteria for the specific-topic filter mode.
            topic_name = None
            if current_filter == 'Specific Topic-Undownloaded':
                topic_name = None if current_topic_name == 'All Topics' else current_topic_name
            
            # Get new filtered count
            new_filtered_count = self.content_db.db.get_content_count(
                filter_type=filter_type,
                topic_filter=topic_name
            )
            
            logger.info(f"[FILTER_UPDATE] New filtered count: {new_filtered_count}")
            
            # Case 1: No items remain matching the filter
            if new_filtered_count == 0:
                logger.info(f"[FILTER_UPDATE] No items remain for filter '{current_filter}', switching to 'All'")
                
                # Switch to "All (Unfiltered)"
                self.filter_combo.blockSignals(True)  # Prevent triggering apply_sort_and_filter
                self.filter_combo.setCurrentText('All (Unfiltered)')
                self.filter_combo.blockSignals(False)
                
                # Show dialog to user
                QMessageBox.information(
                    self,
                    "Filter Reset",
                    f"All items matching the filter '{current_filter}' have been processed.\n\n"
                    f"Filter has been reset to 'All (Unfiltered)'."
                )
                
                # Apply the new filter
                self.apply_sort_and_filter()
                return
            
            # Case 2: Items remain, update pagination
            old_total = self.total_items
            self.total_items = new_filtered_count
            old_total_pages = (old_total + self.tiles_per_page - 1) // self.tiles_per_page
            new_total_pages = (new_filtered_count + self.tiles_per_page - 1) // self.tiles_per_page
            
            logger.info(f"[FILTER_UPDATE] Total items: {old_total} -> {new_filtered_count}")
            logger.info(f"[FILTER_UPDATE] Total pages: {old_total_pages} -> {new_total_pages}")
            logger.info(f"[FILTER_UPDATE] Current page: {self.current_page + 1}")
            
            # Update pagination controls
            if hasattr(self, 'current_page_spin') and hasattr(self, 'page_label'):
                self.current_page_spin.setMaximum(max(1, new_total_pages))
                self.page_label.setText(f"/ {new_total_pages}")
            
            # Case 3: Current page is now beyond last page
            if self.current_page >= new_total_pages:
                # Move to last valid page
                new_page = max(0, new_total_pages - 1)
                logger.info(f"[FILTER_UPDATE] Current page {self.current_page + 1} is beyond last page, moving to page {new_page + 1}")
                
                self.current_page = new_page
                if hasattr(self, 'current_page_spin'):
                    self.current_page_spin.blockSignals(True)
                    self.current_page_spin.setValue(new_page + 1)
                    self.current_page_spin.blockSignals(False)
                
                # Clear entire cache and reload the new current page
                self.page_cache.clear()
                self.last_displayed_page = -1
            else:
                # Current page is still valid, just clear its cache entry to force reload
                logger.info(f"[FILTER_UPDATE] Current page is still valid, clearing cache for page {self.current_page}")
                if self.current_page in self.page_cache:
                    del self.page_cache[self.current_page]
                self.last_displayed_page = -1
                if hasattr(self, 'current_page_spin'):
                    self.current_page_spin.blockSignals(True)
                    self.current_page_spin.setValue(self.current_page + 1)
                    self.current_page_spin.blockSignals(False)
            
            # Update status message
            if hasattr(self, 'browse_status'):
                self.browse_status.setText(f"Showing {new_filtered_count} items (filtered)")
            
            # Reload the current page data and repaint tiles
            self.load_page(self.current_page)
            self.preload_adjacent_pages(self.current_page)
            if self.current_view_mode == 'tiles':
                self.populate_tiles()
            
        except Exception as e:
            logger.error(f"[FILTER_UPDATE] Error handling post-download filter update: {e}", exc_info=True)
    
    def download_finished(self, success, failed, process_id=None):
        """Handle download completion"""
        # Restore cursor after operation completes
        QApplication.restoreOverrideCursor()
        
        self.download_btn.setEnabled(True)
        self.download_btn.setText("Start Download")
        self.download_progress.setValue(0)
        
        # Update process status
        if process_id:
            if failed > 0:
                self.process_manager.update_process(process_id, status='completed_with_errors')
            else:
                self.process_manager.update_process(process_id, status='completed')
        
        message = f"Download complete!\n\nSuccess: {success}\nFailed: {failed}"
        if failed > 0:
            message += "\n\nFailed items remain in queue. Use 'Clear All Failures' to remove them."
        QMessageBox.information(self, "Download Complete", message)
        
        # Remove only successful downloads from queue
        rows_to_remove = []
        shortcodes_to_remove = []
        for row in range(self.queue_table.rowCount()):
            filename_item = self.queue_table.item(row, 3)
            if filename_item and filename_item.text() != "✗ FAILED" and filename_item.text() != "Pending...":
                # This row was successful (has actual filename)
                rows_to_remove.append(row)
                # Get shortcode for database removal
                id_item = self.queue_table.item(row, 1)
                if id_item:
                    shortcodes_to_remove.append(id_item.text())
        
        # Remove successful downloads from database queue
        if self.content_db and self.content_db.db and shortcodes_to_remove:
            for shortcode in shortcodes_to_remove:
                try:
                    # Update to completed status first (for logging)
                    self.content_db.db.update_queue_status(shortcode, 'completed')
                    # Then remove from queue
                    self.content_db.db.remove_from_queue(shortcode)
                    logger.info(f"Removed completed {shortcode} from database queue")
                except Exception as e:
                    logger.error(f"Failed to remove {shortcode} from database queue: {e}")
        
        # Remove in reverse order to avoid index shifting
        for row in reversed(rows_to_remove):
            self.queue_table.removeRow(row)
        
        # Update Download tab styling
        self.update_download_tab_style()
        
        if failed == 0:
            self.download_status.setText("Ready to download")
        else:
            self.download_status.setText(f"{failed} download(s) failed - check debug info")
        
        # Handle filter recalculation if filter is active
        self.handle_post_download_filter_update()
        
        # Refresh views to show newly downloaded content
        self.refresh_current_view()
    
    # ========== VIEW SWITCHING AND TILE VIEW METHODS ==========
    
    def switch_view_mode(self, mode):
        """Switch between table and tile view - FORCED TO TILES ONLY"""
        # Force tiles mode only (table view disabled)
        mode = 'tiles'
        self.current_view_mode = mode
        
        # Update button states
        self.table_view_btn.setChecked(False)
        self.tile_view_btn.setChecked(True)
        
        # Always show tile view
        self.view_stack.setCurrentIndex(1)
        # Don't reset to first page - keep current position
        self.last_displayed_page = -1  # Force full rebuild when switching views
        self.filtered_posts = self.saved_posts.copy()
        self.populate_tiles()
        
        # Save UI setting
        self.save_ui_setting('view_mode', mode)
    
    def toggle_tile_size(self):
        """Cycle through tile sizes: small -> medium -> large -> xlarge -> small"""
        sizes = ['small', 'medium', 'large', 'xlarge']
        current_idx = sizes.index(self.tile_size)
        next_idx = (current_idx + 1) % len(sizes)
        self.tile_size = sizes[next_idx]
        
        # Update button text
        size_icons = {'small': '🔹', 'medium': '📐', 'large': '🔲', 'xlarge': '⬛'}
        self.tile_size_btn.setText(f"{size_icons[self.tile_size]} {self.tile_size.capitalize()}")
        
        # Update table thumbnail column width and row height
        thumb_size = self.get_thumbnail_size()
        self.posts_table.setColumnWidth(0, thumb_size + 20)  # Add padding
        self.posts_table.verticalHeader().setDefaultSectionSize(thumb_size + 10)
        
        # Refresh views
        if self.current_view_mode == 'tiles':
            # Tile size change requires full rebuild
            self.last_displayed_page = -1
            self.populate_tiles()
        else:
            # Refresh table view thumbnails
            self.refresh_table_thumbnails()
        
        # Save UI setting
        self.save_ui_setting('tile_size', self.tile_size)
    
    def toggle_theme(self):
        """Toggle between light and dark theme"""
        self.theme = 'dark' if self.theme == 'light' else 'light'
        
        # Update button text
        theme_icons = {'light': '☀️ Light', 'dark': '🌙 Dark'}
        self.theme_btn.setText(theme_icons[self.theme])
        
        # Apply theme
        self.apply_theme()
        
        # Save UI setting
        self.save_ui_setting('theme', self.theme)
    
    def apply_theme(self):
        """Apply light or dark theme to the entire application"""
        # Get absolute path to assets folder for SVG icons
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
        # Format paths for Qt stylesheet (forward slashes, no file:// protocol)
        tree_collapsed_dark = os.path.join(assets_dir, 'tree_collapsed_dark.svg').replace('\\', '/')
        tree_expanded_dark = os.path.join(assets_dir, 'tree_expanded_dark.svg').replace('\\', '/')
        tree_leaf_dark = os.path.join(assets_dir, 'tree_leaf_dark.svg').replace('\\', '/')
        tree_collapsed_light = os.path.join(assets_dir, 'tree_collapsed_light.svg').replace('\\', '/')
        tree_expanded_light = os.path.join(assets_dir, 'tree_expanded_light.svg').replace('\\', '/')
        tree_leaf_light = os.path.join(assets_dir, 'tree_leaf_light.svg').replace('\\', '/')
        checkbox_checked = os.path.join(assets_dir, 'checkbox_checked.svg').replace('\\', '/')
        checkbox_checked = os.path.join(assets_dir, 'checkbox_checked.svg').replace('\\', '/')
        
        if self.theme == 'dark':
            # Dark theme colors
            palette = f"""
                QMainWindow, QWidget {{
                    background-color: #2b2b2b;
                    color: #e0e0e0;
                }}
                QTableWidget {{
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    gridline-color: #444444;
                    selection-background-color: #0078d4;
                }}
                QTableWidget::item {{
                    padding: 5px;
                }}
                QHeaderView::section {{
                    background-color: #3c3c3c;
                    color: #e0e0e0;
                    padding: 5px;
                    border: 1px solid #444444;
                }}
                QTextEdit, QLineEdit {{
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    border: 1px solid #444444;
                }}
                QPushButton {{
                    background-color: #3c3c3c;
                    color: #e0e0e0;
                    border: 1px solid #555555;
                    padding: 5px;
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background-color: #4c4c4c;
                }}
                QPushButton:checked {{
                    background-color: #0078d4;
                    color: white;
                    font-weight: bold;
                }}
                QLabel {{
                    color: #e0e0e0;
                }}
                QListWidget {{
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    border: 1px solid #444444;
                }}
                QComboBox, QSpinBox {{
                    background-color: #3c3c3c;
                    color: #e0e0e0;
                    border: 1px solid #555555;
                }}
                QScrollBar:vertical {{
                    background-color: #2b2b2b;
                    width: 12px;
                }}
                QScrollBar::handle:vertical {{
                    background-color: #555555;
                    border-radius: 6px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background-color: #666666;
                }}
                QTabWidget::pane {{
                    border: 1px solid #444444;
                    background-color: #2b2b2b;
                }}
                QTabBar::tab {{
                    background-color: #3c3c3c;
                    color: #e0e0e0;
                    padding: 8px 16px;
                    border: 1px solid #444444;
                }}
                QTabBar::tab:selected {{
                    background-color: #0078d4;
                    color: white;
                }}
                QProgressBar {{
                    background-color: #1e1e1e;
                    border: 1px solid #444444;
                    border-radius: 3px;
                    text-align: center;
                }}
                QProgressBar::chunk {{
                    background-color: #0078d4;
                }}
                QTreeWidget {{
                    background-color: #1e1e1e;
                    color: #e0e0e0;
                    border: 1px solid #444444;
                    outline: 0;
                }}
                QTreeWidget::item {{
                    color: #e0e0e0;
                }}
                QTreeWidget::item:selected {{
                    background-color: #0078d4;
                    color: white;
                }}
                QTreeWidget::branch:has-children:!has-siblings:closed,
                QTreeWidget::branch:closed:has-children:has-siblings {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_collapsed_dark});
                }}
                QTreeWidget::branch:open:has-children:!has-siblings,
                QTreeWidget::branch:open:has-children:has-siblings {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_expanded_dark});
                }}
                QTreeWidget::branch:!has-children:!has-siblings:adjoins-item,
                QTreeWidget::branch:!has-children:has-siblings:adjoins-item {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_leaf_dark});
                }}
                QTreeWidget::indicator {{
                    width: 16px;
                    height: 16px;
                    background-color: #2b2b2b;
                    border: 1px solid #888888;
                }}
                QTreeWidget::indicator:unchecked {{
                    background-color: #2b2b2b;
                    border: 1px solid #888888;
                }}
                QTreeWidget::indicator:checked {{
                    background-color: #28a745;
                    border: 1px solid #28a745;
                    image: url({checkbox_checked});
                }}
            """
        else:
            # Light theme (default Qt styling with minor tweaks)
            palette = f"""
                QPushButton:checked {{
                    background-color: #0078d4;
                    color: white;
                    font-weight: bold;
                }}
                QTabBar::tab:selected {{
                    background-color: #0078d4;
                    color: white;
                }}
                QTreeWidget::branch:has-children:!has-siblings:closed,
                QTreeWidget::branch:closed:has-children:has-siblings {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_collapsed_light});
                }}
                QTreeWidget::branch:open:has-children:!has-siblings,
                QTreeWidget::branch:open:has-children:has-siblings {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_expanded_light});
                }}
                QTreeWidget::branch:!has-children:!has-siblings:adjoins-item,
                QTreeWidget::branch:!has-children:has-siblings:adjoins-item {{
                    background: transparent;
                    border: none;
                    width: 14px;
                    height: 14px;
                    margin: 2px;
                    image: url({tree_leaf_light});
                }}
                QTreeWidget::indicator {{
                    width: 16px;
                    height: 16px;
                    background-color: white;
                    border: 1px solid #999999;
                }}
                QTreeWidget::indicator:unchecked {{
                    background-color: white;
                    border: 1px solid #999999;
                }}
                QTreeWidget::indicator:checked {{
                    background-color: #28a745;
                    border: 1px solid #28a745;
                    image: url({checkbox_checked});
                }}
            """
        
        self.setStyleSheet(palette)
    
    def toggle_video_mode(self):
        """Toggle between inline and popup video playback"""
        self.inline_video = not self.inline_video
        mode_icons = {False: '🎬 Popup', True: '📺 Inline'}
        self.video_mode_btn.setText(mode_icons[self.inline_video])
        self.save_ui_setting('inline_video', 'true' if self.inline_video else 'false')
        
        # Show helpful message about requirements
        if self.inline_video and not self._check_vlc_available():
            self.statusBar().showMessage(
                "Inline video requires VLC media player - will fallback to popup", 5000
            )
        else:
            self.statusBar().showMessage(
                f"Video playback: {'Inline (requires VLC)' if self.inline_video else 'Popup'}", 2000
            )
    
    def load_ui_settings(self):
        """Load UI settings for current account"""
        if not self.current_username:
            return
        
        # Load theme
        saved_theme = self.account_manager.get_account_setting(self.current_username, 'ui_theme', 'light')
        self.theme = saved_theme
        theme_icons = {'light': '☀️ Light', 'dark': '🌙 Dark'}
        self.theme_btn.setText(theme_icons[self.theme])
        self.apply_theme()
        
        # Load tile size
        saved_size = self.account_manager.get_account_setting(self.current_username, 'ui_tile_size', 'medium')
        if saved_size in ['small', 'medium', 'large', 'xlarge']:
            self.tile_size = saved_size
            size_icons = {'small': '🔹', 'medium': '📐', 'large': '🔲', 'xlarge': '⬛'}
            self.tile_size_btn.setText(f"{size_icons[self.tile_size]} {self.tile_size.capitalize()}")
            
            # Update table thumbnails
            thumb_size = self.get_thumbnail_size()
            self.posts_table.setColumnWidth(0, thumb_size + 20)
            self.posts_table.verticalHeader().setDefaultSectionSize(thumb_size + 10)
        
        # Load current tab
        saved_tab = self.account_manager.get_account_setting(self.current_username, 'ui_current_tab', '0')
        try:
            tab_index = int(saved_tab)
            if 0 <= tab_index < self.tabs.count():
                self.tabs.setCurrentIndex(tab_index)
        except (ValueError, AttributeError):
            pass  # Invalid tab index, ignore
        
        # Load view mode - FORCE tiles only (table view disabled)
        saved_view_mode = self.account_manager.get_account_setting(self.current_username, 'ui_view_mode', 'tiles')
        # Always use tiles regardless of saved setting
        self.switch_view_mode('tiles')
        
        # Load inline video preference
        saved_inline = self.account_manager.get_account_setting(self.current_username, 'ui_inline_video', 'false')
        self.inline_video = saved_inline == 'true'
        mode_icons = {False: '🎬 Popup', True: '📺 Inline'}
        self.video_mode_btn.setText(mode_icons[self.inline_video])
        
        # Load tile video volume preference
        saved_volume = self.account_manager.get_account_setting(self.current_username, 'ui_tile_video_volume', '30')
        try:
            volume = int(saved_volume)
            if 0 <= volume <= 100:
                self.tile_video_volume = volume
                if hasattr(self, 'tile_volume_slider'):
                    self.tile_volume_slider.blockSignals(True)
                    self.tile_volume_slider.setValue(volume)
                    self.tile_volume_slider.blockSignals(False)
        except (ValueError, AttributeError):
            pass  # Invalid value, ignore
        
        # Load items per page
        saved_items_per_page = self.account_manager.get_account_setting(self.current_username, 'ui_tiles_per_page', '20')
        try:
            items_per_page = int(saved_items_per_page)
            if 10 <= items_per_page <= 100:
                self.tiles_per_page = items_per_page
                # Block signals to prevent triggering change_items_per_page which would reset current_page to 0
                self.items_per_page_spin.blockSignals(True)
                self.items_per_page_spin.setValue(items_per_page)
                self.items_per_page_spin.blockSignals(False)
                logger.info(f"Restored items per page: {items_per_page}")
        except (ValueError, AttributeError):
            pass  # Invalid value, ignore
        
        # Load last visited page
        saved_page = self.account_manager.get_account_setting(self.current_username, 'ui_current_page', '0')
        logger.info(f"[PAGE RESTORE] Raw saved_page value: '{saved_page}' (type: {type(saved_page)})")
        try:
            page_num = int(saved_page)
            if page_num >= 0:
                self.current_page = page_num
                self.target_page = page_num  # Store target to restore after data loads
                logger.info(f"[PAGE RESTORE] Loaded saved page number: {page_num}, set current_page={self.current_page}, target_page={self.target_page}")
                logger.info(f"[PAGE RESTORE] This will display as 'Page {page_num + 1}' in UI")
        except (ValueError, AttributeError) as e:
            logger.warning(f"[PAGE RESTORE] Failed to parse saved page: '{saved_page}' - Error: {e}")
            pass  # Invalid page number, ignore
    
    def on_tile_volume_changed(self, volume):
        """Handle tile video volume slider change"""
        self.tile_video_volume = volume
        self.save_ui_setting('tile_video_volume', str(volume))
        logger.debug(f"Tile video volume changed to {volume}")
    
    def save_ui_setting(self, key: str, value: str):
        """Save a UI setting for the current account"""
        if not self.current_username:
            logger.warning(f"[SAVE_SETTING] Cannot save {key}={value}: no current username")
            return
        
        logger.info(f"[SAVE_SETTING] Saving {key}={value} for account {self.current_username}")
        result = self.account_manager.set_account_setting(self.current_username, f'ui_{key}', value)
        logger.info(f"[SAVE_SETTING] Save result: {result}")

    def _get_topic_tree_expanded_ids(self, topic_tree):
        """Collect expanded topic IDs from a topic tree."""
        expanded_ids = []

        def collect_expanded(item):
            topic_data = item.data(0, Qt.UserRole)
            topic_id = None
            if isinstance(topic_data, dict):
                topic_id = topic_data.get('id')

            if topic_id is not None and item.isExpanded():
                expanded_ids.append(int(topic_id))

            for i in range(item.childCount()):
                collect_expanded(item.child(i))

        for i in range(topic_tree.topLevelItemCount()):
            collect_expanded(topic_tree.topLevelItem(i))

        return expanded_ids

    def _save_topic_tree_expansion_state(self, topic_tree, setting_key='topic_assignment_tree_expanded_ids'):
        """Persist expanded/collapsed state for topic assignment trees."""
        if not self.current_username:
            return

        try:
            expanded_ids = self._get_topic_tree_expanded_ids(topic_tree)
            self.save_ui_setting(setting_key, json.dumps(expanded_ids))
        except Exception as e:
            logger.debug(f"Failed to save topic tree expansion state: {e}")
    
    def _save_topic_tree_scroll_position(self, topic_tree, setting_key='topic_assignment_tree_scroll_pos'):
        """Persist scroll position for topic assignment trees."""
        if not self.current_username:
            return
        
        try:
            scrollbar = topic_tree.verticalScrollBar()
            scroll_pos = scrollbar.value()
            self.save_ui_setting(setting_key, str(scroll_pos))
            logger.debug(f"Saved topic tree scroll position: {scroll_pos}")
        except Exception as e:
            logger.debug(f"Failed to save topic tree scroll position: {e}")

    def _restore_topic_tree_expansion_state(self, topic_tree, setting_key='topic_assignment_tree_expanded_ids'):
        """Restore expanded/collapsed state for topic assignment trees."""
        if not self.current_username:
            topic_tree.expandAll()
            return

        try:
            raw_state = self.account_manager.get_account_setting(
                self.current_username,
                f'ui_{setting_key}',
                ''
            )

            if not raw_state:
                topic_tree.expandAll()
                return

            parsed = json.loads(raw_state)
            expanded_ids = set()
            if isinstance(parsed, list):
                for value in parsed:
                    try:
                        expanded_ids.add(int(value))
                    except (TypeError, ValueError):
                        continue

            if not expanded_ids:
                topic_tree.expandAll()
                return

            topic_tree.collapseAll()

            def apply_state(item):
                topic_data = item.data(0, Qt.UserRole)
                topic_id = None
                if isinstance(topic_data, dict):
                    topic_id = topic_data.get('id')

                if topic_id is not None and int(topic_id) in expanded_ids:
                    item.setExpanded(True)

                for i in range(item.childCount()):
                    apply_state(item.child(i))

            for i in range(topic_tree.topLevelItemCount()):
                apply_state(topic_tree.topLevelItem(i))
        except Exception as e:
            logger.debug(f"Failed to restore topic tree expansion state: {e}")
            topic_tree.expandAll()
    
    def _restore_topic_tree_scroll_position(self, topic_tree, setting_key='topic_assignment_tree_scroll_pos'):
        """Restore scroll position for topic assignment trees."""
        if not self.current_username:
            return
        
        try:
            raw_value = self.account_manager.get_account_setting(
                self.current_username,
                f'ui_{setting_key}',
                '0'
            )
            scroll_pos = int(raw_value)
            scrollbar = topic_tree.verticalScrollBar()
            scrollbar.setValue(scroll_pos)
            logger.debug(f"Restored topic tree scroll position: {scroll_pos}")
        except Exception as e:
            logger.debug(f"Failed to restore topic tree scroll position: {e}")
    
    def on_tab_changed(self, index):
        """Handle tab change - save current tab"""
        logger.info(f"Tab changed to index {index}")
        if self.current_username:
            self.save_ui_setting('current_tab', str(index))
        
        # Load topics when Topics tab is selected (Browse=0, Download=1, Topics=2, Settings=3, Accounts=4)
        if index == 2 and self.content_db and self.content_db.db:
            logger.info("Loading topics tree for Topics tab")
            self.load_topics_tree()
        
        # Refresh Settings tab paths when Settings tab is selected
        if index == 3:
            logger.info("Refreshing Settings tab paths")
            self.refresh_settings_paths()
    
    def populate_tiles(self):
        """Populate the tile view with current page from cache - lazy loaded"""
        # Prevent re-entrant calls (if already populating, skip this call)
        if self._populating_tiles:
            logger.debug("populate_tiles() called while already populating - skipping")
            return
        
        logger.debug(f"[POPULATE] populate_tiles() called - current_page={self.current_page}, cache has page: {self.current_page in self.page_cache}")
        
        self._populating_tiles = True
        
        try:
            # Check if we have any items at all
            if self.total_items == 0:
                # Clear all tiles and show empty message
                self._clear_all_tiles()
                empty_label = QLabel("No posts to display")
                empty_label.setAlignment(Qt.AlignCenter)
                empty_label.setStyleSheet("font-size: 14pt; color: #888; padding: 40px;")
                self.tiles_grid.addWidget(empty_label, 0, 0)
                self.current_tile_data = {}
                self.last_displayed_page = -1
                self.last_displayed_columns = 0
                self.update_pagination_controls()
                self.update_topic_assigned_download_button_text()
                return
            
            # Validate and clamp current_page to available pages
            total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
            if self.current_page >= total_pages:
                self.current_page = max(0, total_pages - 1)
                logger.info(f"Clamped current_page to {self.current_page} (total pages: {total_pages})")
            
            # Check if current page is in cache
            if self.current_page not in self.page_cache:
                logger.debug(f"[POPULATE] Page {self.current_page} not in cache, will trigger load")
                # Show loading message
                self._clear_all_tiles()
                loading_label = QLabel(f"Loading page {self.current_page + 1}...")
                loading_label.setAlignment(Qt.AlignCenter)
                loading_label.setStyleSheet("font-size: 14pt; color: #0066cc; padding: 40px;")
                self.tiles_grid.addWidget(loading_label, 0, 0)
                self.update_pagination_controls()
                self.update_topic_assigned_download_button_text()
                
                # Trigger load if not already loading
                if self.current_page not in self.loading_pages:
                    logger.debug(f"[POPULATE] Starting load for page {self.current_page}")
                    self.load_page(self.current_page)
                
                return
            
            # Get posts for current page from cache
            current_page_posts = self.page_cache[self.current_page]
            logger.debug(f"[POPULATE] Got {len(current_page_posts)} posts from cache for page {self.current_page}")
            
            # Calculate pagination
            start_idx = self.current_page * self.tiles_per_page
            
            # Calculate columns dynamically based on available width
            columns = self.calculate_tile_columns()
            
            # Check if we need a full rebuild (page changed or column count changed)
            needs_full_rebuild = (
                self.current_page != self.last_displayed_page or 
                columns != self.last_displayed_columns
            )
            
            if needs_full_rebuild:
                # Page or layout changed - do a full rebuild
                self._clear_all_tiles()
                
                # Build all tiles for the new page
                for i, post in enumerate(current_page_posts):
                    row = i // columns
                    col = i % columns
                    row_number = start_idx + i + 1
                    tile = self.create_tile_widget(post, row_number)
                    self.tiles_grid.addWidget(tile, row, col)
                
                # Update tracking
                self.current_tile_data = {}
                for i, post in enumerate(current_page_posts):
                    row = i // columns
                    col = i % columns
                    shortcode = post.get('shortcode', '')
                    content_info = post.get('ContentInformation', {})
                    status_hash = (
                        shortcode,
                        post.get('download_status', ''),
                        shortcode in self.queued_shortcodes,
                        post.get('typename', ''),
                        content_info.get('topicID'),  # Include topic_id from ContentInformation to detect assignment changes
                    )
                    self.current_tile_data[(row, col)] = status_hash
                
                self.last_displayed_page = self.current_page
                self.last_displayed_columns = columns
                self.update_pagination_controls()
                self.update_topic_assigned_download_button_text()
                return
            
            # Same page - do differential update for changed items only
            # Build map of what should be displayed: {(row, col): post}
            new_layout = {}
            for i, post in enumerate(current_page_posts):
                row = i // columns
                col = i % columns
                new_layout[(row, col)] = post
            
            # Compare with current layout - build hash to detect changes
            new_tile_data = {}
            tiles_to_update = []
            
            for position, post in new_layout.items():
                shortcode = post.get('shortcode', '')
                content_info = post.get('ContentInformation', {})
                # Create hash from relevant fields that would affect display
                status_hash = (
                    shortcode,
                    post.get('download_status', ''),
                    shortcode in self.queued_shortcodes,
                    post.get('typename', ''),
                    content_info.get('topicID'),  # Include topic_id from ContentInformation to detect assignment changes
                )
                new_tile_data[position] = status_hash
                
                # Check if this position needs updating
                if position not in self.current_tile_data or self.current_tile_data[position] != status_hash:
                    # Data changed or new position - need to update
                    tiles_to_update.append((position, post))
            
            # Only proceed if there are changes
            if not tiles_to_update:
                # Nothing changed, just update pagination controls
                self.update_pagination_controls()
                self.update_topic_assigned_download_button_text()
                return
            
            # Update tiles that changed
            for position, post in tiles_to_update:
                # Remove old tile if it exists
                item = self.tiles_grid.itemAtPosition(position[0], position[1])
                if item and item.widget():
                    widget = item.widget()
                    self.tiles_grid.removeWidget(widget)
                    widget.setParent(None)
                    widget.deleteLater()
                # Add new tile
                row_number = start_idx + (position[0] * columns + position[1]) + 1
                tile = self.create_tile_widget(post, row_number)
                self.tiles_grid.addWidget(tile, position[0], position[1])
            
            # Update tracking
            self.current_tile_data = new_tile_data
            
            # Update pagination controls
            self.update_pagination_controls()
            self.update_topic_assigned_download_button_text()
        except Exception as e:
            logger.error(f"Error in populate_tiles: {e}", exc_info=True)
            self.browse_status.setText(f"Error displaying page {self.current_page + 1}")
            QMessageBox.warning(self, "Display Error", f"Failed to display tiles:\n{str(e)}")
        finally:
            # Always reset the flag, even if an error occurred
            self._populating_tiles = False
    
    def _clear_all_tiles(self):
        """Clear all tiles from the grid"""
        while self.tiles_grid.count():
            child = self.tiles_grid.takeAt(0)
            if child.widget():
                widget = child.widget()
                widget.setParent(None)
                widget.deleteLater()
        self.current_tile_data = {}
    
    def get_item_background_color(self, shortcode, download_status, topic_id=None):
        """Determine background color based on priority:
        1. Ignored (black) - user marked as ignored
        2. Errors (red) - download errors or other issues
        3. In Queue (aqua) - added to download queue
        4. Topic assigned + Downloaded (blue) - categorized and complete
        5. Topic assigned + Not Downloaded (pink) - categorized but not downloaded
        6. Downloaded (green) - content downloaded but not organized
        7. Not downloaded (gray) - default state
        
        Args:
            shortcode: The post shortcode
            download_status: Download status string
            topic_id: Optional topic_id from cached data (preferred over DB query)
        """
        # Priority 1: Check if ignored
        if download_status == 'ignored':
            return '#1a1a1a', '#2d2d2d'  # Black, lighter black hover
        
        # Priority 2: Check for errors (both 'error' and 'failed' statuses)
        if download_status in ('error', 'failed', 'success_with_issues'):
            return '#ff4444', '#cc0000'  # Bright red, darker red hover
        
        # Priority 3: Check if in download queue
        if shortcode in self.queued_shortcodes:
            return '#b2ebf2', '#80deea'  # Light aqua, darker aqua hover
        
        # Priority 4 & 5: Check if topic is assigned
        # Use provided topic_id if available (from cache), otherwise query database
        has_topic = False
        if topic_id is None and self.content_db and self.content_db.db:
            try:
                entry = self.content_db.db.get_content_entry(shortcode)
                if entry:
                    content_info = entry.get('ContentInformation', {})
                    topic_id = content_info.get('topicID')
            except Exception:
                pass  # Continue to next check
        
        # Check if topic is assigned (either from cache or DB)
        if topic_id is not None:
            has_topic = True
            # Priority 4: Topic + Downloaded = FULL BLUE
            if download_status in ['downloaded', 'completed', 're-downloaded']:
                logger.debug(f"[COLOR] {shortcode}: topic_id={topic_id}, status={download_status} -> BLUE (downloaded+topic)")
                return '#4169E1', '#1E90FF'  # Royal blue, dodger blue hover
            # Priority 5: Topic + Not Downloaded = FULL PINK
            else:
                logger.debug(f"[COLOR] {shortcode}: topic_id={topic_id}, status={download_status} -> PINK (not downloaded+topic)")
                return '#FF69B4', '#FF1493'  # Hot pink, deep pink hover
        
        # Priority 6: Check if downloaded (no topic)
        if download_status in ['downloaded', 'completed', 're-downloaded']:
            return '#c8e6c9', '#a5d6a7'  # Light green, darker green hover
        
        # Priority 7: Not downloaded (default)
        return '#e0e0e0', '#bdbdbd'  # Gray, darker gray hover
    
    def get_downloaded_files(self, shortcode):
        """Get list of downloaded files for a shortcode from database"""
        logger.info(f"get_downloaded_files() called for {shortcode}")
        if not self.content_db or not self.content_db.db:
            logger.warning("No content database available")
            return []
        
        try:
            entry = self.content_db.db.get_content_entry(shortcode)
            if not entry:
                logger.warning(f"No database entry found for {shortcode}")
                return []
            
            logger.info(f"Found database entry for {shortcode}")
            files_info = entry.get('FilesInformation', {})
            file_list = files_info.get('FileList', [])
            logger.info(f"FileList contains {len(file_list)} file(s)")
            
            # Check overall download status to adjust logging level
            overall_status = entry.get('download_status', 'unknown')
            is_failed = overall_status in ['failed', 'error', 'success_with_issues']
            
            # Filter for successfully downloaded files with valid paths
            downloaded_files = []
            for i, f in enumerate(file_list):
                file_path = f.get('FileDestinationPath') or f.get('file_destination_path')
                file_status = f.get('FileDownloadStatus') or f.get('file_download_status')
                file_type = f.get('FileType') or f.get('file_type', '')
                
                logger.debug(f"  File {i}: path={file_path}, status={file_status}, type={file_type}")
                
                # Accept 'downloaded', 'completed', and 're-downloaded' as valid statuses
                if file_path and os.path.exists(file_path) and file_status in ['downloaded', 'completed', 're-downloaded']:
                    downloaded_files.append({
                        'path': file_path,
                        'type': file_type,
                        'number': f.get('FileNumber') or f.get('file_number', 0)
                    })
                    logger.debug(f"  ✓ File {i} added to downloaded list")
                else:
                    # Use debug level for failed downloads (expected), warning for successful ones (unexpected)
                    log_level = logger.debug if is_failed else logger.warning
                    if not file_path:
                        log_level(f"  ✗ File {i} skipped: no path")
                    elif not os.path.exists(file_path):
                        log_level(f"  ✗ File {i} skipped: path doesn't exist: {file_path}")
                    elif file_status not in ['downloaded', 'completed', 're-downloaded']:
                        log_level(f"  ✗ File {i} skipped: status '{file_status}' not in ['downloaded', 'completed', 're-downloaded']")
            
            # Sort by file number
            downloaded_files.sort(key=lambda x: x['number'])
            
            logger.info(f"Returning {len(downloaded_files)} downloaded file(s) for {shortcode}")
            
            # Debug logging for carousel detection
            if len(downloaded_files) > 1:
                logger.info(f"Carousel detected for {shortcode}: {len(downloaded_files)} files")
            
            return downloaded_files
        except Exception as e:
            logger.error(f"Error getting downloaded files for {shortcode}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def play_video(self, video_path, inline_container=None):
        """Play video either inline or in popup dialog
        
        Args:
            video_path: Path to video file
            inline_container: If provided, play inline in this widget. Otherwise use popup.
        """
        if not os.path.exists(video_path):
            QMessageBox.warning(self, "File Not Found", f"Video file not found:\n{video_path}")
            return
        
        try:
            if self.inline_video and inline_container:
                # Play inline in the tile
                self._play_video_inline(video_path, inline_container)
            else:
                # Play in popup dialog
                self._play_video_popup(video_path)
                
            logger.info(f"Playing video: {video_path}")
        except Exception as e:
            logger.error(f"Failed to play video {video_path}: {e}")
            QMessageBox.warning(self, "Error", f"Failed to play video:\n{e}")
    
    def _check_vlc_available(self):
        """Check if VLC player is available (cached check)"""
        if self.vlc_available is not None:
            return self.vlc_available
        
        try:
            import vlc
            import struct
            
            # Check Python bitness
            python_is_64bit = struct.calcsize('P') * 8 == 64
            
            # Try to find VLC on Windows
            if platform.system() == "Windows":
                import os
                
                # Check for matching architecture first
                if python_is_64bit:
                    vlc_paths = [
                        r"C:\Program Files\VideoLAN\VLC",
                    ]
                else:
                    vlc_paths = [
                        r"C:\Program Files (x86)\VideoLAN\VLC",
                    ]
                
                vlc_path = None
                for path in vlc_paths:
                    dll_path = os.path.join(path, "libvlc.dll")
                    if os.path.exists(dll_path):
                        vlc_path = path
                        logger.info(f"Found VLC at: {vlc_path}")
                        break
                
                if not vlc_path:
                    # Check if wrong architecture is installed
                    wrong_arch_path = r"C:\Program Files (x86)\VideoLAN\VLC" if python_is_64bit else r"C:\Program Files\VideoLAN\VLC"
                    if os.path.exists(wrong_arch_path):
                        arch_type = "64-bit" if python_is_64bit else "32-bit"
                        wrong_arch_type = "32-bit" if python_is_64bit else "64-bit"
                        raise Exception(
                            f"Python is {arch_type} but VLC appears to be {wrong_arch_type}.\n"
                            f"Please install {arch_type} VLC from videolan.org"
                        )
                    raise Exception(f"VLC not found. Please install {'64-bit' if python_is_64bit else '32-bit'} VLC")
                
                # Add VLC directory to PATH for DLL loading
                if vlc_path not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = vlc_path + os.pathsep + os.environ.get('PATH', '')
                
                # Try to create instance
                try:
                    self.vlc_instance = vlc.Instance('--quiet')
                except Exception as init_error:
                    logger.error(f"VLC instance creation failed: {init_error}")
                    raise Exception(f"VLC found but failed to initialize: {init_error}")
            else:
                # Linux/Mac
                args = ['--quiet']
                if platform.system() == "Linux":
                    args.append('--no-xlib')
                self.vlc_instance = vlc.Instance(*args)
            
            if not self.vlc_instance:
                raise Exception("VLC instance is None after creation")
            
            # Test that we can create a media player
            test_player = self.vlc_instance.media_player_new()
            if not test_player:
                raise Exception("Failed to create VLC media player")
            
            self.vlc_available = True
            logger.info(f"VLC player successfully initialized (Python: {'64-bit' if python_is_64bit else '32-bit'})")
            
        except ImportError:
            logger.info("python-vlc package not installed")
            self.vlc_available = False
            self.vlc_instance = None
        except Exception as e:
            logger.warning(f"VLC initialization failed: {e}")
            self.vlc_available = False
            self.vlc_instance = None
        
        return self.vlc_available
    
    def _check_qt_multimedia(self):
        """Check if Qt multimedia codecs are available (cached check)"""
        if self.qt_multimedia_available is not None:
            return self.qt_multimedia_available
        
        try:
            # Try to create a media player
            test_player = QMediaPlayer()
            # Just check if player creation works - actual codec check happens on playback
            # We'll detect failures during actual playback and update the flag
            self.qt_multimedia_available = True
            logger.info("Qt multimedia player available - will test codecs on first playback")
        except Exception as e:
            logger.warning(f"Qt multimedia not available: {e}")
            self.qt_multimedia_available = False
            self.account_manager.set_setting('qt_multimedia_available', 'false')
        
        return self.qt_multimedia_available
    
    def _play_video_popup(self, video_path):
        """Play video in popup dialog or fall back to system player"""
        # Check if user wants to force system player
        if self.force_system_player:
            logger.info("Force system player enabled - using system player")
            self._play_video_system(video_path)
            return
        
        # Try VLC first (has its own codecs)
        if self._check_vlc_available():
            try:
                self._play_video_vlc_popup(video_path)
                return
            except Exception as e:
                logger.warning(f"VLC player failed: {e}, trying Qt player")
        
        # Check if Qt multimedia is available (cached check)
        if not self._check_qt_multimedia():
            logger.info("Qt multimedia unavailable, using system player directly")
            self._play_video_system(video_path)
            return
        
        try:
            # Try Qt multimedia player
            self._try_qt_video_player(video_path)
        except Exception as e:
            logger.warning(f"Qt video player failed: {e}, falling back to system player")
            # Fall back to system default player
            self._play_video_system(video_path)
    
    def _try_qt_video_player(self, video_path):
        """Try to play video using Qt multimedia"""
        # Create video player dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Video Player")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Video widget
        video_widget = QVideoWidget()
        layout.addWidget(video_widget)
        
        # Control buttons
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(10, 5, 10, 5)
        
        play_pause_btn = QPushButton("⏸ Pause")
        play_pause_btn.setMaximumWidth(100)
        controls_layout.addWidget(play_pause_btn)
        
        stop_btn = QPushButton("⏹ Stop")
        stop_btn.setMaximumWidth(100)
        controls_layout.addWidget(stop_btn)
        
        controls_layout.addStretch()
        
        fallback_btn = QPushButton("Open Externally")
        fallback_btn.setMaximumWidth(120)
        fallback_btn.setToolTip("Open in system video player")
        fallback_btn.clicked.connect(lambda: self._play_video_system(video_path))
        controls_layout.addWidget(fallback_btn)
        
        close_btn = QPushButton("Close")
        close_btn.setMaximumWidth(100)
        close_btn.clicked.connect(dialog.close)
        controls_layout.addWidget(close_btn)
        
        layout.addLayout(controls_layout)
        
        # Media player
        player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        player.setVideoOutput(video_widget)
        
        # Track if we had errors
        had_error = [False]
        
        # Handle media status changes
        def on_media_status_changed(status):
            if status == QMediaPlayer.LoadedMedia:
                player.play()
            elif status == QMediaPlayer.InvalidMedia:
                error_string = player.errorString()
                logger.error(f"Qt Media Player - Invalid media: {error_string}")
                had_error[0] = True
                # Mark Qt multimedia as unavailable for future playback and save setting
                self.qt_multimedia_available = False
                self.account_manager.set_setting('qt_multimedia_available', 'false')
                logger.info("Qt codecs unavailable - saved preference to use system player")
                # Close dialog and fall back to system player
                dialog.close()
                QMessageBox.information(
                    self, 
                    "Video Player",
                    "Qt video codecs not available.\n\nVideos will now open in your system player.\nThis preference has been saved."
                )
                self._play_video_system(video_path)
        
        player.mediaStatusChanged.connect(on_media_status_changed)
        
        # Connect controls
        def toggle_play_pause():
            if player.state() == QMediaPlayer.PlayingState:
                player.pause()
                play_pause_btn.setText("▶ Play")
            else:
                player.play()
                play_pause_btn.setText("⏸ Pause")
        
        def stop_video():
            player.stop()
            play_pause_btn.setText("▶ Play")
        
        play_pause_btn.clicked.connect(toggle_play_pause)
        stop_btn.clicked.connect(stop_video)
        
        # Set media and load
        media_url = QUrl.fromLocalFile(video_path)
        player.setMedia(QMediaContent(media_url))
        
        # Show dialog (blocking) only if no error
        if not had_error[0]:
            dialog.exec_()
        
        # Cleanup
        player.stop()
        player.setMedia(QMediaContent())
    
    def _play_video_system(self, video_path):
        """Open video in system default player"""
        import subprocess
        import platform
        
        try:
            system = platform.system()
            if system == 'Windows':
                os.startfile(video_path)
            elif system == 'Darwin':  # macOS
                subprocess.Popen(['open', video_path])
            else:  # Linux
                subprocess.Popen(['xdg-open', video_path])
            
            logger.info(f"Opened video in system player: {video_path}")
        except Exception as e:
            logger.error(f"Failed to open video {video_path}: {e}")
            QMessageBox.warning(self, "Error", f"Failed to open video:\n{e}")
    
    def _play_video_vlc_popup(self, video_path):
        """Play video in popup using VLC player"""
        import vlc
        
        # Create video player dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Video Player (VLC)")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Video frame for VLC
        if platform.system() == "Windows":
            video_frame = QFrame()
        else:
            from PyQt5.QtWidgets import QFrame
            video_frame = QFrame()
        
        video_frame.setStyleSheet("background-color: black;")
        layout.addWidget(video_frame)
        
        # Control buttons
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(10, 5, 10, 5)
        
        play_pause_btn = QPushButton("⏸ Pause")
        play_pause_btn.setMaximumWidth(100)
        controls_layout.addWidget(play_pause_btn)
        
        stop_btn = QPushButton("⏹ Stop")
        stop_btn.setMaximumWidth(100)
        controls_layout.addWidget(stop_btn)
        
        position_slider = QSlider(Qt.Horizontal)
        position_slider.setMaximum(1000)
        position_slider.setEnabled(False)
        controls_layout.addWidget(position_slider)
        
        volume_slider = QSlider(Qt.Horizontal)
        volume_slider.setMaximum(100)
        volume_slider.setValue(50)
        volume_slider.setMaximumWidth(100)
        volume_slider.setToolTip("Volume")
        controls_layout.addWidget(volume_slider)
        
        close_btn = QPushButton("Close")
        close_btn.setMaximumWidth(100)
        close_btn.clicked.connect(dialog.close)
        controls_layout.addWidget(close_btn)
        
        layout.addLayout(controls_layout)
        
        # Create VLC player
        player = self.vlc_instance.media_player_new()
        media = self.vlc_instance.media_new(video_path)
        player.set_media(media)
        
        # Set video output to Qt widget
        if platform.system() == "Windows":
            player.set_hwnd(int(video_frame.winId()))
        elif platform.system() == "Darwin":  # macOS
            player.set_nsobject(int(video_frame.winId()))
        else:  # Linux
            player.set_xwindow(int(video_frame.winId()))
        
        # Connect controls
        def toggle_play_pause():
            if player.is_playing():
                player.pause()
                play_pause_btn.setText("▶ Play")
            else:
                player.play()
                play_pause_btn.setText("⏸ Pause")
        
        def stop_video():
            # Stop timer FIRST to prevent update_ui from running during stop
            timer.stop()
            play_pause_btn.setText("▶ Play")
            position_slider.setValue(0)
            # Stop player in background to avoid blocking main thread
            from threading import Thread
            def _bg_stop():
                try:
                    player.stop()
                except Exception as e:
                    logger.debug(f"VLC popup stop_video bg: {e}")
                QMetaObject.invokeMethod(timer, "start", Qt.QueuedConnection, Q_ARG(int, 100))
            Thread(target=_bg_stop, daemon=True).start()
        
        def set_position(position):
            player.set_position(position / 1000.0)
        
        def set_volume(volume):
            player.audio_set_volume(volume)
        
        # Update position slider
        def update_ui():
            try:
                if player.is_playing():
                    position_slider.setValue(int(player.get_position() * 1000))
                    position_slider.setEnabled(True)
            except RuntimeError:
                # Widget has been deleted - stop the timer
                timer.stop()
            except Exception as e:
                # Any other error - log and stop timer
                logger.debug(f"Error in VLC update_ui: {e}")
                timer.stop()
        
        play_pause_btn.clicked.connect(toggle_play_pause)
        stop_btn.clicked.connect(stop_video)
        position_slider.sliderMoved.connect(set_position)
        volume_slider.valueChanged.connect(set_volume)
        
        # Timer to update position
        timer = QTimer(dialog)
        timer.timeout.connect(update_ui)
        timer.start(100)
        
        # Non-blocking cleanup — always stop timer on main thread, stop player in background.
        def _cleanup_player():
            """Tear down timer + VLC player without blocking the main thread."""
            try:
                timer.stop()
                timer.timeout.disconnect()
            except Exception:
                pass
            
            from threading import Thread
            def _bg_stop():
                try:
                    player.stop()
                    player.set_media(None)
                except Exception as e:
                    logger.debug(f"VLC popup bg stop: {e}")
            Thread(target=_bg_stop, daemon=True).start()
        
        dialog.finished.connect(lambda _: _cleanup_player())
        
        # Start playback
        player.play()
        set_volume(50)
        
        # Show dialog (non-blocking teardown is handled by finished signal above)
        dialog.exec_()
    
    def _play_video_vlc_inline(self, video_path, container):
        """Play video inline in a container using VLC"""
        try:
            import vlc
            
            logger.info(f"Starting VLC inline playback for {video_path}")
            
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")
            
            # Clear existing widgets
            while container.count():
                child = container.takeAt(0)
                if child.widget():
                    widget = child.widget()
                    # Stop any existing VLC player - timer first, then player
                    if hasattr(widget, 'vlc_player'):
                        try:
                            if hasattr(widget, 'vlc_timer'):
                                widget.vlc_timer.stop()
                            widget.vlc_player.stop()
                        except Exception as e:
                            logger.debug(f"Error stopping existing VLC player: {e}")
                    widget.deleteLater()
            
            # Create video frame
            video_frame = QFrame()
            video_frame.setStyleSheet("background-color: black;")
            
            # Get thumbnail size from existing carousel image or use default
            thumb_size = 150  # default width
            video_height = 150  # default height (will be adjusted to be taller)
            
            # Try to get size from media container first (most reliable)
            try:
                parent = container.parent()
                if parent and hasattr(parent, 'is_carousel_media_container'):
                    thumb_size = parent.width() if parent.width() > 0 else 150
                else:
                    # Try finding it in parent hierarchy
                    current = container.parent()
                    while current and thumb_size == 150:
                        if hasattr(current, 'is_carousel_media_container'):
                            thumb_size = current.width() if current.width() > 0 else 150
                            break
                        for widget in current.findChildren(QWidget):
                            if hasattr(widget, 'is_carousel_media_container'):
                                thumb_size = widget.width() if widget.width() > 0 else 150
                                break
                        current = current.parent()
            except:
                pass
            
            # Fallback: check carousel images
            if thumb_size == 150:
                try:
                    parent_widget = container.parent()
                    while parent_widget and thumb_size == 150:
                        for widget in parent_widget.findChildren(QLabel):
                            if hasattr(widget, 'is_carousel_image'):
                                thumb_size = widget.width() if widget.width() > 0 else 150
                                break
                        parent_widget = parent_widget.parent()
                except:
                    pass
            
            # Use square aspect ratio to ensure inline controls fit properly
            video_height = thumb_size
            
            video_frame.setFixedSize(thumb_size, video_height)
            container.addWidget(video_frame)
            
            # Create thumbnail overlay to show before playback starts
            thumbnail_overlay = QLabel(video_frame)
            thumbnail_overlay.setFixedSize(thumb_size, video_height)
            thumbnail_overlay.setScaledContents(True)
            thumbnail_overlay.setStyleSheet("background-color: black;")
            thumbnail_overlay.setAlignment(Qt.AlignCenter)
            
            # Load video thumbnail
            pixmap = self._extract_video_thumbnail(video_path)
            if pixmap and not pixmap.isNull():
                thumbnail_overlay.setPixmap(pixmap.scaled(
                    thumb_size, video_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
            else:
                # Show video icon if thumbnail extraction fails
                thumbnail_overlay.setText("🎬\nReady")
                thumbnail_overlay.setStyleSheet(
                    "background-color: black; color: white; font-size: 24pt; border: 1px solid #666;"
                )
            
            thumbnail_overlay.show()
            video_frame.thumbnail_overlay = thumbnail_overlay
            
            logger.debug("Video frame created and added to container")
        except Exception as e:
            logger.error(f"Error setting up VLC inline player: {e}")
            raise
        
        # Create compact controls
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(2, 2, 2, 2)
        controls_layout.setSpacing(2)
        
        play_pause_btn = QPushButton("▶")
        play_pause_btn.setMaximumWidth(30)
        play_pause_btn.setToolTip("Play/Pause")
        controls_layout.addWidget(play_pause_btn)
        
        stop_btn = QPushButton("⏹")
        stop_btn.setMaximumWidth(30)
        stop_btn.setToolTip("Stop")
        controls_layout.addWidget(stop_btn)
        
        position_slider = QSlider(Qt.Horizontal)
        position_slider.setMaximum(1000)
        position_slider.setEnabled(False)
        controls_layout.addWidget(position_slider)
        
        popup_btn = QPushButton("⤢")
        popup_btn.setMaximumWidth(30)
        popup_btn.setToolTip("Open in popup")
        popup_btn.clicked.connect(lambda: self._play_video_popup(video_path))
        controls_layout.addWidget(popup_btn)
        
        container.addLayout(controls_layout)
        
        try:
            # Create VLC player
            player = self.vlc_instance.media_player_new()
            if not player:
                raise Exception("Failed to create VLC media player instance")
            
            media = self.vlc_instance.media_new(video_path)
            if not media:
                raise Exception(f"Failed to create VLC media from path: {video_path}")
            
            player.set_media(media)
            
            # Set video output
            if platform.system() == "Windows":
                player.set_hwnd(int(video_frame.winId()))
            elif platform.system() == "Darwin":
                player.set_nsobject(int(video_frame.winId()))
            else:
                player.set_xwindow(int(video_frame.winId()))
        except Exception as e:
            logger.error(f"Error creating VLC player/media: {e}")
            raise
        
        # Connect controls
        def toggle_play_pause():
            if player.is_playing():
                player.pause()
                play_pause_btn.setText("▶")
            else:
                # Hide thumbnail overlay when starting playback
                if hasattr(video_frame, 'thumbnail_overlay'):
                    video_frame.thumbnail_overlay.hide()
                player.play()
                play_pause_btn.setText("⏸")
        
        def stop_video():
            # Stop timer FIRST to prevent update_ui from running during stop
            timer.stop()
            play_pause_btn.setText("▶")
            position_slider.setValue(0)
            # Show thumbnail overlay again when stopped
            if hasattr(video_frame, 'thumbnail_overlay'):
                video_frame.thumbnail_overlay.show()
            # Stop player in background to avoid blocking main thread
            from threading import Thread
            def _bg_stop():
                try:
                    player.stop()
                except Exception as e:
                    logger.debug(f"VLC inline stop_video bg: {e}")
                QMetaObject.invokeMethod(timer, "start", Qt.QueuedConnection, Q_ARG(int, 100))
            Thread(target=_bg_stop, daemon=True).start()
        
        def set_position(position):
            player.set_position(position / 1000.0)
        
        def update_ui():
            try:
                if player.is_playing():
                    position_slider.setValue(int(player.get_position() * 1000))
                    position_slider.setEnabled(True)
            except RuntimeError:
                # Widget has been deleted (tile was rebuilt) - stop the timer
                timer.stop()
            except Exception as e:
                # Any other error - log and stop timer
                logger.debug(f"Error in VLC inline update_ui: {e}")
                timer.stop()
        
        play_pause_btn.clicked.connect(toggle_play_pause)
        stop_btn.clicked.connect(stop_video)
        position_slider.sliderMoved.connect(set_position)
        
        # Timer to update position — parented to video_frame so it dies with the widget
        timer = QTimer(video_frame)
        timer.timeout.connect(update_ui)
        timer.start(100)
        
        # Store references to prevent garbage collection
        video_frame.vlc_player = player
        video_frame.vlc_timer = timer
        
        # Non-blocking cleanup when the container widget is destroyed
        def _inline_cleanup():
            """Stop timer on main thread, stop VLC player in background."""
            try:
                timer.stop()
                timer.timeout.disconnect()
            except Exception:
                pass
            
            from threading import Thread
            def _bg_stop():
                try:
                    player.stop()
                    player.set_media(None)
                except Exception as e:
                    logger.debug(f"VLC inline bg stop: {e}")
            Thread(target=_bg_stop, daemon=True).start()
        
        video_frame.destroyed.connect(lambda: _inline_cleanup())
        
        # Auto-play (thumbnail overlay will hide when playback starts)
        player.play()
        player.audio_set_volume(self.tile_video_volume)  # Use saved volume preference
        
        logger.info(f"VLC inline player started for {video_path} (volume: {self.tile_video_volume})")
    
    
    def _play_video_inline(self, video_path, container):
        """Play video inline within a tile container"""
        # Check if user wants to force system player
        if self.force_system_player:
            logger.info("Force system player enabled - using system player (no inline)")
            self._play_video_system(video_path)
            return
        
        # Try VLC for inline playback
        vlc_check_result = self._check_vlc_available()
        
        if vlc_check_result:
            try:
                self._play_video_vlc_inline(video_path, container)
                return
            except Exception as e:
                error_msg = str(e)
                logger.error(f"VLC inline playback error: {error_msg}", exc_info=True)
                
                # Show error only if VLC seemed to be available
                import struct
                python_bits = 64 if struct.calcsize('P') * 8 == 64 else 32
                
                QMessageBox.warning(
                    self,
                    "VLC Inline Playback Error",
                    f"Failed to play video inline with VLC:\\n\\n{error_msg}\\n\\n"
                    f"System Info:\\n"
                    f"• Python: {python_bits}-bit\\n"
                    f"• VLC Version: Check if {python_bits}-bit VLC is installed\\n\\n"
                    f"Troubleshooting:\\n"
                    f"• Ensure VLC {python_bits}-bit is installed\\n"
                    f"• Try popup mode instead of inline\\n"
                    f"• Check VLC installation at C:\\\\Program Files\\\\VideoLAN\\\\VLC\\n\\n"
                    f"Using popup mode instead..."
                )
        else:
            # VLC not available - show helpful message once per session
            if not hasattr(self, '_vlc_warning_shown'):
                self._vlc_warning_shown = True
                import struct
                python_bits = 64 if struct.calcsize('P') * 8 == 64 else 32
                
                logger.info("VLC not available for inline playback - falling back to popup")
                QMessageBox.information(
                    self,
                    "VLC Required for Inline Video",
                    f"Inline video requires VLC media player ({python_bits}-bit).\\n\\n"
                    f"To enable inline video:\\n"
                    f"1. Download VLC {python_bits}-bit from https://www.videolan.org/\\n"
                    f"2. Install VLC with default settings\\n"
                    f"3. Restart this application\\n\\n"
                    f"Using popup mode for now...\\n"
                    f"(This message will not show again this session)"
                )
        
        # Fall back to popup (VLC or Qt or system)
        self._play_video_popup(video_path)
    
    def show_carousel_item(self, tile_frame, shortcode, files, index):
        """Update carousel display to show item at index"""
        if not files or index < 0 or index >= len(files):
            return
        
        # Stop any playing videos first and restore thumbnail view
        self._stop_inline_videos_and_restore(tile_frame, files, index)
        
        # Store current index
        self.carousel_indices[shortcode] = index
        
        # Update counter label
        for widget in tile_frame.findChildren(QLabel):
            if hasattr(widget, 'is_carousel_counter'):
                widget.setText(f"{index + 1}/{len(files)}")
                break
        
        # Update play button visibility and connection
        self._update_carousel_play_button(tile_frame, shortcode, files, index)
    
    def _stop_inline_videos_and_restore(self, tile_frame, files, index):
        """Stop inline videos and restore thumbnail display for carousel navigation"""
        # Find media container
        media_container = None
        for widget in tile_frame.findChildren(QWidget):
            if hasattr(widget, 'is_carousel_media_container'):
                media_container = widget
                break
        
        if not media_container:
            return
        
        media_layout = media_container.layout()
        if not media_layout:
            return
        
        # Stop any VLC players and clear the media layout
        while media_layout.count():
            child = media_layout.takeAt(0)
            if child.widget():
                widget = child.widget()
                # Stop any existing VLC player
                if hasattr(widget, 'vlc_player'):
                    try:
                        widget.vlc_player.stop()
                        if hasattr(widget, 'vlc_timer'):
                            widget.vlc_timer.stop()
                        logger.debug("Stopped inline VLC player during navigation")
                    except Exception as e:
                        logger.debug(f"Error stopping VLC player: {e}")
                widget.deleteLater()
        
        # Restore thumbnail for new index
        if index < len(files):
            file_info = files[index]
            file_path = file_info['path']
            is_video = file_info['type'] in ['video', 'mp4']
            
            # Get thumbnail size from media container's fixed size (most reliable)
            thumb_size = media_container.width() if media_container.width() > 0 else 150
            media_height = media_container.height() if media_container.height() > 0 else thumb_size
            
            logger.debug(f"Restoring thumbnail at index {index} with size {thumb_size}x{media_height}")
            
            # Create new thumbnail label with fixed size (taller for videos)
            thumb_label = HoverImageLabel(file_path) if not is_video else QLabel()
            thumb_label.is_carousel_image = True
            thumb_label.setFixedSize(thumb_size, media_height)
            thumb_label.setScaledContents(True)
            thumb_label.setStyleSheet("border: 1px solid #ccc;")
            thumb_label.setAlignment(Qt.AlignCenter)
            
            # Load image or video thumbnail
            if is_video:
                pixmap = self._extract_video_thumbnail(file_path)
                if pixmap and not pixmap.isNull():
                    thumb_label.setPixmap(pixmap.scaled(
                        thumb_size, media_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                else:
                    thumb_label.setText("🎬\nVideo")
                    thumb_label.setStyleSheet("border: 1px solid #ccc; font-size: 24pt; color: #666;")
            else:
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    thumb_label.setPixmap(pixmap.scaled(
                        thumb_size, media_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    if isinstance(thumb_label, HoverImageLabel):
                        thumb_label.image_path = file_path
            
            media_layout.addWidget(thumb_label)
    
    def _stop_inline_videos(self, container):
        """Stop any VLC videos playing inline in the container"""
        try:
            for widget in container.findChildren(QFrame):
                if hasattr(widget, 'vlc_player'):
                    try:
                        widget.vlc_player.stop()
                        if hasattr(widget, 'vlc_timer'):
                            widget.vlc_timer.stop()
                        logger.debug("Stopped inline VLC player")
                    except Exception as e:
                        logger.debug(f"Error stopping VLC player: {e}")
        except Exception as e:
            logger.debug(f"Error in _stop_inline_videos: {e}")
    
    def _update_carousel_play_button(self, tile_frame, shortcode, files, index):
        """Update play button state and connection for current carousel item"""
        if index < 0 or index >= len(files):
            return
        
        current_file = files[index]
        is_video = current_file['type'] in ['video', 'mp4']
        
        # Find and update play button
        for button in tile_frame.findChildren(QPushButton):
            if hasattr(button, 'is_carousel_play_button'):
                # Update button appearance based on file type
                if is_video:
                    button.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
                    button.setEnabled(True)
                    button.setToolTip(f"Play Video {index + 1}")
                else:
                    button.setStyleSheet("QPushButton { background-color: #ccc; color: #666; }")
                    button.setEnabled(False)
                    button.setToolTip("Not a video")
                
                # Reconnect button with updated index
                try:
                    button.clicked.disconnect()
                except:
                    pass
                
                # Get carousel layout for inline playback - find media container
                media_container_layout = None
                if hasattr(button, 'carousel_tile'):
                    for widget in button.carousel_tile.findChildren(QWidget):
                        if hasattr(widget, 'is_carousel_media_container'):
                            media_container_layout = widget.layout()
                            break
                
                def play_current():
                    if is_video and media_container_layout:
                        self.play_video(current_file['path'], media_container_layout)
                
                button.clicked.connect(play_current)
                break
    
    def _extract_video_thumbnail(self, video_path):
        """Extract first frame from video as thumbnail
        
        Returns:
            QPixmap or None if extraction failed
        """
        try:
            # Try using OpenCV if available
            import cv2
            
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None
            
            # Read first frame
            ret, frame = cap.read()
            cap.release()
            
            if not ret or frame is None:
                return None
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Convert to QPixmap
            height, width, channel = frame_rgb.shape
            bytes_per_line = 3 * width
            from PyQt5.QtGui import QImage
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image)
            
            return pixmap
        except ImportError:
            # OpenCV not available, return None
            logger.debug(f"OpenCV not available for video thumbnail extraction")
            return None
        except Exception as e:
            logger.error(f"Error extracting video thumbnail from {video_path}: {e}")
            return None
    
    def _add_tile_media_display(self, layout, tile, config, shortcode, downloaded_files):
        """Add media display to tile with interactive controls based on content type"""
        thumb_size = config['thumb']
        
        logger.debug(f"[MEDIA_DISPLAY] {shortcode}: downloaded_files count={len(downloaded_files) if downloaded_files else 0}")
        
        if downloaded_files:
            # Content is downloaded - add interactive controls
            file_count = len(downloaded_files)
            is_carousel = file_count > 1
            has_video = any(f['type'] in ['video', 'mp4'] for f in downloaded_files)
            
            logger.info(f"[MEDIA_DISPLAY] {shortcode}: file_count={file_count}, is_carousel={is_carousel}, has_video={has_video}")
            
            if is_carousel:
                # Carousel with navigation
                logger.info(f"[MEDIA_DISPLAY] {shortcode}: Creating CAROUSEL display")
                self._add_carousel_display(layout, tile, thumb_size, shortcode, downloaded_files)
            elif any(f['type'] in ['video', 'mp4'] for f in downloaded_files):
                # Single video with play button
                logger.info(f"[MEDIA_DISPLAY] {shortcode}: Creating VIDEO display with PLAY BUTTON")
                self._add_video_display(layout, thumb_size, shortcode, downloaded_files[0])
            else:
                # Single image with hover tooltip
                logger.info(f"[MEDIA_DISPLAY] {shortcode}: Creating IMAGE display")
                self._add_image_display(layout, thumb_size, downloaded_files[0])
        else:
            # Not downloaded - show regular thumbnail
            logger.debug(f"[MEDIA_DISPLAY] {shortcode}: No files - creating PLACEHOLDER")
            self._add_placeholder_thumbnail(layout, thumb_size, shortcode)
    
    def _add_carousel_display(self, layout, tile, thumb_size, shortcode, downloaded_files):
        """Add carousel display with navigation controls"""
        carousel_container = QWidget()
        carousel_layout = QVBoxLayout(carousel_container)
        carousel_layout.setSpacing(2)
        carousel_layout.setContentsMargins(0, 0, 0, 0)
        
        # Initialize carousel index
        if shortcode not in self.carousel_indices:
            self.carousel_indices[shortcode] = 0
        current_index = self.carousel_indices[shortcode]
        current_file = downloaded_files[current_index]
        
        # Create dedicated video/image display area (THIS is what gets replaced during playback)
        media_container = QWidget()
        # Use square aspect ratio to ensure controls fit within tile max heights
        media_height = thumb_size
        media_container.setFixedSize(thumb_size, media_height)
        media_layout = QVBoxLayout(media_container)
        media_layout.setSpacing(0)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_container.is_carousel_media_container = True
        
        # Image/Video display
        is_video = current_file['type'] in ['video', 'mp4']
        thumb_label = HoverImageLabel(current_file['path']) if not is_video else QLabel()
        thumb_label.is_carousel_image = True
        thumb_label.setFixedSize(thumb_size, media_height)  # Match container height
        thumb_label.setScaledContents(True)
        thumb_label.setStyleSheet("border: 1px solid #ccc;")
        thumb_label.setAlignment(Qt.AlignCenter)
        
        # Load image or video thumbnail
        if is_video:
            # Try to extract video thumbnail
            pixmap = self._extract_video_thumbnail(current_file['path'])
            if pixmap and not pixmap.isNull():
                thumb_label.setPixmap(pixmap.scaled(
                    thumb_size, media_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
            else:
                # Try loading from database
                thumbnail_loaded = False
                if self.content_db and self.content_db.db:
                    thumbnail = self.content_db.db.get_thumbnail(shortcode)
                    if thumbnail and os.path.exists(thumbnail['file_path']):
                        db_pixmap = QPixmap(thumbnail['file_path'])
                        if not db_pixmap.isNull():
                            # Cache it for future use
                            self.thumbnail_cache[shortcode] = db_pixmap
                            thumb_label.setPixmap(db_pixmap.scaled(
                                thumb_size, media_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            ))
                            thumbnail_loaded = True
                
                # Show video icon placeholder if no thumbnail found
                if not thumbnail_loaded:
                    thumb_label.setText("🎬\nVideo")
                    thumb_label.setStyleSheet("border: 1px solid #ccc; font-size: 24pt; color: #666;")
        else:
            pixmap = QPixmap(current_file['path'])
            if not pixmap.isNull():
                thumb_label.setPixmap(pixmap.scaled(
                    thumb_size, media_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                ))
        
        media_layout.addWidget(thumb_label)
        carousel_layout.addWidget(media_container)
        
        # Navigation controls row: First | ◀ | Play | ▶ | Last | Counter
        nav_row = QHBoxLayout()
        nav_row.setSpacing(2)
        
        file_count = len(downloaded_files)
        
        # First button
        first_btn = QPushButton("⏮")
        first_btn.setMaximumWidth(30)
        first_btn.setMaximumHeight(24)
        first_btn.setToolTip("First")
        first_btn.clicked.connect(lambda: self.show_carousel_item(
            tile, shortcode, downloaded_files, 0
        ))
        nav_row.addWidget(first_btn)
        
        # Previous button
        prev_btn = QPushButton("◀")
        prev_btn.setMaximumWidth(30)
        prev_btn.setMaximumHeight(24)
        prev_btn.setToolTip("Previous")
        prev_btn.clicked.connect(lambda: self.show_carousel_item(
            tile, shortcode, downloaded_files, 
            (self.carousel_indices.get(shortcode, 0) - 1) % file_count
        ))
        nav_row.addWidget(prev_btn)
        
        # Play button for current item if video (middle position)
        play_btn = QPushButton("▶")
        play_btn.setMaximumWidth(30)
        play_btn.setMaximumHeight(24)
        play_btn.setToolTip("Play Video")
        play_btn.is_carousel_play_button = True
        
        if current_file['type'] in ['video', 'mp4']:
            play_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
            play_btn.setEnabled(True)
        else:
            play_btn.setStyleSheet("QPushButton { background-color: #ccc; color: #666; }")
            play_btn.setEnabled(False)
        
        # Store data for dynamic reconnection
        play_btn.carousel_shortcode = shortcode
        play_btn.carousel_files = downloaded_files
        play_btn.carousel_tile = tile
        
        # Connect play button - pass media_container, not carousel_layout
        def play_current_video():
            current_idx = self.carousel_indices.get(shortcode, 0)
            if current_idx < len(downloaded_files):
                current = downloaded_files[current_idx]
                if current['type'] in ['video', 'mp4']:
                    # Find the media container
                    media_cont = None
                    for widget in tile.findChildren(QWidget):
                        if hasattr(widget, 'is_carousel_media_container'):
                            media_cont = widget.layout()
                            break
                    if media_cont:
                        self.play_video(current['path'], media_cont)
        
        play_btn.clicked.connect(play_current_video)
        nav_row.addWidget(play_btn)
        
        # Next button
        next_btn = QPushButton("▶")
        next_btn.setMaximumWidth(30)
        next_btn.setMaximumHeight(24)
        next_btn.setToolTip("Next")
        next_btn.clicked.connect(lambda: self.show_carousel_item(
            tile, shortcode, downloaded_files,
            (self.carousel_indices.get(shortcode, 0) + 1) % file_count
        ))
        nav_row.addWidget(next_btn)
        
        # Last button
        last_btn = QPushButton("⏭")
        last_btn.setMaximumWidth(30)
        last_btn.setMaximumHeight(24)
        last_btn.setToolTip("Last")
        last_btn.clicked.connect(lambda: self.show_carousel_item(
            tile, shortcode, downloaded_files, file_count - 1
        ))
        nav_row.addWidget(last_btn)
        
        # Counter label
        counter_label = QLabel(f"{current_index + 1}/{file_count}")
        counter_label.is_carousel_counter = True
        counter_label.setAlignment(Qt.AlignCenter)
        counter_label.setStyleSheet("""
            font-size: 10pt; 
            font-weight: bold; 
            color: #000000;
            background-color: rgba(255, 255, 255, 200);
            padding: 2px 6px;
            border-radius: 3px;
        """)
        counter_label.setMinimumWidth(40)
        nav_row.addWidget(counter_label)
        
        carousel_layout.addLayout(nav_row)
        layout.addWidget(carousel_container, 0, Qt.AlignLeft)
    
    def _add_video_display(self, layout, thumb_size, shortcode, video_file):
        """Add video display with play button"""
        video_container = QWidget()
        video_layout = QVBoxLayout(video_container)
        video_layout.setSpacing(2)
        video_layout.setContentsMargins(0, 0, 0, 0)
        
        # Use square aspect ratio to ensure play button fits within tile max height
        video_height = thumb_size
        
        # Set fixed size on container to ensure it has enough space for video playback
        video_container.setFixedSize(thumb_size, video_height + 32)  # +32 for play button
        
        # Video thumbnail
        thumb_label = QLabel()
        thumb_label.setFixedSize(thumb_size, video_height)
        thumb_label.setScaledContents(True)
        thumb_label.setStyleSheet("border: 1px solid #ccc;")
        thumb_label.setAlignment(Qt.AlignCenter)
        
        # Try to extract video thumbnail
        pixmap = self._extract_video_thumbnail(video_file['path'])
        if pixmap and not pixmap.isNull():
            thumb_label.setPixmap(pixmap.scaled(
                thumb_size, video_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        elif shortcode in self.thumbnail_cache:
            # Fall back to cached thumbnail
            thumb_label.setPixmap(self.thumbnail_cache[shortcode].scaled(
                thumb_size, video_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        else:
            # Try loading from database
            thumbnail_loaded = False
            if self.content_db and self.content_db.db:
                thumbnail = self.content_db.db.get_thumbnail(shortcode)
                if thumbnail and os.path.exists(thumbnail['file_path']):
                    db_pixmap = QPixmap(thumbnail['file_path'])
                    if not db_pixmap.isNull():
                        # Cache it for future use
                        self.thumbnail_cache[shortcode] = db_pixmap
                        thumb_label.setPixmap(db_pixmap.scaled(
                            thumb_size, video_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        ))
                        thumbnail_loaded = True
            
            # Show video icon placeholder if no thumbnail found
            if not thumbnail_loaded:
                thumb_label.setText("\ud83c\udfac\\nVideo")
                thumb_label.setStyleSheet("border: 1px solid #ccc; font-size: 24pt; color: #666;")
        
        video_layout.addWidget(thumb_label)
        
        # Play button
        play_btn = QPushButton("▶ Play Video")
        play_btn.setMaximumHeight(28)
        play_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
                padding: 4px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        # Pass video_layout as inline container for inline playback
        play_btn.clicked.connect(lambda: self.play_video(video_file['path'], video_layout))
        video_layout.addWidget(play_btn)
        
        layout.addWidget(video_container, 0, Qt.AlignLeft)
    
    def _add_image_display(self, layout, thumb_size, image_file):
        """Add image display with hover tooltip"""
        thumb_label = HoverImageLabel(image_file['path'])
        thumb_label.setFixedSize(thumb_size, thumb_size)
        thumb_label.setScaledContents(True)
        thumb_label.setStyleSheet("border: 1px solid #ccc;")
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setToolTip("Hover to view full size")
        
        # Load image
        pixmap = QPixmap(image_file['path'])
        if not pixmap.isNull():
            thumb_label.setPixmap(pixmap.scaled(
                thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        
        layout.addWidget(thumb_label, 0, Qt.AlignLeft)
    
    def _add_placeholder_thumbnail(self, layout, thumb_size, shortcode):
        """Add placeholder thumbnail for non-downloaded content"""
        thumb_label = QLabel()
        thumb_label.is_placeholder_thumbnail = True
        thumb_label.setFixedSize(thumb_size, thumb_size)
        thumb_label.setScaledContents(True)
        thumb_label.setStyleSheet("border: 1px solid #ccc;")
        thumb_label.setAlignment(Qt.AlignCenter)
        
        # Try to load thumbnail from cache first
        if shortcode in self.thumbnail_cache:
            thumb_label.setPixmap(self.thumbnail_cache[shortcode].scaled(
                thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        else:
            # Not in cache - try loading from database
            thumbnail_loaded = False
            if self.content_db and self.content_db.db:
                thumbnail = self.content_db.db.get_thumbnail(shortcode)
                if thumbnail and os.path.exists(thumbnail['file_path']):
                    pixmap = QPixmap(thumbnail['file_path'])
                    if not pixmap.isNull():
                        # Cache the pixmap for future use
                        self.thumbnail_cache[shortcode] = pixmap
                        thumb_label.setPixmap(pixmap.scaled(
                            thumb_size, thumb_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        ))
                        thumbnail_loaded = True
            
            # If no thumbnail found, show placeholder
            if not thumbnail_loaded:
                thumb_label.setText("No\nThumb")
                thumb_label.setAlignment(Qt.AlignCenter)
                thumb_label.setStyleSheet("border: 1px solid #ccc; background: #f0f0f0;")
        
        layout.addWidget(thumb_label, 0, Qt.AlignLeft)
    
    def get_display_typename(self, typename, post=None):
        """Convert raw typename to user-friendly display name with icon
        
        Args:
            typename: The typename from database
            post: Optional post dict to determine content details
        """
        shortcode = post.get('shortcode') if post else None
        
        # For downloaded content, show detailed information
        if shortcode and post.get('download_status') in ['downloaded', 'completed', 're-downloaded']:
            files = self.get_downloaded_files(shortcode)
            if files:
                file_count = len(files)
                
                if file_count > 1:
                    # Carousel - count videos and images
                    videos = sum(1 for f in files if f['type'] in ['video', 'mp4'])
                    images = file_count - videos
                    
                    if videos == file_count:
                        return f'🎬 Carousel - {videos} Video' + ('s' if videos != 1 else '')
                    elif images == file_count:
                        return f'📷 Carousel - {images} Image' + ('s' if images != 1 else '')
                    else:
                        return f'📂 Carousel - {videos} Video' + ('s' if videos != 1 else '') + f', {images} Image' + ('s' if images != 1 else '')
                else:
                    # Single file
                    file_type = files[0]['type']
                    if file_type in ['video', 'mp4']:
                        return '🎬 Post - Single Video'
                    else:
                        return '🖼️ Post - Single Image'
        
        # Fallback to typename-based display
        typename_map = {
            'GraphImage': '🖼️ Image',
            'GraphVideo': '🎬 Reel',
            'GraphSidecar': '📷 Carousel',
            'Unknown': '❓ Unknown'
        }
        return typename_map.get(typename, f'📁 {typename}')
    
    def _has_video_files(self, shortcode):
        """Check if shortcode has any video files"""
        if not shortcode or not self.content_db:
            return False
        
        try:
            files = self.get_downloaded_files(shortcode)
            return any(f['type'] in ['video', 'mp4'] for f in files)
        except Exception:
            return False
    
    def create_tile_widget(self, post, row_number=None):
        """Create a tile widget for a single post
        
        Args:
            post: Post dictionary
            row_number: Optional row number in the full list (1-based)
        """
        # Tile dimensions based on size - reduced heights for tighter fit
        tile_config = {
            'small': {'thumb': 100, 'min_height': 180, 'max_height': 200},
            'medium': {'thumb': 150, 'min_height': 235, 'max_height': 260},
            'large': {'thumb': 220, 'min_height': 305, 'max_height': 340},
            'xlarge': {'thumb': 300, 'min_height': 380, 'max_height': 420}
        }
        config = tile_config[self.tile_size]
        
        shortcode = post.get('shortcode', '')
        
        # CRITICAL: Validate shortcode - never create tiles with blank shortcodes
        if not shortcode or not shortcode.strip():
            logger.error(f"[TILE] Attempted to create tile with blank shortcode! Post data: {post}")
            logger.error(f"[TILE] This indicates cache corruption - post object missing 'shortcode' field")
            # Try to recover from 'id' field if present (database uses 'id' instead of 'shortcode')
            if 'id' in post:
                shortcode = post['id']
                post['shortcode'] = shortcode  # Fix the cache entry
                logger.warning(f"[TILE] Recovered shortcode from 'id' field: {shortcode}")
            else:
                logger.error(f"[TILE] Cannot create tile without shortcode - skipping")
                return QFrame()  # Return empty frame to prevent crash
        
        typename = post.get('typename', 'Unknown')
        status = post.get('download_status', 'not_downloaded')
        # Extract topic_id from ContentInformation (nested structure)
        content_info = post.get('ContentInformation', {})
        topic_id = content_info.get('topicID')  # Get topic_id from nested ContentInformation
        
        # DEBUG: Log topic_id extraction
        if topic_id is not None:
            logger.debug(f"[TILE] {shortcode}: topic_id={topic_id}, status={status}, content_info keys={list(content_info.keys())}")
        
        # Determine background color based on priority system
        bg_color, hover_color = self.get_item_background_color(shortcode, status, topic_id)
        
        # DEBUG: Log color determination
        if topic_id is not None:
            logger.debug(f"[TILE] {shortcode}: color={bg_color} (expected pink=#FF69B4 for undownloaded or blue=#4169E1 for downloaded)")
        
        tile = QFrame()
        tile.setFrameStyle(QFrame.Box | QFrame.Raised)
        tile.setLineWidth(1)
        tile.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border: 1px solid #aaa;
                border-radius: 3px;
                padding: 3px;
            }}
            QFrame:hover {{
                border: 2px solid #0078d4;
                background-color: {hover_color};
            }}
        """)
        tile.setMinimumHeight(config['min_height'])
        tile.setMaximumHeight(config['max_height'])
        # Set fixed width to match thumbnail + padding (left-aligned, no extra space)
        tile.setFixedWidth(config['thumb'] + 10)  # thumb + margins
        tile.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(tile)
        layout.setSpacing(2)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        
        # Checkbox at the top-left with ID and type
        checkbox_row = QHBoxLayout()
        checkbox = QCheckBox()
        checkbox.setMaximumWidth(20)
        checkbox.setMaximumHeight(20)
        checkbox.setChecked(shortcode in self.selected_tiles)
        checkbox.setToolTip("Select for batch operations")
        checkbox.stateChanged.connect(lambda state, sc=shortcode: self.toggle_tile_selection(sc, state))
        checkbox_row.addWidget(checkbox)
        
        # Add ID and type info next to checkbox
        # Use appropriate text colors based on background
        if status == 'ignored':
            shortcode_color = '#ffffff'  # White text on black background
            type_color = '#cccccc'  # Light gray text on black background
        else:
            shortcode_color = '#000000'  # Black text on light backgrounds
            type_color = '#555555'  # Dark gray text on light backgrounds
        
        # Build shortcode display with row number if available
        if row_number is not None:
            shortcode_display = f"[{row_number}] / {shortcode}"
        else:
            shortcode_display = shortcode
        
        display_typename = self.get_display_typename(typename, post)
        info_label = QLabel(f"<b style='color: {shortcode_color}; font-size: 9pt;'>{shortcode_display}</b> <span style='color: {type_color}; font-size: 8pt;'>({display_typename})</span>")
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        info_label.setContentsMargins(3, 0, 0, 0)
        info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        checkbox_row.addWidget(info_label, 1)  # Stretch factor 1 to take available space
        
        layout.addLayout(checkbox_row)
        
        # Buttons at the top
        button_row = QHBoxLayout()
        button_row.setSpacing(2)
        
        # Open button
        open_btn = QPushButton("📂")
        open_btn.setMaximumWidth(35)
        open_btn.setMaximumHeight(24)
        open_btn.setToolTip("Open in Instagram")
        open_btn.clicked.connect(lambda: self.open_post(shortcode))
        button_row.addWidget(open_btn)
        
        # Copy URL button
        copy_btn = QPushButton("📋")
        copy_btn.setMaximumWidth(35)
        copy_btn.setMaximumHeight(24)
        copy_btn.setToolTip("Copy URL")
        copy_btn.clicked.connect(lambda: self.copy_url_to_clipboard(f"https://www.instagram.com/p/{shortcode}/"))
        button_row.addWidget(copy_btn)
        
        # Firefox button
        ff_btn = QPushButton("🦊")
        ff_btn.setMaximumWidth(35)
        ff_btn.setMaximumHeight(24)
        ff_btn.setToolTip("Open in Firefox")
        ff_btn.clicked.connect(lambda: self.open_in_firefox(f"https://www.instagram.com/p/{shortcode}/"))
        button_row.addWidget(ff_btn)
        
        # Chrome button
        chrome_btn = QPushButton("🌐")
        chrome_btn.setMaximumWidth(35)
        chrome_btn.setMaximumHeight(24)
        chrome_btn.setToolTip("Open in Chrome")
        chrome_btn.clicked.connect(lambda: self.open_in_chrome(f"https://www.instagram.com/p/{shortcode}/"))
        button_row.addWidget(chrome_btn)
        
        # Classify button
        classify_btn = QPushButton("🏷️")
        classify_btn.setMaximumWidth(35)
        classify_btn.setMaximumHeight(24)
        classify_btn.setToolTip("Classify Content")
        classify_btn.clicked.connect(lambda: self.classify_content_by_shortcode(shortcode))
        button_row.addWidget(classify_btn)
        
        # Open In Explorer button (only show if content is downloaded)
        if status in ['downloaded', 'completed', 're-downloaded']:
            downloaded_files = self.get_downloaded_files(shortcode)
            if downloaded_files:
                explorer_btn = QPushButton("📁")
                explorer_btn.setMaximumWidth(35)
                explorer_btn.setMaximumHeight(24)
                explorer_btn.setToolTip("Open In Explorer")
                explorer_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
                explorer_btn.clicked.connect(lambda checked=False, sc=shortcode: self.open_downloaded_file(sc))
                button_row.addWidget(explorer_btn)
        
        # Re-copy to Topics button (only show if content has topic assignments)
        if self.content_db and self.content_db.db:
            topic_ids = self.content_db.db.get_content_topics(shortcode)
            if topic_ids:
                recopy_btn = QPushButton("�")
                recopy_btn.setMaximumWidth(35)
                recopy_btn.setMaximumHeight(24)
                recopy_btn.setToolTip("Re-copy files to assigned topic folders")
                recopy_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; }")
                recopy_btn.clicked.connect(lambda: self.recopy_to_topics(shortcode))
                button_row.addWidget(recopy_btn)
        
        # Ignore button OR Restore/Remove buttons (if already ignored)
        if status == 'ignored':
            # Restore to Active button
            restore_btn = QPushButton("↩️")
            restore_btn.setMaximumWidth(35)
            restore_btn.setMaximumHeight(24)
            restore_btn.setToolTip("Restore to Active")
            restore_btn.setStyleSheet("QPushButton { background-color: #28a745; color: white; font-weight: bold; }")
            restore_btn.clicked.connect(lambda: self.restore_to_active(shortcode))
            button_row.addWidget(restore_btn)
            
            # Remove from View button
            remove_btn = QPushButton("❌")
            remove_btn.setMaximumWidth(35)
            remove_btn.setMaximumHeight(24)
            remove_btn.setToolTip("Remove from View")
            remove_btn.setStyleSheet("QPushButton { background-color: #dc3545; color: white; font-weight: bold; }")
            remove_btn.clicked.connect(lambda: self.remove_from_view(shortcode))
            button_row.addWidget(remove_btn)
        else:
            ignore_btn = QPushButton("🚫")
            ignore_btn.setMaximumWidth(35)
            ignore_btn.setMaximumHeight(24)
            ignore_btn.setToolTip("Mark as Ignored")
            ignore_btn.clicked.connect(lambda: self.ignore_content(shortcode))
            button_row.addWidget(ignore_btn)
        
        # Get Thumbnail button
        thumb_btn = QPushButton("🖼️")
        thumb_btn.setMaximumWidth(35)
        thumb_btn.setMaximumHeight(24)
        thumb_btn.setToolTip("Download Thumbnail")
        thumb_btn.clicked.connect(lambda: self.download_thumbnail_by_shortcode(shortcode))
        button_row.addWidget(thumb_btn)
        
        # Add to Queue button (toggle between Queue/Unqueue)
        is_queued = shortcode in self.queued_shortcodes
        
        queue_btn = QPushButton("➖" if is_queued else "➕")
        queue_btn.setMaximumWidth(35)
        queue_btn.setMaximumHeight(24)
        if is_queued:
            queue_btn.setStyleSheet("QPushButton { background-color: #FFB6C1; color: #333; font-weight: bold; }")
            queue_btn.setToolTip("Remove from download queue")
        else:
            queue_btn.setStyleSheet("QPushButton { background-color: #17a2b8; color: white; font-weight: bold; }")
            queue_btn.setToolTip("Add to download queue")
        queue_btn.clicked.connect(lambda: self.toggle_post_in_queue(post, queue_btn))
        button_row.addWidget(queue_btn)
        
        # Download Now button
        download_btn = QPushButton("⬇️")
        download_btn.setMaximumWidth(35)
        download_btn.setMaximumHeight(24)
        download_btn.setStyleSheet("QPushButton { background-color: #0078d4; color: white; font-weight: bold; }")
        download_btn.setToolTip("Download immediately")
        download_btn.clicked.connect(lambda: self.download_post_now(post))
        button_row.addWidget(download_btn)
        
        button_row.addStretch()
        layout.addLayout(button_row)
        
        # Check if content is downloaded and get files
        # Accept 'downloaded', 'completed', and 're-downloaded' status values
        downloaded_files = self.get_downloaded_files(shortcode) if status in ['downloaded', 'completed', 're-downloaded'] else []
        
        # DEBUG: Log file retrieval for downloaded posts
        if status in ['downloaded', 'completed', 're-downloaded']:
            logger.info(f"[TILE] {shortcode}: status={status}, downloaded_files count={len(downloaded_files)}")
            if downloaded_files:
                for i, f in enumerate(downloaded_files):
                    logger.info(f"[TILE] {shortcode}: file {i+1}: type={f.get('type')}, path exists={os.path.exists(f.get('path', ''))}")
            else:
                logger.warning(f"[TILE] {shortcode}: status={status} but no downloaded files found!")
        
        # Add interactive media display based on download status
        self._add_tile_media_display(layout, tile, config, shortcode, downloaded_files)
        
        # Make tile clickable to show details - but don't interfere with button clicks
        def tile_mouse_press(event):
            # Only handle left clicks on the tile itself (not on buttons)
            if event.button() == Qt.LeftButton:
                widget = tile.childAt(event.pos())
                # If clicked on a button or its child, let the button handle it
                if widget and not isinstance(widget, (QPushButton, QLabel)):
                    self.tile_clicked(post)
                elif not widget or isinstance(widget, QLabel):
                    # Clicked on tile background or label - show details
                    self.tile_clicked(post)
        
        tile.mousePressEvent = tile_mouse_press
        
        # Store post data and status for later updates
        tile.post_data = post
        tile.download_status = post.get('download_status', 'not_downloaded')
        
        return tile
    
    def tile_clicked(self, post):
        """Handle tile click - show post details"""
        shortcode = post.get('shortcode', '')
        
        # Get post details from database
        if not self.content_db:
            self.details_panel.setPlainText("No database connection")
            self.current_entry = None
            self.copy_caption_btn.setEnabled(False)
            self.edit_notes_btn.setEnabled(False)
            return
        
        entry = self.content_db.db.get_content_entry(shortcode)
        if not entry:
            self.details_panel.setPlainText(f"No details found for {shortcode}")
            self.current_entry = None
            self.copy_caption_btn.setEnabled(False)
            self.edit_notes_btn.setEnabled(False)
            return
        
        # Store entry for buttons
        self.current_entry = entry
        self.copy_caption_btn.setEnabled(True)
        self.edit_notes_btn.setEnabled(True)
        
        # Format details (reuse existing logic)
        details = []
        details.append(f"═══ POST DETAILS: {shortcode} ═══\n")
        
        # Basic info
        details.append(f"URL: https://www.instagram.com/p/{shortcode}/")
        details.append(f"Account: {entry.get('account_name', 'Unknown')}")
        details.append(f"Type: {entry.get('typename', 'Unknown')}")
        details.append(f"Row Number: {entry.get('row_number', 'N/A')}")
        details.append(f"Status: {entry.get('download_status', 'Unknown')}")
        details.append("")
        
        # Caption
        caption = entry.get('text', '')
        if caption:
            details.append(f"Caption: {caption[:200]}{'...' if len(caption) > 200 else ''}")
            details.append("")
        
        # Tags (from validation_log)
        validation_log = entry.get('validation_log', '')
        if validation_log and validation_log.startswith('Tags: '):
            tags = validation_log.replace('Tags: ', '')
            details.append(f"Tags: {tags}")
            details.append("")
        
        # Files
        files_info = entry.get('FilesInformation', {})
        file_list = files_info.get('FileList', [])
        
        if file_list:
            details.append(f"Files ({len(file_list)}):")
            for i, file_info in enumerate(file_list, 1):
                file_name = file_info.get('DownloadFilename', file_info.get('FileName', 'Unknown'))
                file_type = file_info.get('FileType', 'unknown')
                file_status = file_info.get('FileDownloadStatus', 'unknown')
                file_path = file_info.get('FileDestinationPath', '')
                file_caption = file_info.get('FileCaption', '')
                file_tags = file_info.get('FileTags', '')
                user_notes = file_info.get('UserNotes', '')
                
                details.append(f"  {i}. {file_name}")
                details.append(f"     Type: {file_type} | Status: {file_status}")
                if file_path:
                    details.append(f"     Path: {file_path}")
                if file_caption:
                    details.append(f"     Caption: {file_caption[:100]}{'...' if len(file_caption) > 100 else ''}")
                if file_tags:
                    details.append(f"     Tags: {file_tags}")
                if user_notes:
                    details.append(f"     📝 Notes: {user_notes}")
            details.append("")
        else:
            details.append("No files downloaded yet")
            details.append("")
        
        # Metadata
        created = entry.get('created_at', '')
        if created:
            details.append(f"Added: {str(created)[:19]}")
        
        updated = entry.get('updated_at', '')
        if updated:
            details.append(f"Updated: {str(updated)[:19]}")
        
        self.details_panel.setPlainText('\n'.join(details))
    
    def first_page(self):
        """Go to first page"""
        if self.current_page != 0:
            # Cancel threads for distant pages
            self.cancel_distant_page_loads(0)
            
            self.current_page = 0
            self.load_page(self.current_page)
            self.preload_adjacent_pages(self.current_page)
            self.save_ui_setting('current_page', str(self.current_page))
    
    def prev_page(self):
        """Go to previous page"""
        logger.info(f"[NAV] prev_page() called - current_page before: {self.current_page}")
        
        # Validate current_page is within valid range
        total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page if self.total_items > 0 else 1
        if self.current_page >= total_pages:
            logger.warning(f"[NAV] current_page ({self.current_page}) >= total_pages ({total_pages}), clamping")
            self.current_page = max(0, total_pages - 1)
        
        if self.current_page > 0:
            self.current_page -= 1
            logger.info(f"[NAV] Moving to page {self.current_page} (Page {self.current_page + 1} in UI)")
            self.load_page(self.current_page)
            self.preload_adjacent_pages(self.current_page)
            self.save_ui_setting('current_page', str(self.current_page))
        else:
            logger.info(f"[NAV] Already on first page")
    
    def next_page(self):
        """Go to next page"""
        logger.info(f"[NAV] next_page() called - current_page before: {self.current_page}")
        total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
        
        # Validate current_page is within valid range
        if total_pages > 0 and self.current_page >= total_pages:
            logger.warning(f"[NAV] current_page ({self.current_page}) >= total_pages ({total_pages}), clamping")
            self.current_page = max(0, total_pages - 1)
        
        if self.current_page < total_pages - 1:
            self.current_page += 1
            logger.info(f"[NAV] Moving to page {self.current_page} (Page {self.current_page + 1} in UI)")
            self.load_page(self.current_page)
            self.preload_adjacent_pages(self.current_page)
            self.save_ui_setting('current_page', str(self.current_page))
        else:
            logger.info(f"[NAV] Already on last page ({self.current_page})")
    
    def last_page(self):
        """Go to last page"""
        total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
        if total_pages > 0:
            last_page = total_pages - 1
            if self.current_page != last_page:
                # Cancel threads for distant pages
                self.cancel_distant_page_loads(last_page)
                
                self.current_page = last_page
                self.load_page(self.current_page)
                self.preload_adjacent_pages(self.current_page)
                self.save_ui_setting('current_page', str(self.current_page))
    
    def refresh_current_page(self):
        """Refresh current page by clearing cache and reloading from database"""
        try:
            logger.info(f"[REFRESH] Refreshing page {self.current_page + 1}...")
            
            # Remove current page from cache
            if self.current_page in self.page_cache:
                del self.page_cache[self.current_page]
                logger.info(f"[REFRESH] Cleared page {self.current_page} from cache")
            
            # Cancel any pending load for this page
            if self.current_page in self.loading_pages:
                self.loading_pages.discard(self.current_page)
            
            if self.current_page in self.page_load_threads:
                thread = self.page_load_threads[self.current_page]
                try:
                    thread.page_loaded.disconnect()
                    thread.error.disconnect()
                except:
                    pass
                thread.stop()
                del self.page_load_threads[self.current_page]
                thread.deleteLater()
            
            # Clear tile tracking to force full rebuild
            self.current_tile_data = {}
            self.last_displayed_page = -1
            
            # Reload from database
            self.load_page(self.current_page)
            
            self.statusBar().showMessage(f"Page {self.current_page + 1} refreshed", 2000)
            logger.info(f"[REFRESH] Page {self.current_page + 1} refresh complete")
            
        except Exception as e:
            logger.error(f"Error refreshing page: {e}")
            QMessageBox.warning(self, "Refresh Error", f"Failed to refresh page:\n{e}")
    
    def change_items_per_page(self, value):
        """Change number of items per page"""
        # Cancel all page load threads since we're changing page size
        for page_num in list(self.page_load_threads.keys()):
            thread = self.page_load_threads[page_num]
            
            # Disconnect all signals
            try:
                thread.page_loaded.disconnect()
            except:
                pass
            try:
                thread.error.disconnect()
            except:
                pass
            
            # Stop thread
            thread.stop()
            
            # Remove from tracking
            del self.page_load_threads[page_num]
            
            # Schedule for deletion
            thread.deleteLater()
            
        self.loading_pages.clear()
        
        self.tiles_per_page = value
        self.current_page = 0
        self.last_displayed_page = -1  # Force full rebuild when items per page changes
        self.page_cache.clear()  # Clear cache since page size changed
        self.load_page(self.current_page)
        self.preload_adjacent_pages(self.current_page)
        self.save_ui_setting('current_page', str(self.current_page))
        self.save_ui_setting('tiles_per_page', str(value))
    
    def jump_to_page(self, page_num):
        """Jump to a specific page (1-indexed)"""
        try:
            logger.debug(f"jump_to_page called with page_num={page_num}")
            
            # Convert from 1-indexed to 0-indexed
            target_page = page_num - 1
            
            # Validate page number
            if self.total_items == 0:
                logger.debug("jump_to_page: no items, returning")
                return
            
            total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
            logger.debug(f"jump_to_page: target_page={target_page}, total_pages={total_pages}, current_page={self.current_page}")
            
            if 0 <= target_page < total_pages:
                if self.current_page != target_page:
                    logger.info(f"Jumping from page {self.current_page} to page {target_page}")
                    
                    # Cancel threads loading pages far from target
                    self.cancel_distant_page_loads(target_page)
                    
                    self.current_page = target_page
                    self.load_page(self.current_page)
                    self.preload_adjacent_pages(self.current_page)
                    self.save_ui_setting('current_page', str(self.current_page))
                else:
                    logger.debug(f"Already on page {target_page}, no action needed")
            else:
                logger.warning(f"Invalid page number: target_page={target_page} not in range [0, {total_pages})")
        except Exception as e:
            logger.error(f"Error in jump_to_page: {e}", exc_info=True)
            QMessageBox.warning(self, "Page Navigation Error", f"Failed to jump to page {page_num}:\n{str(e)}")
    
    def update_pagination_controls(self):
        """Update pagination button states and labels"""
        if self.total_items == 0:
            total_pages = 1
        else:
            total_pages = (self.total_items + self.tiles_per_page - 1) // self.tiles_per_page
        
        # If fetching new posts, adjust current_page to account for items added at beginning
        if getattr(self, 'fetch_in_progress', False):
            items_added = self.total_items - self.fetch_initial_total_items
            if items_added > 0:
                # Calculate how many pages the new items represent
                pages_shifted = items_added // self.tiles_per_page
                # Update current page to maintain view of same content
                new_page = self.fetch_initial_page + pages_shifted
                if new_page != self.current_page:
                    self.current_page = new_page
                    logger.info(f"Pagination shift: +{items_added} items = +{pages_shifted} pages, current_page now {self.current_page}")
                    # Clear page cache since database changed
                    self.page_cache.clear()
        
        current_page_display = self.current_page + 1  # Display as 1-indexed
        
        self.page_label.setText(f"Page {current_page_display} of {total_pages} ({self.total_items} items)")
        
        self.first_page_btn.setEnabled(self.current_page > 0)
        self.prev_page_btn.setEnabled(self.current_page > 0)
        self.next_page_btn.setEnabled(self.current_page < total_pages - 1)
        self.last_page_btn.setEnabled(self.current_page < total_pages - 1)
        
        # Update current page spinner
        if hasattr(self, 'current_page_spin'):
            self.current_page_spin.setRange(1, max(1, total_pages))
            # Temporarily disconnect to avoid triggering jump_to_page
            self.current_page_spin.blockSignals(True)
            self.current_page_spin.setValue(current_page_display)
            self.current_page_spin.blockSignals(False)
    
    def table_prev_page(self):
        """Go to previous page in table view"""
        if self.table_current_page > 0:
            self.table_current_page -= 1
            self.update_table_pagination()
    
    def table_next_page(self):
        """Go to next page in table view"""
        total_items = self.posts_table.rowCount()
        total_pages = (total_items + self.table_items_per_page - 1) // self.table_items_per_page
        if self.table_current_page < total_pages - 1:
            self.table_current_page += 1
            self.update_table_pagination()
    
    def change_table_items_per_page(self, value):
        """Change number of items per page in table view"""
        self.table_items_per_page = value
        self.table_current_page = 0
        self.update_table_pagination()
    
    def update_table_pagination(self):
        """Update table view to show only current page"""
        total_items = self.posts_table.rowCount()
        if total_items == 0:
            self.table_page_label.setText("Page 1 of 1 (0 items)")
            self.table_prev_page_btn.setEnabled(False)
            self.table_next_page_btn.setEnabled(False)
            return
        
        total_pages = (total_items + self.table_items_per_page - 1) // self.table_items_per_page
        current_page_display = self.table_current_page + 1
        
        # Calculate which rows to show
        start_row = self.table_current_page * self.table_items_per_page
        end_row = min(start_row + self.table_items_per_page, total_items)
        
        # Hide/show rows based on pagination
        for row in range(total_items):
            self.posts_table.setRowHidden(row, row < start_row or row >= end_row)
        
        # Update pagination controls
        self.table_page_label.setText(f"Page {current_page_display} of {total_pages} ({total_items} items)")
        self.table_prev_page_btn.setEnabled(self.table_current_page > 0)
        self.table_next_page_btn.setEnabled(self.table_current_page < total_pages - 1)
    
    def classify_content_by_shortcode(self, shortcode):
        """Classify content using shortcode (called from tile)"""
        if not self.content_db:
            return
        
        # Call classify_content directly with the shortcode
        self.classify_content(shortcode)
    
    # Topics Tab Methods
    
    def load_topics_tree(self):
        """Load topics from database and populate tree"""
        logger.info("=" * 60)
        logger.info("LOAD TOPICS TREE")
        
        if not self.content_db or not self.content_db.db:
            logger.warning("No database loaded - cannot load topics")
            self.topics_status.setText("No database loaded")
            logger.info("=" * 60)
            return
        
        logger.info(f"content_db available: {self.content_db is not None}")
        logger.info(f"content_db.db available: {self.content_db.db is not None}")
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            logger.info("Calling get_all_topics()...")
            topics = self.content_db.db.get_all_topics()
            logger.info(f"Retrieved {len(topics)} topics from database")
            
            self.topics_tree.clear()
            
            if not topics:
                logger.warning("No topics found in database")
                self.topics_status.setText("No topics found in database")
                QApplication.restoreOverrideCursor()
                logger.info("=" * 60)
                return
            
            # Get item counts for all topics (using many-to-many table)
            try:
                item_counts = self.content_db.db.get_topic_item_counts_v2()
                pending_counts = self.content_db.db.get_topic_pending_download_counts()
            except Exception as e:
                logger.error(f"Error getting topic item counts: {e}")
                item_counts = {}
                pending_counts = {}
            
            # Build a map of topic_id -> topic
            topic_map = {}
            for topic in topics:
                topic_map[topic['id']] = topic
            
            # Build a map of parent_id -> list of children
            children_map = {}
            root_topics = []
            
            for topic in topics:
                parent_id = topic.get('parent_topic_id')
                if parent_id is None:
                    root_topics.append(topic)
                else:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(topic)
            
            # Recursively add topics to tree
            def add_topic_and_children(topic, parent_item=None):
                item = QTreeWidgetItem()
                item.setText(0, topic['topic_name'])
                
                # Show item count and pending downloads in separate columns
                topic_id = topic['id']
                count = item_counts.get(topic_id, 0)
                pending = pending_counts.get(topic_id, 0)
                
                # Column 1: Total items
                item.setText(1, str(count) if count > 0 else "")
                item.setTextAlignment(1, Qt.AlignCenter)
                
                # Column 2: Pending downloads
                item.setText(2, str(pending) if pending > 0 else "")
                item.setTextAlignment(2, Qt.AlignCenter)
                
                item.setText(3, str(topic_id))
                item.setText(4, topic.get('content_path', ''))
                item.setText(5, str(topic.get('display_order', 0)))
                item.setData(0, Qt.UserRole, topic)  # Store full topic data
                
                if parent_item:
                    parent_item.addChild(item)
                else:
                    self.topics_tree.addTopLevelItem(item)
                
                # Add children
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_and_children(child_topic, item)
                
                return item
            
            # Add all root topics and their children
            for root_topic in root_topics:
                add_topic_and_children(root_topic)
            
            self.topics_tree.expandAll()
            
            # Calculate total items and pending downloads
            total_items = sum(item_counts.values())
            total_pending = sum(pending_counts.values())
            logger.info(f"Populated tree with {len(root_topics)} root topics")
            logger.info(f"Total items assigned: {total_items}")
            logger.info(f"Total pending downloads: {total_pending}")
            self.topics_status.setText(f"Loaded {len(topics)} topics ({total_items} items, {total_pending} awaiting download)")
            
            # Update the topic filter dropdown in Browse tab
            self.update_topic_filter_dropdown()
            
            logger.info("✓ Topics tree loaded successfully")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error loading topics: {e}", exc_info=True)
            self.topics_status.setText(f"Error: {e}")
            logger.info("=" * 60)
        finally:
            QApplication.restoreOverrideCursor()
    
    def on_topic_selection_changed(self):
        """Handle topic selection change"""
        selected = self.topics_tree.selectedItems()
        if selected:
            topic = selected[0].data(0, Qt.UserRole)
            self.topics_status.setText(f"Selected: {topic['topic_name']} (ID: {topic['id']})")
            self.assign_topic_btn.setEnabled(True)
            self.add_child_topic_btn.setEnabled(True)
            self.copy_files_for_topic_btn.setEnabled(True)
            
            # Enable/disable promote button (can promote if has parent)
            parent_id = topic.get('parent_topic_id')
            self.promote_topic_btn.setEnabled(parent_id is not None)
            
            # Enable/disable demote button (can demote if has siblings before it)
            can_demote = False
            can_move_up = False
            can_move_down = False
            can_alphabetize = False
            if self.content_db and self.content_db.db:
                try:
                    all_topics = self.content_db.db.get_all_topics()
                    # Find siblings (topics with same parent)
                    siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id and t['id'] != topic['id']]
                    # Can demote if there's at least one sibling
                    can_demote = len(siblings) > 0
                    # Can alphabetize if there are siblings (even one means ordering matters)
                    can_alphabetize = len(siblings) > 0
                    
                    # For move up/down, sort siblings by display_order and check position
                    if len(siblings) > 0:
                        all_siblings_including_current = [topic] + siblings
                        all_siblings_including_current.sort(key=lambda t: (t.get('display_order', 0), t['id']))
                        current_index = next(i for i, t in enumerate(all_siblings_including_current) if t['id'] == topic['id'])
                        can_move_up = current_index > 0
                        can_move_down = current_index < len(all_siblings_including_current) - 1
                except Exception as e:
                    logger.error(f"Error checking topic movement availability: {e}")
            self.demote_topic_btn.setEnabled(can_demote)
            self.move_up_topic_btn.setEnabled(can_move_up)
            self.move_down_topic_btn.setEnabled(can_move_down)
            self.move_to_top_btn.setEnabled(can_move_up)  # Can move to top if can move up
            self.move_to_bottom_btn.setEnabled(can_move_down)  # Can move to bottom if can move down
            self.alphabetize_selected_btn.setEnabled(can_alphabetize)
            self.alphabetize_level_btn.setEnabled(can_alphabetize)
        else:
            self.topics_status.setText("No topic selected")
            self.assign_topic_btn.setEnabled(False)
            self.add_child_topic_btn.setEnabled(False)
            self.promote_topic_btn.setEnabled(False)
            self.demote_topic_btn.setEnabled(False)
            self.move_up_topic_btn.setEnabled(False)
            self.move_down_topic_btn.setEnabled(False)
            self.move_to_top_btn.setEnabled(False)
            self.move_to_bottom_btn.setEnabled(False)
            self.alphabetize_selected_btn.setEnabled(False)
            self.alphabetize_level_btn.setEnabled(False)
            self.copy_files_for_topic_btn.setEnabled(False)
    
    def add_new_topic(self):
        """Add a new topic to the database"""
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        # Create dialog for new topic
        dialog = QDialog(self)
        dialog.setWindowTitle("Add New Topic")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Topic name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Topic Name:"))
        name_input = QLineEdit()
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)
        
        # Content path
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Content Path:"))
        path_input = QLineEdit()
        path_layout.addWidget(path_input)
        layout.addLayout(path_layout)
        
        # Track if user manually edited content path
        path_manually_edited = [False]
        def on_path_edited():
            path_manually_edited[0] = True
        path_input.textEdited.connect(on_path_edited)
        
        # Update content path based on parent selection and name
        def update_path_based_on_context():
            if path_manually_edited[0]:
                return
            
            topic_name = name_input.text()
            selected_items = parent_tree.selectedItems()
            
            if not selected_items:
                path_input.setText(topic_name)
                return
            
            parent_id = selected_items[0].data(0, Qt.UserRole)
            
            if parent_id is None:
                # Root topic - use topics_root_path
                if self.topics_root_path:
                    path_input.setText(str(Path(self.topics_root_path) / topic_name))
                else:
                    path_input.setText(topic_name)
            else:
                # Child topic - get parent's content_path
                try:
                    conn = self.content_db.db._get_connection()
                    cursor = conn.cursor()
                    cursor.execute('SELECT content_path FROM DL.topics WHERE id = ?', (parent_id,))
                    result = cursor.fetchone()
                    parent_path = result[0] if result and result[0] else ''
                    if parent_path and not parent_path.endswith('/'):
                        parent_path += '/'
                    path_input.setText(parent_path + topic_name)
                except Exception as e:
                    logger.error(f"Error getting parent path: {e}")
                    path_input.setText(topic_name)
        
        # Sync topic name to content path
        def on_name_changed(text):
            update_path_based_on_context()
        name_input.textChanged.connect(on_name_changed)
        
        # Display order
        order_layout = QHBoxLayout()
        order_layout.addWidget(QLabel("Display Order:"))
        order_input = QSpinBox()
        order_input.setMinimum(0)
        order_input.setMaximum(9999)
        order_input.setValue(0)
        order_layout.addWidget(order_input)
        layout.addLayout(order_layout)
        
        # Parent topic - use tree widget for hierarchical selection
        parent_label = QLabel("Parent Topic:")
        layout.addWidget(parent_label)
        
        parent_tree = QTreeWidget()
        parent_tree.setHeaderLabels(["Topic Name"])
        parent_tree.setMaximumHeight(350)
        parent_tree.setSelectionMode(QTreeWidget.SingleSelection)
        
        # Add Root node
        root_item = QTreeWidgetItem()
        root_item.setText(0, "(Root - No Parent)")
        root_item.setData(0, Qt.UserRole, None)  # Store None for root
        root_item.setExpanded(True)
        parent_tree.addTopLevelItem(root_item)
        
        # Build hierarchical topic tree
        try:
            topics = self.content_db.db.get_all_topics()
            
            # Build parent-child relationships
            topic_map = {}
            children_map = {}
            root_topics = []
            
            for topic in topics:
                topic_map[topic['id']] = topic
                parent_id = topic.get('parent_topic_id')
                if parent_id is None:
                    root_topics.append(topic)
                else:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(topic)
            
            # Sort topics by display order and name
            root_topics.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            for children_list in children_map.values():
                children_list.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            # Recursively add topics to tree
            def add_topic_to_parent_tree(topic, parent_item):
                item = QTreeWidgetItem()
                item.setText(0, topic['topic_name'])
                item.setData(0, Qt.UserRole, topic['id'])  # Store topic ID
                parent_item.addChild(item)
                item.setExpanded(True)
                
                # Add children
                topic_id = topic['id']
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_to_parent_tree(child_topic, item)
                
                return item
            
            # Add all root topics under Root node
            for root_topic in root_topics:
                add_topic_to_parent_tree(root_topic, root_item)
        
        except Exception as e:
            logger.error(f"Error loading topics for parent selection: {e}")
        
        # Select Root by default
        parent_tree.setCurrentItem(root_item)
        
        # Update path when parent selection changes
        def on_parent_changed():
            update_path_based_on_context()
        parent_tree.itemSelectionChanged.connect(on_parent_changed)
        
        layout.addWidget(parent_tree)
        
        # Auto-calculate alphabetic display order when parent selection or name changes
        def update_display_order():
            try:
                topic_name = name_input.text().strip()
                if not topic_name:
                    order_input.setValue(0)
                    return
                
                selected_items = parent_tree.selectedItems()
                if not selected_items:
                    return
                
                parent_id = selected_items[0].data(0, Qt.UserRole)
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                # Get all siblings sorted alphabetically
                if parent_id is None:
                    cursor.execute('SELECT topic_name FROM DL.topics WHERE parent_topic_id IS NULL ORDER BY topic_name')
                else:
                    cursor.execute('SELECT topic_name FROM DL.topics WHERE parent_topic_id = ? ORDER BY topic_name', (parent_id,))
                
                siblings = [row[0] for row in cursor.fetchall()]
                
                # Find alphabetic position
                insert_position = 0
                for i, sibling_name in enumerate(siblings):
                    if topic_name.lower() < sibling_name.lower():
                        insert_position = i
                        break
                    insert_position = i + 1
                
                order_input.setValue(insert_position)
                logger.debug(f"Auto-calculated alphabetic display_order: {insert_position} (parent_id={parent_id})")
            except Exception as e:
                logger.error(f"Error calculating display order: {e}")
                order_input.setValue(0)
        
        # Calculate initial display order
        update_display_order()
        
        # Update when parent selection or name changes
        parent_tree.itemSelectionChanged.connect(update_display_order)
        name_input.textChanged.connect(lambda: update_display_order())
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        if dialog.exec_() == QDialog.Accepted:
            topic_name = name_input.text().strip()
            content_path = path_input.text().strip()
            display_order = order_input.value()
            
            # Get parent_id from selected tree item
            selected_items = parent_tree.selectedItems()
            if selected_items:
                parent_id = selected_items[0].data(0, Qt.UserRole)
            else:
                parent_id = None  # Default to Root if nothing selected
            
            if not topic_name:
                QMessageBox.warning(self, "Invalid Input", "Topic name is required.")
                return
            
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                try:
                    cursor.execute('''
                        INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                        VALUES (?, ?, ?, ?)
                    ''', (topic_name, content_path or None, display_order, parent_id))
                    
                    # Get the new topic ID
                    cursor.execute('SELECT @@IDENTITY')
                    new_topic_id = cursor.fetchone()[0]
                    
                    # Update display_order for topics that come after the new one
                    if parent_id is None:
                        cursor.execute('''
                            UPDATE DL.topics 
                            SET display_order = display_order + 1 
                            WHERE parent_topic_id IS NULL 
                            AND id != ? 
                            AND display_order >= ?
                        ''', (new_topic_id, display_order))
                    else:
                        cursor.execute('''
                            UPDATE DL.topics 
                            SET display_order = display_order + 1 
                            WHERE parent_topic_id = ? 
                            AND id != ? 
                            AND display_order >= ?
                        ''', (parent_id, new_topic_id, display_order))
                    
                    conn.commit()
                    logger.info(f"Topic '{topic_name}' added at alphabetic position {display_order}")
                except Exception as insert_error:
                    # Check if it's a PRIMARY KEY constraint violation
                    error_str = str(insert_error)
                    if 'PRIMARY KEY constraint' in error_str or 'duplicate key' in error_str.lower():
                        logger.warning(f"PRIMARY KEY violation detected, reseeding identity column")
                        conn.rollback()
                        
                        # Reseed the identity column
                        if self.content_db.db.reseed_topics_identity():
                            # Retry the insert
                            cursor.execute('''
                                INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                                VALUES (?, ?, ?, ?)
                            ''', (topic_name, content_path or None, display_order, parent_id))
                            
                            # Get the new topic ID
                            cursor.execute('SELECT @@IDENTITY')
                            new_topic_id = cursor.fetchone()[0]
                            
                            # Update display_order for topics that come after
                            if parent_id is None:
                                cursor.execute('''
                                    UPDATE DL.topics 
                                    SET display_order = display_order + 1 
                                    WHERE parent_topic_id IS NULL 
                                    AND id != ? 
                                    AND display_order >= ?
                                ''', (new_topic_id, display_order))
                            else:
                                cursor.execute('''
                                    UPDATE DL.topics 
                                    SET display_order = display_order + 1 
                                    WHERE parent_topic_id = ? 
                                    AND id != ? 
                                    AND display_order >= ?
                                ''', (parent_id, new_topic_id, display_order))
                            
                            conn.commit()
                            logger.info("Successfully inserted topic after reseeding")
                        else:
                            raise insert_error
                    else:
                        raise insert_error
                
                # Create folder if path specified and doesn't exist
                if content_path:
                    # Sanitize path to ensure it's safe
                    sanitized_path, is_absolute = self.sanitize_topic_path(content_path)
                    if sanitized_path:
                        try:
                            # Use absolute path or combine with base download path
                            if is_absolute:
                                folder_path = Path(sanitized_path)
                            else:
                                base_path = Path(self.download_path_input.text())
                                folder_path = base_path / Path(sanitized_path)
                            if not folder_path.exists():
                                folder_path.mkdir(parents=True, exist_ok=True)
                                logger.info(f"Created folder: {folder_path}")
                        except Exception as folder_error:
                            logger.error(f"Failed to create folder {content_path}: {folder_error}")
                            QMessageBox.warning(
                                self, "Folder Creation Error",
                                f"Topic saved but failed to create folder:\n{content_path}\n\nError: {str(folder_error)}"
                            )
                    else:
                        logger.warning(f"Invalid content path '{content_path}' - folder not created")
                        QMessageBox.warning(
                            self, "Invalid Path",
                            f"Content path contains invalid characters (< > \" | ? * or ..).\n\nProvided path: {content_path}"
                        )
                
                logger.info(f"Topic '{topic_name}' added successfully.")
                self.load_topics_tree()
                
            except Exception as e:
                logger.error(f"Error adding topic: {e}")
                QMessageBox.critical(self, "Error", f"Failed to add topic:\n{str(e)}")
            finally:
                QApplication.restoreOverrideCursor()
    
    def add_child_to_selected_topic(self):
        """Add a child topic to the currently selected topic"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a parent topic first.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        parent_topic = selected[0].data(0, Qt.UserRole)
        
        # Create dialog for new child topic
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Add Child to: {parent_topic['topic_name']}")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Show parent info
        parent_info = QLabel(f"Parent Topic: {parent_topic['topic_name']}")
        parent_info.setStyleSheet("font-weight: bold; color: #0066cc; padding: 5px;")
        layout.addWidget(parent_info)
        
        # Topic name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Topic Name:"))
        name_input = QLineEdit()
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)
        
        # Content path - pre-fill with parent's path + "/"
        parent_path = parent_topic.get('content_path', '')
        if parent_path and not parent_path.endswith('/'):
            parent_path += '/'
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Content Path:"))
        path_input = QLineEdit(parent_path)  # Pre-fill with parent path
        path_layout.addWidget(path_input)
        layout.addLayout(path_layout)
        
        # Track if user manually edited content path
        path_manually_edited = [False]
        def on_path_edited():
            path_manually_edited[0] = True
        path_input.textEdited.connect(on_path_edited)
        
        # Sync topic name to content path (append keystrokes)
        def on_name_changed(text):
            if not path_manually_edited[0]:
                path_input.setText(parent_path + text)
            # Also update display order for alphabetic insertion
            update_alphabetic_order()
        name_input.textChanged.connect(on_name_changed)
        
        # Display order - auto-calculate alphabetic position based on parent's existing children
        order_layout = QHBoxLayout()
        order_layout.addWidget(QLabel("Display Order:"))
        order_input = QSpinBox()
        order_input.setMinimum(0)
        order_input.setMaximum(9999)
        
        # Calculate alphabetic display order for this parent's children
        def update_alphabetic_order():
            try:
                topic_name = name_input.text().strip()
                if not topic_name:
                    order_input.setValue(0)
                    return
                
                parent_id = parent_topic['id']
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                # Get all siblings sorted alphabetically
                cursor.execute('SELECT topic_name FROM DL.topics WHERE parent_topic_id = ? ORDER BY topic_name', (parent_id,))
                siblings = [row[0] for row in cursor.fetchall()]
                
                # Find alphabetic position
                insert_position = 0
                for i, sibling_name in enumerate(siblings):
                    if topic_name.lower() < sibling_name.lower():
                        insert_position = i
                        break
                    insert_position = i + 1
                
                order_input.setValue(insert_position)
                logger.debug(f"Auto-calculated alphabetic display_order for child: {insert_position} (parent_id={parent_id})")
            except Exception as e:
                logger.error(f"Error calculating display order for child: {e}")
                order_input.setValue(0)
        
        # Initial calculation
        update_alphabetic_order()
        
        order_layout.addWidget(order_input)
        layout.addLayout(order_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        if dialog.exec_() == QDialog.Accepted:
            topic_name = name_input.text().strip()
            content_path = path_input.text().strip()
            display_order = order_input.value()
            parent_id = parent_topic['id']
            
            if not topic_name:
                QMessageBox.warning(self, "Invalid Input", "Topic name is required.")
                return
            
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                try:
                    cursor.execute('''
                        INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                        VALUES (?, ?, ?, ?)
                    ''', (topic_name, content_path or None, display_order, parent_id))
                    
                    # Get the new topic ID
                    cursor.execute('SELECT @@IDENTITY')
                    new_topic_id = cursor.fetchone()[0]
                    
                    # Update display_order for topics that come after the new one
                    cursor.execute('''
                        UPDATE DL.topics 
                        SET display_order = display_order + 1 
                        WHERE parent_topic_id = ? 
                        AND id != ? 
                        AND display_order >= ?
                    ''', (parent_id, new_topic_id, display_order))
                    
                    conn.commit()
                    logger.info(f"Child topic '{topic_name}' added at alphabetic position {display_order}")
                except Exception as insert_error:
                    # Check if it's a PRIMARY KEY constraint violation
                    error_str = str(insert_error)
                    if 'PRIMARY KEY constraint' in error_str or 'duplicate key' in error_str.lower():
                        logger.warning(f"PRIMARY KEY violation detected, reseeding identity column")
                        conn.rollback()
                        
                        # Reseed the identity column
                        if self.content_db.db.reseed_topics_identity():
                            # Retry the insert
                            cursor.execute('''
                                INSERT INTO DL.topics (topic_name, content_path, display_order, parent_topic_id)
                                VALUES (?, ?, ?, ?)
                            ''', (topic_name, content_path or None, display_order, parent_id))
                            
                            # Get the new topic ID
                            cursor.execute('SELECT @@IDENTITY')
                            new_topic_id = cursor.fetchone()[0]
                            
                            # Update display_order for topics that come after
                            cursor.execute('''
                                UPDATE DL.topics 
                                SET display_order = display_order + 1 
                                WHERE parent_topic_id = ? 
                                AND id != ? 
                                AND display_order >= ?
                            ''', (parent_id, new_topic_id, display_order))
                            
                            conn.commit()
                            logger.info("Successfully inserted child topic after reseeding")
                        else:
                            raise insert_error
                    else:
                        raise insert_error
                
                # Create folder if path specified and doesn't exist
                if content_path:
                    # Sanitize path to ensure it's safe
                    sanitized_path, is_absolute = self.sanitize_topic_path(content_path)
                    if sanitized_path:
                        try:
                            # Use absolute path or combine with base download path
                            if is_absolute:
                                folder_path = Path(sanitized_path)
                            else:
                                base_path = Path(self.download_path_input.text())
                                folder_path = base_path / Path(sanitized_path)
                            if not folder_path.exists():
                                folder_path.mkdir(parents=True, exist_ok=True)
                                logger.info(f"Created folder: {folder_path}")
                        except Exception as folder_error:
                            logger.error(f"Failed to create folder {content_path}: {folder_error}")
                            QMessageBox.warning(
                                self, "Folder Creation Error",
                                f"Topic saved but failed to create folder:\n{content_path}\n\nError: {str(folder_error)}"
                            )
                    else:
                        logger.warning(f"Invalid content path '{content_path}' - folder not created")
                        QMessageBox.warning(
                            self, "Invalid Path",
                            f"Content path contains invalid characters (< > \" | ? * or ..).\n\nProvided path: {content_path}"
                        )
                
                logger.info(f"Child topic '{topic_name}' added to '{parent_topic['topic_name']}'.")
                self.load_topics_tree()
                
            except Exception as e:
                logger.error(f"Error adding child topic: {e}")
                QMessageBox.critical(self, "Error", f"Failed to add child topic:\n{str(e)}")
            finally:
                QApplication.restoreOverrideCursor()
    
    def edit_selected_topic(self):
        """Edit the selected topic"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to edit.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        
        # Create dialog for editing topic
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit Topic: {topic['topic_name']}")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        # Topic name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Topic Name:"))
        name_input = QLineEdit(topic['topic_name'])
        name_layout.addWidget(name_input)
        layout.addLayout(name_layout)
        
        # Content path
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Content Path:"))
        path_input = QLineEdit(topic.get('content_path', ''))
        path_layout.addWidget(path_input)
        layout.addLayout(path_layout)
        
        # Track if user manually edited content path
        original_path = topic.get('content_path', '')
        path_manually_edited = [False]
        def on_path_edited():
            path_manually_edited[0] = True
        path_input.textEdited.connect(on_path_edited)
        
        # Sync topic name to content path (append keystrokes)
        original_name = topic['topic_name']
        def on_name_changed(text):
            if not path_manually_edited[0]:
                # Calculate what changed
                if text.startswith(original_name):
                    # Text was appended
                    added_text = text[len(original_name):]
                    path_input.setText(original_path + added_text)
                else:
                    # Text was completely changed, sync it
                    path_input.setText(text)
        name_input.textChanged.connect(on_name_changed)
        
        # Display order
        order_layout = QHBoxLayout()
        order_layout.addWidget(QLabel("Display Order:"))
        order_input = QSpinBox()
        order_input.setMinimum(0)
        order_input.setMaximum(9999)
        order_input.setValue(topic.get('display_order', 0))
        order_layout.addWidget(order_input)
        layout.addLayout(order_layout)
        
        # Parent topic - use tree widget for hierarchical selection
        parent_label = QLabel("Parent Topic:")
        layout.addWidget(parent_label)
        
        parent_tree = QTreeWidget()
        parent_tree.setHeaderLabels(["Topic Name"])
        parent_tree.setMaximumHeight(350)
        parent_tree.setSelectionMode(QTreeWidget.SingleSelection)
        
        # Add Root node
        root_item = QTreeWidgetItem()
        root_item.setText(0, "(Root - No Parent)")
        root_item.setData(0, Qt.UserRole, None)  # Store None for root
        root_item.setExpanded(True)
        parent_tree.addTopLevelItem(root_item)
        
        current_parent_id = topic.get('parent_topic_id')
        item_to_select = root_item  # Default to Root
        
        # Build hierarchical topic tree
        try:
            topics = self.content_db.db.get_all_topics()
            
            # Build parent-child relationships
            topic_map = {}
            children_map = {}
            root_topics = []
            
            for t in topics:
                if t['id'] == topic['id']:  # Skip self - can't be parent of itself
                    continue
                topic_map[t['id']] = t
                parent_id = t.get('parent_topic_id')
                if parent_id is None:
                    root_topics.append(t)
                else:
                    if parent_id not in children_map:
                        children_map[parent_id] = []
                    children_map[parent_id].append(t)
            
            # Sort topics by display order and name
            root_topics.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            for children_list in children_map.values():
                children_list.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            # Recursively add topics to tree
            def add_topic_to_parent_tree(t, parent_item):
                item = QTreeWidgetItem()
                item.setText(0, t['topic_name'])
                item.setData(0, Qt.UserRole, t['id'])  # Store topic ID
                parent_item.addChild(item)
                item.setExpanded(True)
                
                # Check if this is the current parent
                nonlocal item_to_select
                if t['id'] == current_parent_id:
                    item_to_select = item
                
                # Add children
                topic_id = t['id']
                if topic_id in children_map:
                    for child_topic in children_map[topic_id]:
                        add_topic_to_parent_tree(child_topic, item)
                
                return item
            
            # Add all root topics under Root node
            for root_topic in root_topics:
                add_topic_to_parent_tree(root_topic, root_item)
        
        except Exception as e:
            logger.error(f"Error loading topics for parent selection: {e}")
        
        # Select current parent (or Root if no parent)
        parent_tree.setCurrentItem(item_to_select)
        layout.addWidget(parent_tree)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        if dialog.exec_() == QDialog.Accepted:
            topic_name = name_input.text().strip()
            content_path = path_input.text().strip()
            display_order = order_input.value()
            
            # Get parent_id from selected tree item
            selected_items = parent_tree.selectedItems()
            if selected_items:
                parent_id = selected_items[0].data(0, Qt.UserRole)
            else:
                parent_id = None  # Default to Root if nothing selected
            
            if not topic_name:
                QMessageBox.warning(self, "Invalid Input", "Topic name is required.")
                return
            
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE DL.topics
                    SET topic_name = ?, content_path = ?, display_order = ?, parent_topic_id = ?
                    WHERE id = ?
                ''', (topic_name, content_path or None, display_order, parent_id, topic['id']))
                
                conn.commit()
                
                # Create folder if path specified and doesn't exist
                if content_path:
                    # Sanitize path to ensure it's safe
                    sanitized_path, is_absolute = self.sanitize_topic_path(content_path)
                    if sanitized_path:
                        try:
                            # Use absolute path or combine with base download path
                            if is_absolute:
                                folder_path = Path(sanitized_path)
                            else:
                                base_path = Path(self.download_path_input.text())
                                folder_path = base_path / Path(sanitized_path)
                            if not folder_path.exists():
                                folder_path.mkdir(parents=True, exist_ok=True)
                                logger.info(f"Created folder: {folder_path}")
                        except Exception as folder_error:
                            logger.error(f"Failed to create folder {content_path}: {folder_error}")
                            QMessageBox.warning(
                                self, "Folder Creation Error",
                                f"Topic updated but failed to create folder:\n{content_path}\n\nError: {str(folder_error)}"
                            )
                    else:
                        logger.warning(f"Invalid content path '{content_path}' - folder not created")
                        QMessageBox.warning(
                            self, "Invalid Path",
                            f"Content path contains invalid characters (< > \" | ? * or ..).\n\nProvided path: {content_path}"
                        )
                
                logger.info(f"Topic '{topic_name}' updated successfully.")
                self.load_topics_tree()
                
            except Exception as e:
                logger.error(f"Error updating topic: {e}")
                QMessageBox.critical(self, "Error", f"Failed to update topic:\n{str(e)}")
            finally:
                QApplication.restoreOverrideCursor()
    
    def delete_selected_topic(self):
        """Delete the selected topic"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to delete.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete topic '{topic['topic_name']}'?\n\n"
            "This will also remove this topic assignment from all content items.",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                
                conn = self.content_db.db._get_connection()
                cursor = conn.cursor()
                
                # Delete the topic
                cursor.execute('DELETE FROM DL.topics WHERE id = ?', (topic['id'],))
                
                conn.commit()
                
                logger.info(f"Topic '{topic['topic_name']}' deleted successfully.")
                self.load_topics_tree()
                
            except Exception as e:
                logger.error(f"Error deleting topic: {e}")
                QMessageBox.critical(self, "Error", f"Failed to delete topic:\n{str(e)}")
            finally:
                QApplication.restoreOverrideCursor()
    
    def promote_selected_topic(self):
        """Promote topic to same level as its parent"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to promote.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        if parent_id is None:
            QMessageBox.warning(self, "Cannot Promote", "This is already a root topic (no parent).")
            return
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get the parent topic to find its parent (grandparent)
            parent_topic = self.content_db.db.get_topic(parent_id)
            if not parent_topic:
                QMessageBox.warning(self, "Error", "Parent topic not found.")
                return
            
            grandparent_id = parent_topic.get('parent_topic_id')
            
            # Update the topic's parent to be the grandparent
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE DL.topics
                SET parent_topic_id = ?
                WHERE id = ?
            ''', (grandparent_id, topic['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' promoted successfully.")
            self.load_topics_tree()
            
        except Exception as e:
            logger.error(f"Error promoting topic: {e}")
            QMessageBox.critical(self, "Error", f"Failed to promote topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def demote_selected_topic(self):
        """Demote topic as child of previous sibling"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to demote.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id and t['id'] != topic['id']]
            
            if not siblings:
                QMessageBox.warning(self, "Cannot Demote", "No siblings found to demote under.")
                return
            
            # Sort siblings by display_order and id to get consistent ordering
            siblings.sort(key=lambda t: (t.get('display_order', 0), t['id']))
            
            # Use the last sibling as the new parent
            new_parent = siblings[-1]
            
            # Let user choose which sibling to demote under
            sibling_names = [f"{s['topic_name']} (ID: {s['id']})" for s in siblings]
            chosen_name, ok = QInputDialog.getItem(
                self, "Choose New Parent",
                f"Select which sibling to make '{topic['topic_name']}' a child of:",
                sibling_names, len(sibling_names) - 1, False
            )
            
            if not ok:
                return
            
            # Find the chosen sibling
            chosen_index = sibling_names.index(chosen_name)
            new_parent = siblings[chosen_index]
            
            # Update the topic's parent to be the chosen sibling
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE DL.topics
                SET parent_topic_id = ?
                WHERE id = ?
            ''', (new_parent['id'], topic['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' demoted under '{new_parent['topic_name']}'.")
            self.load_topics_tree()
            
        except Exception as e:
            logger.error(f"Error demoting topic: {e}")
            QMessageBox.critical(self, "Error", f"Failed to demote topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def move_topic_up(self):
        """Move topic up in display order (swap with previous sibling)"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to move.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.warning(self, "Cannot Move", "No siblings to swap with.")
                return
            
            # Sort siblings by display_order, then by topic_name for consistent ordering
            siblings.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Normalize display orders - assign sequential values (0, 1, 2, ...)
            logger.info(f"Normalizing display orders for {len(siblings)} siblings with parent_id={parent_id}")
            for idx, sibling in enumerate(siblings):
                if sibling.get('display_order', 0) != idx:
                    cursor.execute('''
                        UPDATE DL.topics
                        SET display_order = ?
                        WHERE id = ?
                    ''', (idx, sibling['id']))
                    logger.debug(f"Updated topic '{sibling['topic_name']}' display_order: {sibling.get('display_order', 0)} -> {idx}")
                    sibling['display_order'] = idx  # Update in memory for subsequent logic
            
            conn.commit()
            
            # Find current topic's position after normalization
            current_index = next((i for i, t in enumerate(siblings) if t['id'] == topic['id']), -1)
            
            if current_index <= 0:
                QMessageBox.warning(self, "Cannot Move", "Topic is already at the top.")
                return
            
            # Swap display_order with previous sibling
            previous_sibling = siblings[current_index - 1]
            current_display_order = siblings[current_index]['display_order']
            previous_display_order = previous_sibling['display_order']
            
            # Update both topics
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = ?
                WHERE id = ?
            ''', (previous_display_order, topic['id']))
            
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = ?
                WHERE id = ?
            ''', (current_display_order, previous_sibling['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' moved up (swapped orders {current_display_order} <-> {previous_display_order}).")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error moving topic up: {e}")
            QMessageBox.critical(self, "Error", f"Failed to move topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def move_topic_down(self):
        """Move topic down in display order (swap with next sibling)"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to move.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.warning(self, "Cannot Move", "No siblings to swap with.")
                return
            
            # Sort siblings by display_order, then by topic_name for consistent ordering
            siblings.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Normalize display orders - assign sequential values (0, 1, 2, ...)
            logger.info(f"Normalizing display orders for {len(siblings)} siblings with parent_id={parent_id}")
            for idx, sibling in enumerate(siblings):
                if sibling.get('display_order', 0) != idx:
                    cursor.execute('''
                        UPDATE DL.topics
                        SET display_order = ?
                        WHERE id = ?
                    ''', (idx, sibling['id']))
                    logger.debug(f"Updated topic '{sibling['topic_name']}' display_order: {sibling.get('display_order', 0)} -> {idx}")
                    sibling['display_order'] = idx  # Update in memory for subsequent logic
            
            conn.commit()
            
            # Find current topic's position after normalization
            current_index = next((i for i, t in enumerate(siblings) if t['id'] == topic['id']), -1)
            
            if current_index >= len(siblings) - 1:
                QMessageBox.warning(self, "Cannot Move", "Topic is already at the bottom.")
                return
            
            # Swap display_order with next sibling
            next_sibling = siblings[current_index + 1]
            current_display_order = siblings[current_index]['display_order']
            next_display_order = next_sibling['display_order']
            
            # Update both topics
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = ?
                WHERE id = ?
            ''', (next_display_order, topic['id']))
            
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = ?
                WHERE id = ?
            ''', (current_display_order, next_sibling['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' moved down (swapped orders {current_display_order} <-> {next_display_order}).")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error moving topic down: {e}")
            QMessageBox.critical(self, "Error", f"Failed to move topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def move_topic_to_top(self):
        """Move topic to the top of its siblings (display_order = 0)"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to move.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.warning(self, "Cannot Move", "No siblings to reorder with.")
                return
            
            # Sort siblings by display_order, then by topic_name for consistent ordering
            siblings.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Find current topic's position
            current_index = next((i for i, t in enumerate(siblings) if t['id'] == topic['id']), -1)
            
            if current_index == 0:
                QMessageBox.information(self, "Already at Top", "Topic is already at the top.")
                return
            
            # Move selected topic to position 0
            # Set current topic to display_order = 0
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = 0
                WHERE id = ?
            ''', (topic['id'],))
            
            # Increment display_order for all other siblings
            for idx, sibling in enumerate(siblings):
                if sibling['id'] != topic['id']:
                    new_order = idx + 1 if idx < current_index else idx
                    cursor.execute('''
                        UPDATE DL.topics
                        SET display_order = ?
                        WHERE id = ?
                    ''', (new_order, sibling['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' moved to top.")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error moving topic to top: {e}")
            QMessageBox.critical(self, "Error", f"Failed to move topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def move_topic_to_bottom(self):
        """Move topic to the bottom of its siblings (last display_order)"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to move.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.warning(self, "Cannot Move", "No siblings to reorder with.")
                return
            
            # Sort siblings by display_order, then by topic_name for consistent ordering
            siblings.sort(key=lambda t: (t.get('display_order', 0), t['topic_name'].lower()))
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Find current topic's position
            current_index = next((i for i, t in enumerate(siblings) if t['id'] == topic['id']), -1)
            
            if current_index == len(siblings) - 1:
                QMessageBox.information(self, "Already at Bottom", "Topic is already at the bottom.")
                return
            
            # Move selected topic to last position
            last_position = len(siblings) - 1
            
            # Set current topic to last display_order
            cursor.execute('''
                UPDATE DL.topics
                SET display_order = ?
                WHERE id = ?
            ''', (last_position, topic['id']))
            
            # Update display_order for all other siblings
            for idx, sibling in enumerate(siblings):
                if sibling['id'] != topic['id']:
                    new_order = idx if idx < current_index else idx - 1
                    cursor.execute('''
                        UPDATE DL.topics
                        SET display_order = ?
                        WHERE id = ?
                    ''', (new_order, sibling['id']))
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' moved to bottom.")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error moving topic to bottom: {e}")
            QMessageBox.critical(self, "Error", f"Failed to move topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def alphabetize_selected_topic(self):
        """Move selected topic to its alphabetical position among siblings"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to alphabetize.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.information(self, "Nothing to Alphabetize", "No siblings to sort with.")
                return
            
            # Sort siblings alphabetically by topic_name
            siblings.sort(key=lambda t: t['topic_name'].lower())
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Assign sequential display orders based on alphabetical position
            logger.info(f"Alphabetizing selected topic '{topic['topic_name']}' among {len(siblings)} siblings")
            for idx, sibling in enumerate(siblings):
                cursor.execute('''
                    UPDATE DL.topics
                    SET display_order = ?
                    WHERE id = ?
                ''', (idx, sibling['id']))
                logger.debug(f"Updated topic '{sibling['topic_name']}' display_order: -> {idx}")
            
            conn.commit()
            
            logger.info(f"Topic '{topic['topic_name']}' moved to alphabetical position.")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error alphabetizing selected topic: {e}")
            QMessageBox.critical(self, "Error", f"Failed to alphabetize topic:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def alphabetize_level(self):
        """Sort all siblings of the selected topic alphabetically"""
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a topic to alphabetize its level.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        parent_id = topic.get('parent_topic_id')
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all topics to find siblings
            all_topics = self.content_db.db.get_all_topics()
            
            # Find siblings (topics with same parent_topic_id)
            siblings = [t for t in all_topics if t.get('parent_topic_id') == parent_id]
            
            if len(siblings) < 2:
                QMessageBox.information(self, "Nothing to Alphabetize", "No siblings to sort.")
                return
            
            # Sort siblings alphabetically by topic_name
            siblings.sort(key=lambda t: t['topic_name'].lower())
            
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            
            # Assign sequential display orders based on alphabetical position
            logger.info(f"Alphabetizing entire level (parent_id={parent_id}) with {len(siblings)} topics")
            for idx, sibling in enumerate(siblings):
                cursor.execute('''
                    UPDATE DL.topics
                    SET display_order = ?
                    WHERE id = ?
                ''', (idx, sibling['id']))
                logger.debug(f"Updated topic '{sibling['topic_name']}' display_order: -> {idx}")
            
            conn.commit()
            
            logger.info(f"Level alphabetized ({len(siblings)} topics sorted).")
            self.load_topics_tree()
            
            # Re-select the topic
            self.select_topic_by_id(topic['id'])
            
        except Exception as e:
            logger.error(f"Error alphabetizing level: {e}")
            QMessageBox.critical(self, "Error", f"Failed to alphabetize level:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def select_topic_by_id(self, topic_id):
        """Helper method to select a topic in the tree by its ID"""
        def find_and_select(item):
            topic = item.data(0, Qt.UserRole)
            if topic and topic['id'] == topic_id:
                self.topics_tree.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if find_and_select(item.child(i)):
                    return True
            return False
        
        # Search through all top-level items
        for i in range(self.topics_tree.topLevelItemCount()):
            if find_and_select(self.topics_tree.topLevelItem(i)):
                break
    
    def assign_topic_to_selected_item(self):
        """Assign the selected topic to the currently selected browse item"""
        logger.info("[TOPIC_ASSIGN] ========== START assign_topic_to_selected_item ==========")
        
        # Get selected topic
        selected_topics = self.topics_tree.selectedItems()
        # Get selected topic
        selected_topics = self.topics_tree.selectedItems()
        if not selected_topics:
            QMessageBox.warning(self, "No Topic", "Please select a topic first.")
            return
        
        topic = selected_topics[0].data(0, Qt.UserRole)
        topic_id = topic['id']
        topic_name = topic['topic_name']
        
        # Get selected browse item
        shortcode = self.get_currently_selected_browse_item()
        if not shortcode:
            QMessageBox.warning(self, "No Item", "Please select an item in the Browse tab first.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        try:
            # Add topic assignment (uses many-to-many table)
            # Note: No wait cursor to avoid visual disruption during quick operation
            success = self.content_db.db.add_topic_assignment(shortcode, topic_id)
            
            if success:
                logger.info(f"Assigned topic '{topic_name}' (ID: {topic_id}) to item {shortcode}")
                
                # Check if files are already downloaded
                entry = self.content_db.db.get_content_entry(shortcode)
                if entry:
                    download_status = entry.get('download_status', 'not_downloaded')
                    
                    if download_status in ['downloaded', 'completed', 're-downloaded']:
                        # Files exist - copy them now
                        logger.info(f"Files already downloaded for {shortcode}, copying to topic '{topic_name}'")
                        self.copy_files_to_multiple_topic_folders(shortcode, [topic])
                        self.statusBar().showMessage(
                            f"Topic '{topic_name}' assigned to {shortcode} and files copied", 3000
                        )
                    else:
                        # Files not downloaded yet - assignment will be processed after download
                        logger.info(f"Files not downloaded for {shortcode}, assignment is pending")
                        self.statusBar().showMessage(
                            f"Topic '{topic_name}' assigned to {shortcode} (files will copy after download)", 3000
                        )
                else:
                    logger.warning(f"Content entry not found for {shortcode}")
                    self.statusBar().showMessage(
                        f"Topic '{topic_name}' assigned to {shortcode}", 3000
                    )
                
                # Update cache and tile appearance
                logger.info(f"[ASSIGN] Updating cache and tile for shortcode {shortcode}")
                if self.current_page in self.page_cache:
                    updated_entry = self.content_db.db.get_content_entry(shortcode)
                    if updated_entry:
                        # Find the post in cache - use single pass to avoid index corruption
                        target_post = None
                        post_index = None
                        for i, post in enumerate(self.page_cache[self.current_page]):
                            if post.get('shortcode') == shortcode:
                                target_post = post
                                post_index = i
                                break
                        
                        if target_post:
                            # Update ContentInformation fields (topic_id is the key change)
                            if 'ContentInformation' not in target_post:
                                target_post['ContentInformation'] = {}
                            if 'ContentInformation' in updated_entry:
                                target_post['ContentInformation']['topicID'] = updated_entry['ContentInformation'].get('topicID')
                            logger.info(f"[ASSIGN] Cache updated for {shortcode} - topicID={target_post['ContentInformation'].get('topicID')}")
                            
                            # Update tile appearance using the found index
                            if post_index is not None:
                                columns = self.calculate_tile_columns()
                                row = post_index // columns
                                col = post_index % columns
                                layout_item = self.tiles_grid.itemAtPosition(row, col)
                                if layout_item:
                                    tile_widget = layout_item.widget()
                                    if tile_widget:
                                        self.update_tile_appearance(tile_widget, target_post, shortcode)
                                        logger.info(f"[ASSIGN] Tile appearance updated for {shortcode}")
            else:
                QMessageBox.warning(self, "Failed", "Failed to assign topic (may already be assigned).")
                
        except Exception as e:
            logger.error(f"Error assigning topic: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to assign topic:\n{str(e)}")
    
    def unassign_topic_from_selected_item(self):
        """Remove the selected topic from the currently selected browse item"""
        # Get selected topic
        selected_topics = self.topics_tree.selectedItems()
        if not selected_topics:
            QMessageBox.warning(self, "No Topic", "Please select a topic first.")
            return
        
        topic = selected_topics[0].data(0, Qt.UserRole)
        topic_id = topic['id']
        topic_name = topic['topic_name']
        
        # Get selected browse item
        shortcode = self.get_currently_selected_browse_item()
        if not shortcode:
            QMessageBox.warning(self, "No Item", "Please select an item in the Browse tab first.")
            return
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        try:
            # Remove the specific topic assignment (uses many-to-many table)
            # Note: No wait cursor to avoid visual disruption during quick operation
            success = self.content_db.db.remove_topic_assignment(shortcode, topic_id)
            
            if success:
                logger.info(f"Removed topic '{topic_name}' (ID: {topic_id}) from item {shortcode}")
                self.statusBar().showMessage(f"Removed topic '{topic_name}' from {shortcode}", 3000)
                
                # Update cache and tile appearance
                logger.info(f"[UNASSIGN] Updating cache and tile for shortcode {shortcode}")
                if self.current_page in self.page_cache:
                    updated_entry = self.content_db.db.get_content_entry(shortcode)
                    if updated_entry:
                        # Find the post in cache - use single pass to avoid index corruption
                        target_post = None
                        post_index = None
                        for i, post in enumerate(self.page_cache[self.current_page]):
                            if post.get('shortcode') == shortcode:
                                target_post = post
                                post_index = i
                                break
                        
                        if target_post:
                            # Update ContentInformation fields (topic_id is the key change)
                            if 'ContentInformation' not in target_post:
                                target_post['ContentInformation'] = {}
                            if 'ContentInformation' in updated_entry:
                                target_post['ContentInformation']['topicID'] = updated_entry['ContentInformation'].get('topicID')
                            logger.info(f"[UNASSIGN] Cache updated for {shortcode} - topicID={target_post['ContentInformation'].get('topicID')}")
                            
                            # Update tile appearance using the found index
                            if post_index is not None:
                                columns = self.calculate_tile_columns()
                                row = post_index // columns
                                col = post_index % columns
                                layout_item = self.tiles_grid.itemAtPosition(row, col)
                                if layout_item:
                                    tile_widget = layout_item.widget()
                                    if tile_widget:
                                        self.update_tile_appearance(tile_widget, target_post, shortcode)
                                        logger.info(f"[UNASSIGN] Tile appearance updated for {shortcode}")
            else:
                QMessageBox.warning(self, "Failed", "Failed to remove topic assignment (may not be assigned).")
                
        except Exception as e:
            logger.error(f"Error removing topic assignment: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove topic assignment:\n{str(e)}")
    
    def get_currently_selected_browse_item(self):
        """Get the shortcode of the currently selected item in Browse tab"""
        if self.current_view_mode == 'table':
            selected = self.posts_table.selectedItems()
            if selected:
                row = selected[0].row()
                shortcode_item = self.posts_table.item(row, 2)
                if shortcode_item:
                    return shortcode_item.text().replace('✓ ', '').strip()
        # For tile view, we don't have a good way to track selection yet
        return None
    
    def on_browse_item_selection_changed(self):
        """Handle browse item selection change - update Topics tab"""
        shortcode = self.get_currently_selected_browse_item()
        
        if shortcode:
            # Get topic info for this item
            topic_name = "None"
            if self.content_db and self.content_db.db:
                try:
                    entry = self.content_db.db.get_content_entry(shortcode)
                    if entry:
                        content_info = entry.get('ContentInformation', {})
                        topic_id = content_info.get('topicID')
                        if topic_id:
                            topic = self.content_db.db.get_topic(topic_id)
                            if topic:
                                topic_name = topic['topic_name']
                except Exception as e:
                    logger.error(f"Error getting topic for {shortcode}: {e}")
            
            self.selected_item_label.setText(
                f"Selected: {shortcode}\n"
                f"Current Topic: {topic_name}"
            )
            self.unassign_topic_btn.setEnabled(topic_name != "None")
        else:
            self.selected_item_label.setText("No item selected in Browse tab")
            self.unassign_topic_btn.setEnabled(False)
    
    def confirm_all_topic_folders(self):
        """Check and create all topic folders in the file system"""
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        download_path = self.download_path_input.text()
        if not download_path:
            QMessageBox.warning(self, "No Download Path", "Please set a download path first.")
            return
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            base_path = Path(download_path)
            
            # Get all topics
            topics = self.content_db.db.get_all_topics()
            if not topics:
                QMessageBox.information(self, "No Topics", "No topics found in the database.")
                return
            
            created_folders = []
            existing_folders = []
            invalid_paths = []
            
            for topic in topics:
                topic_name = topic.get('topic_name', 'Unknown')
                topic_path = topic.get('content_path') or topic.get('topic_name')
                
                if not topic_path:
                    invalid_paths.append(f"{topic_name} (ID: {topic['id']})")
                    continue
                
                # Sanitize path
                sanitized_path, is_absolute = self.sanitize_topic_path(topic_path)
                if not sanitized_path:
                    invalid_paths.append(f"{topic_name} - Invalid path: {topic_path}")
                    continue
                
                # Build full folder path: use absolute or combine with base
                if is_absolute:
                    topic_folder = Path(sanitized_path)
                else:
                    topic_folder = base_path / Path(sanitized_path)
                
                # Create folder if it doesn't exist
                if not topic_folder.exists():
                    topic_folder.mkdir(parents=True, exist_ok=True)
                    created_folders.append(f"{topic_name} → {sanitized_path}")
                    logger.info(f"Created topic folder: {topic_folder}")
                else:
                    existing_folders.append(f"{topic_name} → {sanitized_path}")
            
            # Show results
            result_msg = f"Folder Confirmation Complete:\n\n"
            result_msg += f"✓ Created: {len(created_folders)}\n"
            result_msg += f"✓ Already Existed: {len(existing_folders)}\n"
            result_msg += f"✗ Invalid Paths: {len(invalid_paths)}\n\n"
            
            if created_folders:
                result_msg += "Created Folders:\n" + "\n".join(created_folders[:10])
                if len(created_folders) > 10:
                    result_msg += f"\n...and {len(created_folders) - 10} more"
                result_msg += "\n\n"
            
            if invalid_paths:
                result_msg += "Invalid Paths (needs fixing):\n" + "\n".join(invalid_paths[:5])
                if len(invalid_paths) > 5:
                    result_msg += f"\n...and {len(invalid_paths) - 5} more"
            
            QMessageBox.information(self, "Folder Confirmation", result_msg)
            self.topics_status.setText(f"Folders confirmed: {len(created_folders)} created, {len(existing_folders)} existed")
            
        except Exception as e:
            logger.error(f"Error confirming topic folders: {e}")
            QMessageBox.critical(self, "Error", f"Failed to confirm folders:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def manually_copy_files_to_topics(self):
        """Re-copy all files for all items assigned to the selected topic"""
        # Get selected topic
        selected = self.topics_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "No Topic", "Please select a topic first.")
            return
        
        topic = selected[0].data(0, Qt.UserRole)
        topic_id = topic['id']
        topic_name = topic['topic_name']
        
        if not self.content_db or not self.content_db.db:
            QMessageBox.warning(self, "No Database", "No database is loaded.")
            return
        
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            # Get all content items assigned to this topic
            conn = self.content_db.db._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT content_id 
                FROM DL.topic_assignments 
                WHERE account_name = ? AND topic_id = ?
            ''', (self.current_username, topic_id))
            
            content_ids = [row[0] for row in cursor.fetchall()]
            
            if not content_ids:
                QMessageBox.information(
                    self, "No Items", 
                    f"Topic '{topic_name}' has no items assigned to it."
                )
                QApplication.restoreOverrideCursor()
                return
            
            # Ask for confirmation
            reply = QMessageBox.question(
                self, "Confirm Copy",
                f"Copy files for {len(content_ids)} item(s) to topic '{topic_name}'?\n\n"
                "This will replace any missing files in the topic folder.",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                QApplication.restoreOverrideCursor()
                return
            
            # Process each content item
            copied_count = 0
            skipped_count = 0
            error_count = 0
            
            logger.info(f"Re-copying files for {len(content_ids)} items to topic '{topic_name}' (ID: {topic_id})")
            
            for shortcode in content_ids:
                try:
                    # Check if files are downloaded
                    entry = self.content_db.db.get_content_entry(shortcode)
                    if not entry:
                        logger.warning(f"Item {shortcode} not found in database, skipping")
                        skipped_count += 1
                        continue
                    
                    download_status = entry.get('download_status', 'not_downloaded')
                    if download_status not in ['downloaded', 'completed', 're-downloaded']:
                        logger.info(f"Item {shortcode} not downloaded, skipping")
                        skipped_count += 1
                        continue
                    
                    # Copy files to this topic
                    self.copy_files_to_multiple_topic_folders(shortcode, [topic])
                    copied_count += 1
                    logger.info(f"✓ Copied files for {shortcode} to '{topic_name}'")
                    
                except Exception as e:
                    logger.error(f"Error copying files for {shortcode}: {e}")
                    error_count += 1
            
            # Show summary
            summary = f"Copy operation complete for topic '{topic_name}':\n\n"
            summary += f"✓ Copied: {copied_count} item(s)\n"
            if skipped_count > 0:
                summary += f"⊘ Skipped: {skipped_count} item(s) (not downloaded)\n"
            if error_count > 0:
                summary += f"✗ Errors: {error_count} item(s)\n"
            summary += "\nCheck the console log for details."
            
            QMessageBox.information(self, "Copy Complete", summary)
            self.topics_status.setText(f"Copied files for {copied_count} item(s) to '{topic_name}'")
            
        except Exception as e:
            logger.error(f"Error copying files for topic: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to copy files:\n{str(e)}")
        finally:
            QApplication.restoreOverrideCursor()
    
    def download_thumbnail_by_shortcode(self, shortcode):
        """Download thumbnail using shortcode (called from tile)"""
        if not self.content_db or not self.instagram_manager.logged_in:
            QMessageBox.warning(self, "Not Ready", "Please login first")
            return
        
        # Find the post in page_cache (or saved_posts for backward compatibility)
        post = None
        # First check page_cache (current system)
        for page_num, posts in self.page_cache.items():
            for p in posts:
                if p.get('shortcode') == shortcode:
                    post = p
                    break
            if post:
                break
        
        # Fallback to saved_posts for backward compatibility
        if not post:
            for p in self.saved_posts:
                if p.get('shortcode') == shortcode:
                    post = p
                    break
        
        if not post:
            logger.warning(f"Post {shortcode} not found in page_cache or saved_posts")
            return
        
        # Create process entry for individual thumbnail download
        process_id = self.process_manager.add_process(
            'thumbnail_single',
            f'Thumbnail: {shortcode}',
            None
        )
        
        # Download thumbnail asynchronously with process tracking
        self.download_thumbnail_async(shortcode, post, process_id=process_id)
    
    def calculate_tile_columns(self):
        """Calculate number of columns based on available width"""
        # Get tile width for current size
        tile_widths = {'small': 110, 'medium': 160, 'large': 230, 'xlarge': 310}
        tile_width = tile_widths[self.tile_size]
        
        # Get available width (accounting for scrollbar and margins)
        available_width = self.tiles_scroll.viewport().width() - 20  # Subtract margins
        
        # Calculate columns (with spacing between tiles)
        spacing = 5  # Match grid spacing
        columns = max(1, (available_width + spacing) // (tile_width + spacing))
        
        return columns
    
    def resizeEvent(self, event):
        """Handle window resize - debounce and refresh tiles"""
        super().resizeEvent(event)
        
        # Only refresh tiles if in tile view mode
        if self.current_view_mode == 'tiles':
            # Debounce: start timer, will trigger after 150ms of no resize
            self.resize_timer.start(150)
    
    def on_resize_complete(self):
        """Called after resize completes (debounced)"""
        if self.current_view_mode == 'tiles' and self.filtered_posts:
            self.populate_tiles()
    
    # ========== END VIEW SWITCHING AND TILE VIEW METHODS ==========
    
    def closeEvent(self, event):
        """Handle application close - clean up resources"""
        try:
            # Save current page before closing
            if self.current_username:
                self.save_ui_setting('current_page', str(self.current_page))
                logger.info(f"[PAGE SAVE] Saved current page on close: {self.current_page} (displays as 'Page {self.current_page + 1}' in UI)")
                logger.info(f"[PAGE SAVE] Account: {self.current_username}, saved value: '{self.current_page}'")
            
            # Close database connections
            if hasattr(self, 'content_db') and self.content_db:
                try:
                    self.content_db.db.close()
                except:
                    pass
        except Exception as e:
            # Use print instead of logger as Qt widgets may be destroyed
            print(f"Error during cleanup: {e}", file=sys.stderr)
        finally:
            event.accept()
    
    def exit_application(self):
        """Exit the application with confirmation"""
        try:
            # Check for running processes
            running_count = 0
            if hasattr(self, 'process_manager'):
                for process in self.process_manager.get_all_processes().values():
                    if process['status'] in ['running', 'paused']:
                        running_count += 1
            
            # Check for active download threads
            active_threads = 0
            if hasattr(self, 'active_download_threads'):
                active_threads = len(self.active_download_threads)
            
            # Show confirmation dialog if there are running processes or downloads
            total_active = running_count + active_threads
            if total_active > 0:
                reply = QMessageBox.question(
                    self, "Exit Application",
                    f"There are {total_active} active operation(s).\n\nExiting will stop all downloads and processes.\n\nAre you sure you want to exit?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
            
            # Close the application
            logger.info("User initiated application exit")
            self.close()
            
        except Exception as e:
            logger.error(f"Error during exit: {e}", exc_info=True)
            self.close()


def main():
    """Application entry point"""
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Create application
    app = QApplication(sys.argv)
    window = InstagramDownloaderGUI()
    
    # Clean up GUI logger before Qt objects are destroyed
    def cleanup_logging():
        try:
            if hasattr(window, 'gui_handler'):
                root_logger = logging.getLogger()
                root_logger.removeHandler(window.gui_handler)
                # Don't call close() as Qt objects are already being destroyed
                # Just disconnect the signal
                try:
                    window.gui_handler.log_signal.disconnect()
                except:
                    pass
        except Exception as e:
            print(f"Logging cleanup error: {e}", file=sys.stderr)
    
    app.aboutToQuit.connect(cleanup_logging)
    
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

