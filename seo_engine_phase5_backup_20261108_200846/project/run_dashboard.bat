@echo off
setlocal
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m scripts.serve_dashboard
) else (
  python -m scripts.serve_dashboard
)
endlocal
