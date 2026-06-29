@echo off
echo ================================================
echo  D2R Traderie Tracker - Install
echo ================================================
echo.

echo [1/3] Installing Python packages...
pip install -r "%~dp0..\requirements.txt"
if %errorlevel% neq 0 (
    echo ERROR: pip install failed
    pause & exit /b 1
)

echo.
echo [2/3] Installing node_worker packages...
cd "%~dp0..\node_worker"
npm install
if %errorlevel% neq 0 (
    echo ERROR: npm install failed - check Node.js is installed
    pause & exit /b 1
)
cd "%~dp0.."

echo.
echo [3/3] Downloading Tesseract language data...
set TRAINEDDATA_URL=https://github.com/naptha/tessdata/releases/download/4.0.0
set TRAINEDDATA_DIR=%~dp0..\node_worker

if not exist "%TRAINEDDATA_DIR%\kor.traineddata" (
    echo Downloading kor.traineddata ...
    curl -L -o "%TRAINEDDATA_DIR%\kor.traineddata" "%TRAINEDDATA_URL%/kor.traineddata.gz" --fail
    if %errorlevel% neq 0 (
        echo ERROR: Failed to download kor.traineddata
        pause & exit /b 1
    )
    echo Extracting kor.traineddata ...
    powershell -Command "& { Add-Type -Assembly System.IO.Compression.FileSystem; $src='%TRAINEDDATA_DIR%\kor.traineddata'; $tmp='%TRAINEDDATA_DIR%\kor.traineddata.gz'; Rename-Item $src $tmp; $in=[System.IO.File]::OpenRead($tmp); $out=[System.IO.File]::Create($src); $gz=New-Object System.IO.Compression.GZipStream($in,[System.IO.Compression.CompressionMode]::Decompress); $gz.CopyTo($out); $gz.Close(); $in.Close(); $out.Close(); Remove-Item $tmp }"
) else (
    echo kor.traineddata already exists, skipping.
)

if not exist "%TRAINEDDATA_DIR%\eng.traineddata" (
    echo Downloading eng.traineddata ...
    curl -L -o "%TRAINEDDATA_DIR%\eng.traineddata" "%TRAINEDDATA_URL%/eng.traineddata.gz" --fail
    if %errorlevel% neq 0 (
        echo ERROR: Failed to download eng.traineddata
        pause & exit /b 1
    )
    echo Extracting eng.traineddata ...
    powershell -Command "& { Add-Type -Assembly System.IO.Compression.FileSystem; $src='%TRAINEDDATA_DIR%\eng.traineddata'; $tmp='%TRAINEDDATA_DIR%\eng.traineddata.gz'; Rename-Item $src $tmp; $in=[System.IO.File]::OpenRead($tmp); $out=[System.IO.File]::Create($src); $gz=New-Object System.IO.Compression.GZipStream($in,[System.IO.Compression.CompressionMode]::Decompress); $gz.CopyTo($out); $gz.Close(); $in.Close(); $out.Close(); Remove-Item $tmp }"
) else (
    echo eng.traineddata already exists, skipping.
)

echo.
echo ================================================
echo  Install complete. Run run.bat to start.
echo ================================================
pause
