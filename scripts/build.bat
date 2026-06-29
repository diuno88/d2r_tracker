@echo off
setlocal enabledelayedexpansion

set CONDA_ENV=d2r-tracker
set TRACKER_DIR=%~dp0..\
set DIST_DIR=%TRACKER_DIR%dist\D2R_Tracker

echo ================================================
echo  D2R Traderie Tracker - Build Script
echo ================================================
echo.

:: Step 1: Activate conda env
echo [1/6] Activating conda env: %CONDA_ENV%
call conda activate %CONDA_ENV%
if %errorlevel% neq 0 (
    echo WARN: conda activate failed, continuing with current env...
)

:: Step 2: Install Python packages
echo.
echo [2/6] Installing Python packages...
pip install -r "%TRACKER_DIR%requirements.txt" -q
pip install pyinstaller -q
if %errorlevel% neq 0 (
    echo ERROR: pip install failed
    pause & exit /b 1
)

:: Step 3: npm install for node_worker
echo.
echo [3/6] Installing node_worker packages...
cd "%TRACKER_DIR%node_worker"
if not exist node_modules (
    npm install
    if %errorlevel% neq 0 (
        echo ERROR: npm install failed
        pause & exit /b 1
    )
) else (
    echo       node_modules already exists, skipping...
)
cd "%TRACKER_DIR%"

:: Step 4: PyInstaller build
echo.
echo [4/6] Running PyInstaller...
if exist "%TRACKER_DIR%dist" rmdir /s /q "%TRACKER_DIR%dist"
if exist "%TRACKER_DIR%build" rmdir /s /q "%TRACKER_DIR%build"

pyinstaller "%TRACKER_DIR%D2R_Tracker.spec" --noconfirm
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller build failed
    pause & exit /b 1
)
echo       Build done: dist\D2R_Tracker\

:: Step 5: Copy node_worker
echo.
echo [5/6] Copying node_worker...
xcopy /e /i /q "%TRACKER_DIR%node_worker" "%DIST_DIR%\node_worker"

:: Step 6: Copy tessdata
echo.
echo [6/6] Copying tessdata...
if not exist "%DIST_DIR%\tessdata" mkdir "%DIST_DIR%\tessdata"
copy /y "%TRACKER_DIR%..\extension\data\kor.traineddata.gz" "%DIST_DIR%\tessdata\" > nul 2>&1
copy /y "%TRACKER_DIR%..\extension\data\eng.traineddata.gz" "%DIST_DIR%\tessdata\" > nul 2>&1

echo.
echo ================================================
echo  Build complete: dist\D2R_Tracker\
echo ================================================
echo.
echo  [Manual step] Portable Node.js
echo  - Download node-v22.x.x-win-x64.zip from nodejs.org
echo  - Copy node.exe to: dist\D2R_Tracker\node\node.exe
echo ================================================
echo.

:: Copy icon
copy /y "%TRACKER_DIR%icon.ico" "%DIST_DIR%" > nul 2>&1

:: Copy user manual PDF
copy /y "%TRACKER_DIR%..\docs\tracker\사용자메뉴열.pdf" "%DIST_DIR%" > nul 2>&1

:: Create ZIP
set /p MAKE_ZIP=Create ZIP package? (y/n):
if /i "%MAKE_ZIP%"=="y" (
    echo Creating ZIP...
    powershell -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%TRACKER_DIR%dist\D2R_Tracker.zip' -Force"
    if %errorlevel% equ 0 (
        echo Done: dist\D2R_Tracker.zip
    ) else (
        echo ERROR: ZIP creation failed
    )
)

echo.
pause
