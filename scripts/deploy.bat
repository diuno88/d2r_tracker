@echo off
setlocal enabledelayedexpansion

set CONDA_ENV=d2r-tracker
for %%I in ("%~dp0..") do set TRACKER_DIR=%%~fI
set DIST_DIR=%TRACKER_DIR%\dist\D2R_Tracker
set EXE_OUT=%DIST_DIR%\D2R_Tracker.exe
set ZIP_OUT=%TRACKER_DIR%\dist\D2R_Tracker.zip

echo.
echo ============================================================
echo  D2R Tracker - Deploy Build
echo ============================================================
echo.

echo [1/6] conda env: %CONDA_ENV%
call conda activate %CONDA_ENV% 2>nul
if !errorlevel! neq 0 (
    echo      Not found. Creating python 3.11 env...
    call conda create -n %CONDA_ENV% python=3.11 -y
    if !errorlevel! neq 0 ( echo ERROR: conda create failed & pause & exit /b 1 )
    call conda activate %CONDA_ENV%
    if !errorlevel! neq 0 ( echo ERROR: conda activate failed & pause & exit /b 1 )
)
echo      OK

echo.
echo [2/6] Installing packages...
pip install -r "%TRACKER_DIR%\requirements.txt" -q
if !errorlevel! neq 0 ( echo ERROR: pip install requirements failed & pause & exit /b 1 )
pip install pyinstaller -q
if !errorlevel! neq 0 ( echo ERROR: pip install pyinstaller failed & pause & exit /b 1 )
echo      OK

echo.
echo [3/6] PyInstaller build...
pyinstaller "%TRACKER_DIR%\D2R_Tracker.spec" --noconfirm --clean --distpath "%TRACKER_DIR%\dist" --workpath "%TRACKER_DIR%\build"
if !errorlevel! neq 0 ( echo ERROR: PyInstaller exited with error & pause & exit /b 1 )
if not exist "%EXE_OUT%" (
    echo ERROR: Build finished but D2R_Tracker.exe not found
    echo        Check PyInstaller output above for details
    pause & exit /b 1
)
echo      OK

echo.
echo [4/5] Cleanup unnecessary bundled files...
set INTERNAL=%DIST_DIR%\_internal

rd /s /q "%INTERNAL%\pymupdf"           2>nul && echo      pymupdf\              removed
rd /s /q "%INTERNAL%\pypdfium2_raw"     2>nul && echo      pypdfium2_raw\        removed
rd /s /q "%INTERNAL%\hf_xet"            2>nul && echo      hf_xet\               removed
rd /s /q "%INTERNAL%\grpc"              2>nul && echo      grpc\                 removed
rd /s /q "%INTERNAL%\tessdata"          2>nul && echo      tessdata\             removed

if exist "%INTERNAL%\googleapiclient\discovery_cache\documents" (
    del /f /q "%INTERNAL%\googleapiclient\discovery_cache\documents\*.json" 2>nul
    echo      googleapiclient discovery JSON  removed
)

del /f /q "%INTERNAL%\cv2\opencv_videoio_ffmpeg4130_64.dll" 2>nul && echo      opencv_videoio_ffmpeg (video codec)  removed
del /f /q "%INTERNAL%\PIL\_avif.cp311-win_amd64.pyd"        2>nul && echo      PIL\_avif (AVIF codec)               removed

echo      OK

echo.
echo [5/6] Copying files...
if exist "%TRACKER_DIR%\icon\" (
    xcopy /e /i /y "%TRACKER_DIR%\icon" "%DIST_DIR%\icon\" > nul
    echo      icon\ - OK
) else ( echo      WARN: icon\ not found )
if exist "%TRACKER_DIR%\data\" (
    xcopy /e /i /y "%TRACKER_DIR%\data" "%DIST_DIR%\data\" > nul
    echo      data\ - OK
) else ( echo      WARN: data\ not found )

echo.
echo [6/6] Creating ZIP...
powershell -NoProfile -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ZIP_OUT%' -Force"
if !errorlevel! neq 0 ( echo ERROR: ZIP creation failed & pause & exit /b 1 )
for %%F in ("%ZIP_OUT%") do set ZIP_SIZE=%%~zF
set /a ZIP_MB=!ZIP_SIZE! / 1048576
echo      OK  (!ZIP_MB! MB)

echo.
echo ============================================================
echo  Done
echo  Folder : %DIST_DIR%
echo  ZIP    : %ZIP_OUT%
echo ============================================================
echo.
pause