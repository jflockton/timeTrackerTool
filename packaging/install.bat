@echo off
rem timeTrackerTool installer launcher - double-click me.
rem Runs the PowerShell installer with the execution policy bypassed so
rem recipients don't need to change any settings (or have Python).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
