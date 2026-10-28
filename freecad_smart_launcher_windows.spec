# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("py7zr",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Embarquer les icônes dans l'exe
datas += [
    ("icon.png", "."),
    ("icon.ico", "."),
]

a = Analysis(
    ["freecad_smart_launcher_windows.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="FreeCAD_Smart_Launcher",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="icon.ico",
)