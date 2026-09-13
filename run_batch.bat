@echo off
REM Double-click to open Nano Batch Studio.
cd /d "%~dp0"
python nano_batch.py
if errorlevel 1 pause
