@echo off
setlocal
cd /d %~dp0

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 goto :error

echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 goto :error

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :error

echo Installing Python packages...
pip install -r requirements.txt
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
