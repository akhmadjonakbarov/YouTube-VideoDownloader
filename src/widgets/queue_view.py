from collections.abc import Callable

import customtkinter as ctk

from config import theme
from config.i18n import t, tn
from services import download_queue as dq
from services.download_queue import QueueItem
from services.formatting import format_duration, format_speed, truncate
from widgets.icons import icon
from widgets.images import rounded_thumbnail
from widgets.scroll import AutoScrollFrame, bind_visible_resize

THUMB = (144, 81)

# on_action(action, item_id): "pause", "resume", "cancel", "remove", "retry", "play", "folder", "details"
ActionHandler = Callable[[str, int], None]


def status_text(item: QueueItem) -> str:
    if item.cancelling:
        return t("queue.status.cancelling")
    if item.status == dq.QUEUED:
        return t("queue.status.queued")
    if item.status == dq.PAUSING:
        return t("queue.status.pausing")
    if item.status == dq.PAUSED:
        return t(f"queue.status.paused.{item.pause_reason or 'user'}")
    if item.status == dq.COMPLETED:
        result = item.result
        if result and result.total > 1 and result.completed < result.total:
            return t("queue.status.completed_partial", done=result.completed, total=result.total,
                     failed=result.total - result.completed)
        return t("queue.status.completed")
    if item.status == dq.FAILED:
        return t("queue.status.failed", message=truncate(item.error or "", 120))
    if item.status == dq.CANCELLED:
        return t("queue.status.cancelled")

    if item.per_video:  # several videos of the playlist at once
        running = len(item.running_tasks)
        parts = [tn("queue.videos_running", running) if running else t("queue.status.starting")]
        if item.speed:
            parts.append(format_speed(item.speed))
        parts.append(t("queue.saved_of", done=item.saved_count, total=item.total))
        return "  ·  ".join(parts)

    p = item.progress  # running
    if p is None:
        return t("queue.status.starting")
    parts = []
    if item.is_playlist and p.item_number:
        parts.append(t("progress.video_n", n=min(p.item_number, item.total), total=item.total))
    parts.append(t(f"stage.{p.stage}"))
    if p.stage in dq.DOWNLOAD_STAGES:
        if p.speed:
            parts.append(format_speed(p.speed))
        if p.eta is not None:
            parts.append(t("progress.left", time=format_duration(p.eta)))
    return "  ·  ".join(parts)


