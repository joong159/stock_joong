@echo off
cd /d "%~dp0"
echo ============================================================ >> news_run_log.txt
echo [START] %date% %time% >> news_run_log.txt
echo ============================================================ >> news_run_log.txt
python -u sync_news_hourly.py >> news_run_log.txt 2>&1
if %errorlevel% equ 0 (
    echo [SUCCESS] News sync completed cleanly. >> news_run_log.txt
) else (
    echo [ERROR] News sync failed with exit code %errorlevel%. >> news_run_log.txt
)
