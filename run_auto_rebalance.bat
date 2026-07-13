@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo [Quant Auto Run] 시작 시각: %date% %time% >> auto_run_log.txt

:: 기본 상태는 모의 실행(Dry-run) 및 노션 동기화 모드입니다.
:: 만약 실제 토스증권 API를 통해 자동 매수/매도 주문까지 실행하시려면,
:: 아래 명령어 끝에 --execute 를 추가해 주세요.
:: 예: python quant_analyzer.py --execute >> auto_run_log.txt 2>&1
python quant_analyzer.py >> auto_run_log.txt 2>&1

if %errorlevel% equ 0 (
    echo [Quant Auto Run] 성공 종료: %date% %time% >> auto_run_log.txt
) else (
    echo [Quant Auto Run] 오류 발생(에러코드: %errorlevel%): %date% %time% >> auto_run_log.txt
)
