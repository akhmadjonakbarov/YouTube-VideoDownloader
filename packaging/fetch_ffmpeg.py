"""Download a portable ffmpeg + ffprobe for the current OS/CPU, to bundle with the app.

    python packaging/fetch_ffmpeg.py [--dest build/ffmpeg] [--force]

Result layout (what the app expects inside the bundle):
    <dest>/bin/ffmpeg[.exe], <dest>/bin/ffprobe[.exe]  (+ shared libraries)
    <dest>/LICENSE.txt

Sources
  Windows / Linux: BtbN/FFmpeg-Builds, "latest" LGPL shared builds (smaller than static).
  macOS:           Martin Riedl's static builds (Apple Silicon and Intel).
Override any URL with the environment variable FFMPEG_URL (one archive containing
bin/ffmpeg and bin/ffprobe) if a source moves.
"""
import argparse
import os
import platform
import shutil
import ssl
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
RIEDL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release"

SOURCES = {
    ("windows", "x64"): [f"{BTBN}/ffmpeg-master-latest-win64-lgpl-shared.zip"],
    ("windows", "arm64"): [f"{BTBN}/ffmpeg-master-latest-winarm64-lgpl-shared.zip"],
    ("linux", "x64"): [f"{BTBN}/ffmpeg-master-latest-linux64-lgpl-shared.tar.xz"],
    ("linux", "arm64"): [f"{BTBN}/ffmpeg-master-latest-linuxarm64-lgpl-shared.tar.xz"],
    ("macos", "arm64"): [f"{RIEDL.format(arch='arm64')}/ffmpeg.zip", f"{RIEDL.format(arch='arm64')}/ffprobe.zip"],
    ("macos", "x64"): [f"{RIEDL.format(arch='amd64')}/ffmpeg.zip", f"{RIEDL.format(arch='amd64')}/ffprobe.zip"],
}


def current_target() -> tuple[str, str]:
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return system, arch


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("SSL_CERT_FILE"):  # e.g. behind a corporate proxy
        return ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    try:
        import certifi  # installed with yt-dlp[default]; python.org macOS builds lack system certs
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(url: str, target: Path) -> None:
    print(f"  downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "youtube-downloader-build"})
    with urllib.request.urlopen(request, context=_ssl_context(), timeout=300) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)


def extract(archive: Path, into: Path) -> None:
    if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(into)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(into, filter="tar") if hasattr(tarfile, "data_filter") else tf.extractall(into)


def _find(root: Path, name: str) -> Path | None:
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def collect(extracted: Path, dest: Path, system: str) -> None:
    exe = ".exe" if system == "windows" else ""
    ffmpeg = _find(extracted, f"ffmpeg{exe}")
    ffprobe = _find(extracted, f"ffprobe{exe}")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe not found in the downloaded archive")

    bin_dir = dest / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    src_bin = ffmpeg.parent
    if system == "windows":
        # Shared build: the .exe files and their DLLs sit together in bin/.
        for item in src_bin.iterdir():
            if item.suffix.lower() == ".dll" or item.name in (f"ffmpeg{exe}", f"ffprobe{exe}"):
                shutil.copy2(item, bin_dir / item.name)
    else:
        shutil.copy2(ffmpeg, bin_dir / ffmpeg.name)
        shutil.copy2(ffprobe, bin_dir / ffprobe.name)
        lib_dir = src_bin.parent / "lib"
        if lib_dir.is_dir():  # Linux shared build: binaries load ../lib via RUNPATH
            shutil.copytree(
                lib_dir, dest / "lib", symlinks=True, dirs_exist_ok=True,
                ignore=lambda _d, names: [n for n in names if n in ("pkgconfig",) or n.endswith((".a", ".la"))],
            )
        for binary in bin_dir.iterdir():  # zip files don't keep the executable bit
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    license_file = _find(extracted, "LICENSE.txt") or _find(extracted, "LICENSE")
    if license_file:
        shutil.copy2(license_file, dest / "LICENSE.txt")


def fetch(dest: Path, force: bool = False) -> Path:
    system, arch = current_target()
    exe = ".exe" if system == "windows" else ""
    if (dest / "bin" / f"ffmpeg{exe}").exists() and not force:
        print(f"ffmpeg already present in {dest}")
        return dest
    urls = [os.environ["FFMPEG_URL"]] if os.environ.get("FFMPEG_URL") else SOURCES.get((system, arch))
    if not urls:
        raise RuntimeError(f"No ffmpeg source configured for {system}/{arch}; set FFMPEG_URL")

    print(f"Fetching ffmpeg for {system}/{arch}")
    if dest.exists():
        shutil.rmtree(dest)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        extracted = tmp_path / "extracted"
        for i, url in enumerate(urls):
            name = url.rsplit("/", 1)[-1] or f"archive{i}"
            archive = tmp_path / f"{i}-{name}"
            download(url, archive)
            extract(archive, extracted / str(i))
        collect(extracted, dest, system)
    print(f"ffmpeg ready in {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=ROOT / "build" / "ffmpeg")
    parser.add_argument("--force", action="store_true", help="download again even if already present")
    args = parser.parse_args()
    fetch(args.dest, args.force)


if __name__ == "__main__":
    main()
