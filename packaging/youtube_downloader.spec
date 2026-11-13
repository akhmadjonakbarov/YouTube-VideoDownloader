# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for YouTube Downloader. Run it through packaging/build.py, which
# also bundles ffmpeg and makes the installer/archive for the current OS.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
APP_NAME = "YouTube Downloader"
EXE_NAME = "YouTubeDownloader"
VERSION = os.environ.get("APP_VERSION", "0.1.0")
BUNDLE_ID = "com.akhmadjonakbarov.youtubedownloader"

ASSETS = ROOT / "assets"
icon = str(ASSETS / ("icon.ico" if sys.platform == "win32" else "icon.icns"))

datas = collect_data_files("customtkinter")  # themes and fonts
datas += [(str(ASSETS / name), "assets") for name in ("icon.png", "icon-256.png", "icon.ico")]
datas += [(str(ASSETS / "fonts"), "assets/fonts")]  # Inter (OFL): artwork text, and the UI font on Linux

a = Analysis(
    [str(ROOT / "src" / "app.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    # Pillow loads this lazily when drawing images in Tk; PyInstaller misses it.
    # (yt-dlp ships its own PyInstaller hook, so it needs nothing here.)
    hiddenimports=["PIL._tkinter_finder"],
    excludes=["pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    console=False,             # GUI app: no terminal window
    icon=icon,
    upx=False,
    target_arch=None,          # build for the CPU of the machine running the build
)

coll = COLLECT(exe, a.binaries, a.datas, name=EXE_NAME, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon,
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # allow dark mode
        },
    )
