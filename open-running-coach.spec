# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Coach Running.

Build on each target OS (PyInstaller does not cross-compile):

    .venv/bin/pip install pyinstaller
    .venv/bin/pyinstaller open-running-coach.spec

Output: ``dist/CoachRunning/`` (and ``CoachRunning.app`` on macOS).
User data lives in ``~/CoachRunning`` (see app/config.py).
"""
import sys

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + collect_submodules("starlette")
)

datas = [("app/static", "static")]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CoachRunning",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="CoachRunning",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="CoachRunning.app",
        bundle_identifier="local.coachrunning",
        icon=None,
    )
