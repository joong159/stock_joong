@echo off

chcp 65001 > nul

setlocal enabledelayedexpansion



echo =======================================================================

echo   📊 퀀트 자동 리밸런싱 및 노션 동기화 스케줄러 자동 등록기

echo =======================================================================

echo.

echo 이 스크립트는 매일 오전 07:30(미국/한국 시장 종가 반영 시점)에

echo 퀀트 분석 및 노션 자동 리밸런싱 프로그램을 자동으로 무인 실행하도록

echo Windows 작업 스케줄러(Task Scheduler)에 등록합니다.

echo.

echo * 권장 사항: 매일 한 번 자동으로 돌리기 위해 컴퓨터가 켜져 있어야 합니다.

echo   (만약 지정된 시간에 켜져 있지 않다면, PC가 켜지는 즉시 실행됩니다.)

echo.

echo -----------------------------------------------------------------------



set SCRIPT_DIR=%~dp0



:: Delete old task if exists

schtasks /delete /tn "StockQuantAutoSync" /f >nul 2>&1



:: Create new task

schtasks /create /tn "StockQuantAutoSync" /tr "\"%SCRIPT_DIR%run_auto_rebalance.bat\"" /sc daily /st 07:30 /f



if %errorlevel% equ 0 (

    echo.

    echo =======================================================================

    echo 🎉 [성공] 매일 오전 07:30에 자동 실행되도록 스케줄러 등록이 완료되었습니다!

    echo.

    echo * 등록된 작업 이름: StockQuantAutoSync

    echo * 등록된 명령어: "%SCRIPT_DIR%run_auto_rebalance.bat"

    echo.

    echo 이제 매일 아침 자동으로 분석이 수행되고 노션 대시보드가 업데이트됩니다.

    echo Windows 작업 스케줄러 앱에서 설정을 변경하거나 수동 실행해 보실 수 있습니다.

    echo =======================================================================

) else (

    echo.

    echo ❌ [오류] 작업 스케줄러 등록에 실패했습니다.

    echo * 원인: 관리자 권한이 필요합니다.

    echo   마우스 우클릭 후 [관리자 권한으로 실행]을 클릭하여 다시 실행해 주세요.

    echo.

)

pause