class QueueItemCard(ctk.CTkFrame):
    """One download in the list: thumbnail, title, status, progress bar and actions."""

    def __init__(self, parent, item: QueueItem, on_action: ActionHandler):
        super().__init__(parent, **theme.card(corner_radius=18))
        self.item_id = item.id
        self.on_action = on_action
        self.grid_columnconfigure(1, weight=1)

        source = rounded_thumbnail(item.media.thumbnail, THUMB, 10,
                                   badge=tn("preview.videos", item.total) if item.is_playlist else None)
        self.thumb_img = ctk.CTkImage(source, source, size=THUMB)
        self.thumb_label = ctk.CTkLabel(self, text="", image=self.thumb_img)
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=(14, 16), pady=14)

        self.title_label = ctk.CTkLabel(self, text=truncate(item.title, 90), anchor="w", justify="left",
                                        wraplength=480, font=theme.font(14, "bold"))
        self.title_label.grid(row=0, column=1, sticky="sew", pady=(14, 0))
        quality = item.option.label if not item.option.audio_only else t("quality.audio")
        self.status_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=480,
                                         text_color=theme.MUTED, font=theme.font(12))
        self.status_label.grid(row=1, column=1, sticky="ew", pady=(2, 6))
        self.quality_pill = ctk.CTkLabel(self, text=f"  {quality}  ", height=22, corner_radius=8,
                                         fg_color=theme.SECONDARY, text_color=theme.MUTED, font=theme.font(11, "bold"))
        self.quality_pill.grid(row=0, column=2, sticky="se", padx=(10, 0), pady=(14, 0))
        self.percent_label = ctk.CTkLabel(self, text="", anchor="e", font=theme.font(15, "bold"), width=48)
        self.percent_label.grid(row=1, column=2, sticky="e", padx=(10, 0))
        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=theme.SECONDARY,
                                      progress_color=theme.ACCENT)
        self.bar.set(0)
        self.bar.grid(row=2, column=1, columnspan=2, sticky="new", pady=(0, 16))

        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.grid(row=0, column=3, rowspan=3, padx=(14, 14))
        make = self._icon_button
        self.btn = {
            "pause": make("pause", theme.TEXT, "pause"),
            "resume": make("play", theme.WHITE, "resume", primary=True),
            "play": make("play", theme.WHITE, "play", primary=True),
            "folder": make("folder", theme.TEXT, "folder"),
            "retry": make("refresh", theme.TEXT, "retry"),
            "cancel": make("x", theme.TEXT, "cancel"),
            "remove": make("x", theme.MUTED, "remove", ghost=True),
        }
        self.is_playlist = item.is_playlist
        if item.is_playlist:
            # Playlists open a page with every video; the whole card (except its buttons) is clickable.
            self.videos_button = ctk.CTkButton(
                self.buttons, text=t("queue.show_videos"), height=38, corner_radius=12, compound="right",
                image=icon("chevron-right", 13, theme.MUTED), font=theme.font(12, "bold"),
                command=lambda: self.on_action("details", self.item_id), **theme.secondary(),
            )
            self.videos_button.grid(row=0, column=0, padx=(0, 6))
            open_details = lambda _e: self.on_action("details", self.item_id)
            for widget in (self, self.thumb_label, self.title_label, self.status_label, self.percent_label,
                           self.quality_pill, self.bar):
                widget.bind("<Button-1>", open_details, add="+")
                try:
                    widget.configure(cursor="hand2")
                except Exception:
                    pass
        self.shown: tuple[str, ...] = ()
        self.signature: tuple | None = None
        self.update_item(item)

    def _icon_button(self, glyph: str, color, action: str, primary: bool = False, ghost: bool = False):
        style = theme.primary() if primary else theme.ghost() if ghost else theme.secondary()
        style.pop("text_color", None)
        return ctk.CTkButton(self.buttons, text="", width=38, height=38, corner_radius=12,
                             image=icon(glyph, 15 if glyph != "play" else 13, color),
                             command=lambda: self.on_action(action, self.item_id), **style)

    def _show_buttons(self, names: tuple[str, ...]):
        if names == self.shown:
            return
        for button in self.btn.values():
            button.grid_forget()
        first = 1 if self.is_playlist else 0  # column 0 holds "Show videos"
        for col, name in enumerate(names, start=first):
            self.btn[name].grid(row=0, column=col, padx=(0 if col == 0 else 6, 0))
        self.shown = names

    def update_item(self, item: QueueItem):
        text = status_text(item)
        # Redrawing CustomTkinter widgets is slow: do nothing if what's shown wouldn't change.
        signature = (text, item.status, item.pause_reason, item.cancelling, round(item.fraction, 3))
        if signature == self.signature:
            return
        self.signature = signature
        self.status_label.configure(text=text)
        status = item.status
        percent = f"{int(item.fraction * 100)}%"
        colors = {
            dq.RUNNING: theme.ACCENT, dq.PAUSING: theme.SUBTLE, dq.PAUSED: theme.SUBTLE, dq.QUEUED: theme.SUBTLE,
            dq.COMPLETED: theme.SUCCESS, dq.FAILED: theme.ERROR, dq.CANCELLED: theme.SUBTLE,
        }
        self.bar.configure(progress_color=colors[status])
        self.bar.set(1.0 if status == dq.COMPLETED else item.fraction)
        self.percent_label.configure(
            text="" if status in (dq.QUEUED, dq.FAILED, dq.CANCELLED) and item.fraction == 0 else
            ("100%" if status == dq.COMPLETED else percent),
            text_color=theme.SUCCESS if status == dq.COMPLETED else theme.TEXT,
        )
        warn = status == dq.PAUSED and item.pause_reason in ("network", "slow", "failing")
        self.status_label.configure(text_color=theme.ERROR if status == dq.FAILED else
                                    theme.WARNING if warn else theme.MUTED)

        if status in (dq.RUNNING, dq.QUEUED):
            buttons = ("pause", "cancel")
        elif status == dq.PAUSING:
            buttons = ("pause", "cancel")
        elif status == dq.PAUSED:
            buttons = ("resume", "cancel")
        elif status == dq.COMPLETED:
            buttons = ("play", "folder", "remove")
        else:
            buttons = ("retry", "remove")
        self._show_buttons(buttons)
        busy = item.cancelling
        self.btn["pause"].configure(state="disabled" if status == dq.PAUSING or busy else "normal")
        self.btn["cancel"].configure(state="disabled" if busy else "normal")

    def set_wraplength(self, width: int):
        self.title_label.configure(wraplength=width)
        self.status_label.configure(wraplength=width)


