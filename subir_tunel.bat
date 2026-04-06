@echo off
chcp 65001 >nul
title iScholar ETL - Tunel HTTPS (ngrok)

echo.
echo ============================================================
echo   iScholar ETL - Tunel HTTPS publico (ngrok)
echo ============================================================
echo.
echo IMPORTANTE: copie a URL "Forwarding https://..." que aparecer abaixo
echo e cole como API_BASE_URL no Apps Script do Google Sheets.
echo.
echo O tunel ficara ativo enquanto esta janela estiver aberta.
echo Feche esta janela para encerrar o tunel.
echo.
echo ============================================================
echo.

"C:\Users\PICHAU\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe" http 5000
