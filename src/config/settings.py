from pathlib import Path

# Single source of truth for where downloads are stored.
VIDEOS_FOLDER = Path.home() / "Downloads" / "Youtube Videos"

# Quality pre-selected in the quality menu (the highest option at or below it).
DEFAULT_HEIGHT = 720

# Resolutions offered for playlists (per-video formats aren't known up front).
PLAYLIST_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)

# Playlists larger than this download in full instead of showing a checklist.
MAX_PLAYLIST_CHECKLIST = 300

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mkv", ".mov")
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".opus", ".ogg", ".wav")
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS + AUDIO_EXTENSIONS
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class AppSettings:
    def __init__(self):
        self.title = "YouTube Downloader"
        self.geometry = "1240x800"
        self.min_size = (1100, 720)
