@echo off
cd /d "%~dp0.."

set CONDA_PYTHON=%USERPROFILE%\miniconda3\envs\d2r-tracker\pythonw.exe
set CONDA_PYTHON2=%USERPROFILE%\anaconda3\envs\d2r-tracker\pythonw.exe

if exist "%CONDA_PYTHON%" (
    "%CONDA_PYTHON%" main.py
) else if exist "%CONDA_PYTHON2%" (
    "%CONDA_PYTHON2%" main.py
) else (
    pythonw main.py
)

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Run install.bat first if not installed.
    pause
)
