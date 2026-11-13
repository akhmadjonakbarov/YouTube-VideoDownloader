from services.formatting import format_duration, format_size, format_speed, quality_tag, truncate


def test_format_size():
    assert format_size(None) == ""
    assert format_size(5 * 1024 * 1024) == "5.0 MB"
    assert format_size(250 * 1024 * 1024) == "250 MB"
    assert format_size(3 * 1024**3) == "3.00 GB"


def test_format_duration():
    assert format_duration(None) == ""
    assert format_duration(65) == "1:05"
    assert format_duration(3725) == "1:02:05"


def test_format_speed():
    assert format_speed(None) == ""
    assert format_speed(2 * 1024 * 1024) == "2.0 MB/s"


def test_truncate():
    assert truncate("short", 10) == "short"
    assert truncate("a very long title", 8) == "a very…"


def test_quality_tag():
    assert [quality_tag(h) for h in (None, 2160, 1440, 1080, 720, 480)] == ["Auto", "4K", "2K", "Full HD", "HD", "SD"]
