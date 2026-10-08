@echo off
setlocal
cd /d "%~dp0"

set "PY_EXE=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\pythonw.exe"
if not exist "%PY_EXE%" (
    set "PY_EXE=pythonw"
)

start "" "%PY_EXE%" main.py --now
