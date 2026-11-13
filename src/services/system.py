"""Open files and folders with the operating system's default apps."""
import os
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - Windows only
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_folder(path: Path) -> None:
    """Show the file selected in Finder / Explorer (or open its folder on Linux)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        open_path(path.parent)
