# SQL Server Setup Script
# Run this to set up the complete SQL Server environment

Write-Host "=" * 80
Write-Host "Instagram Downloader - SQL Server Setup"
Write-Host "=" * 80

# Step 1: Install pyodbc
Write-Host "`n[1/4] Installing Python dependencies..."
pip install pyodbc

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install pyodbc" -ForegroundColor Red
    exit 1
}

Write-Host "  ✓ pyodbc installed" -ForegroundColor Green

# Step 2: Test connection
Write-Host "`n[2/4] Testing SQL Server connection..."
python test_sqlserver_connection.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nPlease fix SQL Server connection issues before proceeding" -ForegroundColor Yellow
    Write-Host "`nSetup checklist:" -ForegroundColor Cyan
    Write-Host "  1. SQL Server is installed and running"
    Write-Host "  2. ODBC Driver 17 for SQL Server is installed"
    Write-Host "  3. Database 'InstagramDownloader' is created"
    Write-Host "  4. User 'DOWLOAD-SYSTEM' exists with password 'DOWLOAD-SYSTEM-1971~'"
    Write-Host "  5. Run: sql_server_schema.sql"
    exit 1
}

Write-Host "  ✓ SQL Server connection successful" -ForegroundColor Green

# Step 3: Ask about migration
Write-Host "`n[3/4] Data Migration"
Write-Host "Do you want to migrate data from SQLite to SQL Server now?"
$migrate = Read-Host "Enter 'yes' to migrate, or 'no' to skip"

if ($migrate -eq "yes") {
    Write-Host "`nEnter the user directory containing repo.db:"
    Write-Host "  (Press Enter for default: 'sassenheimer')"
    $userDir = Read-Host
    
    if ([string]::IsNullOrWhiteSpace($userDir)) {
        $userDir = "sassenheimer"
    }
    
    if (-not (Test-Path "$userDir\repo.db")) {
        Write-Host "ERROR: repo.db not found in $userDir" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "`nStarting migration from $userDir\repo.db..."
    python migrate_sqlite_to_sqlserver.py $userDir
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nMigration failed. Check error messages above." -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  ✓ Migration completed successfully" -ForegroundColor Green
} else {
    Write-Host "  Skipping migration" -ForegroundColor Yellow
}

# Step 4: Final status
Write-Host "`n[4/4] Setup Complete!"
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  Database Type: SQL Server"
Write-Host "  Server: localhost"
Write-Host "  Database: InstagramDownloader"
Write-Host "  Schema: DL"
Write-Host "  Account: sassenheimer"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run: python main.py"
Write-Host "  2. Use SQL Server Management Studio to query data without locking"
Write-Host "  3. See SQL_SERVER_MIGRATION_GUIDE.md for more information"
Write-Host ""
Write-Host "Useful queries:" -ForegroundColor Cyan
Write-Host "  -- View content summary"
Write-Host "  SELECT * FROM DL.vw_content_summary;"
Write-Host ""
Write-Host "  -- Get download stats"
Write-Host "  EXEC DL.sp_get_download_stats;"
Write-Host ""
Write-Host "=" * 80
