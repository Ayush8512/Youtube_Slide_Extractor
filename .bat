@echo off
color 0A
title YT Smart Extractor Pro
echo ===================================================
echo    🚀 Starting YT Smart Extractor Server...
echo ===================================================
echo.
echo Please wait while the server boots up...
echo (Your browser will open automatically in a few seconds)
echo.

:: Ek chhota timer taaki server pehle start ho jaye
ping 127.0.0.1 -n 3 > nul
start "" "http://127.0.0.1:8000"

:: Python server start karne ki command
python app.py

pause