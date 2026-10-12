# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for DullE
# Build with: uv run pyinstaller dulle.spec
# Output:     dist/dulle.exe

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['src/dulle/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        # Bundle the example config so first-time users see it
        ('.env.example', '.'),
        ('knowledge.yaml', '.'),
    ],
    hiddenimports=[
        # pydantic-settings needs these
        'pydantic_settings',
        'pydantic_settings.main',
        # pyautogui platform backends
        'pyautogui',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # mss Windows backend
        'mss.windows',
        # loguru
        'loguru',
        # yaml
        'yaml',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Strip test frameworks and unused heavy packages
        'pytest',
        'IPython',
        'matplotlib',
        'numpy',
        'pandas',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dulle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # Compress — reduces size by ~30%
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # Keep console visible (it's a CLI tool)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='Resources/dulle.ico',  # Uncomment and add an icon file to use one
)
