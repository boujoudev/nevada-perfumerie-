@echo off
rem ============================================================
rem  Construit GestionParfumerie.exe (a lancer sur Windows)
rem  Resultat : dist\GestionParfumerie\GestionParfumerie.exe
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo [1/4] Environnement Python...
if not exist .venv py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto erreur

echo [2/4] Tests automatiques...
python -m unittest discover -s tests
if errorlevel 1 goto erreur

echo [3/4] Nettoyage...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/4] Construction de l'application...
pyinstaller --noconfirm --clean --windowed --name GestionParfumerie ^
    --icon assets\icone.ico ^
    --collect-all customtkinter ^
    --hidden-import openpyxl ^
    --add-data "database\schema.sql;database" ^
    --add-data "assets;assets" ^
    main.py
if errorlevel 1 goto erreur

echo.
echo ==== TERMINE ====
echo Application : dist\GestionParfumerie\GestionParfumerie.exe
echo (Optionnel) Installateur : ouvrez installer.iss avec Inno Setup puis Build ^> Compile
pause
exit /b 0

:erreur
echo.
echo ==== ECHEC : lisez le message d'erreur ci-dessus ====
pause
exit /b 1
