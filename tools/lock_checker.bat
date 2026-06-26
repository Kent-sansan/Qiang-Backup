@echo off
chcp 65001 >nul
python "%~dp0lock_checker.py" %*
pause
