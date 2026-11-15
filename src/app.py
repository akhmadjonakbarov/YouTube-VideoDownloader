import queue
import shutil
import sys
import threading
import time
import tkinter
import traceback
from tkinter import messagebox

import customtkinter as ctk

from config import i18n, theme, user_settings
from config.i18n import t, tn
from config.paths import resource_path
from config.settings import VIDEOS_FOLDER, AppSettings
from models.media import MediaInfo, QualityOption
from models.video import Video
from services import download_queue as dq
from services.download_queue import DownloadQueue, JobSpec, QueueItem, Task
from services.formatting import format_size
from services.network import is_online
from services.system import open_path, reveal_in_folder
from services.video_downloader import (
    DownloadJob,
    clean_error,
    fetch_info,
    find_deno,
    find_ffmpeg,
    missing_tools_message,
)
from services.video_manager import VideoManager
from widgets.download_view import DownloadView
from widgets.library_view import LibraryView
from widgets.playlist_view import PlaylistView
from widgets.queue_view import QueueView
from widgets.sidebar import Sidebar
from widgets.toast import Toast

POLL_MS = 100
EVENT_BUDGET_SECONDS = 0.04  # handle worker events for at most this long per poll, so clicks stay responsive
LIBRARY_RELOAD_DELAY_MS = 1500  # while a playlist saves file after file, rescan the library at most this often
NETWORK_CHECK_SECONDS = 3
NOTIFY_COOLDOWN = 3.0  # seconds; one "connection lost" toast even if several downloads pause


