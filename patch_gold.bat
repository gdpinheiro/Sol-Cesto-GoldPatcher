@echo off
setlocal enabledelayedexpansion
title SolCesto Gold Patcher

:: Install customtkinter if missing
python -c "import customtkinter" 2>nul
if errorlevel 1 (
    echo Installing customtkinter...
    python -m pip install customtkinter --quiet
)
python -c "import PIL" 2>nul
if errorlevel 1 (
    echo Installing Pillow...
    python -m pip install pillow --quiet
)

pythonw gold_patcher_gui.py
endlocal
