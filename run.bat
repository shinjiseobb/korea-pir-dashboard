@echo off
chcp 65001 >nul
title 전국 시·군·구 부동산 PIR 비교 대시보드
echo ========================================================
echo  전국 시·군·구 소득 대비 주택가격(PIR) 대시보드 실행기
echo ========================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [오류] 가상환경(.venv)을 찾을 수 없습니다.
    pause
    exit /b 1
)

echo [1/2] 대시보드 웹 브라우저 자동 오픈 준비 중...
start http://127.0.0.1:8000

echo [2/2] 백엔드 서버 구동 중... (종료하려면 창을 닫거나 Ctrl+C를 누르세요)
echo.
".venv\Scripts\python.exe" main.py

pause
