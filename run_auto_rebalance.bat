@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo [Quant Auto Run] 시작 시각: %date% %time% >> auto_run_log.txt

:: 퀀트 분석 및 노션 대시보드 동기화 (추천/기록 전용, 실제 주문 없음)
python quant_analyzer.py >> auto_run_log.txt 2>&1

if %errorlevel% equ 0 (
    echo [Quant Auto Run] 성공 종료: %date% %time% >> auto_run_log.txt
) else (
    echo [Quant Auto Run] 오류 발생(에러코드: %errorlevel%): %date% %time% >> auto_run_log.txt
)
