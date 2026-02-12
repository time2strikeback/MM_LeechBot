@echo off
REM MM_LeechBot - Windows Startup Script
REM Ensure Python 3.10+ is installed and in PATH

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing/Updating dependencies...
pip install -r requirements.txt

echo Running update script...
python update.py

echo Starting bot...
python -m bot
