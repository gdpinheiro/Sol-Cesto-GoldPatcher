@echo off
setlocal enabledelayedexpansion
title SolCesto Gold Patcher
cls

echo.
echo  ==============================================
echo   SolCesto Gold Patcher
echo  ==============================================
echo.
echo  Patches your gold value in SolCesto.
echo  Your original save files are backed up to
echo  .\backup\ before anything is modified.
echo.
echo  Press Ctrl+C at any time to cancel.
echo  ----------------------------------------------
echo.

:: STEP 1 - Current gold
echo  STEP 1 of 3
echo  -----------
echo  Enter your current gold amount exactly as
echo  shown in-game.
echo.
set /p CURRENT_GOLD=  Current gold: 

if "!CURRENT_GOLD!"=="" (
    echo.
    echo  [ERROR] No value entered. Please restart.
    pause
    exit /b 1
)

echo.

:: STEP 2 - Target gold
echo  STEP 2 of 3
echo  -----------
echo  Enter the gold amount you want after patching.
echo.
echo  Rules:
echo    - Must end in 0  (e.g. 10, 20, 50, 60, 100)
echo    - Must be in the same range as current gold:
echo        Current  1-63   =^>  Target must be 10-60
echo        Current 64-8191 =^>  Target must be 70-8190
echo.
set /p TARGET_GOLD=  Target gold: 

if "!TARGET_GOLD!"=="" (
    echo.
    echo  [ERROR] No value entered. Please restart.
    pause
    exit /b 1
)

:: Check last digit is 0 using string slice (no arithmetic needed)
set LAST_DIGIT=!TARGET_GOLD:~-1!
if not "!LAST_DIGIT!"=="0" (
    echo.
    echo  [ERROR] Target gold must end in 0.
    echo          You entered: !TARGET_GOLD!
    echo.
    pause
    exit /b 1
)

echo.

:: STEP 3 - Save directory (optional)
echo  STEP 3 of 3
echo  -----------
echo  Save directory path (optional).
echo  Press Enter to auto-detect from %%LOCALAPPDATA%%.
echo.
echo  Only needed if auto-detect failed before.
echo  Paste the full path to your .indexeddb.leveldb folder.
echo.
set SAVE_DIR=
set /p SAVE_DIR=  Save dir (Enter to skip): 

echo.

:: Confirm
echo  ----------------------------------------------
echo   Review your settings
echo  ----------------------------------------------
echo   Current gold : !CURRENT_GOLD!
echo   Target gold  : !TARGET_GOLD!
if "!SAVE_DIR!"=="" (
    echo   Save dir     : (auto-detect)
) else (
    echo   Save dir     : !SAVE_DIR!
)
echo  ----------------------------------------------
echo.
set /p CONFIRM=  Looks correct? Type Y and press Enter: 

if /i not "!CONFIRM!"=="Y" (
    echo.
    echo  Cancelled. No files were modified.
    pause
    exit /b 0
)

echo.
echo  Starting patcher...
echo.

:: Run Python script
if "!SAVE_DIR!"=="" (
    python gold_patcher.py --current-gold !CURRENT_GOLD! --target-gold !TARGET_GOLD!
) else (
    python gold_patcher.py --current-gold !CURRENT_GOLD! --target-gold !TARGET_GOLD! --save-dir "!SAVE_DIR!"
)

set EXIT_CODE=!ERRORLEVEL!

echo.
if "!EXIT_CODE!"=="0" (
    echo  ============================================
    echo   Done!
    echo   Patched files are in .\save\
    echo   Originals are safely in .\backup\
    echo  ============================================
) else (
    echo  ============================================
    echo   Something went wrong.
    echo   See the message above for details.
    echo   Your original files are in .\backup\
    echo  ============================================
)

echo.
pause
endlocal
