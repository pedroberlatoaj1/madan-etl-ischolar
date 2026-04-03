@echo off
chcp 65001 >nul
title iScholar ETL - Encerrando servicos

echo.
echo ============================================================
echo   iScholar ETL - Encerrando servicos
echo ============================================================
echo.

echo Encerrando backend e worker...
taskkill /FI "WINDOWTITLE eq iScholar ETL - Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq iScholar ETL - Worker" /F >nul 2>&1

REM Garantia: matar qualquer python rodando webhook ou worker neste diretório
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul') do (
    wmic process where "ProcessId=%%i and CommandLine like '%%webhook_google_sheets%%'" delete >nul 2>&1
    wmic process where "ProcessId=%%i and CommandLine like '%%worker.py%%'" delete >nul 2>&1
)

echo.
echo   Servicos encerrados.
echo ============================================================
echo.
pause
