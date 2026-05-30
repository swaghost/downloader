"""
Database Manager Factory
Returns SQL Server database manager for Instagram content
"""

from config_constants import SQL_SERVER_CONFIG, DEFAULT_ACCOUNT_NAME
from database_manager_sqlserver import DatabaseManagerSQLServer


def get_database_manager(user_dir: str, account_name: str = None):
    """
    Get SQL Server database manager for Instagram content.
    
    Args:
        user_dir: User directory path (kept for compatibility)
        account_name: Account name for SQL Server (optional, uses default if not provided)
    
    Returns:
        DatabaseManagerSQLServer instance
    """
    if account_name is None:
        account_name = DEFAULT_ACCOUNT_NAME
    
    return DatabaseManagerSQLServer(
        user_dir=user_dir,
        account_name=account_name,
        server=SQL_SERVER_CONFIG['server'],
        database=SQL_SERVER_CONFIG['database'],
        username=SQL_SERVER_CONFIG['username'],
        password=SQL_SERVER_CONFIG['password']
    )


def get_database_info():
    """Get current database configuration info."""
    return {
        'type': 'SQL Server',
        'server': SQL_SERVER_CONFIG['server'],
        'database': SQL_SERVER_CONFIG['database'],
        'schema': SQL_SERVER_CONFIG['schema'],
        'account': DEFAULT_ACCOUNT_NAME
    }


def get_system_database_manager():
    """
    Get a system-level database manager for operations not tied to a specific account.
    Used for account management (listing accounts, etc.)
    
    Returns:
        DatabaseManagerSQLServer instance for system operations
    """
    # Use a dummy user_dir since we're only accessing global tables like accounts
    return DatabaseManagerSQLServer(
        user_dir='system',
        account_name='system',
        server=SQL_SERVER_CONFIG['server'],
        database=SQL_SERVER_CONFIG['database'],
        username=SQL_SERVER_CONFIG['username'],
        password=SQL_SERVER_CONFIG['password']
    )
