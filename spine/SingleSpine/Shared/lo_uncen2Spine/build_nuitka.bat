@echo off
rem ===========================================================================
rem  lo_uncen2Spine packaging (Nuitka).  See docs\GUI与CLI使用说明.md section 6.
rem
rem  1) Do NOT build with Anaconda python: Nuitka's pyside6 plugin crashes on
rem     conda-meta (KeyError: 'files').  Use a standalone interpreter:
rem         uv venv --python 3.13 --python-preference only-managed env\.venv-build
rem         uv pip install --python env\.venv-build\Scripts\python.exe nuitka PySide6 Pillow numpy
rem         set U2SPINE_PYTHON=%CD%\env\.venv-build\Scripts\python.exe
rem  2) This machine refuses to create files named msvcp140.dll /
rem     vcruntime140*.dll directly (EACCES; other names are fine, rename works),
rem     so we exclude them here and add them back afterwards with
rem     src\tools\fix_dist_runtime_dlls.py (temp name + rename).
rem  3) The two extension libs must be included explicitly: in a frozen app there
rem     are no entry-point dist-infos, so discover() falls back to importing the
rem     packages by name (unity2spine.api.plugin.FALLBACK_MODULES).
rem
rem  Output: dist\main.dist\lo_uncen2Spine.exe (double-click, or --cli list).
rem ===========================================================================
setlocal
set "ROOT=%~dp0"
set "PY=%U2SPINE_PYTHON%"
if "%PY%"=="" set "PY=python"
cd /d "%ROOT%"
rem Code lives in src\ -> make the packages findable for Nuitka's analysis
rem (the frozen app resolves them from the bundled module tree).
set "PYTHONPATH=%ROOT%src"
"%PY%" -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --enable-plugin=pyside6 ^
  --include-package=unity2spine ^
  --include-package=unity2spine_compat ^
  --include-package=ngui2spine ^
  --include-package=ext_bdone ^
  --include-package=ext_lo ^
  --include-data-files=.u2s_root=.u2s_root ^
  --include-data-files=config\lo_uncen2Spine.json=config\lo_uncen2Spine.json ^
  --include-data-files=config\per_char_env.txt=config\per_char_env.txt ^
  --include-data-files=src\tools\static_check.py=src\tools\static_check.py ^
  --include-data-files=src\tools\face_check.py=src\tools\face_check.py ^
  --noinclude-dlls=msvcp140.dll ^
  --noinclude-dlls=msvcp140_1.dll ^
  --noinclude-dlls=msvcp140_2.dll ^
  --noinclude-dlls=msvcp140_codecvt_ids.dll ^
  --noinclude-dlls=vcruntime140.dll ^
  --noinclude-dlls=vcruntime140_1.dll ^
  --windows-console-mode=disable ^
  --output-dir=dist ^
  --output-filename=lo_uncen2Spine.exe ^
  main.py
"%PY%" "%ROOT%src\tools\fix_dist_runtime_dlls.py" "%ROOT%dist\main.dist"
