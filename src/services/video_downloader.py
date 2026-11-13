import http.client
import io
import os
import re
import shutil
import socket
import ssl
import sys
import threading
import urllib.error
from collections.abc import Callable

import yt_dlp
from PIL import Image
from yt_dlp.networking.exceptions import TransportError
from yt_dlp.utils import DownloadCancelled

from config.paths import resource_path
from config.settings import DEFAULT_HEIGHT, PLAYLIST_HEIGHTS, VIDEOS_FOLDER
from models.media import (
    AUDIO_ONLY,
    DownloadResult,
    MediaInfo,
    PlaylistEntry,
    ProgressInfo,
    QualityOption,
)

ProgressCallback = Callable[[ProgressInfo], None]

PREVIEW_THUMBNAIL_SIZE = (480, 270)

# yt-dlp postprocessor keys -> what we show the user while they run.
_POSTPROCESSOR_STAGES = {
    "Merger": "Merging video and audio",
    "ExtractAudio": "Converting to MP3",
}


# Where package managers put ffmpeg. Apps opened from the macOS Finder (or a Linux
# desktop launcher) get a minimal PATH that usually doesn't include these.
_EXTRA_FFMPEG_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin", "/snap/bin")


def find_ffmpeg() -> str | None:
    """Folder containing ffmpeg (+ ffprobe), or None if it isn't installed.

    Order: the copy bundled inside a packaged build, then PATH, then common
    install locations.
    """
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = resource_path("ffmpeg", "bin")
    if (bundled / exe).is_file():
        return str(bundled)
    on_path = shutil.which("ffmpeg")
    if on_path:
        return os.path.dirname(on_path)
    if sys.platform != "win32":
        for folder in _EXTRA_FFMPEG_DIRS:
            if os.access(os.path.join(folder, exe), os.X_OK):
                return folder
    return None


def ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def find_deno() -> str | None:
    """Path to the Deno executable, or None.

    yt-dlp needs a JavaScript runtime (Deno recommended) to solve YouTube's
    JS challenges; without one many YouTube videos can't be downloaded.
    """
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    bundled = resource_path("deno", exe)
    if bundled.is_file():
        return str(bundled)
    on_path = shutil.which("deno")
    if on_path:
        return on_path
    candidates = [os.path.join(os.path.expanduser("~"), ".deno", "bin", exe)]
    if sys.platform != "win32":
        candidates += [os.path.join(folder, exe) for folder in _EXTRA_FFMPEG_DIRS]
    return next((c for c in candidates if os.path.isfile(c) and os.access(c, os.X_OK)), None)


def js_runtime_options(deno_path: str | None) -> dict:
    """yt-dlp options pointing at our Deno (yt-dlp itself only looks on PATH)."""
    return {"js_runtimes": {"deno": {"path": deno_path}}} if deno_path else {}


def missing_tools_message(has_ffmpeg: bool, has_deno: bool, platform: str = sys.platform) -> str | None:
    """Warning shown in the app when ffmpeg and/or Deno are missing (None if all is well)."""
    if has_ffmpeg and has_deno:
        return None
    if platform == "darwin":
        install = "brew install " + " ".join(n for n, ok in (("ffmpeg", has_ffmpeg), ("deno", has_deno)) if not ok)
    elif platform == "win32":
        install = "winget install " + " ".join(
            n for n, ok in (("Gyan.FFmpeg", has_ffmpeg), ("DenoLand.Deno", has_deno)) if not ok)
    else:
        parts = [] if has_ffmpeg else ["sudo apt install ffmpeg"]
        parts += [] if has_deno else ["curl -fsSL https://deno.land/install.sh | sh"]
        install = "  and  ".join(parts)
    problems = []
    if not has_deno:
        problems.append("Deno isn't installed, so many YouTube videos can't be downloaded")
    if not has_ffmpeg:
        problems.append("ffmpeg isn't installed, so only lower qualities (often 360p) and M4A audio are available")
    return f"{'; '.join(problems)}. To fix it, install: {install}"


# ---------------------------------------------------------------------------
# Reading what a link points to
# ---------------------------------------------------------------------------

