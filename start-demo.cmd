@echo off
cd /d "%~dp0"
python "%~dp0start_demo.py"
if errorlevel 1 pause
