@echo off
cd /d "%~dp0"
echo Installation des dependances...
py -3.13 -m pip install PySide6 pyinstaller
echo.
set "ICON="
if exist kinesis.ico set "ICON=--icon kinesis.ico"
echo Generation de l'application (cela peut prendre plusieurs minutes)...
py -3.13 -m PyInstaller --noconfirm --windowed --name Kinesis %ICON% --add-data "assets;assets" kinesis.py
echo.
echo Termine : dist\Kinesis\Kinesis.exe
pause
