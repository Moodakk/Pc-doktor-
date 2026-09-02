# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

pydicom_data, pydicom_binaries, pydicom_hidden = collect_all("pydicom")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=pydicom_binaries,
    datas=pydicom_data,
    hiddenimports=pydicom_hidden + ["send2trash.plat_win"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DentalArchiveManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
