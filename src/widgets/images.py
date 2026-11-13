"""Thumbnail helpers: rounded corners and good-looking placeholders."""
from PIL import Image, ImageDraw, ImageFont, ImageOps

from widgets.icons import render_icon

_VIDEO_GRADIENT = ("#3F3F46", "#18181B")
_AUDIO_GRADIENT = ("#7C3AED", "#DB2777")


def _gradient(width: int, height: int, top: str, bottom: str) -> Image.Image:
    mask = Image.linear_gradient("L").resize((width, height))
    return Image.composite(Image.new("RGB", (width, height), bottom), Image.new("RGB", (width, height), top), mask)


def placeholder(width: int, height: int, audio: bool = False) -> Image.Image:
    base = _gradient(width, height, *(_AUDIO_GRADIENT if audio else _VIDEO_GRADIENT))
    glyph_px = max(12, height // 6)
    glyph = render_icon("music" if audio else "play", glyph_px, "#FFFFFF")
    glyph.putalpha(glyph.getchannel("A").point(lambda a: int(a * 0.8)))
    base.paste(glyph, ((width - glyph.width) // 2, (height - glyph.height) // 2), glyph)
    return base


def _draw_badge(img: Image.Image, text: str) -> None:
    """Dark rounded label in the bottom-right corner (e.g. "22:05", "MP4")."""
    w, h = img.size
    font = ImageFont.load_default(size=max(14, w // 24))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad_x, pad_y = font.size * 0.55, font.size * 0.35
    box_w, box_h = right - left + 2 * pad_x, bottom - top + 2 * pad_y
    margin = w * 0.03
    x1, y1 = w - margin, h - margin
    x0, y0 = x1 - box_w, y1 - box_h

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle((x0, y0, x1, y1), radius=box_h * 0.3, fill=(0, 0, 0, 190))
    img.alpha_composite(overlay)
    ImageDraw.Draw(img).text((x0 + pad_x - left, y0 + pad_y - top), text, font=font, fill="white")


def rounded_thumbnail(image: Image.Image | None, size: tuple[int, int], radius: int,
                      audio: bool = False, badge: str | None = None) -> Image.Image:
    """RGBA image at 2x `size` (sharp on Retina), cropped to fit, with rounded corners."""
    w, h = size[0] * 2, size[1] * 2
    if image is not None:
        base = ImageOps.fit(image.convert("RGB"), (w, h), Image.LANCZOS)
    else:
        base = placeholder(w, h, audio)

    # Anti-aliased mask: draw 4x larger and scale down.
    big = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 8, fill=255)
    mask = big.resize((w, h), Image.LANCZOS)

    result = base.convert("RGBA")
    if badge:
        _draw_badge(result, badge)
    result.putalpha(mask)
    return result
