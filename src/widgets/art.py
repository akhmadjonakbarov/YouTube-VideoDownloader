"""Decorative images drawn with Pillow: hero banner, progress ring, empty-state art.

Everything is rendered at 2x for sharpness on Retina/HiDPI screens and uses the
bundled Inter font so it looks identical on every OS.
"""
import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.theme import FONTS_DIR
from widgets.icons import render_icon

HERO_BASE = "#4A1236"
HERO_BLOBS = [  # (x, y, radius) as fractions of the banner, color
    ((0.08, 0.10, 0.55), "#F23A4E"),
    ((0.35, 1.05, 0.50), "#FF7A45"),
    ((0.70, 0.05, 0.45), "#B83280"),
    ((0.95, 0.85, 0.55), "#7C3AED"),
    ((0.50, 0.45, 0.35), "#D62F5C"),
]


@lru_cache(maxsize=16)
def load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONTS_DIR / name), size)
    except OSError:
        return ImageFont.load_default(size=size)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    w, h = size
    big = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=radius * 4, fill=255)
    return big.resize(size, Image.LANCZOS)


@lru_cache(maxsize=4)
def _hero_background(width: int, height: int) -> Image.Image:
    """Soft 'mesh gradient': blurred colour blobs on a dark base, plus fine grain."""
    small_w, small_h = max(1, width // 8), max(1, height // 8)
    img = Image.new("RGB", (small_w, small_h), HERO_BASE)
    draw = ImageDraw.Draw(img)
    for (fx, fy, fr), color in HERO_BLOBS:
        r = fr * small_h * 1.6
        cx, cy = fx * small_w, fy * small_h
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    img = img.filter(ImageFilter.GaussianBlur(small_h * 0.45)).resize((width, height), Image.BICUBIC)

    rng = random.Random(7)  # subtle grain, same every time
    grain = Image.new("L", (width // 2, height // 2))
    grain.putdata([rng.randint(118, 138) for _ in range(grain.width * grain.height)])
    grain = grain.resize((width, height)).convert("RGB")
    return Image.blend(img, grain, 0.06)


def hero_banner(width: int, height: int, title: str, subtitle: str, radius: int = 22) -> Image.Image:
    """Banner at 2x the given size, text included."""
    w, h = width * 2, height * 2
    img = _hero_background(w, h).copy().convert("RGBA")

    # Decorative stacked "video cards" on the right.
    deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    card_w, card_h = int(h * 0.95), int(h * 0.95 * 9 / 16)
    base_x, base_y = w - card_w - int(h * 0.28), int(h * 0.30)
    for i, alpha in enumerate((40, 70, 120)):
        off = (2 - i) * int(h * 0.09)
        box = (base_x + off, base_y - off, base_x + off + card_w, base_y - off + card_h)
        d.rounded_rectangle(box, radius=int(h * 0.06), fill=(255, 255, 255, alpha),
                            outline=(255, 255, 255, alpha + 40), width=2)
    play = render_icon("play", max(12, int(card_h * 0.22)), "#FFFFFF")
    front_cx, front_cy = base_x + card_w // 2, base_y + card_h // 2
    deco.alpha_composite(play, (front_cx - play.width // 2, front_cy - play.height // 2))
    if w > h * 4.2:  # only when there's room next to the text
        img.alpha_composite(deco)

    # Text goes on its own layer: ImageDraw replaces pixels instead of blending,
    # so translucent fills must be composited.
    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    pad = int(h * 0.17)
    title_font = load_font("InterDisplay-Bold.otf", int(h * 0.20))
    sub_font = load_font("Inter-Medium.otf", int(h * 0.092))
    pill_font = load_font("Inter-SemiBold.otf", int(h * 0.072))

    pill_text = "YT DOWNLOADER"
    pb = draw.textbbox((0, 0), pill_text, font=pill_font)
    pill_h = int(h * 0.15)
    pill_w = pb[2] - pb[0] + int(pill_h * 1.1)
    py = pad
    draw.rounded_rectangle((pad, py, pad + pill_w, py + pill_h), radius=pill_h // 2, fill=(255, 255, 255, 40), outline=(255, 255, 255, 70), width=2)
    draw.text((pad + pill_h * 0.55 - pb[0], py + (pill_h - (pb[3] - pb[1])) / 2 - pb[1]), pill_text,
              font=pill_font, fill=(255, 255, 255, 235))

    ty = py + pill_h + int(h * 0.09)
    draw.text((pad, ty), title, font=title_font, fill="white")
    tb = draw.textbbox((pad, ty), title, font=title_font)
    draw.text((pad, tb[3] + int(h * 0.06)), subtitle, font=sub_font, fill=(255, 255, 255, 215))
    img.alpha_composite(text_layer)

    img.putalpha(_rounded_mask((w, h), radius * 2))
    return img


def progress_ring(fraction: float, size: int, track: str, color: str, text_color: str,
                  label: str | None = None) -> Image.Image:
    """Circular progress indicator with the percentage in the middle (2x size)."""
    s = size * 2
    scale = 3
    n = s * scale
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = int(n * 0.075)
    inset = stroke // 2 + 2
    box = (inset, inset, n - inset, n - inset)
    d.ellipse(box, outline=track, width=stroke)
    fraction = max(0.0, min(1.0, fraction))
    if fraction > 0:
        start, end = -90, -90 + 360 * fraction
        d.arc(box, start=start, end=end, fill=color, width=stroke)
        mid_r = (n - 2 * inset) / 2 - stroke / 2  # radius of the stroke's centre line
        c = n / 2
        for angle in (start, end):  # round caps
            a = math.radians(angle)
            x, y = c + mid_r * math.cos(a), c + mid_r * math.sin(a)
            d.ellipse((x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2), fill=color)
    img = img.resize((s, s), Image.LANCZOS)

    d = ImageDraw.Draw(img)
    text = label if label is not None else f"{int(fraction * 100)}%"
    f = load_font("InterDisplay-SemiBold.otf", int(s * 0.24))
    b = d.textbbox((0, 0), text, font=f)
    d.text(((s - (b[2] - b[0])) / 2 - b[0], (s - (b[3] - b[1])) / 2 - b[1]), text, font=f, fill=text_color)
    return img


def empty_illustration(size: int, accent: str, card: str, line: str) -> Image.Image:
    """Stacked video cards with a download badge (2x size)."""
    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cw, ch = int(s * 0.62), int(s * 0.42)
    for i, (dx, dy, alpha) in enumerate(((0.26, 0.20, 90), (0.18, 0.28, 160), (0.10, 0.36, 255))):
        x, y = int(s * dx), int(s * dy)
        fill = _with_alpha(card, alpha)
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=int(s * 0.05), fill=fill, outline=_with_alpha(line, alpha), width=3)
        if i == 2:
            # thumbnail lines on the front card
            d.rounded_rectangle((x + int(cw * 0.08), y + int(ch * 0.62), x + int(cw * 0.62), y + int(ch * 0.72)),
                                radius=6, fill=_with_alpha(line, 255))
            d.rounded_rectangle((x + int(cw * 0.08), y + int(ch * 0.80), x + int(cw * 0.42), y + int(ch * 0.88)),
                                radius=6, fill=_with_alpha(line, 160))
            tri = int(ch * 0.16)
            cx, cy = x + int(cw * 0.5), y + int(ch * 0.33)
            d.polygon([(cx - tri * 0.7, cy - tri), (cx + tri, cy), (cx - tri * 0.7, cy + tri)], fill=_with_alpha(line, 255))
    # download badge
    r = int(s * 0.14)
    bx, by = int(s * 0.74), int(s * 0.74)
    d.ellipse((bx - r, by - r, bx + r, by + r), fill=accent)
    arrow = render_icon("download", int(r * 0.55), "#FFFFFF")
    img.alpha_composite(arrow, (bx - arrow.width // 2, by - arrow.height // 2))
    return img


def _with_alpha(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), alpha)


def check_badge(size: int, color: str) -> Image.Image:
    """Filled circle with a white check mark (2x size)."""
    s = size * 2
    n = s * 4
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, n - 1, n - 1), fill=color)
    img = img.resize((s, s), Image.LANCZOS)
    check = render_icon("check", int(size * 0.62), "#FFFFFF")
    img.alpha_composite(check, ((s - check.width) // 2, (s - check.height) // 2 + 1))
    return img
