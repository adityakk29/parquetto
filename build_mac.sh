#!/usr/bin/env bash
set -euo pipefail

# Build a standalone Parquetto.app on macOS.
# Run this from a macOS machine with Python installed.

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller

python3 -m PyInstaller --onefile --windowed --name Parquetto \
  --icon assets/icon.icns \
  --add-data "assets/icon_128.png:assets" \
  main.py

echo
echo "Build complete. Find Parquetto.app in the dist folder."