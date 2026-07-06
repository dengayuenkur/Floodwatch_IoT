@echo off
:: ============================================================
::  Flood Monitoring System -- Windows Setup Script
::  Author: Deng Daniel Ayuen Kur (240103002054)
:: ============================================================
setlocal EnableDelayedExpansion

echo ============================================
echo   FloodWatch IoT -- Server Setup (Windows)
echo ============================================

cd /d "%~dp0..\server"

:: ── Python check ────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download from https://www.python.org/downloads/
    pause & exit /b 1
)
echo [OK] Python found

:: ── Virtual environment ──────────────────────────────────────
if not exist "venv\" (
    echo [...] Creating virtual environment...
    python -m venv venv
)
echo [OK] Virtual environment ready

call venv\Scripts\activate.bat

:: ── Install packages ─────────────────────────────────────────
echo [...] Installing Python packages...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo [OK] Dependencies installed

:: ── Create .env ──────────────────────────────────────────────
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] .env created from .env.example
    echo.
    echo   !! ACTION REQUIRED: Edit server\.env and fill in your values !!
    echo      Especially: SECRET_KEY, JWT_SECRET_KEY, SENSOR_API_KEY
    echo.
)

:: ── Logs dir ─────────────────────────────────────────────────
if not exist "logs\" mkdir logs
echo [OK] logs\ directory ready

:: ── Generate keys ────────────────────────────────────────────
echo.
echo ============================================
echo   Generated secret keys (paste into .env)
echo ============================================
echo.
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('SENSOR_API_KEY=' + secrets.token_urlsafe(32))"
echo.

echo ============================================
echo   Setup complete!
echo.
echo   To start the server:
echo     cd server
echo     venv\Scripts\activate
echo     python app.py
echo.
echo   Then open: http://localhost:5000
echo.
echo   Default login: admin / Admin@FloodWatch2025!
echo   CHANGE THE PASSWORD AFTER FIRST LOGIN!
echo ============================================
pause
