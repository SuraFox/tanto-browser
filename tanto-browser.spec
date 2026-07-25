# -*- mode: python ; coding: utf-8 -*-
# Сборка onedir (не onefile): QtWebEngine в onefile каждый запуск
# распаковывает ~200 МБ и часто ломается. Работает и на Linux, и на Windows.

a = Analysis(
    ['tanto_browser.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['adblock', 'import_helium'],
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
    [],
    exclude_binaries=True,
    name='tanto-browser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='tanto-browser',
)
