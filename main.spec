# -*- mode: python ; coding: utf-8 -*-

# PyInstaller spec for Drift Race Test
# - Bundles the entire `assets` directory (recursively)
# - Produces a windowed (no console) executable
# - Works for both one-folder (default via COLLECT) and can be switched to one-file by
#   replacing COLLECT with a BUNDLE, if desired

import sys
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import Tree

block_cipher = None

app_name = 'DriftRaceTest'

# Collect pygame submodules (including _sdl2 if present) to avoid missing imports.
hiddenimports = []
try:
    hiddenimports += collect_submodules('pygame')
except Exception:
    pass
try:
    hiddenimports += collect_submodules('pygame._sdl2')
except Exception:
    pass
# Ensure pkg_resources vendor/extern modules are included to avoid runtime errors
try:
    hiddenimports += collect_submodules('pkg_resources._vendor')
except Exception:
    pass
try:
    hiddenimports += collect_submodules('pkg_resources.extern')
except Exception:
    pass
# Some setuptools/pkg_resources configurations expect real 'jaraco' modules at runtime
try:
    hiddenimports += collect_submodules('jaraco')
except Exception:
    pass
# Add drift package modules
try:
    hiddenimports += collect_submodules('drift')
except Exception:
    pass


a = Analysis(
    ['src/drift/__main__.py'],
    # In spec files, __file__ is not defined; use current working directory instead.
    pathex=[os.getcwd(), os.path.join(os.getcwd(), 'src')],
    binaries=[],
    datas=[],  # add assets in COLLECT below using Tree(...)
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    # Ensure working directory is the executable folder to support relative asset loads
    runtime_hooks=[os.path.join('tools', 'set_cwd.py')],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed app (no console window)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# Default build: one-folder distribution with the assets directory copied next to the exe.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    Tree('assets', prefix='assets'),  # include entire assets directory next to the exe
    Tree('ai_models', prefix='ai_models'),  # include AI models directory
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)

# NOTE: If you prefer a single-file executable, comment-out COLLECT above and
# uncomment the BUNDLE section below. Keep the datas as-is; PyInstaller will
# extract them beside the executable in a temp folder at runtime, preserving
# ./assets relative paths used by the game.
#
# app = BUNDLE(
#     exe,
#     name=app_name + '.exe',
#     icon=None,
#     bundle_identifier=None,
# )
