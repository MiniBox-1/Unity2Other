@echo off
rem Open the GUI. Path-independent: project root from %~dp0, python from PATH
rem (override with U2SPINE_PYTHON, e.g. set U2SPINE_PYTHON=D:\Anconda\python.exe).
setlocal
set "ROOT=%~dp0"
set "PY=%U2SPINE_PYTHON%"
if "%PY%"=="" set "PY=python"
cd /d "%ROOT%"
"%PY%" "%ROOT%main.py" %*