class App(ctk.CTk):
    def __init__(self, settings: AppSettings, video_manager: VideoManager):
        # className sets the Linux WM_CLASS, which desktop launchers use to match the window.
        super().__init__(className="youtube-downloader")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        theme.setup_fonts(self)

        # Saved choices; the language defaults to the operating system's language.
        saved = user_settings.load()
        i18n.set_language(saved.get("language") or i18n.detect_system_language())
        self.theme_mode = saved.get("theme") if saved.get("theme") in ("Light", "Dark", "System") else "Dark"
        concurrency = saved.get("max_downloads")
        if concurrency not in dq.CONCURRENCY_CHOICES:
            concurrency = dq.DEFAULT_CONCURRENCY

        self.video_manager = video_manager
        self.ffmpeg_location = find_ffmpeg()
        self.has_ffmpeg = self.ffmpeg_location is not None
        self.deno_path = find_deno()
        # Worker threads never touch widgets: they post (kind, payload) events here
        # and the main thread applies them in _process_events (Tkinter isn't thread-safe).
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False  # a link lookup (Fetch) is running
        self.current_view = ""
        self.fetch_id = 0  # bumped per lookup, so results that arrive too late are ignored
        self.last_url_text = ""
        self.monitor_alive = False
        self.last_notified: dict[str, float] = {}
        self.detail_id: int | None = None  # playlist shown on the detail page
        # UI updates are batched: queue events only mark items as changed, and the
        # widgets are redrawn once per event-loop pass (see _flush_ui).
        self._dirty: set[int] = set()
        self._queue_stale: set[int] = set()  # changed while the Downloads page was hidden
        self._flush_pending = False
        # The library is scanned in a worker thread (see request_library_reload).
        self.videos: list[Video] = []
        self._library_job: str | None = None
        self._scan_running = False
        self._scan_again = False
        self._library_stale = False  # new scan results not yet shown (Library page hidden)

        self.queue = DownloadQueue(
            job_factory=self._make_job, spawn=self._spawn, on_event=self._on_queue_event,
            max_concurrent=concurrency,
        )

        self.title(settings.title)
        self.geometry(settings.geometry)
        self.minsize(*settings.min_size)
        self._set_window_icon()
        self.configure(fg_color=theme.BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.bind("<Configure>", self._fit_content_width, add="+")
        self._build_ui()
        self.request_library_reload()
        self.after(POLL_MS, self._process_events)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        """Create every widget (again, after a language change)."""
        self.sidebar = Sidebar(
            self, on_navigate=self.show_view, on_theme=self.set_theme,
            on_open_folder=lambda: self.open_file(VIDEOS_FOLDER), on_language=self.set_language,
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar_border = ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=theme.BORDER)
        self.sidebar_border.grid(row=0, column=0, sticky="nse")

        # Content keeps a comfortable maximum width on big screens (centred).
        self.main = main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=40, pady=(32, 28))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.download_view = DownloadView(
            main, on_fetch=self.fetch, on_paste=self.paste_url, on_download=self.start_download,
            audio_format="MP3" if self.has_ffmpeg else "M4A",
            warning=missing_tools_message(self.has_ffmpeg, self.deno_path is not None),
        )
        self.queue_view = QueueView(
            main, on_action=self.on_queue_action, on_concurrency=self.set_concurrency,
            on_clear_finished=self.queue.clear_finished, concurrency=self.queue.max_concurrent,
        )
        self.library_view = LibraryView(
            main, on_open=lambda v: self.open_file(v.path), on_reveal=self.reveal_file,
            on_delete=self.delete_video, on_refresh=self.request_library_reload,
        )
        self.playlist_view = PlaylistView(main, on_back=lambda: self.show_view("downloads"),
                                          on_action=self.on_queue_action)
        self.views = {"download": self.download_view, "downloads": self.queue_view, "library": self.library_view,
                      "playlist": self.playlist_view}
        self.toast = Toast(self)

        self.sidebar.select_theme(self.theme_mode)
        self.current_view = ""
        self.show_view("download")
        self.queue_view.sync(self.queue.items)
        self._refresh_activity()
        detail = self.queue.get(self.detail_id) if self.detail_id is not None else None
        if detail is not None:
            self.playlist_view.show(detail)

    def _rebuild_ui(self):
        """Re-create the interface in the new language, keeping what the user was doing."""
        view = self.current_view or "download"
        if view == "playlist" and self.queue.get(self.detail_id) is None:
            view = "downloads"
        url = self.download_view.url_input.get()
        media = self.download_view.preview.media
        toast = self.toast.current
        for widget in (self.sidebar, self.sidebar_border, self.main, self.toast):
            widget.destroy()
        self._build_ui()
        if url:
            self.download_view.url_input.insert(0, url)
        self.last_url_text = url.strip()
        if media is not None:
            self.download_view.show_preview(media)
        self.download_view.set_fetching(self.busy, self.busy)
        self._library_stale = True  # the new Library page is empty: fill it when shown
        self._queue_stale.clear()
        self.show_view(view)
        self._apply_content_width(self.winfo_width())
        if toast:
            self.notify(*toast)

    def set_language(self, code: str):
        if code == i18n.get_language():
            return
        user_settings.save(language=code)
        i18n.set_language(code)
        self._rebuild_ui()  # downloads keep running; their cards are re-created from the queue

    def set_theme(self, mode: str):
        self.theme_mode = mode
        ctk.set_appearance_mode(mode)
        user_settings.save(theme=mode)

    def set_concurrency(self, n: int):
        self.queue.set_max_concurrent(n)
        user_settings.save(max_downloads=n)

    def _set_window_icon(self):
        """Window/taskbar icon. (A packaged macOS .app gets its Dock icon from the bundle.)"""
        try:
            if sys.platform == "win32":
                ico = resource_path("assets", "icon.ico")
                if ico.exists():
                    # CustomTkinter sets its own icon ~200 ms after start; apply ours after that.
                    self.after(300, lambda: self.iconbitmap(str(ico)))
            elif sys.platform != "darwin":
                png = resource_path("assets", "icon-256.png")
                if png.exists():
                    self.icon_photo = tkinter.PhotoImage(file=str(png))
                    self.iconphoto(True, self.icon_photo)
        except tkinter.TclError:
            pass  # an icon is cosmetic; never fail startup over it

    MAX_CONTENT_WIDTH = 1180

    def _fit_content_width(self, event):
        if event.widget is self:
            self._apply_content_width(event.width)

    def _apply_content_width(self, window_width: int):
        if not self.sidebar.winfo_exists():
            return  # the interface is being rebuilt (language change)
        available = window_width - self.sidebar.winfo_reqwidth()
        side = max(40, (available - self.MAX_CONTENT_WIDTH) // 2)
        if self.main.grid_info().get("padx") != side:
            self.main.grid_configure(padx=side)

    def _on_close(self):
        active = len(self.queue.active_items())
        if active and not messagebox.askyesno(t("quit.title"), tn("quit.message", active),
                                              icon=messagebox.WARNING, parent=self):
            return
        for item in self.queue.active_items():
            for task in item.tasks:
                task.job.cancel_event.set()  # stop workers; partial files stay, so a re-download resumes
        self.destroy()

    # ------------------------------------------------------------- navigation

    def show_view(self, key: str):
        if key == self.current_view:
            return
        for name, view in self.views.items():
            if name == key:
                view.grid(row=0, column=0, sticky="nsew")
            else:
                view.grid_forget()
        self.current_view = key
        self.sidebar.set_active("downloads" if key == "playlist" else key)
        # Hidden pages aren't redrawn while downloading; bring them up to date now.
        if key == "downloads" and self._queue_stale:
            for item_id in sorted(self._queue_stale):
                item = self.queue.get(item_id)
                if item is not None:
                    self.queue_view.update_item(item, self.queue.items)
            self._queue_stale.clear()
        elif key == "library" and self._library_stale:
            self._library_stale = False
            self.library_view.set_videos(self.videos)
        elif key == "playlist":
            item = self.queue.get(self.detail_id) if self.detail_id is not None else None
            if item is not None:
                self.playlist_view.update_item(item)

    def show_playlist(self, item: QueueItem):
        """The detail page of a playlist download: all its videos and their progress."""
        self.detail_id = item.id
        self.playlist_view.show(item)
        self.show_view("playlist")

    def notify(self, message: str, kind: str = "info", duration_ms: int = 5000):
        self.toast.show(message, kind, duration_ms)

    def _notify_once(self, key: str, message: str, kind: str, duration_ms: int = 5000):
        """Like notify(), but at most once per NOTIFY_COOLDOWN for the same key."""
        now = time.monotonic()
        if now - self.last_notified.get(key, 0) >= NOTIFY_COOLDOWN:
            self.last_notified[key] = now
            self.notify(message, kind, duration_ms)

    # ---------------------------------------------------------------- library

    def request_library_reload(self, delay_ms: int = 0):
        """Rescan the downloads folder in a worker thread.

        With a delay, several requests in a row (e.g. a playlist saving file after
        file) are merged into one scan.
        """
        if self._library_job is not None:
            if delay_ms:
                return  # a scan is already coming
            self.after_cancel(self._library_job)
        self._library_job = self.after(delay_ms, self._start_library_scan)

    def _start_library_scan(self):
        self._library_job = None
        if self._scan_running:
            self._scan_again = True  # scan once more when the current one is done
            return
        self._scan_running = True
        threading.Thread(target=self._scan_library, daemon=True).start()

    def _scan_library(self):
        """Worker thread: list the downloads and load their thumbnails (slow on big folders)."""
        error = None
        try:
            videos = self.video_manager.get_videos()
        except OSError as e:
            videos, error = [], str(e)
        try:
            free = shutil.disk_usage(VIDEOS_FOLDER).free
        except OSError:
            free = None
        self.events.put(("library", (videos, free, error)))

    def _on_library(self, payload):
        videos, free, error = payload
        self._scan_running = False
        if error:
            self.notify(t("notify.read_error", error=error), "error")
        self.videos = videos
        if self.current_view == "library":
            self._library_stale = False
            self.library_view.set_videos(videos)
        else:
            self._library_stale = True  # build the cards when the Library is opened
        self._update_storage(videos, free)
        if self._scan_again:
            self._scan_again = False
            self.request_library_reload()

    def _update_storage(self, videos: list[Video], free: int | None):
        total = sum(v.size_bytes for v in videos)
        used = format_size(total) if total else t("storage.empty")
        extra = ""
        if free is not None:
            free_gb = free / 1024 ** 3
            size = f"{free_gb:.0f} GB" if free_gb >= 10 else f"{free_gb:.1f} GB"
            extra = " · " + t("storage.free", size=size)
        self.sidebar.set_storage(f"{used}{extra}")

    def delete_video(self, video: Video):
        try:
            self.video_manager.delete_video(video)
        except OSError as e:
            self.notify(t("notify.delete_error", error=e), "error")
        else:
            self.notify(t("notify.deleted", title=video.title), "info", 3000)
            # Remove the card right away; the rescan below fixes up the totals.
            self.videos = [v for v in self.videos if v.path != video.path]
            self.library_view.set_videos(self.videos)
        self.request_library_reload()

    def open_file(self, path):
        try:
            open_path(path)
        except OSError as e:
            self.notify(t("notify.open_error", error=e), "error")

    def reveal_file(self, video: Video):
        self._reveal(video.path)

    def _reveal(self, path):
        try:
            reveal_in_folder(path)
        except OSError as e:
            self.notify(t("notify.folder_error", error=e), "error")

    # ------------------------------------------------------------------ fetch

    def paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:  # empty clipboard / non-text content
            self.notify(t("notify.clipboard_empty"), "warning", 3000)
            return
        self.download_view.url_input.delete(0, "end")
        self.download_view.url_input.insert(0, text)
        self.fetch()

    def fetch(self):
        if self.busy:
            return
        url = self.download_view.url_input.get().strip()
        if not url:
            self.notify(t("notify.paste_first"), "warning", 3000)
            return
        self.set_busy(True, fetching=True)
        self.fetch_id += 1
        threading.Thread(target=self._run_fetch, args=(url, self.fetch_id), daemon=True).start()

    def _run_fetch(self, url: str, fetch_id: int):
        try:
            media = fetch_info(url, self.deno_path)
        except Exception as e:  # yt-dlp raises many exception types
            self.events.put(("fetch_error", (fetch_id, clean_error(e))))
        else:
            self.events.put(("fetched", (fetch_id, media)))

    def _on_fetched(self, payload: tuple[int, MediaInfo]):
        fetch_id, media = payload
        if fetch_id != self.fetch_id:
            return  # the link was cleared while this lookup was running
        self.set_busy(False)
        if media.is_playlist and not media.entries:
            self.notify(t("notify.playlist_empty"), "warning")
            return
        self.download_view.show_preview(media)

    def _on_fetch_error(self, payload: tuple[int, str]):
        fetch_id, message = payload
        if fetch_id != self.fetch_id:
            return
        self.set_busy(False)
        self.notify(t("notify.fetch_error", message=message), "error", 9000)

    def set_busy(self, busy: bool, fetching: bool = False):
        self.busy = busy
        self.download_view.set_fetching(fetching, busy)

    # ------------------------------------------------------------- link field

    def _watch_url(self):
        """Clear the preview when the link field is emptied (however it was emptied)."""
        text = self.download_view.url_input.get().strip()
        if text == self.last_url_text:
            return
        self.last_url_text = text
        if not text:
            self._on_url_cleared()

    def _on_url_cleared(self):
        if self.busy:  # a lookup is running: forget its result
            self.fetch_id += 1
            self.set_busy(False)
        self.download_view.clear_preview()

    # --------------------------------------------------------------- download queue

    def start_download(self, media: MediaInfo, option: QualityOption, items: list[int] | None):
        """The Download button: add to the queue and get ready for the next link."""
        if self.queue.find_duplicate(media, option, items):
            self.notify(t("notify.duplicate"), "warning", 4000)
            return
        item = self.queue.add(media, option, items)
        self.download_view.url_input.delete(0, "end")
        self.download_view.clear_preview()
        self.last_url_text = ""
        self.notify(t("notify.added") if item.status == dq.RUNNING else t("notify.added_waiting"), "success", 3500)
        self._start_network_monitor()

    def _make_job(self, task_id: int, spec: JobSpec, option: QualityOption) -> DownloadJob:
        return DownloadJob(
            spec.url, option,
            on_progress=lambda p: self.events.put(("task_progress", (task_id, p))),
            has_ffmpeg=self.has_ffmpeg,
            cancel_event=threading.Event(),
            playlist=spec.playlist,
            items=spec.items,
            total=spec.total,
            ffmpeg_location=self.ffmpeg_location,
            deno_path=self.deno_path,
            folder=spec.folder,
            index=spec.index,
        )

    def _spawn(self, task: Task):
        threading.Thread(target=self._run_task, args=(task.id, task.job), daemon=True).start()

    def _run_task(self, task_id: int, job: DownloadJob):
        """Worker thread: run (or continue) one video, or a whole playlist one by one."""
        try:
            result = job.run()
        except Exception as e:
            self.events.put(("task_error", (task_id, clean_error(e))))
        else:
            self.events.put(("task_done", (task_id, result)))

    def on_queue_action(self, action: str, item_id: int):
        item = self.queue.get(item_id)
        if item is None:
            return
        if action == "pause":
            self.queue.pause(item)
        elif action == "resume":
            self.queue.resume(item)
        elif action == "cancel":
            self.queue.cancel(item)
        elif action == "remove":
            self.queue.remove(item)
        elif action == "details":
            if item.is_playlist:
                self.show_playlist(item)
        elif action == "retry":
            on_detail = self.current_view == "playlist" and self.detail_id == item.id
            self.queue.remove(item)
            new = self.queue.add(item.media, item.option, item.items)
            if on_detail:
                self.show_playlist(new)  # keep showing the playlist, now the new attempt
            self._start_network_monitor()
        elif action in ("play", "folder"):
            files = sorted(item.completed_files)
            if not files:
                self.open_file(VIDEOS_FOLDER)
            elif action == "play" and not item.is_playlist:
                self.open_file(files[0])
            else:
                self._reveal(files[0])

    def _on_queue_event(self, kind: str, item: QueueItem):
        """Called by the queue whenever something changes."""
        if kind in ("added", "removed"):
            self.queue_view.sync(self.queue.items)
            self._dirty.discard(item.id)
            self._queue_stale.discard(item.id)
        else:
            self._dirty.add(item.id)  # redrawn once, in _flush_ui
        if item.id == self.detail_id and kind == "removed":
            self.detail_id = None
            if self.current_view == "playlist":
                self.show_view("downloads")

        if kind == "completed":
            self.notify(t("notify.item_done", title=item.title), "success", 5000)
            self.request_library_reload(300)
        elif kind == "failed":
            self.notify(t("notify.item_failed", title=item.title, message=item.error or ""), "error", 9000)
        elif kind == "saved":
            self.request_library_reload(LIBRARY_RELOAD_DELAY_MS)  # playlist videos show up as they finish
        elif kind == "auto_paused":
            key = "notify.connection_lost" if item.pause_reason == "network" else "notify.connection_stalled"
            self._notify_once(key, t(key), "warning", 6000)
        elif kind == "auto_resumed":
            self._notify_once("back_online", t("notify.back_online"), "info", 3000)

        if not self._flush_pending:
            self._flush_pending = True
            self.after_idle(self._flush_ui)

    def _flush_ui(self):
        """Redraw the downloads that changed since the last pass (once each)."""
        self._flush_pending = False
        changed, self._dirty = self._dirty, set()
        for item_id in sorted(changed):
            item = self.queue.get(item_id)
            if item is None:
                continue
            if self.current_view == "downloads":
                self.queue_view.update_item(item, self.queue.items)
            else:
                self._queue_stale.add(item_id)  # updated when the page is opened
            if item_id == self.detail_id and self.current_view == "playlist":
                self.playlist_view.update_item(item)
        self._refresh_activity()

    def _refresh_activity(self):
        """Sidebar: the 'Downloads (n)' count and the live progress card."""
        active = self.queue.active_items()
        self.sidebar.set_badge("downloads", len(active))
        if not active:
            self.sidebar.hide_activity()
            return
        title = active[0].title if len(active) == 1 else tn("activity.items", len(active))
        self.sidebar.show_activity(title)
        self.sidebar.update_activity(sum(i.fraction for i in active) / len(active))
        if any(i.status == dq.RUNNING for i in active):
            self.sidebar.set_activity_paused(False)
        else:
            reasons = {i.pause_reason for i in active if i.status in (dq.PAUSED, dq.PAUSING)}
            if "network" in reasons:
                label = t("activity.offline")
            elif "slow" in reasons:
                label = t("activity.stalled")
            else:
                label = t("activity.paused")
            self.sidebar.set_activity_paused(True, label)

    # ----------------------------------------------------------- connection watch

    def _start_network_monitor(self):
        if self.monitor_alive:
            return
        self.monitor_alive = True
        threading.Thread(target=self._network_monitor, daemon=True).start()

    def _network_monitor(self):
        """Worker thread: check the connection every few seconds while downloads exist."""
        try:
            while self.queue.has_active():
                self.events.put(("network", is_online()))
                for _ in range(NETWORK_CHECK_SECONDS * 10):
                    if not self.queue.has_active():
                        break
                    time.sleep(0.1)
        finally:
            self.monitor_alive = False

    # ------------------------------------------------------------- event loop

    def _process_events(self):
        handlers = {
            "fetched": self._on_fetched,
            "fetch_error": self._on_fetch_error,
            "task_progress": lambda payload: self.queue.on_progress(*payload),
            "task_done": lambda payload: self.queue.on_result(*payload),
            "task_error": lambda payload: self.queue.on_error(*payload),
            "network": self.queue.on_network,
            "library": self._on_library,
        }
        more = False
        try:
            # Limited time per pass: clicks and redraws must not wait behind a burst of events.
            deadline = time.monotonic() + EVENT_BUDGET_SECONDS
            while True:
                if time.monotonic() > deadline:
                    more = True
                    break
                try:
                    kind, payload = self.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    handlers[kind](payload)
                except Exception:  # one bad event must not stop the whole loop
                    traceback.print_exc()
            self._watch_url()
            self.queue.tick()
            if self.queue.has_active() and not self.monitor_alive:
                self._start_network_monitor()
        except Exception:
            traceback.print_exc()
        finally:
            # Always poll again; otherwise the window would stop updating for good.
            self.after(10 if more else POLL_MS, self._process_events)


def run() -> None:
    app = App(AppSettings(), VideoManager())
    app.mainloop()


if __name__ == "__main__":
    run()
