"""The playlist detail page: every video of a playlist download and how far it got."""
from collections.abc import Callable

import customtkinter as ctk

from config import theme
from config.i18n import t, tn
from services import download_queue as dq
from services.download_queue import EntryState, QueueItem
from services.formatting import format_duration, format_speed, truncate
from widgets.icons import icon
from widgets.images import rounded_thumbnail
from widgets.queue_view import ActionHandler, status_text
from widgets.scroll import AutoScrollFrame, bind_visible_resize

THUMB = (192, 108)


def entry_status(item: QueueItem, entry: EntryState) -> tuple[str, str]:
    """(text, kind) for one video; kind is "done", "failed", "active", "paused" or "idle"."""
    if entry.state == dq.ENTRY_DONE:
        return t("entry.saved"), "done"
    if entry.state == dq.ENTRY_FAILED:
        return t("entry.failed"), "failed"
    if item.status == dq.CANCELLED:
        return t("entry.cancelled"), "idle"
    if item.status in (dq.FAILED, dq.COMPLETED):
        return t("entry.not_downloaded"), "idle"
    if not entry.running:
        if entry.state == dq.ENTRY_WAITING:
            return t("entry.waiting"), "idle"
        # Started earlier and stopped part-way (keeps its progress bar).
        if item.status in (dq.PAUSED, dq.PAUSING):
            return t("entry.paused"), "paused"
        return t("entry.waiting"), "paused"

    # Being downloaded right now.
    if item.status == dq.PAUSING:
        return t("queue.status.pausing"), "paused"
    parts = [t(f"stage.{entry.stage}") if entry.stage else t("queue.status.starting")]
    if entry.stage in dq.DOWNLOAD_STAGES:
        if entry.speed:
            parts.append(format_speed(entry.speed))
        if entry.eta is not None:
            parts.append(t("progress.left", time=format_duration(entry.eta)))
    return "  ·  ".join(parts), "active"


class EntryRow(ctk.CTkFrame):
    """One video: number, title and status on one line. The video being downloaded
    gets a second line with live details and a progress bar."""

    def __init__(self, parent, entry: EntryState):
        super().__init__(parent, fg_color="transparent", corner_radius=12, border_width=1,
                         border_color=theme.BG)
        self.grid_columnconfigure(1, weight=1)
        self.number = ctk.CTkLabel(self, text=str(entry.index), width=30, height=30, corner_radius=9,
                                   fg_color=theme.SECONDARY, text_color=theme.MUTED, font=theme.font(12, "bold"))
        self.number.grid(row=0, column=0, rowspan=1, padx=(10, 14), pady=7)
        self.title = ctk.CTkLabel(self, text=truncate(entry.title, 90), anchor="w", font=theme.font(13, "bold"))
        self.title.grid(row=0, column=1, sticky="w")
        self.status = ctk.CTkLabel(self, text="", anchor="e", font=theme.font(12), text_color=theme.MUTED)
        self.duration = ctk.CTkLabel(self, text=format_duration(entry.duration) if entry.duration else "",
                                     text_color=theme.SUBTLE, font=theme.font(12), width=50, anchor="e")
        self.duration.grid(row=0, column=3, padx=(12, 8))
        self.mark = ctk.CTkLabel(self, text="", width=42, anchor="e", font=theme.font(13, "bold"))
        self.mark.grid(row=0, column=4, padx=(0, 12))
        self.bar: ctk.CTkProgressBar | None = None
        self.shown: tuple | None = None
        self.current = False

    def update_entry(self, item: QueueItem, entry: EntryState):
        text, kind = entry_status(item, entry)
        percent = int(entry.fraction * 100)
        signature = (text, kind, percent)
        if signature == self.shown:
            return
        self.shown = signature

        colors = {"done": theme.SUCCESS, "failed": theme.ERROR, "active": theme.ACCENT_TEXT,
                  "paused": theme.WARNING, "idle": theme.SUBTLE}
        self.status.configure(text=text, text_color=colors[kind])
        current = kind in ("active", "paused")
        if current != self.current or self.shown is None or not self.status.winfo_manager():
            self.status.grid_forget()
            if current:  # live details under the title
                self.status.grid(row=1, column=1, columnspan=3, sticky="w", pady=(0, 2))
                for widget in (self.number, self.duration, self.mark):
                    widget.grid_configure(rowspan=2)
                self.number.grid_configure(pady=12)
            else:
                self.status.grid(row=0, column=2, sticky="e")
                for widget in (self.number, self.duration, self.mark):
                    widget.grid_configure(rowspan=1)
                self.number.grid_configure(pady=7)
            self.current = current
        self.configure(fg_color=theme.CARD if current else "transparent",
                       border_color=theme.BORDER_STRONG if current else theme.BG)
        self.title.grid_configure(pady=(10, 0) if current else 0)
        self.title.configure(text_color=theme.MUTED if kind in ("idle", "failed") else theme.TEXT)
        self.number.configure(
            fg_color=theme.ACCENT if kind == "active" else theme.SECONDARY,
            text_color=theme.WHITE if kind == "active" else theme.MUTED,
        )

        if kind == "done":
            self.mark.configure(text="", image=icon("check", 16, theme.SUCCESS))
        elif kind == "failed":
            self.mark.configure(text="", image=icon("alert", 16, theme.ERROR))
        elif current:
            self.mark.configure(text=f"{percent}%", image=None, text_color=theme.TEXT)
        else:
            self.mark.configure(text="", image=None)

        if current:
            if self.bar is None:
                self.bar = ctk.CTkProgressBar(self, height=5, corner_radius=3, fg_color=theme.SECONDARY,
                                              progress_color=theme.ACCENT)
            self.bar.configure(progress_color=theme.ACCENT if kind == "active" else theme.SUBTLE)
            self.bar.set(entry.fraction)
            self.bar.grid(row=2, column=1, columnspan=4, sticky="ew", padx=(0, 12), pady=(6, 12))
        elif self.bar is not None:
            self.bar.grid_forget()

    def set_wraplength(self, width: int):
        pass  # titles are kept to one line


