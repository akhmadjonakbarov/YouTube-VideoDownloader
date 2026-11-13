from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class Video:
    """A downloaded file in the library."""

    path: Path
    size: str
    image: Image.Image | None = None
    folder_label: str | None = None  # playlist folder, if not in the root folder
    is_audio: bool = False
    modified: float = 0.0
    size_bytes: int = 0

    @property
    def title(self) -> str:
        """Display title: the file name without its extension."""
        return self.path.stem

    def __str__(self) -> str:
        return self.title
