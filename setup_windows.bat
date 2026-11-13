@echo off
setlocal
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python tools\download_models.py
if not exist .env copy .env.example .env
echo.
echo Setup complete.
echo Run: run_windows.bat
pause
