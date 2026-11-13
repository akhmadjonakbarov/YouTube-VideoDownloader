import queue
import shutil
import sys
import threading
import time
import tkinter

import customtkinter as ctk

from config import theme
from config.paths import resource_path
from config.settings import VIDEOS_FOLDER, AppSettings
from models.media import DownloadResult, MediaInfo, ProgressInfo, QualityOption
from models.video import Video
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
from widgets.sidebar import Sidebar
from widgets.toast import Toast

POLL_MS = 100

# Auto-pause: when the speed stays below SLOW_BYTES_PER_SEC for STALL_SECONDS, the
# connection counts as stalled. Downloads also pause as soon as the network is gone.
SLOW_BYTES_PER_SEC = 16 * 1024
STALL_SECONDS = 25
NETWORK_CHECK_SECONDS = 3
RESUME_DELAY = {"network": 3, "slow": 10}  # wait a little after the connection returns
MAX_AUTO_RESUMES = 5                       # then stop retrying and ask the user


class App(ctk.CTk):
    def __init__(self, settings: AppSettings, video_manager: VideoManager):
        # className sets the Linux WM_CLASS, which desktop launchers use to match the window.
        super().__init__(className="youtube-downloader")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        theme.setup_fonts(self)

        self.video_manager = video_manager
        self.ffmpeg_location = find_ffmpeg()
        self.has_ffmpeg = self.ffmpeg_location is not None
        self.deno_path = find_deno()
        # Worker threads never touch widgets: they post (kind, payload) events here
        # and the main thread applies them in _process_events (Tkinter isn't thread-safe).
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event: threading.Event | None = None
        self.busy = False  # fetching or downloading
        self.current_view = ""
        self.fetch_id = 0  # bumped per lookup, so results that arrive too late are ignored
        self.last_url_text = ""

        # Download job state (pause / resume)
        self.job: DownloadJob | None = None
        self.job_title = ""
        self.job_running = False           # a worker thread is downloading right now
        self.pause_reason: str | None = None  # None (running) / "user" / "network" / "slow" / "failing"
        self.paused_at = 0.0
        self.last_good_progress = 0.0
        self.downloading_stage = False
        self.auto_resumes = 0
        self.monitor_alive = False

        self.title(settings.title)
        self.geometry(settings.geometry)
        self.minsize(*settings.min_size)
        self._set_window_icon()
        self.configure(fg_color=theme.BG)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(
            self, on_navigate=self.show_view, on_theme=ctk.set_appearance_mode,
            on_open_folder=lambda: self.open_file(VIDEOS_FOLDER),
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=theme.BORDER).grid(row=0, column=0, sticky="nse")

        # Content keeps a comfortable maximum width on big screens (centred).
        self.main = main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=40, pady=(32, 28))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)
        self.bind("<Configure>", self._fit_content_width, add="+")

        self.download_view = DownloadView(
            main, on_fetch=self.fetch, on_paste=self.paste_url, on_download=self.start_download,
            on_cancel=self.cancel_download, on_pause_toggle=self.toggle_pause, audio_format="MP3" if self.has_ffmpeg else "M4A",
            warning=missing_tools_message(self.has_ffmpeg, self.deno_path is not None),
        )
        self.library_view = LibraryView(
            main, on_open=lambda v: self.open_file(v.path), on_reveal=self.reveal_file,
            on_delete=self.delete_video, on_refresh=self.load_videos,
        )
        self.views = {"download": self.download_view, "library": self.library_view}
        self.toast = Toast(self)

        self.sidebar.select_theme("Dark")
        self.show_view("download")
        self.load_videos()
        self.after(POLL_MS, self._process_events)

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
        if event.widget is not self:
            return
        available = event.width - self.sidebar.winfo_width()
        side = max(40, (available - self.MAX_CONTENT_WIDTH) // 2)
        if self.main.grid_info().get("padx") != side:
            self.main.grid_configure(padx=side)

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
        self.sidebar.set_active(key)

    def notify(self, message: str, kind: str = "info", duration_ms: int = 5000):
        self.toast.show(message, kind, duration_ms)

    # ---------------------------------------------------------------- library

    def load_videos(self):
        try:
            videos = self.video_manager.get_videos()
        except OSError as e:
            videos = []
            self.notify(f"Could not read the downloads folder: {e}", "error")
        self.library_view.set_videos(videos)
        total = sum(v.size_bytes for v in videos)
        used = format_size(total) if total else "Empty"
        try:
            free_gb = shutil.disk_usage(VIDEOS_FOLDER).free / 1024 ** 3
            free = f" · {free_gb:.0f} GB free" if free_gb >= 10 else f" · {free_gb:.1f} GB free"
        except OSError:
            free = ""
        self.sidebar.set_storage(f"{used}{free}")

    def delete_video(self, video: Video):
        try:
            self.video_manager.delete_video(video)
        except OSError as e:
            self.notify(f"Could not delete: {e}", "error")
        else:
            self.notify(f"Deleted “{video.title}”.", "info", 3000)
        self.load_videos()

    def open_file(self, path):
        try:
            open_path(path)
        except OSError as e:
            self.notify(f"Could not open: {e}", "error")

    def reveal_file(self, video: Video):
        try:
            reveal_in_folder(video.path)
        except OSError as e:
            self.notify(f"Could not open the folder: {e}", "error")

    # ------------------------------------------------------------------ fetch

    def paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:  # empty clipboard / non-text content
            self.notify("The clipboard is empty.", "warning", 3000)
            return
        self.download_view.url_input.delete(0, "end")
        self.download_view.url_input.insert(0, text)
        self.fetch()

    def fetch(self):
        if self.busy:
            return
        url = self.download_view.url_input.get().strip()
        if not url:
            self.notify("Paste a YouTube link first.", "warning", 3000)
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
            self.notify("This playlist has no available videos.", "warning")
            return
        self.download_view.show_preview(media)

    def _on_fetch_error(self, payload: tuple[int, str]):
        fetch_id, message = payload
        if fetch_id != self.fetch_id:
            return
        self.set_busy(False)
        self.notify(f"Couldn't read this link: {message}", "error", 9000)

    # --------------------------------------------------------------- download

    def start_download(self, media: MediaInfo, option: QualityOption, items: list[int] | None):
        if self.busy:
            return
        total = (len(items) if items else len(media.entries)) if media.is_playlist else 1
        self.cancel_event = threading.Event()
        self.job = DownloadJob(
            media.url, option,
            on_progress=lambda p: self.events.put(("progress", p)),
            has_ffmpeg=self.has_ffmpeg,
            cancel_event=self.cancel_event,
            playlist=media.is_playlist,
            items=items,
            total=total,
            ffmpeg_location=self.ffmpeg_location,
            deno_path=self.deno_path,
        )
        self.job_title = media.title
        self.auto_resumes = 0
        self.set_busy(True)
        self.download_view.progress.start(media.title, media.thumbnail, media.is_playlist, total)
        self.download_view.show_progress()
        self.sidebar.show_activity(media.title)
        self._run_job()
        self._start_network_monitor()

    def _run_job(self):
        self.job_running = True
        self.pause_reason = None
        self.downloading_stage = False
        self.last_good_progress = time.monotonic()
        threading.Thread(target=self._run_download, args=(self.job,), daemon=True).start()

    def _run_download(self, job: DownloadJob):
        try:
            result = job.run()
        except Exception as e:
            self.events.put(("download_error", clean_error(e)))
        else:
            self.events.put(("download_done", result))

    # ---------------------------------------------------------- pause / resume

    def toggle_pause(self):
        if not self.job:
            return
        if self.job_running and self.pause_reason is None:
            self.pause_reason = "user"
            self.job.pause_event.set()
            self.download_view.progress.set_pausing()
        elif not self.job_running:
            self.resume_download(manual=True)

    def resume_download(self, manual: bool = False):
        if not self.job or self.job_running:
            return
        if manual:
            self.auto_resumes = 0
        self.download_view.progress.set_running()
        self.sidebar.set_activity_paused(False)
        self._run_job()

    def _auto_pause(self, reason: str):
        """Connection lost or stalled: stop now, continue automatically later."""
        if not self.job or not self.job_running or self.pause_reason is not None:
            return
        self.pause_reason = reason
        self.paused_at = time.monotonic()
        self.job.pause_event.set()
        self.download_view.progress.set_paused(reason, stopping=True)
        self.sidebar.set_activity_paused(True, "Offline" if reason == "network" else "Stalled")
        what = "Connection lost" if reason == "network" else "Connection stalled"
        self.notify(f"{what}: download paused. It will resume automatically.", "warning", 6000)

    def _on_network(self, online: bool):
        if not self.job:
            return
        if not online and self.job_running and self.pause_reason is None:
            self._auto_pause("network")
        elif online and not self.job_running and self.pause_reason in RESUME_DELAY:
            if time.monotonic() - self.paused_at < RESUME_DELAY[self.pause_reason]:
                return
            if self.auto_resumes >= MAX_AUTO_RESUMES:
                self.pause_reason = "failing"  # stop retrying on our own; let the user decide
                self.download_view.progress.set_paused("failing")
                self.sidebar.set_activity_paused(True)
                return
            self.auto_resumes += 1
            self.notify("Back online: resuming your download.", "info", 3000)
            self.resume_download()

    def _check_stall(self):
        if (self.job_running and self.pause_reason is None and self.downloading_stage
                and time.monotonic() - self.last_good_progress > STALL_SECONDS):
            self._auto_pause("slow")

    def _start_network_monitor(self):
        if self.monitor_alive:
            return
        self.monitor_alive = True
        threading.Thread(target=self._network_monitor, daemon=True).start()

    def _network_monitor(self):
        """Worker thread: check the connection every few seconds while a job exists."""
        try:
            while self.job is not None:
                self.events.put(("network", is_online()))
                for _ in range(NETWORK_CHECK_SECONDS * 10):
                    if self.job is None:
                        break
                    time.sleep(0.1)
        finally:
            self.monitor_alive = False

    # ------------------------------------------------------------- progress

    def cancel_download(self):
        if not self.job or not self.cancel_event:
            return
        self.cancel_event.set()
        if self.job_running:
            self.download_view.progress.set_cancelling()
        else:  # paused: nothing is running, finish right away
            self._on_download_done(DownloadResult(self.job.completed, self.job.total, cancelled=True))

    def _on_progress(self, p: ProgressInfo):
        now = time.monotonic()
        if p.stage.startswith("Downloading"):
            if not self.downloading_stage:
                self.downloading_stage = True
                self.last_good_progress = now
            if p.speed and p.speed >= SLOW_BYTES_PER_SEC:
                self.last_good_progress = now
                self.auto_resumes = 0
        else:
            self.downloading_stage = False
        if p.stage == "Saved":
            self.load_videos()  # show each playlist item as soon as it's done
        if self.pause_reason is not None:
            return  # keep showing the paused state
        overall = self.download_view.progress.set_progress(p)
        self.sidebar.update_activity(overall)

    def _on_download_done(self, result: DownloadResult):
        self.job_running = False
        cancelled = result.cancelled or (self.cancel_event is not None and self.cancel_event.is_set())
        if result.paused and not cancelled:
            reason = self.pause_reason or ("network" if result.network_error else "user")
            if result.network_error and reason == "user" and self.pause_reason is None:
                reason = "network"
            if self.pause_reason is None:  # yt-dlp hit a network error on its own
                self.paused_at = time.monotonic()
                if reason == "network":
                    self.notify("Connection lost: download paused. It will resume automatically.", "warning", 6000)
            self.pause_reason = reason
            self.download_view.progress.set_paused(reason)
            self.sidebar.set_activity_paused(True, {"network": "Offline", "slow": "Stalled"}.get(reason, "Paused"))
            return

        self._end_download()
        if cancelled:
            message = "Download cancelled."
            if result.total > 1:
                message += f" {result.completed} of {result.total} finished."
            self.notify(message, "warning", 7000)
        elif result.total > 1 and result.completed < result.total:
            failed = result.total - result.completed
            self.notify(
                f"Downloaded {result.completed} of {result.total}. "
                f"{failed} {'video was' if failed == 1 else 'videos were'} unavailable.",
                "warning", 9000,
            )
        else:
            what = f"{result.completed} files" if result.total > 1 else "Your download"
            self.notify(f"{what} saved to the Library.", "success", 6000)
        self.load_videos()

    def _on_download_error(self, message: str):
        self.job_running = False
        self._end_download()
        self.notify(f"Download failed: {message}", "error", 10000)
        self.load_videos()

    def _end_download(self):
        self.job = None  # also stops the network monitor
        self.job_running = False
        self.pause_reason = None
        self.cancel_event = None
        self.set_busy(False)
        self.sidebar.hide_activity()
        if self.download_view.url_input.get().strip():
            self.download_view.show_preview_again()  # ready to download again, e.g. another quality
        else:
            self.download_view.clear_preview()  # link was cleared during the download

    # ------------------------------------------------------------ link field

    def _watch_url(self):
        """Clear the preview when the link field is emptied (however it was emptied)."""
        text = self.download_view.url_input.get().strip()
        if text == self.last_url_text:
            return
        self.last_url_text = text
        if not text:
            self._on_url_cleared()

    def _on_url_cleared(self):
        if self.cancel_event is not None:
            return  # a download is running or paused: keep showing its progress
        if self.busy:  # a lookup is running: forget its result
            self.fetch_id += 1
            self.set_busy(False)
        self.download_view.clear_preview()

    def set_busy(self, busy: bool, fetching: bool = False):
        self.busy = busy
        self.download_view.set_fetching(fetching, busy)

    # ------------------------------------------------------------- event loop

    def _process_events(self):
        handlers = {
            "fetched": self._on_fetched,
            "fetch_error": self._on_fetch_error,
            "progress": self._on_progress,
            "download_done": self._on_download_done,
            "download_error": self._on_download_error,
            "network": self._on_network,
        }
        try:
            while True:
                kind, payload = self.events.get_nowait()
                handlers[kind](payload)
        except queue.Empty:
            pass
        self._watch_url()
        self._check_stall()
        self.after(POLL_MS, self._process_events)


def run() -> None:
    app = App(AppSettings(), VideoManager())
    app.mainloop()


if __name__ == "__main__":
    run()
