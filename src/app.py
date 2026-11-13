import queue
import shutil
import sys
import threading
import tkinter

import customtkinter as ctk

from config import theme
from config.paths import resource_path
from config.settings import VIDEOS_FOLDER, AppSettings
from models.media import DownloadResult, MediaInfo, ProgressInfo, QualityOption
from models.video import Video
from services.formatting import format_size
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
            on_cancel=self.cancel_download, audio_format="MP3" if self.has_ffmpeg else "M4A",
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
        job = DownloadJob(
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
        self.set_busy(True)
        self.download_view.progress.start(media.title, media.thumbnail, media.is_playlist, total)
        self.download_view.show_progress()
        self.sidebar.show_activity(media.title)
        threading.Thread(target=self._run_download, args=(job,), daemon=True).start()

    def _run_download(self, job: DownloadJob):
        try:
            result = job.run()
        except Exception as e:
            self.events.put(("download_error", clean_error(e)))
        else:
            self.events.put(("download_done", result))

    def cancel_download(self):
        if self.cancel_event:
            self.cancel_event.set()
            self.download_view.progress.set_cancelling()

    def _on_progress(self, p: ProgressInfo):
        overall = self.download_view.progress.set_progress(p)
        self.sidebar.update_activity(overall)
        if p.stage == "Saved":
            self.load_videos()  # show each playlist item as soon as it's done

    def _on_download_done(self, result: DownloadResult):
        self._end_download()
        if result.cancelled:
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
        self._end_download()
        self.notify(f"Download failed: {message}", "error", 10000)
        self.load_videos()

    def _end_download(self):
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
            return  # a download is running: keep showing its progress
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
        }
        try:
            while True:
                kind, payload = self.events.get_nowait()
                handlers[kind](payload)
        except queue.Empty:
            pass
        self._watch_url()
        self.after(POLL_MS, self._process_events)


def run() -> None:
    app = App(AppSettings(), VideoManager())
    app.mainloop()


if __name__ == "__main__":
    run()
