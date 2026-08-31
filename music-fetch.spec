# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the music-fetch terminal app (single-file executable)."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ['music_fetch/app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen.mp4',
        'mutagen.flac',
        # Prompt_toolkit loads many submodules lazily; pin the important ones.
        'prompt_toolkit',
        'prompt_toolkit.formatted_text',
        'prompt_toolkit.layout',
        'prompt_toolkit.shortcuts',
        'prompt_toolkit.styles',
        'prompt_toolkit.key_binding',
        'prompt_toolkit.renderer',
        'prompt_toolkit.lexers',
        'prompt_toolkit.completion',
        'prompt_toolkit.history',
        'prompt_toolkit.filters',
        'prompt_toolkit.cursor_shapes',
        # eapi transport encryption (kept for future encrypted endpoints).
        'Crypto',
        'Crypto.Cipher',
        'Crypto.Cipher.AES',
        # Proxy support loads Requests and its SOCKS transport at runtime.
        'requests',
        'socks',
        'urllib3.contrib.socks',
        # Browser login (browser_login.py) lazily imports websocket-client.
        'websocket',
        'websocket._core',
        'websocket._abnf',
        'websocket._handshake',
        'websocket._http',
        'websocket._socket',
        'websocket._url',
        'websocket._utils',
        # wcwidth (CJK-safe table alignment in the TUI).
        'wcwidth',
    ] + collect_submodules('prompt_toolkit.filters'),
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
    console=True,
    icon=None,
)
