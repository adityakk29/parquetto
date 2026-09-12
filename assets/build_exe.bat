@echo off
REM Build a standalone Parquetto.exe on Windows.
REM Run this from a Windows machine with Python installed (python.org or Microsoft Store).

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onefile --windowed --name Parquetto --icon assets\icon.ico --add-data "assets\icon_128.png;assets" main.py

echo.
echo Build complete. Find Parquetto.exe in the "dist" folder.
pause
