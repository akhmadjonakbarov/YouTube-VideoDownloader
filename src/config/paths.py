"""Locating files both when running from source and inside a packaged (PyInstaller) build."""
import sys
from pathlib import Path

# Project root when running from source (src/config/paths.py -> project root).
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, e.g. resource_path("assets", "icon.png").

    In a PyInstaller build, resources live in sys._MEIPASS (the `_internal`
    folder on Windows/Linux, `Contents/Frameworks` in a macOS .app).
    """
    base = Path(getattr(sys, "_MEIPASS", _SOURCE_ROOT))
    return base.joinpath(*parts)
