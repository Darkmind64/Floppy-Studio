@echo off
rem Construit Floppy Studio :
rem   dist\FloppyStudio.exe                  version portable (un seul fichier)
rem   installer\FloppyStudio_Setup_X.Y.Z.exe installateur (Inno Setup 6)
cd /d "%~dp0"
set PY=python
where python >nul 2>&1 || set PY=py -3
for /f %%v in ('%PY% -c "import fstudio; print(fstudio.__version__)"') do set VER=%%v
echo Version %VER%
%PY% -m pip install --upgrade pyinstaller capstone >nul
set COMMON=--noconfirm --clean --windowed --name FloppyStudio --icon icon.ico --add-data "icon.ico;." --add-data "fstudio\assets;fstudio\assets" --collect-data greaseweazle --collect-submodules greaseweazle --hidden-import serial.tools.list_ports --hidden-import PySide6.QtMultimedia --collect-all capstone

echo [1/3] Version portable...
%PY% -m PyInstaller %COMMON% --onefile floppy_studio.py
if errorlevel 1 (echo ECHEC du build portable & exit /b 1)

echo [2/3] Version installable...
%PY% -m PyInstaller %COMMON% --onedir --distpath dist_setup --workpath build\setup floppy_studio.py
if errorlevel 1 (echo ECHEC du build installable & exit /b 1)

echo [3/3] Installateur...
set ISCC=
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if "%ISCC%"=="" (echo Inno Setup 6 introuvable : installateur non construit & exit /b 0)
"%ISCC%" /Q /DAppVer=%VER% installer.iss
if errorlevel 1 (echo ECHEC de l'installateur & exit /b 1)
echo.
echo OK : dist\FloppyStudio.exe et installer\FloppyStudio_Setup_%VER%.exe
