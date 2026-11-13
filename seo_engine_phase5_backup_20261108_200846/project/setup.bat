@echo off
setlocal
cd /d %~dp0

echo Creating virtual environment...
where py >nul 2>&1
if not errorlevel 1 (
    py -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto :error

echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

REM Keep the pip version bundled with the venv; Windows pip self-upgrade can corrupt it.
echo Installing Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Playwright browser download skipped.
echo The project is configured to use an existing Chrome or Edge installation.
echo.
echo Setup complete.
echo Next: edit .env and add your DataForSEO API login and password.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the error above.
pause
exit /b 1