def _has_video(fmt: dict) -> bool:
    return fmt.get("vcodec") not in (None, "none") and bool(fmt.get("height")) and fmt.get("ext") != "mhtml"


def _has_audio(fmt: dict) -> bool:
    return fmt.get("acodec") not in (None, "none")


def _size(fmt: dict) -> int | None:
    return fmt.get("filesize") or fmt.get("filesize_approx")


def _largest_size(formats: list[dict]) -> int | None:
    sizes = [s for s in (_size(f) for f in formats) if s]
    return max(sizes) if sizes else None


def quality_options(info: dict, has_ffmpeg: bool) -> list[QualityOption]:
    """Resolutions this particular video offers, highest first, plus audio only."""
    formats = info.get("formats") or []
    video = [f for f in formats if _has_video(f)]
    if not has_ffmpeg:
        # Without ffmpeg we can't merge separate streams: only files with both.
        video = [f for f in video if _has_audio(f)]
    audio_only = [f for f in formats if not _has_video(f) and _has_audio(f)]
    audio_size = (_largest_size(audio_only) or 0) if has_ffmpeg else 0

    by_height: dict[int, list[dict]] = {}
    for f in video:
        by_height.setdefault(int(f["height"]), []).append(f)

    options = []
    for height in sorted(by_height, reverse=True):
        size = _largest_size(by_height[height])
        options.append(
            QualityOption(f"{height}p", height=height, size_bytes=size + audio_size if size else None)
        )
    if not options:
        options.append(QualityOption("Best available"))
    options.append(AUDIO_ONLY)
    return options


def playlist_quality_options() -> list[QualityOption]:
    return (
        [QualityOption("Best available")]
        + [QualityOption(f"{h}p", height=h) for h in PLAYLIST_HEIGHTS]
        + [AUDIO_ONLY]
    )


def default_quality(options: list[QualityOption]) -> QualityOption:
    """Highest resolution at or below DEFAULT_HEIGHT, else the highest offered."""
    with_height = [o for o in options if o.height]
    at_or_below = [o for o in with_height if o.height <= DEFAULT_HEIGHT]
    if at_or_below:
        return max(at_or_below, key=lambda o: o.height)
    if with_height:
        return min(with_height, key=lambda o: o.height)
    return options[0]


