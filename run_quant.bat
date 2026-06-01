@echo off
chcp 65001 >nul
echo ==========================================
echo Quant Analyzer 실행을 시작합니다...
echo ==========================================
cd /d "%~dp0"
python quant_analyzer.py
pause