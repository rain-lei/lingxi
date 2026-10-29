@echo off
cd /d "%~dp0"
if exist "D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe" (
  "D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe" "%~dp0run_companion.py"
) else (
  python "%~dp0run_companion.py"
)
if errorlevel 1 pause
