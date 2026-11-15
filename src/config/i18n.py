"""Translations (English, Uzbek) and system-language detection.

Use t("key") for text and tn("key", n) for text that depends on a count.
Keys ending in ".one" / ".other" are the singular / plural forms for tn().
"""
import ctypes
import locale
import os
import subprocess
import sys
from datetime import datetime

LANGUAGES = {"en": "English", "uz": "O'zbekcha"}
DEFAULT_LANGUAGE = "en"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # sidebar
        "sidebar.brand_bottom": "Downloader",
        "sidebar.menu": "MENU",
        "nav.download": "Download",
        "nav.library": "Library",
        "activity.downloading": "Downloading",
        "activity.paused": "Paused",
        "activity.offline": "Offline",
        "activity.stalled": "Stalled",
        "storage.title": "Downloads folder",
        "storage.empty": "Empty",
        "storage.free": "{size} free",
        # download page
        "download.hero_title": "Download anything from YouTube",
        "download.hero_subtitle": "Videos, whole playlists and MP3 audio, in the quality you choose.",
        "download.title": "New download",
        "download.placeholder": "Paste a YouTube video or playlist link…",
        "download.paste": "Paste",
        "download.fetch": "Fetch",
        "download.fetching": "Fetching…",
        "empty.title": "Ready when you are",
        "empty.text": "Paste a link above and press Fetch. You'll see every\navailable quality before anything downloads.",
        "feature.4k": "Up to 4K",
        "feature.playlists": "Whole playlists",
        "feature.mp3": "MP3 audio",
        "warning.deno": "Deno isn't installed, so many YouTube videos can't be downloaded",
        "warning.ffmpeg": "ffmpeg isn't installed, so only lower qualities (often 360p) and M4A audio are available",
        "warning.fix": "To fix it, install: {command}",
        # preview
        "preview.video": "VIDEO",
        "preview.playlist": "PLAYLIST",
        "preview.videos.one": "{n} video",
        "preview.videos.other": "{n} videos",
        "preview.choose_quality": "CHOOSE QUALITY",
        "preview.playlist_videos": "Videos in this playlist",
        "preview.selected": "{count} of {total} selected",
        "preview.select_all": "Select all",
        "preview.large_playlist": "This playlist is large, so all {n} videos will be downloaded.",
        "quality.best": "Best",
        "quality.best_detail": "Highest available",
        "quality.audio": "Audio",
        "quality.audio_detail": "{format} only",
        "quality.tag.auto": "Auto",
        "button.download_video": "Download video",
        "button.download_audio": "Download audio",
        "button.download_videos.one": "Download {n} video",
        "button.download_videos.other": "Download {n} videos",
        "button.download_tracks.one": "Download {n} track",
        "button.download_tracks.other": "Download {n} tracks",
        # progress
        "progress.video_n": "Video {n} of {total}",
        "progress.left": "{time} left",
        "stage.download_video": "Downloading video",
        "stage.download_audio": "Downloading audio",
        "stage.processing": "Processing",
        "stage.merging": "Merging video and audio",
        "stage.converting": "Converting to MP3",
        "stage.saved": "Saved",
        # library
        "library.title": "Library",
        "library.subtitle": "Everything you've downloaded, in one place.",
        "library.search": "Search by title or playlist…",
        "library.no_match": "No matching downloads.",
        "library.empty": "No downloads yet.\nFinished videos will show up here.",
        "stat.downloads": "Downloads",
        "stat.videos": "Videos",
        "stat.audio": "Audio tracks",
        "stat.disk": "On disk",
        "filter.all": "All",
        "filter.videos": "Videos",
        "filter.audio": "Audio",
        "card.play": "Play",
        "delete.title": "Delete download",
        "delete.message": 'Delete "{title}"?\n\nThe file will be permanently removed.',
        # downloads (queue) page
        "nav.queue": "Downloads",
        "queue.title": "Downloads",
        "queue.subtitle": "Downloads run in the background. Keep adding links on the Download page.",
        "queue.at_once": "At the same time",
        "queue.clear_finished": "Clear finished",
        "queue.empty": "Nothing here yet.\nVideos you download will appear here.",
        "queue.status.queued": "Waiting in line",
        "queue.status.starting": "Starting…",
        "queue.status.pausing": "Pausing…",
        "queue.status.cancelling": "Cancelling…",
        "queue.status.paused.user": "Paused",
        "queue.status.paused.network": "Paused: no internet. Resumes automatically.",
        "queue.status.paused.slow": "Paused: connection too slow. Resumes automatically.",
        "queue.status.paused.failing": "Paused: the connection keeps failing. Press Resume to retry.",
        "queue.status.completed": "Completed · saved to your Library",
        "queue.status.completed_partial": "Completed: {done} of {total} saved, {failed} unavailable",
        "queue.status.failed": "Failed: {message}",
        "queue.status.cancelled": "Cancelled",
        "queue.show_videos": "Show videos",
        "queue.videos_running.one": "Downloading {n} video",
        "queue.videos_running.other": "Downloading {n} videos",
        "queue.saved_of": "{done} of {total} saved",
        # playlist detail
        "playlist.back": "Downloads",
        "playlist.count.done": "Saved",
        "playlist.count.active": "Downloading",
        "playlist.count.waiting": "Waiting",
        "playlist.count.failed": "Skipped",
        "entry.waiting": "Waiting",
        "entry.saved": "Saved",
        "entry.failed": "Skipped: unavailable or failed",
        "entry.paused": "Paused",
        "entry.cancelled": "Cancelled",
        "entry.not_downloaded": "Not downloaded",
        "activity.items.one": "{n} download",
        "activity.items.other": "{n} downloads",
        "notify.added": "Added to Downloads.",
        "notify.added_waiting": "Added to Downloads. It will start when a slot is free.",
        "notify.duplicate": "This is already in your downloads.",
        "notify.item_done": "Downloaded: {title}",
        "notify.item_failed": "Couldn't download “{title}”: {message}",
        "quit.title": "Quit YouTube Downloader?",
        "quit.message.one": "1 download is still in progress. It will stop now; add it again later and it continues where it left off.",
        "quit.message.other": "{n} downloads are still in progress. They will stop now; add them again later and they continue where they left off.",
        # notifications
        "notify.clipboard_empty": "The clipboard is empty.",
        "notify.paste_first": "Paste a YouTube link first.",
        "notify.playlist_empty": "This playlist has no available videos.",
        "notify.fetch_error": "Couldn't read this link: {message}",
        "notify.deleted": "Deleted “{title}”.",
        "notify.delete_error": "Could not delete: {error}",
        "notify.open_error": "Could not open: {error}",
        "notify.folder_error": "Could not open the folder: {error}",
        "notify.read_error": "Could not read the downloads folder: {error}",
        "notify.connection_lost": "Connection lost: downloads paused. They will resume automatically.",
        "notify.connection_stalled": "Connection stalled: download paused. It will resume automatically.",
        "notify.back_online": "Back online: resuming downloads.",
    },
    "uz": {
        "sidebar.brand_bottom": "Yuklovchi",
        "sidebar.menu": "MENYU",
        "nav.download": "Yuklab olish",
        "nav.library": "Kutubxona",
        "activity.downloading": "Yuklanmoqda",
        "activity.paused": "Pauzada",
        "activity.offline": "Internet yo'q",
        "activity.stalled": "Aloqa sekin",
        "storage.title": "Yuklamalar papkasi",
        "storage.empty": "Bo'sh",
        "storage.free": "{size} bo'sh joy",
        "download.hero_title": "YouTube'dan istalganini yuklab oling",
        "download.hero_subtitle": "Videolar, butun playlistlar va MP3 audio — o'zingiz tanlagan sifatda.",
        "download.title": "Yangi yuklama",
        "download.placeholder": "YouTube video yoki playlist havolasini joylang…",
        "download.paste": "Qo'yish",
        "download.fetch": "Topish",
        "download.fetching": "Qidirilmoqda…",
        "empty.title": "Boshlashga tayyormiz",
        "empty.text": "Yuqoriga havolani qo'yib, «Topish»ni bosing. Yuklashdan\noldin barcha mavjud sifatlarni ko'rasiz.",
        "feature.4k": "4K gacha",
        "feature.playlists": "Butun playlistlar",
        "feature.mp3": "MP3 audio",
        "warning.deno": "Deno o'rnatilmagan, shuning uchun ko'p YouTube videolarini yuklab bo'lmaydi",
        "warning.ffmpeg": "ffmpeg o'rnatilmagan, shuning uchun faqat past sifatlar (ko'pincha 360p) va M4A audio mavjud",
        "warning.fix": "Tuzatish uchun o'rnating: {command}",
        "preview.video": "VIDEO",
        "preview.playlist": "PLAYLIST",
        "preview.videos.other": "{n} ta video",
        "preview.choose_quality": "SIFATNI TANLANG",
        "preview.playlist_videos": "Playlistdagi videolar",
        "preview.selected": "{total} tadan {count} tasi tanlandi",
        "preview.select_all": "Hammasini tanlash",
        "preview.large_playlist": "Bu playlist katta, shuning uchun barcha {n} ta video yuklab olinadi.",
        "quality.best": "Eng yaxshi",
        "quality.best_detail": "Eng yuqori sifat",
        "quality.audio": "Audio",
        "quality.audio_detail": "Faqat {format}",
        "quality.tag.auto": "Avto",
        "button.download_video": "Videoni yuklab olish",
        "button.download_audio": "Audioni yuklab olish",
        "button.download_videos.other": "{n} ta videoni yuklab olish",
        "button.download_tracks.other": "{n} ta audioni yuklab olish",
        "progress.video_n": "{total} tadan {n}-video",
        "progress.left": "{time} qoldi",
        "stage.download_video": "Video yuklanmoqda",
        "stage.download_audio": "Audio yuklanmoqda",
        "stage.processing": "Qayta ishlanmoqda",
        "stage.merging": "Video va audio birlashtirilmoqda",
        "stage.converting": "MP3 ga o'girilmoqda",
        "stage.saved": "Saqlandi",
        "library.title": "Kutubxona",
        "library.subtitle": "Yuklab olganlaringizning hammasi bir joyda.",
        "library.search": "Nomi yoki playlist bo'yicha qidirish…",
        "library.no_match": "Mos yuklama topilmadi.",
        "library.empty": "Hali yuklamalar yo'q.\nYuklab olingan videolar shu yerda paydo bo'ladi.",
        "stat.downloads": "Yuklamalar",
        "stat.videos": "Videolar",
        "stat.audio": "Audio fayllar",
        "stat.disk": "Diskda",
        "filter.all": "Hammasi",
        "filter.videos": "Videolar",
        "filter.audio": "Audio",
        "card.play": "Ko'rish",
        "delete.title": "Yuklamani o'chirish",
        "delete.message": "\"{title}\" o'chirilsinmi?\n\nFayl butunlay o'chiriladi.",
        "nav.queue": "Navbat",
        "queue.title": "Yuklash navbati",
        "queue.subtitle": "Yuklashlar fonda davom etadi. «Yuklab olish» sahifasida yangi havolalar qo'shavering.",
        "queue.at_once": "Bir vaqtda",
        "queue.clear_finished": "Tugaganlarni tozalash",
        "queue.empty": "Hozircha bo'sh.\nYuklab olayotgan videolaringiz shu yerda ko'rinadi.",
        "queue.status.queued": "Navbatda kutmoqda",
        "queue.status.starting": "Boshlanmoqda…",
        "queue.status.pausing": "To'xtatilmoqda…",
        "queue.status.cancelling": "Bekor qilinmoqda…",
        "queue.status.paused.user": "Pauza qilingan",
        "queue.status.paused.network": "Pauza: internet yo'q. Avtomatik davom etadi.",
        "queue.status.paused.slow": "Pauza: aloqa juda sekin. Avtomatik davom etadi.",
        "queue.status.paused.failing": "Pauza: aloqa qayta-qayta uzilmoqda. Qayta urinish uchun davom ettiring.",
        "queue.status.completed": "Tayyor · kutubxonaga saqlandi",
        "queue.status.completed_partial": "Tayyor: {total} tadan {done} tasi saqlandi, {failed} tasi mavjud emas",
        "queue.status.failed": "Xatolik: {message}",
        "queue.status.cancelled": "Bekor qilindi",
        "queue.show_videos": "Videolarni ko'rish",
        "queue.videos_running.one": "{n} ta video yuklanmoqda",
        "queue.videos_running.other": "{n} ta video yuklanmoqda",
        "queue.saved_of": "{total} tadan {done} tasi saqlandi",
        # playlist detail
        "playlist.back": "Yuklash navbati",
        "playlist.count.done": "Saqlandi",
        "playlist.count.active": "Yuklanmoqda",
        "playlist.count.waiting": "Kutmoqda",
        "playlist.count.failed": "O'tkazib yuborildi",
        "entry.waiting": "Navbatda",
        "entry.saved": "Saqlandi",
        "entry.failed": "O'tkazib yuborildi: mavjud emas yoki xato",
        "entry.paused": "Pauza qilingan",
        "entry.cancelled": "Bekor qilindi",
        "entry.not_downloaded": "Yuklanmadi",
        "activity.items.other": "{n} ta yuklama",
        "notify.added": "Navbatga qo'shildi.",
        "notify.added_waiting": "Navbatga qo'shildi. Joy bo'shaganda boshlanadi.",
        "notify.duplicate": "Bu allaqachon navbatda bor.",
        "notify.item_done": "Yuklab olindi: {title}",
        "notify.item_failed": "“{title}” yuklanmadi: {message}",
        "quit.title": "Dasturdan chiqilsinmi?",
        "quit.message.other": "{n} ta yuklash hali tugamagan. Ular hozir to'xtaydi; keyin qayta qo'shsangiz, to'xtagan joyidan davom etadi.",
        "notify.clipboard_empty": "Bufer bo'sh.",
        "notify.paste_first": "Avval YouTube havolasini qo'ying.",
        "notify.playlist_empty": "Bu playlistda mavjud video yo'q.",
        "notify.fetch_error": "Havolani o'qib bo'lmadi: {message}",
        "notify.deleted": "“{title}” o'chirildi.",
        "notify.delete_error": "O'chirib bo'lmadi: {error}",
        "notify.open_error": "Ochib bo'lmadi: {error}",
        "notify.folder_error": "Papkani ochib bo'lmadi: {error}",
        "notify.read_error": "Yuklamalar papkasini o'qib bo'lmadi: {error}",
        "notify.connection_lost": "Internet uzildi: yuklashlar pauza qilindi. Avtomatik davom etadi.",
        "notify.connection_stalled": "Aloqa sekinlashdi: yuklash pauza qilindi. Avtomatik davom etadi.",
        "notify.back_online": "Internet qaytdi: yuklashlar davom etmoqda.",
    },
}

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uz": ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"],
}

