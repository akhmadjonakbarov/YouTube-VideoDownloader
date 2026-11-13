from collections.abc import Callable
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

from config import theme
from models.video import Video
from services.formatting import truncate
from widgets.hover import bind_click, bind_hover
from widgets.icons import icon
from widgets.images import rounded_thumbnail

VideoAction = Callable[[Video], None]

BASE_WIDTH = 280  # card width the thumbnail is rendered for (it scales from there)
PAD = 12


class VideoCard(ctk.CTkFrame):
    """One library item: thumbnail (click to play), title, details and actions."""

    def __init__(self, parent, video: Video, on_open: VideoAction, on_reveal: VideoAction, on_delete: VideoAction):
        super().__init__(parent, **theme.card(corner_radius=18))
        self.video = video
        self.on_delete = on_delete
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)  # spare height goes above the buttons, so rows line up

        thumb_w = BASE_WIDTH - 2 * PAD
        source = rounded_thumbnail(
            video.image, (thumb_w, thumb_w * 9 // 16), 12, audio=video.is_audio,
            badge=video.path.suffix.lstrip(".").upper(),
        )
        self.thumb_img = ctk.CTkImage(source, source, size=(thumb_w, thumb_w * 9 // 16))
        self.thumb = ctk.CTkLabel(self, text="", image=self.thumb_img)
        self.thumb.grid(row=0, column=0, padx=PAD, pady=(PAD, 12))
        bind_click(self.thumb, lambda: on_open(video))

        self.title_label = ctk.CTkLabel(
            self, text=truncate(video.title, 80), anchor="w", justify="left",
            wraplength=thumb_w, font=theme.font(14, "bold"),
        )
        self.title_label.grid(row=1, column=0, sticky="ew", padx=PAD + 4)

        details = []
        if video.folder_label:
            details.append(truncate(video.folder_label, 28))
        details.append(video.size)
        if video.modified:
            details.append(datetime.fromtimestamp(video.modified).strftime("%d %b %Y"))
        self.meta_label = ctk.CTkLabel(
            self, text="  ·  ".join(details), anchor="w", justify="left", wraplength=thumb_w,
            text_color=theme.MUTED, font=theme.font(12),
        )
        self.meta_label.grid(row=2, column=0, sticky="new", padx=PAD + 4, pady=(3, 0))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="sew", padx=PAD, pady=(14, PAD))
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            actions, text=" Play", width=92, height=36, corner_radius=11, font=theme.font(13, "bold"),
            image=icon("play", 13, theme.WHITE), command=lambda: on_open(video), **theme.primary(),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            actions, text="", width=36, height=36, corner_radius=11, image=icon("folder", 16, theme.TEXT),
            command=lambda: on_reveal(video), **theme.secondary(),
        ).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(
            actions, text="", width=36, height=36, corner_radius=11, image=icon("trash", 16, theme.ERROR),
            fg_color="transparent", hover_color=theme.ACCENT_SOFT, border_width=1, border_color=theme.BORDER,
            command=self.confirm_delete,
        ).grid(row=0, column=2)

        bind_hover(self, lambda: self.configure(border_color=theme.BORDER_STRONG, fg_color=theme.CARD_HOVER),
                   lambda: self.configure(border_color=theme.BORDER, fg_color=theme.CARD))
        self.thumb.configure(cursor="hand2")

    def set_card_width(self, width: int):
        """Resize the thumbnail and text wrapping to fit a grid column."""
        thumb_w = max(120, width - 2 * PAD)
        self.thumb_img.configure(size=(thumb_w, thumb_w * 9 // 16))
        self.title_label.configure(wraplength=thumb_w - 8)
        self.meta_label.configure(wraplength=thumb_w - 8)

    def confirm_delete(self):
        confirmed = messagebox.askyesno(
            title="Delete download",
            message=f'Delete "{self.video.title}"?\n\nThe file will be permanently removed.',
            icon=messagebox.WARNING,
            parent=self.winfo_toplevel(),
        )
        if confirmed:
            self.on_delete(self.video)
