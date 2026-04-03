@echo off
chcp 65001 >nul
title iScholar ETL - Iniciando servicos

echo.
echo ============================================================
echo   iScholar ETL - Iniciando servicos
echo ============================================================
echo.

cd /d "%~dp0"

REM Verificar se o .venv existe
if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo        Execute: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM Verificar se o .env existe
if not exist ".env" (
    echo [ERRO] Arquivo .env nao encontrado.
    echo        Copie .env.example para .env e preencha as credenciais.
    pause
    exit /b 1
)

echo [1/2] Iniciando backend (webhook) na porta 5000...
start "iScholar ETL - Backend" /min cmd /c ".venv\Scripts\python.exe webhook_google_sheets.py >> logs\webhook.log 2>&1"

timeout /t 3 /nobreak >nul

echo [2/2] Iniciando worker...
start "iScholar ETL - Worker" /min cmd /c ".venv\Scripts\python.exe worker.py >> logs\worker.log 2>&1"

echo.
echo ============================================================
echo   Servicos iniciados em segundo plano.
echo   Backend : http://localhost:5000
echo   Logs    : pasta logs\
echo   Para encerrar: execute parar_servicos.bat
echo ============================================================
echo.
pause
