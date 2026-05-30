# Setup Guide

## Initial Setup for New Installations

### 1. Database Configuration

**Copy the configuration template:**

```powershell
Copy-Item config_local.example.py config_local.py
```

**Edit `config_local.py` with your credentials:**

```python
SQL_SERVER_CONFIG = {
    'server': 'localhost',  # Your SQL Server hostname
    'database': 'DOWNLOAD-SYSTEM',
    'username': 'YOUR_USERNAME',  # Your SQL username
    'password': 'YOUR_PASSWORD',  # Your SQL password
    'schema': 'DL'
}

DEFAULT_ACCOUNT_NAME = 'your_instagram_username'
```

⚠️ **Important:** `config_local.py` is in `.gitignore` and will never be committed to version control.

### 2. Install Dependencies

**Production:**

```powershell
pip install -r requirements.txt
```

**Development (includes testing and linting tools):**

```powershell
pip install -r requirements-dev.txt
pre-commit install
```

### 3. Setup SQL Server Database

Run the setup script:

```powershell
.\setup_sqlserver.ps1
```

This creates:

- `DOWNLOAD-SYSTEM` database
- `DL` schema
- All required tables

### 4. Run the Application

```powershell
python main.py
```

## Configuration Files

| File                      | Purpose                         | Committed to Git?  |
| ------------------------- | ------------------------------- | ------------------ |
| `config_constants.py`     | App constants and config loader | ✅ Yes             |
| `config_local.example.py` | Template for local config       | ✅ Yes             |
| `config_local.py`         | **Your actual credentials**     | ❌ No (gitignored) |
| `settings.json`           | Runtime app settings            | ❌ No (gitignored) |

## Security Best Practices

1. ✅ **Never commit `config_local.py`** - It's in `.gitignore`
2. ✅ **Use SQL Server authentication** - Create a dedicated user
3. ✅ **Limit database permissions** - Only grant access to `DL` schema
4. ✅ **Rotate passwords regularly** - Update `config_local.py` after rotation
5. ✅ **Use environment variables** - For production/server deployments

## Troubleshooting

**"Using default database config" warning:**

- You haven't created `config_local.py` yet
- Copy from `config_local.example.py` and update credentials

**Database connection error:**

- Verify SQL Server is running
- Check credentials in `config_local.py`
- Confirm database exists (run `setup_sqlserver.ps1`)
- Check firewall settings

**Import errors:**

- Run `pip install -r requirements.txt`
- Verify Python 3.9+ is installed

## For Contributors

When contributing to this project:

1. Never commit your `config_local.py`
2. Update `config_local.example.py` if adding new config options
3. Test with a fresh setup using the example config
4. Run pre-commit hooks: `pre-commit run --all-files`

## Advanced: Environment Variables

For production deployments, you can use environment variables:

```python
# In config_local.py
import os

SQL_SERVER_CONFIG = {
    'server': os.getenv('SQL_SERVER', 'localhost'),
    'database': os.getenv('SQL_DATABASE', 'DOWNLOAD-SYSTEM'),
    'username': os.getenv('SQL_USERNAME'),
    'password': os.getenv('SQL_PASSWORD'),
    'schema': 'DL'
}
```

Then set environment variables:

```powershell
$env:SQL_USERNAME = "your_username"
$env:SQL_PASSWORD = "your_password"
```
