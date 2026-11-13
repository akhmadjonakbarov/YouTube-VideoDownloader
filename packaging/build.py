"""Build a ready-to-share app for the OS this script runs on.

    uv run --group build python packaging/build.py [--version 1.2.3] [--no-ffmpeg]

PyInstaller can't cross-compile, so run this once on each OS (the GitHub Actions
workflow in .github/workflows/build.yml does that for you). Output in dist/release/:

  macOS    YouTube-Downloader-<ver>-macos-<arch>.dmg       (drag-to-Applications disk image)
  Windows  YouTube-Downloader-<ver>-windows-<arch>-setup.exe  (if Inno Setup is installed)
           YouTube-Downloader-<ver>-windows-<arch>.zip      (portable)
ffmpeg and Deno (needed by yt-dlp for YouTube) are downloaded and bundled automatically.
  Linux    YouTube-Downloader-<ver>-linux-<arch>.tar.gz     (with install.sh + .desktop entry)
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
RELEASE = DIST / "release"
WORK = ROOT / "build"
FFMPEG_DIR = WORK / "ffmpeg"
DENO_DIR = WORK / "deno"

APP_NAME = "YouTube Downloader"
EXE_NAME = "YouTubeDownloader"
SLUG = "YouTube-Downloader"

sys.path.insert(0, str(PACKAGING))
import fetch_deno  # noqa: E402
import fetch_ffmpeg  # noqa: E402
import make_icons  # noqa: E402


def run(cmd: list[str], **kwargs) -> None:
    print("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def project_version() -> str:
    import tomllib
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]


def target() -> tuple[str, str]:
    return fetch_ffmpeg.current_target()


# --------------------------------------------------------------------------- steps

def ensure_icons() -> None:
    needed = ["icon.png", "icon-256.png", "icon.ico", "icon.icns"]
    if not all((ROOT / "assets" / name).exists() for name in needed):
        make_icons.main()


def run_pyinstaller(version: str) -> None:
    env = {**os.environ, "APP_VERSION": version}
    run([sys.executable, "-m", "PyInstaller", PACKAGING / "youtube_downloader.spec",
         "--noconfirm", "--clean", "--distpath", DIST, "--workpath", WORK / "pyinstaller"], env=env)


def resources_dir(system: str) -> Path:
    """Where sys._MEIPASS points inside the built app (see src/config/paths.py)."""
    if system == "macos":
        return DIST / f"{APP_NAME}.app" / "Contents" / "Frameworks"
    return DIST / EXE_NAME / "_internal"


def warn(message: str) -> None:
    print(f"\nWARNING: {message}\n")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::{message}")  # shows on the workflow summary page


# Helper tools bundled next to the app: name -> (fetch module, download folder, env var to override the URL)
TOOLS = {
    "ffmpeg": (fetch_ffmpeg, FFMPEG_DIR, "FFMPEG_URL"),
    "deno": (fetch_deno, DENO_DIR, "DENO_URL"),
}


def get_tool(name: str, required: bool) -> bool:
    module, folder, env_var = TOOLS[name]
    try:
        module.fetch(folder)
        return True
    except Exception as e:  # network/source problems shouldn't block the whole build...
        if required:
            raise
        warn(f"Could not download {name} ({e}). Building WITHOUT bundled {name}: users will need "
             f"to install it themselves. Set {env_var} to another download URL to fix this.")
        return False


def bundle_tool(name: str, system: str) -> None:
    _module, folder, _env = TOOLS[name]
    dest = resources_dir(system) / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(folder, dest, symlinks=True)
    print(f"Bundled {name} into {dest}")


def package_macos(version: str, arch: str) -> list[Path]:
    app = DIST / f"{APP_NAME}.app"
    # Ad-hoc signature (required on Apple Silicon after adding files to the bundle).
    # For distribution without Gatekeeper warnings, sign with a Developer ID and notarize.
    identity = os.environ.get("MACOS_SIGN_IDENTITY", "-")
    # Sign the bundled helper executables first, then the app itself.
    frameworks = app / "Contents" / "Frameworks"
    helpers = [p for p in (frameworks / "ffmpeg" / "bin").glob("*") if p.is_file()]
    helpers += [p for p in [frameworks / "deno" / "deno"] if p.is_file()]
    for helper in helpers:
        run(["codesign", "--force", "--sign", identity, helper])
    run(["codesign", "--force", "--deep", "--sign", identity, app])

    staging = WORK / "dmg"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")

    dmg = RELEASE / f"{SLUG}-{version}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", staging, "-ov", "-format", "UDZO", dmg])
    return [dmg]


def package_windows(version: str, arch: str) -> list[Path]:
    outputs = []
    folder = DIST / EXE_NAME
    portable = RELEASE / f"{SLUG}-{version}-windows-{arch}.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            zf.write(path, Path(SLUG) / path.relative_to(folder))
    outputs.append(portable)

    iscc = shutil.which("iscc") or next(
        (p for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                     Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe") if p.exists()),
        None,
    )
    if iscc:
        run([iscc, f"/DAppVersion={version}", f"/DSourceDir={folder}", f"/DOutputDir={RELEASE}",
             f"/DOutputName={SLUG}-{version}-windows-{arch}-setup", f"/DIconFile={ROOT / 'assets' / 'icon.ico'}",
             f"/DArch={arch}", PACKAGING / "windows" / "installer.iss"])
        outputs.append(RELEASE / f"{SLUG}-{version}-windows-{arch}-setup.exe")
    else:
        print("Inno Setup not found: skipping the installer (the portable .zip was still built).")
    return outputs


def package_linux(version: str, arch: str) -> list[Path]:
    folder = DIST / EXE_NAME
    linux_files = PACKAGING / "linux"
    shutil.copy2(ROOT / "assets" / "icon-256.png", folder / "youtube-downloader.png")
    shutil.copy2(linux_files / "youtube-downloader.desktop", folder / "youtube-downloader.desktop")
    shutil.copy2(linux_files / "install.sh", folder / "install.sh")
    (folder / "install.sh").chmod(0o755)

    archive = RELEASE / f"{SLUG}-{version}-linux-{arch}.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(folder, arcname=f"{SLUG}-{version}")
    return [archive]


# ---------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="version to stamp on the build (default: pyproject.toml)")
    parser.add_argument("--no-ffmpeg", action="store_true", help="don't bundle ffmpeg (users must install it)")
    parser.add_argument("--no-deno", action="store_true", help="don't bundle Deno (users must install it)")
    parser.add_argument("--strict", action="store_true",
                        help="fail instead of warning if ffmpeg or Deno can't be downloaded")
    args = parser.parse_args()

    version = (args.version or project_version()).lstrip("v")
    system, arch = target()
    print(f"Building {APP_NAME} {version} for {system}/{arch}")

    RELEASE.mkdir(parents=True, exist_ok=True)
    ensure_icons()
    wanted = [name for name, skip in (("ffmpeg", args.no_ffmpeg), ("deno", args.no_deno)) if not skip]
    bundled = [name for name in wanted if get_tool(name, required=args.strict)]
    run_pyinstaller(version)
    for name in bundled:
        bundle_tool(name, system)

    packagers = {"macos": package_macos, "windows": package_windows, "linux": package_linux}
    outputs = packagers[system](version, arch)

    print(f"\nBundled tools: {', '.join(bundled) or 'none'}")
    print("Done. Release files:")
    for path in outputs:
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
