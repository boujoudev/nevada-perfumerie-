@echo off
rem Lance l'application en mode développement (sans console).
cd /d "%~dp0"
if not exist .venv (
    echo Premiere utilisation : installation des dependances...
    py -3 -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" main.py
