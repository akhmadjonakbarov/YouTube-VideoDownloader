from collections.abc import Callable

import customtkinter as ctk
from PIL import Image

from config import theme
from models.media import ProgressInfo
from services.formatting import format_duration, format_speed, truncate
from widgets.art import progress_ring
from widgets.icons import icon
from widgets.images import rounded_thumbnail

THUMB = (176, 99)
RING = 132

# Stages where speed / time left don't apply.
_QUIET_STAGES = {"Processing", "Saved", "Merging video and audio", "Converting to MP3"}


def _ring_image(fraction: float, label: str | None = None) -> ctk.CTkImage:
    light = progress_ring(fraction, RING, track=theme.SECONDARY[0], color=theme.ACCENT[0], text_color=theme.TEXT[0], label=label)
    dark = progress_ring(fraction, RING, track=theme.SECONDARY[1], color=theme.ACCENT[1], text_color=theme.TEXT[1], label=label)
    return ctk.CTkImage(light, dark, size=(RING, RING))


class ProgressCard(ctk.CTkFrame):
    """Live progress of the running download: ring, stage, speed, playlist progress, Cancel."""

    def __init__(self, parent, on_cancel: Callable[[], None]):
        super().__init__(parent, **theme.card())
        self.grid_columnconfigure(0, weight=1)
        self.is_playlist = False
        self.total = 1
        self.shown_percent = -1
        self.current = 0.0

        # --- Header: thumbnail + title ---
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=26, pady=(26, 0))
        head.grid_columnconfigure(1, weight=1)
        self.thumb_img = ctk.CTkImage(rounded_thumbnail(None, THUMB, 12), size=THUMB)
        self.thumb = ctk.CTkLabel(head, text="", image=self.thumb_img)
        self.thumb.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 20))
        self.pill = ctk.CTkLabel(
            head, text="", height=24, corner_radius=12, fg_color=theme.ACCENT_SOFT,
            text_color=theme.ACCENT_TEXT, font=theme.font(10, "bold"),
        )
        self.pill.grid(row=0, column=1, sticky="w")
        self.title_label = ctk.CTkLabel(
            head, text="", anchor="w", justify="left", wraplength=560, font=theme.font(19, "bold")
        )
        self.title_label.grid(row=1, column=1, sticky="ew", pady=(10, 2))
        self.item_label = ctk.CTkLabel(
            head, text="", anchor="w", justify="left", wraplength=560, text_color=theme.MUTED, font=theme.font(13)
        )
        self.item_label.grid(row=2, column=1, sticky="new")

        ctk.CTkFrame(self, height=1, fg_color=theme.BORDER).grid(row=1, column=0, sticky="ew", padx=26, pady=22)

        # --- Ring + details ---
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 26))
        body.grid_columnconfigure(1, weight=1)
        self.ring_img = _ring_image(0)
        self.ring = ctk.CTkLabel(body, text="", image=self.ring_img)
        self.ring.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 28))

        self.stage_label = ctk.CTkLabel(body, text="", anchor="w", font=theme.font(17, "bold"))
        self.stage_label.grid(row=0, column=1, sticky="sw", pady=(10, 0))
        self.detail_label = ctk.CTkLabel(body, text="", anchor="w", text_color=theme.MUTED, font=theme.font(13))
        self.detail_label.grid(row=1, column=1, sticky="nw")

        self.overall = ctk.CTkFrame(body, fg_color="transparent")
        self.overall.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.overall, text="Playlist progress", text_color=theme.MUTED, font=theme.font(12)).grid(
            row=0, column=0, sticky="w"
        )
        self.overall_label = ctk.CTkLabel(self.overall, text="", font=theme.font(12, "bold"))
        self.overall_label.grid(row=0, column=1, sticky="e")
        self.overall_bar = ctk.CTkProgressBar(
            self.overall, height=6, corner_radius=3, progress_color=theme.SUCCESS, fg_color=theme.SECONDARY
        )
        self.overall_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.cancel_button = ctk.CTkButton(
            body, text="Cancel download", width=170, height=40, corner_radius=12, font=theme.font(13, "bold"),
            image=icon("x", 15, theme.TEXT), command=on_cancel, **theme.secondary(),
        )
        self.cancel_button.grid(row=3, column=1, sticky="sw", pady=(16, 6))

    def _set_ring(self, fraction: float, label: str | None = None):
        percent = int(max(0.0, min(1.0, fraction)) * 100)
        key = (percent, label)
        if key == self.shown_percent:
            return  # redraw only when the number changes
        self.shown_percent = key
        self.ring_img = _ring_image(fraction, label)
        self.ring.configure(image=self.ring_img)

    def start(self, title: str, thumbnail: Image.Image | None, is_playlist: bool, total: int):
        self.is_playlist = is_playlist
        self.total = max(1, total)
        self.shown_percent = -1
        self.current = 0.0
        source = rounded_thumbnail(thumbnail, THUMB, 12)
        self.thumb_img = ctk.CTkImage(source, source, size=THUMB)
        self.thumb.configure(image=self.thumb_img)
        self.pill.configure(text="   DOWNLOADING PLAYLIST   " if is_playlist else "   DOWNLOADING   ")
        self.title_label.configure(text=truncate(title, 100))
        self.item_label.configure(text="Getting ready…")
        self.stage_label.configure(text="Starting…")
        self.detail_label.configure(text="Connecting to YouTube")
        self._set_ring(0)
        if is_playlist:
            self.overall.grid(row=2, column=1, sticky="ew", pady=(14, 0))
            self.overall_bar.set(0)
            self.overall_label.configure(text=f"0 of {self.total}")
        else:
            self.overall.grid_forget()
        self.cancel_button.configure(state="normal", text="Cancel download")

    def set_progress(self, p: ProgressInfo) -> float:
        """Apply an update; returns the overall fraction (for the sidebar)."""
        if self.is_playlist:
            if p.item_number:
                text = f"Video {min(p.item_number, self.total)} of {self.total}"
                if p.item_title:
                    text += f"  ·  {truncate(p.item_title, 60)}"
                self.item_label.configure(text=text)
        else:
            self.item_label.configure(text="")

        self.stage_label.configure(text=p.stage if p.stage == "Saved" else f"{p.stage}…")
        if p.fraction is not None:
            self.current = max(0.0, min(1.0, p.fraction))
            self._set_ring(self.current)
        current = self.current

        if p.stage in _QUIET_STAGES:
            self.detail_label.configure(text="Almost done" if p.stage != "Saved" else "Saved to your Library")
        else:
            parts = [format_speed(p.speed)]
            if p.eta is not None:
                parts.append(f"{format_duration(p.eta)} left")
            self.detail_label.configure(text="  ·  ".join(part for part in parts if part))

        if not self.is_playlist:
            return current
        done = (p.item_number or 1) - (0 if p.stage == "Saved" else 1)
        overall = min(1.0, (done + (0 if p.stage == "Saved" else current)) / self.total)
        self.overall_bar.set(overall)
        self.overall_label.configure(text=f"{max(0, done)} of {self.total}")
        return overall

    def set_cancelling(self):
        self.cancel_button.configure(state="disabled", text="Cancelling…")
        self.stage_label.configure(text="Stopping…")