class PlaylistView(ctk.CTkFrame):
    """Shown when a playlist in the Downloads list is clicked."""

    def __init__(self, parent, on_back: Callable[[], None], on_action: ActionHandler):
        super().__init__(parent, fg_color="transparent")
        self.on_action = on_action
        self.item_id: int | None = None
        self.followed: int | None = None  # playlist index the list last scrolled to
        self.rows: dict[int, EntryRow] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkButton(self, text=f" {t('playlist.back')}", image=icon("arrow-left", 15, theme.MUTED), anchor="w",
                      height=34, corner_radius=10, font=theme.font(13, "bold"), command=on_back,
                      **theme.ghost()).grid(row=0, column=0, sticky="w", pady=(0, 14))

        # Header: thumbnail, title, overall status, progress and actions.
        self.header = header = ctk.CTkFrame(self, **theme.card(corner_radius=20))
        header.grid(row=1, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        self.thumb = ctk.CTkLabel(header, text="")
        self.thumb.grid(row=0, column=0, rowspan=4, padx=(18, 20), pady=18, sticky="n")
        self.title = ctk.CTkLabel(header, text="", anchor="w", justify="left", wraplength=560,
                                  font=theme.font(20, "bold"))
        self.title.grid(row=0, column=1, columnspan=2, sticky="sw", pady=(20, 0), padx=(0, 18))
        self.meta = ctk.CTkLabel(header, text="", anchor="w", text_color=theme.MUTED, font=theme.font(13))
        self.meta.grid(row=1, column=1, columnspan=2, sticky="w", pady=(4, 0))
        self.status = ctk.CTkLabel(header, text="", anchor="w", justify="left", wraplength=560,
                                   text_color=theme.MUTED, font=theme.font(13))
        self.status.grid(row=2, column=1, sticky="w", pady=(10, 6))
        self.percent = ctk.CTkLabel(header, text="", anchor="e", font=theme.font(18, "bold"))
        self.percent.grid(row=2, column=2, sticky="e", padx=(10, 18), pady=(10, 6))
        self.bar = ctk.CTkProgressBar(header, height=8, corner_radius=4, fg_color=theme.SECONDARY,
                                      progress_color=theme.ACCENT)
        self.bar.set(0)
        self.bar.grid(row=3, column=1, columnspan=2, sticky="new", padx=(0, 18), pady=(0, 20))

        self.buttons = ctk.CTkFrame(header, fg_color="transparent")
        self.buttons.grid(row=4, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 18))
        self.buttons.grid_columnconfigure(0, weight=1)
        self.counts = ctk.CTkFrame(self.buttons, fg_color="transparent")
        self.counts.grid(row=0, column=0, sticky="w")
        self.count_labels = {}
        dots = {dq.ENTRY_DONE: theme.SUCCESS, dq.ENTRY_ACTIVE: theme.ACCENT, dq.ENTRY_WAITING: theme.SUBTLE,
                dq.ENTRY_FAILED: theme.ERROR}
        for col, state in enumerate((dq.ENTRY_DONE, dq.ENTRY_ACTIVE, dq.ENTRY_WAITING, dq.ENTRY_FAILED)):
            chip = ctk.CTkFrame(self.counts, fg_color=theme.SECONDARY, corner_radius=10)
            chip.grid(row=0, column=col, padx=(0, 8))
            ctk.CTkLabel(chip, text="●", text_color=dots[state], font=theme.font(10)).grid(
                row=0, column=0, padx=(10, 6), pady=6)
            label = ctk.CTkLabel(chip, text="", font=theme.font(12, "bold"))
            label.grid(row=0, column=1, padx=(0, 12), pady=6)
            self.count_labels[state] = (chip, label)

        self.actions = ctk.CTkFrame(self.buttons, fg_color="transparent")
        self.actions.grid(row=0, column=1, sticky="e")
        self.action_buttons = {
            "pause": self._button("pause", "pause", theme.secondary()),
            "resume": self._button("play", "resume", theme.primary()),
            "folder": self._button("folder", "folder", theme.secondary()),
            "retry": self._button("refresh", "retry", theme.secondary()),
            "cancel": self._button("x", "cancel", theme.secondary()),
        }
        self.shown_actions: tuple[str, ...] = ()

        self.scroll = AutoScrollFrame(self, fg_color="transparent")
        self.scroll.grid(row=3, column=0, sticky="nsew", pady=(16, 0))
        self.scroll.grid_columnconfigure(0, weight=1)
        bind_visible_resize(self, self.scroll, self._on_resize)
        self.wrap = 520
        self.header_shown: tuple | None = None

    def _button(self, glyph: str, action: str, style: dict):
        color = theme.WHITE if style.get("fg_color") == theme.ACCENT else theme.TEXT
        style = dict(style)
        style.pop("text_color", None)
        return ctk.CTkButton(self.actions, text="", width=40, height=40, corner_radius=12,
                             image=icon(glyph, 15 if glyph != "play" else 13, color),
                             command=lambda: self.item_id is not None and self.on_action(action, self.item_id),
                             **style)

    def _on_resize(self, event):
        wrap = max(200, event.width - 230)
        if abs(wrap - self.wrap) > 8:
            self.wrap = wrap
            for row in self.rows.values():
                row.set_wraplength(wrap)
        self.title.configure(wraplength=max(240, event.width - THUMB[0] - 120))
        self.status.configure(wraplength=max(240, event.width - THUMB[0] - 200))

    def show(self, item: QueueItem):
        """Fill the page for a (new) playlist download."""
        if item.id != self.item_id:
            self.item_id = item.id
            for row in self.rows.values():
                row.destroy()
            self.rows = {}
            for n, entry in enumerate(item.entries):
                row = EntryRow(self.scroll, entry)
                row.set_wraplength(self.wrap)
                row.grid(row=n, column=0, sticky="ew", pady=(0, 4))
                self.rows[entry.index] = row
            source = rounded_thumbnail(item.media.thumbnail, THUMB, 12, badge=tn("preview.videos", item.total))
            self.thumb_img = ctk.CTkImage(source, source, size=THUMB)
            self.thumb.configure(image=self.thumb_img)
            self.title.configure(text=truncate(item.title, 120))
            quality = item.option.label if not item.option.audio_only else t("quality.audio")
            meta = [m for m in (item.media.uploader, quality, tn("preview.videos", item.total)) if m]
            self.meta.configure(text="  ·  ".join(meta))
            self.scroll._parent_canvas.yview_moveto(0)
            self.followed = None
            self.header_shown = None
        self.update_item(item)

    def update_item(self, item: QueueItem):
        if item.id != self.item_id:
            return
        status = item.status
        text = status_text(item)
        header = (text, status, item.pause_reason, item.cancelling, round(item.fraction, 3),
                  tuple(item.entry_counts().values()))
        if header == self.header_shown:
            self._update_rows(item)
            return
        self.header_shown = header
        self.status.configure(text=text)
        warn = status == dq.PAUSED and item.pause_reason in ("network", "slow", "failing")
        self.status.configure(text_color=theme.ERROR if status == dq.FAILED else
                              theme.WARNING if warn else theme.MUTED)
        self.percent.configure(text=f"{int((1.0 if status == dq.COMPLETED else item.fraction) * 100)}%",
                               text_color=theme.SUCCESS if status == dq.COMPLETED else theme.TEXT)
        self.bar.configure(progress_color=theme.SUCCESS if status == dq.COMPLETED else
                           theme.ACCENT if status == dq.RUNNING else theme.SUBTLE)
        self.bar.set(1.0 if status == dq.COMPLETED else item.fraction)

        counts = item.entry_counts()
        for state, (chip, label) in self.count_labels.items():
            label.configure(text=f"{t('playlist.count.' + state)}  {counts[state]}")
            if counts[state] or state in (dq.ENTRY_DONE, dq.ENTRY_WAITING):
                chip.grid()
            else:
                chip.grid_remove()

        if status in (dq.RUNNING, dq.QUEUED, dq.PAUSING):
            actions = ("folder", "pause", "cancel")
        elif status == dq.PAUSED:
            actions = ("folder", "resume", "cancel")
        elif status == dq.COMPLETED:
            actions = ("folder",)
        else:
            actions = ("retry",)
        if actions != self.shown_actions:
            for button in self.action_buttons.values():
                button.grid_forget()
            for col, name in enumerate(actions):
                self.action_buttons[name].grid(row=0, column=col, padx=(8, 0))
            self.shown_actions = actions
        self.action_buttons["pause"].configure(
            state="disabled" if status == dq.PAUSING or item.cancelling else "normal")
        self.action_buttons["cancel"].configure(state="disabled" if item.cancelling else "normal")
        self._update_rows(item)

    def _update_rows(self, item: QueueItem):
        for entry in item.entries:
            row = self.rows.get(entry.index)
            if row is not None:
                row.update_entry(item, entry)

        # Keep the videos being downloaded in view as the playlist moves on.
        active = [e.index for e in item.entries if e.running]
        if active and active[0] != self.followed:
            self.followed = active[0]
            self.after(60, lambda: self._scroll_to(active[0], active[-1]))

    def _scroll_to(self, first: int, last: int):
        top_row, bottom_row = self.rows.get(first), self.rows.get(last)
        if top_row is None or bottom_row is None or not top_row.winfo_exists():
            return
        canvas = self.scroll._parent_canvas
        total = self.scroll.winfo_height()
        view = canvas.winfo_height()
        if total <= view:
            return
        top, bottom = canvas.yview()
        y0 = top_row.winfo_y()
        y1 = bottom_row.winfo_y() + bottom_row.winfo_height() + 60  # room for the active rows to grow
        if y0 >= top * total and y1 <= bottom * total:
            return  # already visible
        context = 2 * 48  # a couple of finished videos above
        target = max(0, min(y0 - context, y1 - view)) if y1 - y0 < view else y0 - 8
        canvas.yview_moveto(max(0, target) / total)