def _thumbnail_url(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbs = info.get("thumbnails") or []
    return thumbs[-1].get("url") if thumbs else None


def parse_info(info: dict, url: str, has_ffmpeg: bool) -> MediaInfo:
    uploader = info.get("uploader") or info.get("channel")
    page_url = info.get("webpage_url") or url
    thumb = _thumbnail_url(info)

    if info.get("_type") == "playlist":
        entries = []
        for index, entry in enumerate(info.get("entries") or [], start=1):
            if not entry:
                continue  # unavailable/private video: keep numbering, skip it
            entries.append(
                PlaylistEntry(index=index, title=entry.get("title") or "Untitled", duration=entry.get("duration"))
            )
            thumb = thumb or _thumbnail_url(entry)
        return MediaInfo(
            url=page_url,
            title=info.get("title") or "Playlist",
            is_playlist=True,
            uploader=uploader,
            thumbnail_url=thumb,
            qualities=playlist_quality_options(),
            entries=entries,
        )

    return MediaInfo(
        url=page_url,
        title=info.get("title") or "Untitled",
        is_playlist=False,
        uploader=uploader,
        duration=info.get("duration"),
        thumbnail_url=thumb,
        qualities=quality_options(info, has_ffmpeg),
    )


def fetch_info(url: str, deno_path: str | None = None) -> MediaInfo:
    """Look up a video or playlist (no download). Runs in a worker thread."""
    opts = {
        **js_runtime_options(deno_path),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,          # watch?v=..&list=.. -> just the video
        "extract_flat": "in_playlist",  # playlists: list entries without resolving each one
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError("Nothing was found at this link.")
        media = parse_info(info, url, ffmpeg_available())
        if media.thumbnail_url:
            try:
                data = ydl.urlopen(media.thumbnail_url).read()
                image = Image.open(io.BytesIO(data)).convert("RGB")
                image.thumbnail(PREVIEW_THUMBNAIL_SIZE)
                media.thumbnail = image
            except Exception:  # a missing preview image is not worth failing over
                pass
    return media


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

class DownloadPaused(DownloadCancelled):
    """Raised from our hooks to stop a download so it can be resumed later.

    It subclasses DownloadCancelled because yt-dlp always lets that one through
    (even with ignoreerrors), so the whole download stops right away.
    """


_NETWORK_MESSAGE = re.compile(
    r"timed? ?out|connection (?:reset|refused|aborted|closed)|network is unreachable|no route to host"
    r"|temporary failure in name resolution|name or service not known|nodename nor servname"
    r"|getaddrinfo failed|failed to resolve|no address associated|urlopen error|remote end closed"
    r"|incompleteread|incomplete read|bytes read, \d+ more expected|eof occurred|connection broken|\[errno (?:8|-2|-3|51|54|60|61|65|101|104|110|111|113)\]"
    r"|winerror 100(?:51|53|54|60|61|65)",
    re.IGNORECASE,
)


def is_network_error(error: BaseException | str | None) -> bool:
    """True if a failure looks like a dropped/unstable connection (worth retrying later)."""
    if error is None:
        return False
    if isinstance(error, str):
        return bool(_NETWORK_MESSAGE.search(error))
    seen = set()
    current = error
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        if isinstance(current, (TransportError, socket.timeout, TimeoutError, ConnectionError,
                                urllib.error.URLError, ssl.SSLError, socket.gaierror, http.client.IncompleteRead)):
            if not isinstance(current, urllib.error.HTTPError):  # a 403/404 is not a network problem
                return True
        if _NETWORK_MESSAGE.search(str(current)):
            return True
        exc_info = getattr(current, "exc_info", None)
        nested = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) > 1 else None
        current = nested or getattr(current, "cause", None) or current.__cause__ or current.__context__
    return False


class _YtDlpLogger:
    """Receives yt-dlp's messages. In playlists yt-dlp skips failed videos (ignoreerrors),
    so this is where we notice that a video failed because the connection dropped."""

    def __init__(self, job: "DownloadJob"):
        self.job = job

    def debug(self, msg: str):
        pass

    def info(self, msg: str):
        pass

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        if is_network_error(msg):
            self.job.network_failed = True
            self.job.pause_event.set()  # stop at the next video instead of failing them all

def build_format(option: QualityOption, has_ffmpeg: bool) -> str:
    if option.audio_only:
        return "ba/b" if has_ffmpeg else "ba[ext=m4a]/ba/b"
    height = option.height
    if height is None:
        return "bv*+ba/b" if has_ffmpeg else "b"
    if has_ffmpeg:
        # Best streams up to the chosen height; if none exist, the smallest available.
        return f"bv*[height<={height}]+ba/b[height<={height}]/wv*+ba/w"
    return f"b[height<={height}]/w"


class DownloadJob:
    """One download (a video or a playlist), run in a worker thread."""

    def __init__(
        self,
        url: str,
        option: QualityOption,
        on_progress: ProgressCallback,
        has_ffmpeg: bool,
        cancel_event: threading.Event | None = None,
        playlist: bool = False,
        items: list[int] | None = None,
        total: int = 1,
        ffmpeg_location: str | None = None,
        deno_path: str | None = None,
    ):
        self.url = url
        self.option = option
        self.on_progress = on_progress
        self.has_ffmpeg = has_ffmpeg
        self.cancel_event = cancel_event or threading.Event()
        self.playlist = playlist
        self.items = items
        self.total = total
        self.ffmpeg_location = ffmpeg_location
        self.deno_path = deno_path
        self.pause_event = threading.Event()
        self.network_failed = False
        self.completed_files: set[str] = set()  # kept across pause/resume, so nothing is counted twice
        self._seen_ids: list[str] = []

    @property
    def completed(self) -> int:
        return len(self.completed_files)

    # -- hooks (called by yt-dlp on the worker thread) --

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise DownloadCancelled()
        if self.pause_event.is_set():
            raise DownloadPaused()

    def _item(self, info: dict) -> tuple[int | None, int | None, str | None]:
        if not self.playlist:
            return None, None, info.get("title")
        item_id = info.get("id") or info.get("webpage_url") or info.get("title") or "?"
        if item_id not in self._seen_ids:
            self._seen_ids.append(item_id)
        return self._seen_ids.index(item_id) + 1, self.total, info.get("title")

    def _progress_hook(self, d: dict):
        self._check_cancel()
        info = d.get("info_dict") or {}
        number, count, title = self._item(info)
        if d["status"] == "downloading":
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
            fraction = d.get("downloaded_bytes", 0) / total_bytes if total_bytes else None
            kind = "audio" if self.option.audio_only or info.get("vcodec") == "none" else "video"
            self.on_progress(
                ProgressInfo(f"Downloading {kind}", fraction, d.get("speed"), d.get("eta"), number, count, title)
            )
        elif d["status"] == "finished":
            self.on_progress(ProgressInfo("Processing", 1.0, None, None, number, count, title))

    def _postprocessor_hook(self, d: dict):
        self._check_cancel()
        stage = _POSTPROCESSOR_STAGES.get(d.get("postprocessor"))
        if d["status"] == "started" and stage:
            number, count, title = self._item(d.get("info_dict") or {})
            self.on_progress(ProgressInfo(stage, None, None, None, number, count, title))

    def _post_hook(self, filepath: str):
        """Called once per finished file, after all post-processing."""
        self.completed_files.add(os.path.abspath(filepath))
        number = len(self._seen_ids) if self.playlist else None
        self.on_progress(ProgressInfo("Saved", 1.0, item_number=number, item_count=self.total if self.playlist else None))

    def options(self) -> dict:
        VIDEOS_FOLDER.mkdir(parents=True, exist_ok=True)
        name = "%(title)s.%(ext)s"
        if self.playlist:
            name = "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s"

        opts = {
            "format": build_format(self.option, self.has_ffmpeg),
            "format_sort": ["res", "ext:mp4:m4a"],
            "outtmpl": str(VIDEOS_FOLDER / name),
            "noplaylist": not self.playlist,
            # In playlists, skip unavailable videos instead of stopping everything.
            "ignoreerrors": "only_download" if self.playlist else False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _YtDlpLogger(self),
            "continuedl": True,     # resume .part files after a pause
            "socket_timeout": 20,   # a dead connection fails (and pauses) instead of hanging
            "writethumbnail": True,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "post_hooks": [self._post_hook],
        }
        if self.ffmpeg_location:
            opts["ffmpeg_location"] = self.ffmpeg_location
        opts.update(js_runtime_options(self.deno_path))
        if self.items:
            opts["playlist_items"] = ",".join(str(i) for i in self.items)

        postprocessors = []
        if self.has_ffmpeg:
            if self.option.audio_only:
                postprocessors.append(
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
                )
            else:
                opts["merge_output_format"] = "mp4/mkv"  # mp4 when codecs allow it
            postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
        if postprocessors:
            opts["postprocessors"] = postprocessors
        return opts

    def run(self) -> DownloadResult:
        """Download (or continue after a pause). Safe to call again with the same job."""
        self.pause_event.clear()
        self.network_failed = False
        try:
            with yt_dlp.YoutubeDL(self.options()) as ydl:
                ydl.download([self.url])
        except Exception as e:
            if self.cancel_event.is_set():
                return DownloadResult(self.completed, self.total, cancelled=True)
            network = self.network_failed or is_network_error(e)
            if self.pause_event.is_set() or isinstance(e, DownloadPaused) or network:
                return DownloadResult(self.completed, self.total, paused=True, network_error=network)
            raise
        if self.cancel_event.is_set():
            return DownloadResult(self.completed, self.total, cancelled=True)
        if self.network_failed:  # a playlist video failed because the connection dropped
            return DownloadResult(self.completed, self.total, paused=True, network_error=True)
        if self.playlist and self.total and self.completed == 0:
            raise RuntimeError("None of the selected videos could be downloaded.")
        return DownloadResult(self.completed, self.total)


def clean_error(exc: Exception) -> str:
    """Turn a yt-dlp exception into a short, user-facing message."""
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()  # strip terminal colors
    if msg.startswith("ERROR:"):
        msg = msg[len("ERROR:"):].strip()
    if len(msg) > 200:
        msg = msg[:197] + "..."
    return msg or exc.__class__.__name__
