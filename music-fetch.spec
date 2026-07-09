# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for music-fetch standalone single-file executable."""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['music_fetch/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen.mp4',
        'mutagen.flac',
        'qt_material',
        'qt_material.resources',
        # Project modules imported lazily inside functions (PyInstaller can't
        # detect them via static analysis).
        'music_fetch.search_dialog',
        'music_fetch.playlist_dialog',
        'music_fetch.batch_inputs',
        'music_fetch.batch_dialogs',
        # PySide6 WebEngine — imported in try/except blocks, may be skipped.
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'pydoc'],
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
    name='music-fetch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=None,
)