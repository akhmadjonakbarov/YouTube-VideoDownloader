from collections.abc import Callable

import customtkinter as ctk

from config import theme
from config.settings import MAX_PLAYLIST_CHECKLIST
from models.media import MediaInfo, QualityOption
from services.formatting import format_duration, format_size, quality_tag, truncate
from services.video_downloader import default_quality
from widgets.art import check_badge
from widgets.hover import bind_click, bind_hover
from widgets.icons import icon
from widgets.images import rounded_thumbnail

THUMB = (304, 171)

DownloadHandler = Callable[[MediaInfo, QualityOption, list[int] | None], None]
# (is_playlist, button text, enabled, selection summary) -> None
StateHandler = Callable[[bool, str, bool, str], None]


_CHECK_IMAGE: ctk.CTkImage | None = None


def _check_image() -> ctk.CTkImage:
    global _CHECK_IMAGE
    if _CHECK_IMAGE is None:
        _CHECK_IMAGE = ctk.CTkImage(check_badge(20, theme.ACCENT[0]), check_badge(20, theme.ACCENT[1]), size=(20, 20))
    return _CHECK_IMAGE


class QualityCard(ctk.CTkFrame):
    """One selectable quality: big label, small detail line, check mark when selected."""

    WIDTH, HEIGHT = 116, 68

    def __init__(self, parent, option: QualityOption, title: str, detail: str, on_select: Callable[[QualityOption], None]):
        super().__init__(parent, width=self.WIDTH, height=self.HEIGHT, corner_radius=14, border_width=1,
                         fg_color=theme.CARD_ALT, border_color=theme.BORDER)
        self.grid_propagate(False)
        self.option = option
        self.selected = False
        self.hovered = False

        self.title_label = ctk.CTkLabel(self, text=title, anchor="w", font=theme.font(15, "bold"), height=20)
        self.title_label.place(x=14, y=13)
        self.detail_label = ctk.CTkLabel(self, text=detail, anchor="w", text_color=theme.MUTED,
                                         font=theme.font(11), height=16)
        self.detail_label.place(x=14, y=37)
        self.check = ctk.CTkLabel(self, text="", image=_check_image(), width=20, height=20)

        bind_click(self, lambda: on_select(self.option))
        bind_hover(self, self._enter, self._leave, cursor="hand2")

    def set_selected(self, selected: bool):
        self.selected = selected
        if selected:
            self.check.place(relx=1.0, x=-10, y=10, anchor="ne")
        else:
            self.check.place_forget()
        self._paint()

    def _enter(self):
        self.hovered = True
        self._paint()

    def _leave(self):
        self.hovered = False
        self._paint()

    def _paint(self):
        if self.selected:
            self.configure(fg_color=theme.ACCENT_SOFT, border_color=theme.ACCENT, border_width=2)
            self.title_label.configure(text_color=theme.ACCENT_TEXT)
        else:
            self.configure(fg_color=theme.CARD_ALT, border_width=1,
                           border_color=theme.BORDER_STRONG if self.hovered else theme.BORDER)
            self.title_label.configure(text_color=theme.TEXT)


