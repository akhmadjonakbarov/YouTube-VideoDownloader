import threading

import pytest
from yt_dlp.utils import DownloadCancelled

from models.media import AUDIO_ONLY, QualityOption
from services import video_downloader as vd

FORMATS = [
    {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none", "height": 90},
    {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 3_145_728},
    {"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "filesize": 10_485_760},
    {"format_id": "136", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 720, "filesize": 41_943_040},
    {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080, "filesize_approx": 83_886_080},
    {"format_id": "248", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 1080, "filesize": 73_400_320},
]
VIDEO_INFO = {
    "_type": "video", "id": "abc", "title": "My video", "uploader": "Chan", "duration": 125,
    "webpage_url": "https://www.youtube.com/watch?v=abc", "thumbnail": "https://i.ytimg.com/x.jpg",
    "formats": FORMATS,
}


# ----------------------------------------------------------------- qualities

def test_quality_options_with_ffmpeg_lists_all_resolutions():
    options = vd.quality_options(VIDEO_INFO, has_ffmpeg=True)
    assert [o.height for o in options] == [1080, 720, 360, None]
    assert options[-1].audio_only
    # largest 1080p stream (80 MB) + audio (3 MB)
    assert options[0].label == "1080p"
    assert options[0].size_bytes == 83_886_080 + 3_145_728


def test_quality_options_without_ffmpeg_only_progressive():
    options = vd.quality_options(VIDEO_INFO, has_ffmpeg=False)
    assert [o.height for o in options] == [360, None]
    assert options[0].size_bytes == 10_485_760  # no separate audio to add


def test_quality_options_when_no_heights_known():
    options = vd.quality_options({"formats": []}, has_ffmpeg=True)
    assert [o.label for o in options] == ["Best available", "Audio only"]


def test_default_quality():
    assert vd.default_quality(vd.quality_options(VIDEO_INFO, True)).height == 720
    assert vd.default_quality([QualityOption("1080p", 1080), AUDIO_ONLY]).height == 1080
    assert vd.default_quality([QualityOption("Best available"), AUDIO_ONLY]).label == "Best available"
    assert vd.default_quality(vd.playlist_quality_options()).height == 720


# -------------------------------------------------------------- parse_info

def test_parse_video_info():
    media = vd.parse_info(VIDEO_INFO, "u", has_ffmpeg=True)
    assert not media.is_playlist
    assert media.title == "My video"
    assert media.url == "https://www.youtube.com/watch?v=abc"
    assert media.duration == 125
    assert media.thumbnail_url == "https://i.ytimg.com/x.jpg"


def test_parse_playlist_info_keeps_positions_and_skips_missing():
    info = {
        "_type": "playlist", "title": "PL", "uploader": "Chan",
        "webpage_url": "https://www.youtube.com/playlist?list=PL1",
        "entries": [
            {"title": "One", "duration": 60, "thumbnails": [{"url": "small"}, {"url": "big"}]},
            None,
            {"title": None},
        ],
    }
    media = vd.parse_info(info, "u", has_ffmpeg=True)
    assert media.is_playlist
    assert [(e.index, e.title) for e in media.entries] == [(1, "One"), (3, "Untitled")]
    assert media.thumbnail_url == "big"
    assert media.qualities[-1].audio_only


def test_playlist_entries_keep_their_own_links():
    info = {"_type": "playlist", "title": "PL", "entries": [
        {"title": "A", "url": "https://www.youtube.com/watch?v=a", "ie_key": "Youtube"},
        {"title": "B", "url": "https://www.youtube.com/playlist?list=x", "ie_key": "YoutubeTab"},  # nested list
        {"title": "C", "url": "c-id-only"},
        {"title": "D", "webpage_url": "https://example.com/d", "url": "https://cdn/d.mp4"},
    ]}
    media = vd.parse_info(info, "u", has_ffmpeg=True)
    # B and C have no usable link of their own, so the playlist downloads one by one
    assert [e.url for e in media.entries] == [None, None, None, None]

    info["entries"] = [info["entries"][0], {"title": "D", "webpage_url": "https://example.com/list", "url": "https://cdn/d.mp4"}]
    media = vd.parse_info(info, "https://example.com/list", has_ffmpeg=True)
    assert [e.url for e in media.entries] == ["https://www.youtube.com/watch?v=a", "https://cdn/d.mp4"]


def test_playlist_links_that_are_not_separate_videos_are_ignored():
    page = "https://example.com/list"
    same = {"_type": "playlist", "title": "PL", "entries": [{"title": "A", "url": page}, {"title": "B", "url": page}]}
    assert [e.url for e in vd.parse_info(same, page, True).entries] == [None, None]
    dup = {"_type": "playlist", "title": "PL", "entries": [{"title": "A", "url": "https://x/1"}, {"title": "B", "url": "https://x/1"}]}
    assert [e.url for e in vd.parse_info(dup, page, True).entries] == [None, None]


# ------------------------------------------------------------ build_format

def test_build_format():
    assert vd.build_format(QualityOption("720p", 720), True).startswith("bv*[height<=720]+ba")
    assert "+" not in vd.build_format(QualityOption("720p", 720), False)
    assert vd.build_format(AUDIO_ONLY, True) == "ba/b"
    assert vd.build_format(AUDIO_ONLY, False).startswith("ba[ext=m4a]")
    assert vd.build_format(QualityOption("Best available"), True) == "bv*+ba/b"


# ------------------------------------------------------------- DownloadJob

def make_job(tmp_path, monkeypatch, events=None, **kwargs):
    monkeypatch.setattr(vd, "VIDEOS_FOLDER", tmp_path)
    params = {
        "url": "u",
        "option": QualityOption("720p", 720),
        "on_progress": (events if events is not None else []).append,
        "has_ffmpeg": True,
    }
    params.update(kwargs)
    return vd.DownloadJob(**params)


def test_single_video_options(tmp_path, monkeypatch):
    opts = make_job(tmp_path, monkeypatch).options()
    assert opts["noplaylist"] is True
    assert opts["ignoreerrors"] is False
    assert opts["merge_output_format"] == "mp4/mkv"
    assert opts["outtmpl"] == str(tmp_path / "%(title)s.%(ext)s")
    assert "playlist_items" not in opts


def test_single_playlist_video_goes_to_the_playlist_folder(tmp_path, monkeypatch):
    opts = make_job(tmp_path, monkeypatch, folder="Best of 100% / Part 1", index=7).options()
    assert opts["noplaylist"] is True and opts["playlist_items"] == "1"
    assert opts["outtmpl"] == str(tmp_path / "Best of 100%% ⧸ Part 1" / "007 - %(title)s.%(ext)s")


def test_playlist_options(tmp_path, monkeypatch):
    opts = make_job(tmp_path, monkeypatch, playlist=True, items=[1, 3], total=2).options()
    assert opts["noplaylist"] is False
    assert opts["playlist_items"] == "1,3"
    assert opts["ignoreerrors"] == "only_download"
    assert "%(playlist_title)s" in opts["outtmpl"]


def test_audio_options(tmp_path, monkeypatch):
    opts = make_job(tmp_path, monkeypatch, option=AUDIO_ONLY).options()
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert "FFmpegExtractAudio" in keys
    assert "merge_output_format" not in opts

    opts = make_job(tmp_path, monkeypatch, option=AUDIO_ONLY, has_ffmpeg=False).options()
    assert "postprocessors" not in opts


def test_progress_events_number_playlist_items(tmp_path, monkeypatch):
    events = []
    job = make_job(tmp_path, monkeypatch, events=events, playlist=True, total=2)
    opts = job.options()
    hook, pp_hook, post_hook = opts["progress_hooks"][0], opts["postprocessor_hooks"][0], opts["post_hooks"][0]

    hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 200, "speed": 1000, "eta": 5,
          "info_dict": {"id": "a", "title": "A", "vcodec": "avc1"}})
    hook({"status": "downloading", "downloaded_bytes": 10, "info_dict": {"id": "a", "title": "A", "vcodec": "none"}})
    pp_hook({"status": "started", "postprocessor": "Merger", "info_dict": {"id": "a", "title": "A"}})
    post_hook("/x/A.mp4")
    hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 4,
          "info_dict": {"id": "b", "title": "B", "vcodec": "avc1"}})

    assert [(e.stage, e.fraction, e.item_number, e.item_count) for e in events] == [
        ("download_video", 0.25, 1, 2),
        ("download_audio", None, 1, 2),
        ("merging", None, 1, 2),
        ("saved", 1.0, 1, 2),
        ("download_video", 0.25, 2, 2),
    ]
    assert events[0].speed == 1000 and events[0].eta == 5 and events[0].item_title == "A"
    assert job.completed == 1


