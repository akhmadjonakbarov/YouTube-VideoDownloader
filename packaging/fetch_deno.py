"""Download the Deno JavaScript runtime for the current OS/CPU, to bundle with the app.

    python packaging/fetch_deno.py [--dest build/deno] [--force]

yt-dlp needs a JavaScript runtime (Deno is the recommended one) to solve
YouTube's JS challenges. Source: official Deno releases on GitHub.
Result: <dest>/deno[.exe] and <dest>/LICENSE.md
"""
import argparse
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from fetch_ffmpeg import ROOT, current_target, download

BASE = "https://github.com/denoland/deno/releases/latest/download"
TARGETS = {
    ("windows", "x64"): "x86_64-pc-windows-msvc",
    ("macos", "arm64"): "aarch64-apple-darwin",
    ("macos", "x64"): "x86_64-apple-darwin",
    ("linux", "x64"): "x86_64-unknown-linux-gnu",
    ("linux", "arm64"): "aarch64-unknown-linux-gnu",
}
LICENSE_URL = "https://raw.githubusercontent.com/denoland/deno/main/LICENSE.md"


def fetch(dest: Path, force: bool = False) -> Path:
    system, arch = current_target()
    exe = "deno.exe" if system == "windows" else "deno"
    if (dest / exe).exists() and not force:
        print(f"Deno already present in {dest}")
        return dest
    url = os.environ.get("DENO_URL")
    if not url:
        triple = TARGETS.get((system, arch))
        if not triple:
            raise RuntimeError(f"No Deno build configured for {system}/{arch}; set DENO_URL")
        url = f"{BASE}/deno-{triple}.zip"

    print(f"Fetching Deno for {system}/{arch}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "deno.zip"
        download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extract(exe, dest)
    binary = dest / exe
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    try:
        download(LICENSE_URL, dest / "LICENSE.md")
    except Exception:  # the license file is nice to ship, not essential to the build
        pass
    print(f"Deno ready in {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=ROOT / "build" / "deno")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    fetch(args.dest, args.force)


if __name__ == "__main__":
    main()
