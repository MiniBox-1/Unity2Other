@echo off
rem Command line (same protocol as the GUI). Examples:
rem   run_cli.bat list
rem   run_cli.bat run lo --input <char>.uAnim.prefab --out <dir>
setlocal
set "ROOT=%~dp0"
set "PY=%U2SPINE_PYTHON%"
if "%PY%"=="" set "PY=python"
cd /d "%ROOT%"
"%PY%" "%ROOT%main.py" --cli %*
