# Local Configuration - SQL Server Credentials
# COPY THIS FILE TO config_local.py AND UPDATE WITH YOUR CREDENTIALS
# config_local.py is in .gitignore and will not be committed

SQL_SERVER_CONFIG = {
    'server': 'localhost',  # Your SQL Server hostname/IP
    'database': 'DOWNLOAD-SYSTEM',  # Database name
    'username': 'YOUR_USERNAME',  # SQL Server username
    'password': 'YOUR_PASSWORD',  # SQL Server password
    'schema': 'DL'  # Database schema
}

# Default account name for multi-account support
DEFAULT_ACCOUNT_NAME = 'your_instagram_username'
