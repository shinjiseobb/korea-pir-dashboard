# 전국 시·군·구 부동산 PIR 대시보드 파워쉘 실행 스크립트
$Host.UI.RawUI.WindowTitle = "전국 시·군·구 부동산 PIR 대시보드"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " 전국 시·군·구 소득 대비 주택가격(PIR) 대시보드 실행기" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-Not (Test-Path $VenvPython)) {
    Write-Host "[오류] 가상환경(.venv) 파이썬을 찾을 수 없습니다." -ForegroundColor Red
    Pause
    Exit
}

Write-Host "[1/2] 브라우저 자동 접속 중: http://127.0.0.1:8000" -ForegroundColor Yellow
Start-Process "http://127.0.0.1:8000"

Write-Host "[2/2] FastAPI 서버 실행 중... (종료: Ctrl + C)" -ForegroundColor Yellow
Write-Host ""

& $VenvPython main.py
