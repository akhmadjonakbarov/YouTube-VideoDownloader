#!/bin/sh
# Install YouTube Downloader for the current user (no root needed).
#   ./install.sh            install / update
#   ./install.sh --remove   uninstall
set -e

APP_DIR="$HOME/.local/share/youtube-downloader"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

if [ "$1" = "--remove" ]; then
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/youtube-downloader" "$DESKTOP_DIR/youtube-downloader.desktop" "$ICON_DIR/youtube-downloader.png"
    echo "YouTube Downloader removed."
    exit 0
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
rm -rf "$APP_DIR"
cp -a "$HERE" "$APP_DIR"
ln -sf "$APP_DIR/YouTubeDownloader" "$BIN_DIR/youtube-downloader"
cp "$HERE/youtube-downloader.png" "$ICON_DIR/youtube-downloader.png"
sed "s|^Exec=.*|Exec=$APP_DIR/YouTubeDownloader|" "$HERE/youtube-downloader.desktop" \
    > "$DESKTOP_DIR/youtube-downloader.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true

echo "Installed. Open \"YouTube Downloader\" from your app menu, or run: youtube-downloader"
