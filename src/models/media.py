from dataclasses import dataclass, field

from PIL import Image


@dataclass(frozen=True)
class QualityOption:
    """One entry of the quality menu.

    height=None and audio_only=False means "best available".
    """

    label: str
    height: int | None = None
    audio_only: bool = False
    size_bytes: int | None = None  # estimated download size, when known


AUDIO_ONLY = QualityOption("Audio only", audio_only=True)


@dataclass
class PlaylistEntry:
    index: int  # 1-based position in the playlist (used for yt-dlp's playlist_items)
    title: str
    duration: float | None = None
    url: str | None = None  # the video's own link (lets several playlist videos download at once)


@dataclass
class MediaInfo:
    """What a pasted link points to, as shown in the preview."""

    url: str
    title: str
    is_playlist: bool
    uploader: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    qualities: list[QualityOption] = field(default_factory=list)
    entries: list[PlaylistEntry] = field(default_factory=list)
    thumbnail: Image.Image | None = None


@dataclass
class ProgressInfo:
    stage: str
    fraction: float | None = None  # 0.0–1.0, None when unknown
    speed: float | None = None     # bytes per second
    eta: float | None = None       # seconds
    item_number: int | None = None  # playlist only
    item_count: int | None = None
    item_title: str | None = None
    playlist_index: int | None = None  # position in the playlist (PlaylistEntry.index)


@dataclass
class DownloadResult:
    completed: int
    total: int
    cancelled: bool = False
    paused: bool = False          # stopped part-way; run the same job again to continue
    network_error: bool = False   # paused because the connection failed
