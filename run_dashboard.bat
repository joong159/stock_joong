@echo off
cd /d "%~dp0"
title Toss Live Portfolio Dashboard Launcher
echo ==================================================
echo   Toss Securities Live Portfolio Dashboard
echo   Starting the GUI application...
echo   Please keep this terminal window open.
echo ==================================================
python dashboard.py
pause