class QueueView(ctk.CTkFrame):
    """The 'Downloads' page: every queued, running and finished download."""

    def __init__(self, parent, on_action: ActionHandler, on_concurrency: Callable[[int], None],
                 on_clear_finished: Callable[[], None], concurrency: int):
        super().__init__(parent, fg_color="transparent")
        self.on_action = on_action
        self.cards: dict[int, QueueItemCard] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self, text=t("queue.title"), anchor="w", font=theme.font(30, "bold")).grid(
            row=0, column=0, sticky="w")
        ctk.CTkLabel(self, text=t("queue.subtitle"), anchor="w", text_color=theme.MUTED,
                     font=theme.font(14)).grid(row=1, column=0, sticky="w", pady=(2, 18))

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        toolbar.grid_columnconfigure(0, weight=1)
        self.summary_label = ctk.CTkLabel(toolbar, text="", anchor="w", font=theme.font(14, "bold"))
        self.summary_label.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(toolbar, text=t("queue.at_once"), text_color=theme.MUTED, font=theme.font(13)).grid(
            row=0, column=1, padx=(0, 10))
        self.concurrency = ctk.CTkSegmentedButton(
            toolbar, values=[str(n) for n in dq.CONCURRENCY_CHOICES], width=44 * len(dq.CONCURRENCY_CHOICES),
            height=38, corner_radius=12,
            font=theme.font(13, "bold"), fg_color=theme.SECONDARY, unselected_color=theme.SECONDARY,
            unselected_hover_color=theme.SECONDARY_HOVER, selected_color=theme.SEGMENT_SELECTED,
            selected_hover_color=theme.SEGMENT_SELECTED, text_color=theme.TEXT,
            command=lambda value: on_concurrency(int(value)),
        )
        self.concurrency.set(str(concurrency))
        self.concurrency.grid(row=0, column=2, padx=(0, 12))
        self.clear_button = ctk.CTkButton(
            toolbar, text=t("queue.clear_finished"), height=38, corner_radius=12, font=theme.font(13, "bold"),
            command=on_clear_finished, **theme.secondary(),
        )
        self.clear_button.grid(row=0, column=3)

        self.scroll = AutoScrollFrame(self, fg_color="transparent")
        self.scroll.grid(row=3, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.scroll, text=t("queue.empty"), justify="center",
                                        text_color=theme.MUTED, font=theme.font(15))
        bind_visible_resize(self, self.scroll, self._on_resize)
        self.wrap = 480
        self.summary: tuple[str, str] | None = None

    def _on_resize(self, event):
        wrap = max(200, event.width - THUMB[0] - 330)
        if abs(wrap - self.wrap) > 8:
            self.wrap = wrap
            for card in self.cards.values():
                card.set_wraplength(wrap)

    def sync(self, items: list[QueueItem]):
        """Make the list match the queue (adds, removes, keeps order)."""
        ids = [i.id for i in items]
        for item_id in list(self.cards):
            if item_id not in ids:
                self.cards.pop(item_id).destroy()
        for item in items:
            if item.id not in self.cards:
                card = QueueItemCard(self.scroll, item, self.on_action)
                card.set_wraplength(self.wrap)
                self.cards[item.id] = card
        for row, item_id in enumerate(ids):
            self.cards[item_id].grid(row=row, column=0, sticky="ew", pady=(0, 12))
        if items:
            self.empty_label.grid_forget()
        else:
            self.empty_label.grid(row=0, column=0, pady=100)
        self._update_summary(items)

    def update_item(self, item: QueueItem, items: list[QueueItem]):
        card = self.cards.get(item.id)
        if card is None:
            self.sync(items)
        else:
            card.update_item(item)
            self._update_summary(items)

    def _update_summary(self, items: list[QueueItem]):
        running = sum(1 for i in items if i.status in (dq.RUNNING, dq.PAUSING))
        waiting = sum(1 for i in items if i.status == dq.QUEUED)
        paused = sum(1 for i in items if i.status == dq.PAUSED)
        parts = []
        if running:
            parts.append(f"{t('activity.downloading')}: {running}")
        if waiting:
            parts.append(f"{t('queue.status.queued')}: {waiting}")
        if paused:
            parts.append(f"{t('activity.paused')}: {paused}")
        summary = ("  ·  ".join(parts), "normal" if any(not i.is_active for i in items) else "disabled")
        if summary == self.summary:
            return
        self.summary = summary
        self.summary_label.configure(text=summary[0])
        self.clear_button.configure(state=summary[1])
