from collections.abc import Callable

import customtkinter as ctk

from config import theme
from models.video import Video
from services.formatting import format_size
from widgets.icons import icon
from widgets.scroll import AutoScrollFrame
from widgets.video_item import VideoAction, VideoCard

MIN_CARD_WIDTH = 260
GAP = 18
FILTERS = ("All", "Videos", "Audio")


class StatTile(ctk.CTkFrame):
    def __init__(self, parent, glyph: str, label: str, color):
        super().__init__(parent, **theme.card(corner_radius=18))
        self.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text="", image=icon(glyph, 18, color), width=40, height=40, corner_radius=12,
                     fg_color=theme.SECONDARY).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16)
        self.value_label = ctk.CTkLabel(self, text="0", anchor="w", font=theme.font(22, "bold"), height=26)
        self.value_label.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        ctk.CTkLabel(self, text=label, anchor="w", text_color=theme.MUTED, font=theme.font(12), height=16).grid(
            row=1, column=1, sticky="nw", pady=(0, 14)
        )

    def set_value(self, value: str):
        self.value_label.configure(text=value)


class LibraryView(ctk.CTkFrame):
    """The 'Library' page: stats, search, filter and a responsive grid of downloads."""

    def __init__(
        self,
        parent,
        on_open: VideoAction,
        on_reveal: VideoAction,
        on_delete: VideoAction,
        on_refresh: Callable[[], None],
    ):
        super().__init__(parent, fg_color="transparent")
        self.on_open, self.on_reveal, self.on_delete = on_open, on_reveal, on_delete
        self.videos: list[Video] = []
        self.cards: list[VideoCard] = []
        self.columns = 0
        self.layout_job: str | None = None
        self.last_width = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # --- Header ---
        ctk.CTkLabel(self, text="Library", anchor="w", font=theme.font(30, "bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(self, text="Everything you've downloaded, in one place.", anchor="w",
                     text_color=theme.MUTED, font=theme.font(14)).grid(row=1, column=0, sticky="w", pady=(2, 18))

        # --- Stats + toolbar ---
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", pady=(0, 18))
        for col in range(4):
            top.grid_columnconfigure(col, weight=1, uniform="stats")
        self.stat_total = StatTile(top, "library", "Downloads", theme.ACCENT)
        self.stat_videos = StatTile(top, "play", "Videos", theme.TEXT)
        self.stat_audio = StatTile(top, "music", "Audio tracks", theme.TEXT)
        self.stat_size = StatTile(top, "folder", "On disk", theme.TEXT)
        for col, tile in enumerate((self.stat_total, self.stat_videos, self.stat_audio, self.stat_size)):
            tile.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0 if col == 3 else 8))

        toolbar = ctk.CTkFrame(top, fg_color="transparent")
        toolbar.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        toolbar.grid_columnconfigure(0, weight=1)
        search = ctk.CTkFrame(toolbar, **theme.card(corner_radius=14))
        search.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        search.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search, text="", image=icon("search", 16, theme.MUTED), width=20).grid(
            row=0, column=0, padx=(16, 6)
        )
        self.search_input = ctk.CTkEntry(
            search, placeholder_text="Search by title or playlist…", height=42, border_width=0,
            fg_color="transparent", font=theme.font(14), placeholder_text_color=theme.SUBTLE,
        )
        self.search_input.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=2)
        self.search_input.bind("<KeyRelease>", lambda _e: self.render())

        self.filter = ctk.CTkSegmentedButton(
            toolbar, values=list(FILTERS), height=44, corner_radius=14, font=theme.font(13, "bold"),
            fg_color=theme.SECONDARY, unselected_color=theme.SECONDARY, unselected_hover_color=theme.SECONDARY_HOVER,
            selected_color=theme.SEGMENT_SELECTED, selected_hover_color=theme.SEGMENT_SELECTED, text_color=theme.TEXT,
            command=lambda _v: self.render(),
        )
        self.filter.set("All")
        self.filter.grid(row=0, column=1, padx=(0, 12))
        ctk.CTkButton(
            toolbar, text="", width=44, height=44, corner_radius=14, image=icon("refresh", 17, theme.TEXT),
            command=on_refresh, **theme.secondary(),
        ).grid(row=0, column=2)

        # --- Grid ---
        self.scroll = AutoScrollFrame(self, fg_color="transparent")
        self.scroll.grid(row=3, column=0, sticky="nsew")
        # add="+": keep CustomTkinter's own handler that updates the scrollable area.
        self.scroll.bind("<Configure>", self._on_resize, add="+")
        self.empty_label = ctk.CTkLabel(self.scroll, text="", justify="center", text_color=theme.MUTED, font=theme.font(15))

    # ---------- Data ----------

    def set_videos(self, videos: list[Video]):
        self.videos = videos
        audio = sum(1 for v in videos if v.is_audio)
        self.stat_total.set_value(str(len(videos)))
        self.stat_videos.set_value(str(len(videos) - audio))
        self.stat_audio.set_value(str(audio))
        self.stat_size.set_value(format_size(sum(v.size_bytes for v in videos)) or "0 MB")
        self.render()

    def _visible_videos(self) -> list[Video]:
        query = self.search_input.get().strip().lower()
        kind = self.filter.get()
        result = []
        for v in self.videos:
            if kind == "Videos" and v.is_audio or kind == "Audio" and not v.is_audio:
                continue
            if query and query not in v.title.lower() and query not in (v.folder_label or "").lower():
                continue
            result.append(v)
        return result

    # ---------- Rendering ----------

    def render(self):
        for card in self.cards:
            card.destroy()
        self.cards = []
        self.empty_label.grid_forget()

        visible = self._visible_videos()
        if not visible:
            filtered = bool(self.search_input.get().strip()) or self.filter.get() != "All"
            self.empty_label.configure(
                text="No matching downloads." if filtered and self.videos
                else "No downloads yet.\nFinished videos will show up here."
            )
            self.empty_label.grid(row=0, column=0, columnspan=max(1, self.columns), pady=80)
            return

        for video in visible:
            self.cards.append(VideoCard(self.scroll, video, self.on_open, self.on_reveal, self.on_delete))
        self.columns = 0  # force a full re-layout
        self._layout()

    def _on_resize(self, event):
        if abs(event.width - self.last_width) < 4:
            return  # height-only change (content grew); nothing to re-flow
        self.last_width = event.width
        if self.layout_job:
            self.after_cancel(self.layout_job)
        self.layout_job = self.after(60, self._layout)

    def _layout(self):
        self.layout_job = None
        width = max(self.scroll.winfo_width(), MIN_CARD_WIDTH)
        columns = max(1, width // (MIN_CARD_WIDTH + GAP))
        card_width = width // columns - GAP  # every card has GAP/2 padding on both sides

        if columns != self.columns:
            for col in range(max(columns, self.columns)):
                self.scroll.grid_columnconfigure(col, weight=1 if col < columns else 0,
                                                 uniform="cards" if col < columns else "")
            for i, card in enumerate(self.cards):
                card.grid(row=i // columns, column=i % columns, sticky="nsew", padx=GAP // 2, pady=(0, GAP))
            self.columns = columns
        for card in self.cards:
            card.set_card_width(card_width)