def test_cancel_raises_from_hook(tmp_path, monkeypatch):
    cancel = threading.Event()
    hook = make_job(tmp_path, monkeypatch, cancel_event=cancel).options()["progress_hooks"][0]
    cancel.set()
    with pytest.raises(DownloadCancelled):
        hook({"status": "downloading", "info_dict": {}})


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL; `action` simulates what happens during download()."""

    action = staticmethod(lambda opts: None)

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls):
        type(self).action(self.opts)


def test_run_success(tmp_path, monkeypatch):
    monkeypatch.setattr(FakeYDL, "action", staticmethod(lambda opts: opts["post_hooks"][0]("/x.mp4")))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    result = make_job(tmp_path, monkeypatch).run()
    assert (result.completed, result.total, result.cancelled) == (1, 1, False)


def test_run_cancelled(tmp_path, monkeypatch):
    cancel = threading.Event()

    def action(opts):
        cancel.set()
        opts["progress_hooks"][0]({"status": "downloading", "info_dict": {"id": "a"}})

    monkeypatch.setattr(FakeYDL, "action", staticmethod(action))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    result = make_job(tmp_path, monkeypatch, cancel_event=cancel).run()
    assert result.cancelled and result.completed == 0


def test_run_playlist_with_nothing_downloaded_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(RuntimeError):
        make_job(tmp_path, monkeypatch, playlist=True, total=3).run()


def test_clean_error_strips_prefix_and_colors():
    err = Exception("\x1b[0;31mERROR:\x1b[0m [youtube] abc: Video unavailable")
    assert vd.clean_error(err) == "[youtube] abc: Video unavailable"
    assert len(vd.clean_error(Exception("x" * 500))) == 200


# --------------------------------------------------------------- find_ffmpeg

def test_find_ffmpeg_prefers_bundled_copy(tmp_path, monkeypatch):
    exe = "ffmpeg.exe" if vd.sys.platform == "win32" else "ffmpeg"
    (tmp_path / "ffmpeg" / "bin").mkdir(parents=True)
    (tmp_path / "ffmpeg" / "bin" / exe).write_bytes(b"")
    monkeypatch.setattr(vd, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(vd.shutil, "which", lambda name: "/somewhere/else/ffmpeg")
    assert vd.find_ffmpeg() == str(tmp_path / "ffmpeg" / "bin")


def test_find_ffmpeg_falls_back_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(vd.shutil, "which", lambda name: "/usr/local/bin/ffmpeg")
    assert vd.find_ffmpeg() == "/usr/local/bin"


def test_find_ffmpeg_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(vd.shutil, "which", lambda name: None)
    monkeypatch.setattr(vd, "_EXTRA_FFMPEG_DIRS", ())
    assert vd.find_ffmpeg() is None
    assert not vd.ffmpeg_available()


def test_ffmpeg_location_passed_to_yt_dlp(tmp_path, monkeypatch):
    assert make_job(tmp_path, monkeypatch, ffmpeg_location="/opt/ff/bin").options()["ffmpeg_location"] == "/opt/ff/bin"
    assert "ffmpeg_location" not in make_job(tmp_path, monkeypatch).options()


# ----------------------------------------------------------------- Deno (JS runtime)

def test_find_deno_prefers_bundled_copy(tmp_path, monkeypatch):
    exe = "deno.exe" if vd.sys.platform == "win32" else "deno"
    (tmp_path / "deno").mkdir()
    (tmp_path / "deno" / exe).write_bytes(b"")
    monkeypatch.setattr(vd, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(vd.shutil, "which", lambda name: "/elsewhere/deno")
    assert vd.find_deno() == str(tmp_path / "deno" / exe)


def test_find_deno_on_path_or_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "resource_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(vd.shutil, "which", lambda name: "/usr/local/bin/deno")
    assert vd.find_deno() == "/usr/local/bin/deno"
    monkeypatch.setattr(vd.shutil, "which", lambda name: None)
    monkeypatch.setattr(vd, "_EXTRA_FFMPEG_DIRS", ())
    monkeypatch.setattr(vd.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    assert vd.find_deno() is None


def test_deno_passed_to_yt_dlp(tmp_path, monkeypatch):
    opts = make_job(tmp_path, monkeypatch, deno_path="/x/deno").options()
    assert opts["js_runtimes"] == {"deno": {"path": "/x/deno"}}
    assert "js_runtimes" not in make_job(tmp_path, monkeypatch).options()  # yt-dlp default (deno on PATH)


def test_missing_tools_message():
    assert vd.missing_tools_message(True, True) is None
    mac = vd.missing_tools_message(False, False, "darwin")
    assert "brew install ffmpeg deno" in mac and "Deno" in mac and "ffmpeg" in mac
    assert "brew install deno" in vd.missing_tools_message(True, False, "darwin")
    assert "winget install Gyan.FFmpeg" in vd.missing_tools_message(False, True, "win32")
    assert "deno.land/install.sh" in vd.missing_tools_message(True, False, "linux")


# ------------------------------------------------------------ pause / resume

def test_pause_raises_from_hooks(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    hook = job.options()["progress_hooks"][0]
    job.pause_event.set()
    with pytest.raises(vd.DownloadPaused):
        hook({"status": "downloading", "info_dict": {}})
    assert issubclass(vd.DownloadPaused, DownloadCancelled)  # yt-dlp lets it through ignoreerrors


def test_run_returns_paused_and_can_resume(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    calls = []

    def action(opts):
        calls.append(1)
        if len(calls) == 1:  # first run: user presses Pause mid-download
            job.pause_event.set()
            opts["progress_hooks"][0]({"status": "downloading", "info_dict": {"id": "a"}})
        else:                # second run: continues and finishes
            assert opts["continuedl"] is True
            opts["post_hooks"][0]("/x/a.mp4")

    monkeypatch.setattr(FakeYDL, "action", staticmethod(action))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    first = job.run()
    assert first.paused and not first.network_error and not first.cancelled
    second = job.run()  # same job object = resume
    assert not second.paused and second.completed == 1


def test_network_failure_pauses_instead_of_failing(tmp_path, monkeypatch):
    def action(opts):
        raise vd.yt_dlp.utils.DownloadError(
            "ERROR: unable to download video data: <urlopen error [Errno 8] nodename nor servname provided>")

    monkeypatch.setattr(FakeYDL, "action", staticmethod(action))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    result = make_job(tmp_path, monkeypatch).run()
    assert result.paused and result.network_error


def test_other_errors_still_fail(tmp_path, monkeypatch):
    def action(opts):
        raise vd.yt_dlp.utils.DownloadError("ERROR: [youtube] abc: Video unavailable")

    monkeypatch.setattr(FakeYDL, "action", staticmethod(action))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(vd.yt_dlp.utils.DownloadError):
        make_job(tmp_path, monkeypatch).run()


def test_playlist_video_failing_on_network_pauses_the_playlist(tmp_path, monkeypatch):
    def action(opts):
        opts["post_hooks"][0]("/x/1.mp4")  # first video done
        # yt-dlp (ignoreerrors) logs the network failure of video 2 and carries on...
        opts["logger"].error("ERROR: unable to download video data: The read operation timed out")
        # ...but our logger requested a pause, so the next video's first hook stops everything.
        opts["progress_hooks"][0]({"status": "downloading", "info_dict": {"id": "3"}})

    monkeypatch.setattr(FakeYDL, "action", staticmethod(action))
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", FakeYDL)
    result = make_job(tmp_path, monkeypatch, playlist=True, total=3).run()
    assert result.paused and result.network_error and result.completed == 1


def test_completed_files_not_counted_twice_after_resume(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    post = job.options()["post_hooks"][0]
    post("/x/a.mp4")
    post("/x/a.mp4")  # yt-dlp reports already-finished files again when a playlist resumes
    assert job.completed == 1


@pytest.mark.parametrize("message, expected", [
    ("<urlopen error [Errno 8] nodename nor servname provided, or not known>", True),
    ("The read operation timed out", True),
    ("[Errno 101] Network is unreachable", True),
    ("Connection reset by peer", True),
    ("[download] Got error: 9699328 bytes read, 2884608 more expected", True),
    ("<urlopen error [Errno -3] Temporary failure in name resolution>", True),
    ("HTTP Error 403: Forbidden", False),
    ("[youtube] abc: Video unavailable", False),
    ("Sign in to confirm you're not a bot", False),
])
def test_is_network_error_messages(message, expected):
    assert vd.is_network_error(message) is expected


def test_is_network_error_follows_wrapped_exceptions():
    import socket
    try:
        try:
            raise socket.timeout("timed out")
        except socket.timeout as inner:
            raise vd.yt_dlp.utils.DownloadError("ERROR: something went wrong", exc_info=(type(inner), inner, None))
    except vd.yt_dlp.utils.DownloadError as err:
        assert vd.is_network_error(err)
