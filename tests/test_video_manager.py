import os

from PIL import Image

from services.video_manager import VideoManager


def touch(path, size=0, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_creates_missing_folder(tmp_path):
    folder = tmp_path / "does" / "not" / "exist"
    manager = VideoManager(folder)
    assert folder.is_dir()
    assert manager.get_videos() == []


def test_lists_finished_media_newest_first_including_playlists(tmp_path):
    touch(tmp_path / "old.mp4", mtime=1_000)
    touch(tmp_path / "new.webm", mtime=3_000)
    touch(tmp_path / "song.mp3", mtime=2_500)
    touch(tmp_path / "My list" / "001 - first.mp4", mtime=2_000)
    touch(tmp_path / "partial.mp4.part")
    touch(tmp_path / "stream.f137.mp4")
    touch(tmp_path / "merging.temp.mp4")
    touch(tmp_path / "notes.txt")
    touch(tmp_path / ".hidden" / "x.mp4")

    videos = VideoManager(tmp_path).get_videos()
    assert [v.title for v in videos] == ["new", "song", "001 - first", "old"]

    by_title = {v.title: v for v in videos}
    assert by_title["001 - first"].folder_label == "My list"
    assert by_title["old"].folder_label is None
    assert by_title["song"].is_audio and not by_title["new"].is_audio


def test_loads_thumbnail_next_to_video(tmp_path):
    touch(tmp_path / "clip.mp4")
    Image.new("RGB", (1280, 720), "red").save(tmp_path / "clip.jpg")

    (video,) = VideoManager(tmp_path).get_videos()
    assert video.image is not None
    assert video.image.size == (320, 180)


def test_missing_or_broken_thumbnail_is_none(tmp_path):
    touch(tmp_path / "a.mp4")
    touch(tmp_path / "b.mp4")
    (tmp_path / "b.jpg").write_bytes(b"not an image")

    videos = VideoManager(tmp_path).get_videos()
    assert all(v.image is None for v in videos)


def test_delete_removes_file_thumbnail_and_empty_playlist_folder(tmp_path):
    touch(tmp_path / "PL" / "a.mp4", mtime=2_000)
    Image.new("RGB", (10, 10)).save(tmp_path / "PL" / "a.jpg")
    touch(tmp_path / "PL" / "b.mp4", mtime=1_000)
    manager = VideoManager(tmp_path)

    first, second = manager.get_videos()
    manager.delete_video(first)
    assert sorted(p.name for p in (tmp_path / "PL").iterdir()) == ["b.mp4"]

    manager.delete_video(second)
    assert list(tmp_path.iterdir()) == []
