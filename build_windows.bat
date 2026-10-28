@echo off
REM Build FreeCAD_Smart_Launcher.exe (run from a normal cmd/PowerShell, Python 3.9+ required)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-windows.txt
pyinstaller --noconfirm --clean freecad_smart_launcher_windows.spec
echo.
echo Done: dist\FreeCAD_Smart_Launcher.exe