_current = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    global _current
    _current = code if code in STRINGS else DEFAULT_LANGUAGE


def get_language() -> str:
    return _current


def t(key: str, **values) -> str:
    """Translated text for `key` (falls back to English, then to the key itself)."""
    text = STRINGS[_current].get(key) or STRINGS[DEFAULT_LANGUAGE].get(key) or key
    return text.format(**values) if values else text


def tn(key: str, n: int, **values) -> str:
    """Count-dependent text: uses `key.one` for 1 (where the language has it), else `key.other`."""
    table = STRINGS[_current]
    form = f"{key}.one" if n == 1 and f"{key}.one" in table else f"{key}.other"
    if form not in table:
        table = STRINGS[DEFAULT_LANGUAGE]
        form = f"{key}.one" if n == 1 else f"{key}.other"
    return table[form].format(n=n, **values)


def format_date(timestamp: float) -> str:
    d = datetime.fromtimestamp(timestamp)
    return f"{d.day:02d} {MONTHS[_current][d.month - 1]} {d.year}"


# --------------------------------------------------------------------------- system language

def _language_code(tag: str | None) -> str | None:
    """'uz_UZ.UTF-8' / 'uz-Latn-UZ' / 'en-US' -> 'uz' / 'en' (None if unknown)."""
    if not tag:
        return None
    code = tag.replace("-", "_").split("_")[0].split(".")[0].lower()
    return code if code else None


def _macos_languages() -> list[str]:
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [part.strip().strip('",()') for part in out.split() if part.strip().strip('",()')]


def _windows_language() -> str | None:
    try:
        buffer = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):  # e.g. "uz-Latn-UZ"
            return buffer.value
    except (AttributeError, OSError):
        pass
    return None


def detect_system_language() -> str:
    """The first supported language in the user's OS preferences, else English."""
    candidates: list[str] = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):  # Linux (and terminals everywhere)
        value = os.environ.get(var)
        if value:
            candidates += value.split(":")
    if sys.platform == "darwin":
        candidates = _macos_languages() + candidates  # apps opened from Finder have no LANG
    elif sys.platform == "win32":
        candidates = [_windows_language() or ""] + candidates
    try:
        candidates.append(locale.getlocale()[0] or "")
    except ValueError:
        pass
    for tag in candidates:
        code = _language_code(tag)
        if code in STRINGS:
            return code
        if code and code not in ("c", "posix"):
            return DEFAULT_LANGUAGE  # the user's first choice isn't supported: use English
    return DEFAULT_LANGUAGE
