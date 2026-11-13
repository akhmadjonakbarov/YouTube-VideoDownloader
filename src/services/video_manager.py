import re
from pathlib import Path

from PIL import Image

from config.settings import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS, THUMBNAIL_EXTENSIONS, VIDEOS_FOLDER
from models.video import Video
from services.formatting import format_size

# Intermediate files yt-dlp writes while downloading/merging,
# e.g. "Title.f137.mp4" or "Title.temp.mp4". They are not finished downloads.
_INTERMEDIATE_STEM = re.compile(r"\.(f\d+|temp)$")

THUMBNAIL_SIZE = (320, 180)


class VideoManager:
    def __init__(self, videos_folder: Path | str = VIDEOS_FOLDER):
        self.videos_folder = Path(videos_folder)
        # Create the folder up front so the first run doesn't crash.
        self.videos_folder.mkdir(parents=True, exist_ok=True)
        self._thumbnail_cache: dict[tuple[Path, float], Image.Image | None] = {}

    def _is_media(self, path: Path) -> bool:
        relative = path.relative_to(self.videos_folder)
        return (
            path.is_file()
            and path.suffix.lower() in MEDIA_EXTENSIONS
            and not _INTERMEDIATE_STEM.search(path.stem)
            and not any(part.startswith(".") for part in relative.parts)
        )

    def get_videos(self) -> list[Video]:
        """Finished downloads (including playlist sub-folders), newest first."""
        videos = []
        for path in self.videos_folder.rglob("*"):
            if not self._is_media(path):
                continue
            stat = path.stat()
            folder = None if path.parent == self.videos_folder else str(path.parent.relative_to(self.videos_folder))
            videos.append(
                Video(
                    path=path,
                    size=format_size(stat.st_size),
                    image=self.get_thumbnail(path),
                    folder_label=folder,
                    is_audio=path.suffix.lower() in AUDIO_EXTENSIONS,
                    modified=stat.st_mtime,
                    size_bytes=stat.st_size,
                )
            )
        videos.sort(key=lambda v: v.modified, reverse=True)
        return videos

    def _thumbnail_files(self, video_path: Path) -> list[Path]:
        return [
            video_path.with_suffix(ext)
            for ext in THUMBNAIL_EXTENSIONS
            if video_path.with_suffix(ext).exists()
        ]

    def get_thumbnail(self, video_path: Path) -> Image.Image | None:
        """Load the thumbnail yt-dlp saved next to the file (cached)."""
        candidates = self._thumbnail_files(video_path)
        if not candidates:
            return None
        thumb_path = candidates[0]
        key = (thumb_path, thumb_path.stat().st_mtime)
        if key not in self._thumbnail_cache:
            try:
                with Image.open(thumb_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail(THUMBNAIL_SIZE)
                    self._thumbnail_cache[key] = img
            except OSError:
                self._thumbnail_cache[key] = None
        return self._thumbnail_cache[key]

    def delete_video(self, video: Video) -> None:
        """Delete the file and its thumbnail; remove an emptied playlist folder.

        Raises OSError on failure.
        """
        for thumb in self._thumbnail_files(video.path):
            thumb.unlink(missing_ok=True)
        video.path.unlink(missing_ok=True)

        folder = video.path.parent
        if folder != self.videos_folder and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
