import pytest

from widgets.icons import render_icon
from widgets.images import placeholder, rounded_thumbnail

ICONS = ["play", "download", "library", "folder", "trash", "search", "sun", "moon", "monitor",
         "clipboard", "refresh", "x", "check", "music", "alert", "list"]


@pytest.mark.parametrize("name", ICONS)
def test_every_icon_renders_something(name):
    img = render_icon(name, 18, "#ffffff")
    assert img.size == (36, 36)
    assert img.getchannel("A").getbbox() is not None  # not empty


def test_unknown_icon_raises():
    with pytest.raises(ValueError):
        render_icon("nope", 18, "#ffffff")


def test_rounded_thumbnail_has_transparent_corners():
    img = rounded_thumbnail(None, (160, 90), radius=12)
    assert img.size == (320, 180) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0
    assert img.getpixel((160, 90))[3] == 255


def test_placeholder_size():
    assert placeholder(200, 100, audio=True).size == (200, 100)