class QualityChips(ctk.CTkFrame):
    """The grid of quality cards."""

    COLUMNS = 4

    def __init__(self, parent, on_change: Callable[[], None]):
        super().__init__(parent, fg_color="transparent")
        self.on_change = on_change
        self.chips: list[QualityCard] = []
        self.selected: QualityOption | None = None

    def set_options(self, options: list[QualityOption], selected: QualityOption, audio_format: str):
        for chip in self.chips:
            chip.destroy()
        self.chips = []
        for i, option in enumerate(options):
            title, detail = self._texts(option, audio_format)
            chip = QualityCard(self, option, title, detail, on_select=self.select)
            chip.grid(row=i // self.COLUMNS, column=i % self.COLUMNS, padx=(0, 10), pady=(0, 10), sticky="w")
            self.chips.append(chip)
        self.select(selected, notify=False)

    @staticmethod
    def _texts(option: QualityOption, audio_format: str) -> tuple[str, str]:
        if option.audio_only:
            return "Audio", f"{audio_format} only"
        if option.height is None:
            return "Best", "Highest available"
        detail = f"~{format_size(option.size_bytes)}" if option.size_bytes else quality_tag(option.height)
        return option.label, detail

    def select(self, option: QualityOption, notify: bool = True):
        self.selected = option
        for chip in self.chips:
            chip.set_selected(chip.option == option)
        if notify:
            self.on_change()


class PreviewCard(ctk.CTkFrame):
    """A fetched video/playlist: thumbnail, details, quality cards, playlist checklist."""

    def __init__(self, parent, on_download: DownloadHandler, audio_format: str,
                 on_state_change: StateHandler | None = None):
        super().__init__(parent, **theme.card())
        self.on_download = on_download
        self.on_state_change = on_state_change
        self.audio_format = audio_format
        self.media: MediaInfo | None = None
        self.entry_vars: list[tuple[int, ctk.BooleanVar]] = []
        self.checklist_shown = False

        self.grid_columnconfigure(1, weight=1)

        # --- Thumbnail (badge drawn into the image) ---
        self.thumb_img = ctk.CTkImage(rounded_thumbnail(None, THUMB, 16), size=THUMB)
        self.thumb = ctk.CTkLabel(self, text="", image=self.thumb_img, width=THUMB[0], height=THUMB[1])
        self.thumb.grid(row=0, column=0, sticky="nw", padx=(24, 24), pady=24)

        # --- Details ---
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=1, sticky="nsew", padx=(0, 24), pady=24)
        info.grid_columnconfigure(0, weight=1)

        self.kind_pill = ctk.CTkLabel(
            info, text="VIDEO", height=24, corner_radius=12, fg_color=theme.ACCENT_SOFT,
            text_color=theme.ACCENT_TEXT, font=theme.font(10, "bold"),
        )
        self.kind_pill.grid(row=0, column=0, sticky="w")
        self.title_label = ctk.CTkLabel(
            info, text="", anchor="w", justify="left", wraplength=540, font=theme.font(21, "bold")
        )
        self.title_label.grid(row=1, column=0, sticky="ew", pady=(12, 4))
        self.meta_label = ctk.CTkLabel(info, text="", anchor="w", text_color=theme.MUTED, font=theme.font(13))
        self.meta_label.grid(row=2, column=0, sticky="ew")

        ctk.CTkLabel(info, text="CHOOSE QUALITY", anchor="w", text_color=theme.SUBTLE,
                     font=theme.font(11, "bold")).grid(row=3, column=0, sticky="w", pady=(20, 10))
        self.chips = QualityChips(info, on_change=self._refresh_button)
        self.chips.grid(row=4, column=0, sticky="w")

        self.download_button = ctk.CTkButton(
            info, text="Download", height=48, width=250, corner_radius=14, font=theme.font(15, "bold"),
            image=icon("download", 18, theme.WHITE), command=self._download, **theme.primary(),
        )
        self.download_button.grid(row=5, column=0, sticky="w", pady=(10, 0))

        # --- Playlist checklist ---
        self.playlist_section = ctk.CTkFrame(self, fg_color="transparent")
        self.playlist_section.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(self.playlist_section, height=1, fg_color=theme.BORDER).grid(
            row=0, column=0, sticky="ew", pady=(0, 16)
        )
        head = ctk.CTkFrame(self.playlist_section, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="Videos in this playlist", font=theme.font(15, "bold")).grid(row=0, column=0, sticky="w")
        self.selection_label = ctk.CTkLabel(head, text="", height=24, corner_radius=12, fg_color=theme.SECONDARY,
                                            text_color=theme.MUTED, font=theme.font(12, "bold"))
        self.selection_label.grid(row=0, column=1, sticky="w", padx=12)
        self.select_all_var = ctk.BooleanVar(value=True)
        self.select_all = ctk.CTkCheckBox(
            head, text="Select all", variable=self.select_all_var, command=self._toggle_all,
            font=theme.font(13), checkbox_width=20, checkbox_height=20, corner_radius=6,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, border_color=theme.SUBTLE,
        )
        self.select_all.grid(row=0, column=2, sticky="e")

        # The whole page scrolls (see DownloadView), so the list itself doesn't need to.
        self.entries_list = ctk.CTkFrame(self.playlist_section, corner_radius=14, fg_color=theme.CARD_ALT)
        self.entries_note = ctk.CTkLabel(
            self.playlist_section, text="", anchor="w", justify="left", wraplength=600,
            text_color=theme.MUTED, font=theme.font(13),
        )

    # ---------- Public ----------

    def show(self, media: MediaInfo):
        self.media = media

        badge = f"{len(media.entries)} videos" if media.is_playlist else format_duration(media.duration)
        source = rounded_thumbnail(media.thumbnail, THUMB, 16, badge=badge or None)
        self.thumb_img = ctk.CTkImage(source, source, size=THUMB)
        self.thumb.configure(image=self.thumb_img)

        self.kind_pill.configure(text="   PLAYLIST   " if media.is_playlist else "   VIDEO   ")
        self.title_label.configure(text=truncate(media.title, 110))
        meta = [media.uploader] if media.uploader else []
        if media.is_playlist:
            meta.append(f"{len(media.entries)} videos")
        elif media.duration:
            meta.append(format_duration(media.duration))
        self.meta_label.configure(text="  ·  ".join(meta))

        self.chips.set_options(media.qualities, default_quality(media.qualities), self.audio_format)
        self._build_checklist(media)
        self._refresh_button()

    def selected_quality(self) -> QualityOption | None:
        return self.chips.selected

    def selected_items(self) -> list[int] | None:
        """Playlist positions to download, or None for "everything"."""
        if not self.media or not self.media.is_playlist or not self.checklist_shown:
            return None
        chosen = [index for index, var in self.entry_vars if var.get()]
        return None if len(chosen) == len(self.entry_vars) else chosen

    def selected_count(self) -> int:
        if not self.media:
            return 0
        if not self.media.is_playlist:
            return 1
        if not self.checklist_shown:
            return len(self.media.entries)
        return sum(1 for _index, var in self.entry_vars if var.get())

    # ---------- Internals ----------

    def _build_checklist(self, media: MediaInfo):
        for widget in self.entries_list.winfo_children():
            widget.destroy()
        self.entry_vars = []
        self.checklist_shown = False

        if not media.is_playlist:
            self.playlist_section.grid_forget()
            self.download_button.grid()
            return

        self.download_button.grid_remove()  # playlists use the sticky action bar instead
        self.playlist_section.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=24, pady=(0, 24))
        self.select_all_var.set(True)

        if len(media.entries) > MAX_PLAYLIST_CHECKLIST:
            self.entries_list.grid_forget()
            self.select_all.configure(state="disabled")
            self.entries_note.configure(
                text=f"This playlist is large, so all {len(media.entries)} videos will be downloaded."
            )
            self.entries_note.grid(row=2, column=0, sticky="nw")
            return

        self.checklist_shown = True
        self.select_all.configure(state="normal")
        self.entries_note.grid_forget()
        self.entries_list.grid(row=2, column=0, sticky="ew")
        for row, entry in enumerate(media.entries):
            var = ctk.BooleanVar(value=True)
            ctk.CTkLabel(self.entries_list, text=f"{entry.index:02d}", width=28, text_color=theme.SUBTLE,
                         font=theme.font(12, "bold")).grid(row=row, column=0, sticky="w", padx=(16, 0), pady=(12 if row == 0 else 5, 5))
            ctk.CTkCheckBox(
                self.entries_list, text=truncate(entry.title, 72), variable=var,
                command=self._on_entry_toggled, font=theme.font(13), checkbox_width=18, checkbox_height=18,
                corner_radius=5, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, border_color=theme.SUBTLE,
            ).grid(row=row, column=1, sticky="w", padx=(6, 8), pady=(12 if row == 0 else 5, 5))
            if entry.duration:
                ctk.CTkLabel(
                    self.entries_list, text=format_duration(entry.duration), text_color=theme.MUTED,
                    font=theme.font(12),
                ).grid(row=row, column=2, sticky="e", padx=(8, 16), pady=(12 if row == 0 else 5, 5))
            self.entry_vars.append((entry.index, var))
        # bottom padding after the last row
        ctk.CTkFrame(self.entries_list, width=1, height=8, fg_color="transparent").grid(row=len(media.entries), column=0)
        self.entries_list.grid_columnconfigure(0, weight=0)
        self.entries_list.grid_columnconfigure(1, weight=1)

    def _toggle_all(self):
        value = self.select_all_var.get()
        for _index, var in self.entry_vars:
            var.set(value)
        self._refresh_button()

    def _on_entry_toggled(self):
        self.select_all_var.set(all(var.get() for _index, var in self.entry_vars))
        self._refresh_button()

    def _refresh_button(self):
        option = self.selected_quality()
        audio = bool(option and option.audio_only)
        if self.media and self.media.is_playlist:
            count = self.selected_count()
            self.selection_label.configure(text=f"   {count} of {len(self.media.entries)} selected   ")
            noun = ("track" if audio else "video") + ("" if count == 1 else "s")
            text = f"Download {count} {noun}"
        else:
            count = 1
            text = "Download audio" if audio else "Download video"
        enabled = bool(count and option)
        self.download_button.configure(text=text, state="normal" if enabled else "disabled")
        if self.on_state_change and self.media:
            summary = ""
            if self.media.is_playlist and option:
                summary = f"{count} of {len(self.media.entries)} selected  ·  {QualityChips._texts(option, self.audio_format)[0]}"
            self.on_state_change(self.media.is_playlist, text, enabled, summary)

    def download(self):
        self._download()

    def _download(self):
        option = self.selected_quality()
        if self.media and option and self.selected_count():
            self.on_download(self.media, option, self.selected_items())
