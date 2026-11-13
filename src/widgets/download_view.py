from collections.abc import Callable

import customtkinter as ctk

from config import theme
from models.media import MediaInfo
from widgets.art import empty_illustration, hero_banner
from widgets.icons import icon
from widgets.preview_card import DownloadHandler, PreviewCard
from widgets.progress_card import ProgressCard
from widgets.scroll import AutoScrollFrame

HERO_HEIGHT = 168
HERO_TITLE = "Download anything from YouTube"
HERO_SUBTITLE = "Videos, whole playlists and MP3 audio, in the quality you choose."


class DownloadView(ctk.CTkFrame):
    """The 'Download' page: hero banner, link bar, then empty state / preview / progress."""

    def __init__(
        self,
        parent,
        on_fetch: Callable[[], None],
        on_paste: Callable[[], None],
        on_download: DownloadHandler,
        on_cancel: Callable[[], None],
        audio_format: str,
        warning: str | None = None,
    ):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self.hero_width = 0
        self.hero_job: str | None = None

        # --- Hero banner (re-rendered to fit the width); shown only while nothing is loaded ---
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.hero = ctk.CTkLabel(self.header, text="", height=HERO_HEIGHT)
        self.hero.bind("<Configure>", self._on_hero_resize)
        # Compact title used once a video is previewed/downloading, to leave room for it.
        self.compact_title = ctk.CTkFrame(self.header, fg_color="transparent")
        ctk.CTkLabel(self.compact_title, text="New download", anchor="w", font=theme.font(30, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(self.compact_title, text=HERO_SUBTITLE, anchor="w", text_color=theme.MUTED,
                     font=theme.font(14)).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # --- Link bar ---
        bar = ctk.CTkFrame(self, **theme.card(corner_radius=18))
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bar, text="", image=icon("search", 18, theme.MUTED), width=24).grid(
            row=0, column=0, padx=(20, 6), pady=10
        )
        self.url_input = ctk.CTkEntry(
            bar, placeholder_text="Paste a YouTube video or playlist link…", height=46, border_width=0,
            fg_color="transparent", font=theme.font(15), placeholder_text_color=theme.SUBTLE,
        )
        self.url_input.grid(row=0, column=1, sticky="ew", pady=10)
        self.url_input.bind("<Return>", lambda _e: on_fetch())
        ctk.CTkButton(
            bar, text=" Paste", width=100, height=44, corner_radius=13, font=theme.font(13, "bold"),
            image=icon("clipboard", 16, theme.TEXT), command=on_paste, **theme.secondary(),
        ).grid(row=0, column=2, padx=(8, 6), pady=10)
        self.fetch_button = ctk.CTkButton(
            bar, text="Fetch", width=118, height=44, corner_radius=13, font=theme.font(14, "bold"),
            command=on_fetch, **theme.primary(),
        )
        self.fetch_button.grid(row=0, column=3, padx=(0, 10), pady=10)

        # --- Missing ffmpeg / Deno warning ---
        if warning:
            banner = ctk.CTkFrame(self, corner_radius=14, fg_color=theme.WARNING_SOFT)
            banner.grid(row=2, column=0, sticky="ew", pady=(12, 0))
            banner.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(banner, text="", image=icon("alert", 18, theme.WARNING)).grid(
                row=0, column=0, padx=(16, 10), pady=12
            )
            ctk.CTkLabel(
                banner, anchor="w", justify="left", wraplength=760, text_color=theme.TEXT, font=theme.font(12),
                text=warning,
            ).grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=12)

        # --- Content: one of empty state / preview / progress ---
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=4, column=0, sticky="nsew", pady=(18, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.empty_state = self._build_empty_state(self.content)
        # The preview lives in a page that scrolls when it's taller than the window (long playlists).
        self.preview_scroll = AutoScrollFrame(self.content, fg_color="transparent")
        self.preview_scroll.grid_columnconfigure(0, weight=1)
        self.preview = PreviewCard(self.preview_scroll, on_download=on_download, audio_format=audio_format,
                                   on_state_change=self._on_preview_state)
        self.preview.grid(row=0, column=0, sticky="ew")
        self.progress = ProgressCard(self.content, on_cancel=on_cancel)

        # --- Sticky action bar for playlists (always visible while scrolling the list) ---
        self.action_bar = ctk.CTkFrame(self, **theme.card(corner_radius=18))
        self.action_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.action_bar, text="", image=icon("list", 18, theme.ACCENT), width=40, height=40,
                     corner_radius=12, fg_color=theme.ACCENT_SOFT).grid(row=0, column=0, padx=(14, 12), pady=12)
        self.action_summary = ctk.CTkLabel(self.action_bar, text="", anchor="w", font=theme.font(14, "bold"))
        self.action_summary.grid(row=0, column=1, sticky="w")
        self.action_button = ctk.CTkButton(
            self.action_bar, text="Download", width=230, height=46, corner_radius=14, font=theme.font(15, "bold"),
            image=icon("download", 18, theme.WHITE), command=self.preview.download, **theme.primary(),
        )
        self.action_button.grid(row=0, column=2, padx=12, pady=12)
        self.show_empty()

    # ---------- Hero ----------

    def _on_hero_resize(self, event):
        if abs(event.width - self.hero_width) < 6 or event.width < 50:
            return
        self.hero_width = event.width
        if self.hero_job:
            self.after_cancel(self.hero_job)
        self.hero_job = self.after(40, self._render_hero)

    def _render_hero(self):
        self.hero_job = None
        width = self.hero_width
        image = hero_banner(width, HERO_HEIGHT, HERO_TITLE, HERO_SUBTITLE)
        self.hero_img = ctk.CTkImage(image, image, size=(width, HERO_HEIGHT))
        self.hero.configure(image=self.hero_img)

    # ---------- Empty state ----------

    @staticmethod
    def _build_empty_state(parent) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, **theme.card())
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.place(relx=0.5, rely=0.48, anchor="center")
        art_light = empty_illustration(150, theme.ACCENT[0], "#FFFFFF", "#D2D2DA")
        art_dark = empty_illustration(150, theme.ACCENT[1], "#1A1A21", "#34343F")
        frame.art = ctk.CTkImage(art_light, art_dark, size=(150, 150))  # keep a reference
        ctk.CTkLabel(inner, text="", image=frame.art).grid(row=0, column=0)
        ctk.CTkLabel(inner, text="Ready when you are", font=theme.font(22, "bold")).grid(row=1, column=0, pady=(10, 6))
        ctk.CTkLabel(
            inner, text="Paste a link above and press Fetch. You'll see every\navailable quality before anything downloads.",
            justify="center", text_color=theme.MUTED, font=theme.font(14),
        ).grid(row=2, column=0)

        features = ctk.CTkFrame(inner, fg_color="transparent")
        features.grid(row=3, column=0, pady=(24, 0))
        for col, (glyph, text) in enumerate((("monitor", "Up to 4K"), ("list", "Whole playlists"),
                                             ("music", "MP3 audio"))):
            ctk.CTkLabel(
                features, text=f"  {text}", image=icon(glyph, 15, theme.ACCENT), compound="left",
                height=36, corner_radius=18, fg_color=theme.SECONDARY, text_color=theme.TEXT,
                font=theme.font(12, "bold"), padx=16,
            ).grid(row=0, column=col, padx=5)
        return frame

    # ---------- Switching content ----------

    def _on_preview_state(self, is_playlist: bool, text: str, enabled: bool, summary: str):
        self.action_button.configure(text=text, state="normal" if enabled else "disabled")
        self.action_summary.configure(text=summary)

    def _show(self, widget, sticky="nsew"):
        for child in (self.empty_state, self.preview_scroll, self.progress):
            child.grid_forget()
        show_bar = widget is self.preview_scroll and bool(self.preview.media and self.preview.media.is_playlist)
        if show_bar:
            self.action_bar.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        else:
            self.action_bar.grid_forget()
        widget.grid(row=0, column=0, sticky=sticky)
        if widget is self.empty_state:
            self.compact_title.grid_forget()
            self.hero.grid(row=0, column=0, sticky="ew")
        else:
            self.hero.grid_forget()
            self.compact_title.grid(row=0, column=0, sticky="ew")

    def show_empty(self):
        self._show(self.empty_state)

    def show_preview(self, media: MediaInfo):
        self.preview.show(media)
        self.show_preview_again()
        self.preview_scroll.scroll_to_top()

    def clear_preview(self):
        self.preview.media = None
        self.show_empty()

    def show_preview_again(self):
        if self.preview.media is None:
            self.show_empty()
            return
        self._show(self.preview_scroll)

    def show_progress(self):
        self._show(self.progress, sticky="new")

    def set_fetching(self, fetching: bool, busy: bool):
        self.fetch_button.configure(
            state="disabled" if busy else "normal",
            text="Fetching…" if fetching else "Fetch",
        )
