"""
Account Manager - SQL Server persistence for account data

Handles storing and retrieving account information and settings from SQL Server.
"""
import pyodbc
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import logging

import config

logger = logging.getLogger(__name__)


class AccountManager:
    """Manages account persistence using SQL Server"""
    
    def __init__(self, server: str = "localhost", 
                 database: str = "DOWNLOAD-SYSTEM",
                 username: str = "DOWLOAD-SYSTEM",
                 password: str = "DOWLOAD-SYSTEM-1971~"):
        self.server = server
        self.database = database
        self.username = username
        self.password = password
        self.connection_string = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"TrustServerCertificate=yes;"
        )
        self._ensure_tables()
    
    def _get_connection(self):
        """Get a database connection"""
        return pyodbc.connect(self.connection_string)
    
    def _ensure_tables(self):
        """Ensure required tables exist"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if DL.Accounts table exists
            cursor.execute("""
                SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'DL' AND TABLE_NAME = 'Accounts'
            """)
            if not cursor.fetchone():
                logger.warning("DL.Accounts table does not exist - please create it")
            
            # Check if DL.Settings table exists, create if not
            cursor.execute("""
                SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'DL' AND TABLE_NAME = 'Settings'
            """)
            if not cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE DL.Settings (
                        setting_key NVARCHAR(100) PRIMARY KEY,
                        setting_value NVARCHAR(MAX),
                        updated_at DATETIME2 DEFAULT GETDATE()
                    )
                """)
                conn.commit()
                logger.info("Created DL.Settings table")
            
            # Check if DL.AccountSettings table exists, create if not
            cursor.execute("""
                SELECT 1 FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_SCHEMA = 'DL' AND TABLE_NAME = 'AccountSettings'
            """)
            if not cursor.fetchone():
                cursor.execute("""
                    CREATE TABLE DL.AccountSettings (
                        account_username NVARCHAR(100) NOT NULL,
                        setting_key NVARCHAR(100) NOT NULL,
                        setting_value NVARCHAR(MAX),
                        updated_at DATETIME2 DEFAULT GETDATE(),
                        CONSTRAINT PK_AccountSettings PRIMARY KEY (account_username, setting_key)
                    )
                """)
                conn.commit()
                logger.info("Created DL.AccountSettings table")
            
            conn.close()
            logger.info("SQL Server account management initialized")
        except Exception as e:
            logger.error(f"Failed to ensure tables: {e}")
    
    def save_account(
        self,
        username: str,
        session_file: str,
        download_path: str = None,
        debug_path: str = None,
        ig_username: str = None,
        thumbnails_path: str = None,
        topics_root_path: str = None,
        root_folder: str = None
    ) -> bool:
        """
        Save or update account information
        
        Args:
            username: Account name (local identifier)
            session_file: Path to session file
            download_path: Custom download directory for this account
            debug_path: Custom debug directory for this account
            ig_username: Actual Instagram username (if different from account name)
            thumbnails_path: Custom thumbnails directory for this account
            topics_root_path: Root path for all topic folders
            root_folder: Root folder for all account data
        
        Returns:
            True if successful
        """
        # IMPORTANT: Check if account exists first to preserve existing paths when None is passed
        is_existing_account = False
        try:
            conn_check = self._get_connection()
            cursor_check = conn_check.cursor()
            cursor_check.execute(
                """SELECT root_folder, download_path, debug_path, thumbnails_path, topics_root_path, ig_username 
                   FROM DL.Accounts WHERE account_name = ?""",
                (username,)
            )
            existing_account = cursor_check.fetchone()
            conn_check.close()
            
            if existing_account:
                # Account exists - preserve existing values if new values are None
                is_existing_account = True
                logger.info(f"save_account: Account {username} EXISTS, preserving existing paths where None passed")
                if root_folder is None and existing_account[0]:
                    root_folder = existing_account[0]
                    logger.info(f"  Preserved existing root_folder: {root_folder}")
                if download_path is None and existing_account[1]:
                    download_path = existing_account[1]
                    logger.info(f"  Preserved existing download_path: {download_path}")
                if debug_path is None and existing_account[2]:
                    debug_path = existing_account[2]
                    logger.info(f"  Preserved existing debug_path: {debug_path}")
                if thumbnails_path is None and existing_account[3]:
                    thumbnails_path = existing_account[3]
                    logger.info(f"  Preserved existing thumbnails_path: {thumbnails_path}")
                if topics_root_path is None and existing_account[4]:
                    topics_root_path = existing_account[4]
                    logger.info(f"  Preserved existing topics_root_path: {topics_root_path}")
                if ig_username is None and existing_account[5]:
                    ig_username = existing_account[5]
                    logger.info(f"  Preserved existing ig_username: {ig_username}")
        except Exception as e:
            logger.warning(f"Could not check existing account: {e}")
            existing_account = None
        
        # NEVER use C: drive defaults - paths must be explicitly set by user
        if not is_existing_account:
            # This is a NEW account - leave paths as None if not provided
            if download_path is None:
                logger.warning(f"⚠️ NEW account {username}: No download_path provided - user must set in Settings tab")
            
            if debug_path is None:
                logger.warning(f"⚠️ NEW account {username}: No debug_path provided - user must set in Settings tab")
        else:
            # This is an EXISTING account - preserve all database values
            logger.info(f"✓ EXISTING account {username}: Preserving all database paths")
        
        # Use provided ig_username or fall back to username
        if ig_username is None:
            ig_username = username
        
        # Calculate default thumbnails_path if not provided
        if thumbnails_path is None:
            # First check if account already exists and has a root_folder
            try:
                conn_check = self._get_connection()
                cursor_check = conn_check.cursor()
                cursor_check.execute(
                    "SELECT root_folder, download_path, topics_root_path FROM DL.Accounts WHERE account_name = ?",
                    (username,)
                )
                existing_account = cursor_check.fetchone()
                conn_check.close()
                
                if existing_account and existing_account[0]:  # Use root_folder if exists
                    # root_folder = "G:/.stogram", thumbnails = "G:/.stogram/sassenheimer/.thumbnails"
                    thumbnails_path = str(Path(existing_account[0]) / username / ".thumbnails")
                elif existing_account and existing_account[1]:  # Use download_path if exists
                    # download_path = "G:/.stogram/sassenheimer/content"
                    # Go up to sassenheimer level, then add .thumbnails
                    # Path(...).parent.parent would get us to G:/.stogram, but we want sassenheimer level
                    # So: parent gives us "G:/.stogram/sassenheimer", then add .thumbnails
                    thumbnails_path = str(Path(existing_account[1]).parent / ".thumbnails")
                else:  # New account, use download_path parameter
                    # download_path should be like "path/username/content" or "path/username"
                    # We want "path/username/.thumbnails"
                    dl_path = Path(download_path)
                    # If download_path ends with 'content', go up one level, otherwise use parent
                    if dl_path.name == 'content':
                        thumbnails_path = str(dl_path.parent / ".thumbnails")
                    else:
                        thumbnails_path = str(dl_path / ".thumbnails")
            except Exception as e:
                logger.warning(f"Could not determine existing paths, using default: {e}")
                # Fallback to simple calculation
                dl_path = Path(download_path)
                if dl_path.name == 'content':
                    thumbnails_path = str(dl_path.parent / ".thumbnails")
                else:
                    thumbnails_path = str(dl_path / ".thumbnails")
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            logger.info(f"DEBUG save_account: username={username}, download_path={download_path}, thumbnails_path={thumbnails_path}, ig_username={ig_username}")
            
            # Check if account exists
            cursor.execute(
                "SELECT account_name FROM DL.Accounts WHERE account_name = ?",
                (username,)
            )
            exists = cursor.fetchone()
            
            if exists:
                # Update existing account - include root_folder
                logger.info(f"DEBUG save_account: Updating existing account with SQL params: ig_username={ig_username}, root_folder={root_folder}, download_path={download_path}, thumbnails_path={thumbnails_path}, debug_path={debug_path}, topics_root_path={topics_root_path}, username={username}")
                cursor.execute("""
                    UPDATE DL.Accounts 
                    SET ig_username = ?, root_folder = ?, download_path = ?, thumbnails_path = ?, debug_path = ?, topics_root_path = ?, updated_at = GETDATE()
                    WHERE account_name = ?
                """, (ig_username, root_folder, download_path, thumbnails_path, debug_path, topics_root_path, username))
                logger.info(f"DEBUG save_account: UPDATE executed, rows affected: {cursor.rowcount}")
            else:
                # Insert new account - include root_folder
                logger.info(f"DEBUG save_account: Inserting new account")
                cursor.execute("""
                    INSERT INTO DL.Accounts 
                    (account_name, ig_username, root_folder, download_path, thumbnails_path, debug_path, topics_root_path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE(), GETDATE())
                """, (username, ig_username, root_folder, download_path, thumbnails_path, debug_path, topics_root_path))
            
            conn.commit()
            logger.info(f"DEBUG save_account: Transaction committed")
            conn.close()
            
            logger.info(f"Saved account: {username} (IG: {ig_username}) with download_path: {download_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save account {username}: {e}")
            return False
    
    def get_account(self, username: str) -> Optional[Dict]:
        """
        Get account information
        
        Args:
            username: Instagram username
        
        Returns:
            Dict with account info, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT account_name, ig_username, ig_password, root_folder, 
                       debug_path, download_path, thumbnails_path, topics_root_path, created_at, updated_at
                FROM DL.Accounts 
                WHERE account_name = ?
            """, (username,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                result = {
                    'username': row[0],
                    'ig_username': row[1],
                    'ig_password': row[2],
                    'root_folder': row[3],
                    'debug_path': row[4],
                    'download_path': row[5],
                    'thumbnails_path': row[6],
                    'topics_root_path': row[7],
                    'created_at': row[8],
                    'updated_at': row[9],
                    'session_file': str(config.SESSIONS_DIR / f"{username}.session")
                }
                logger.info(f"DEBUG get_account: Retrieved for {username}: download_path={row[5]}, thumbnails_path={row[6]}")
                return result
            logger.warning(f"DEBUG get_account: No account found for {username}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get account {username}: {e}")
            return None
    
    def list_accounts(self) -> List[Dict]:
        """
        Get all saved accounts
        
        Returns:
            List of account dicts, sorted by last update (most recent first)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT account_name, ig_username, ig_password, root_folder, 
                       debug_path, download_path, thumbnails_path, created_at, updated_at
                FROM DL.Accounts 
                ORDER BY updated_at DESC
            """)
            
            accounts = []
            for row in cursor.fetchall():
                accounts.append({
                    'username': row[0],
                    'ig_username': row[1],
                    'ig_password': row[2],
                    'root_folder': row[3],
                    'debug_path': row[4],
                    'download_path': row[5],
                    'thumbnails_path': row[6],
                    'created_at': row[7],
                    'last_login': row[8],  # Using updated_at as last_login
                    'session_file': str(config.SESSIONS_DIR / f"{row[0]}.session")
                })
            
            conn.close()
            return accounts
            
        except Exception as e:
            logger.error(f"Failed to list accounts: {e}")
            return []
    
    def delete_account(self, username: str) -> bool:
        """
        Delete an account
        
        Args:
            username: Instagram username
        
        Returns:
            True if successful
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM DL.Accounts WHERE account_name = ?", (username,))
            conn.commit()
            conn.close()
            
            logger.info(f"Deleted account: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete account {username}: {e}")
            return False
    
    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """Get a setting value"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT [value] FROM DL.Settings WHERE [key] = ?",
                (key,)
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else default
            
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {e}")
            return default
    
    def set_setting(self, key: str, value: str) -> bool:
        """Set a setting value"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if setting exists
            cursor.execute(
                "SELECT [key] FROM DL.Settings WHERE [key] = ?",
                (key,)
            )
            exists = cursor.fetchone()
            
            if exists:
                cursor.execute("""
                    UPDATE DL.Settings 
                    SET [value] = ?, updated_at = GETDATE()
                    WHERE [key] = ?
                """, (value, key))
            else:
                cursor.execute("""
                    INSERT INTO DL.Settings ([key], [value], updated_at)
                    VALUES (?, ?, GETDATE())
                """, (key, value))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False
    
    def get_account_setting(self, username: str, key: str, default: str = None) -> Optional[str]:
        """Get an account-specific setting value"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT setting_value FROM DL.AccountSettings WHERE account_username = ? AND setting_key = ?",
                (username, key)
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else default
            
        except Exception as e:
            logger.error(f"Failed to get account setting {username}.{key}: {e}")
            return default
    
    def set_account_setting(self, username: str, key: str, value: str) -> bool:
        """Set an account-specific setting value"""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if setting exists
            cursor.execute(
                "SELECT setting_key FROM DL.AccountSettings WHERE account_username = ? AND setting_key = ?",
                (username, key)
            )
            exists = cursor.fetchone()
            
            if exists:
                cursor.execute("""
                    UPDATE DL.AccountSettings 
                    SET setting_value = ?, updated_at = GETDATE()
                    WHERE account_username = ? AND setting_key = ?
                """, (value, username, key))
            else:
                cursor.execute("""
                    INSERT INTO DL.AccountSettings (account_username, setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?, GETDATE())
                """, (username, key, value))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Failed to set account setting {username}.{key}: {e}")
            return False
