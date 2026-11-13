"""A small line-icon set drawn with Pillow, so icons look the same on every OS
and don't depend on which emoji/symbol fonts are installed."""
import math
from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw

from config import theme

GRID = 24        # icons are designed on a 24x24 grid (like Lucide/Feather)
SUPERSAMPLE = 4  # draw big, then downscale for smooth edges

ColorPair = tuple[str, str]


def render_icon(name: str, px: int, color: str) -> Image.Image:
    """Render icon `name` as an RGBA image of px*2 (sharp on Retina screens)."""
    n = px * 2 * SUPERSAMPLE
    u = n / GRID
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, round(2 * u))
    clear = (0, 0, 0, 0)

    def pts(*points):
        return [(x * u, y * u) for x, y in points]

    def line(*points):
        p = pts(*points)
        d.line(p, fill=color, width=w, joint="curve")
        r = w / 2
        for x, y in p:  # round caps
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def rrect(x0, y0, x1, y1, radius, fill=None):
        d.rounded_rectangle((x0 * u, y0 * u, x1 * u, y1 * u), radius=radius * u,
                            outline=color, width=w, fill=fill)

    def circle(cx, cy, r, filled=False):
        box = ((cx - r) * u, (cy - r) * u, (cx + r) * u, (cy + r) * u)
        if filled:
            d.ellipse(box, fill=color)
        else:
            d.ellipse(box, outline=color, width=w)

    if name == "play":
        d.polygon(pts((7.5, 4.5), (19.5, 12), (7.5, 19.5)), fill=color)
    elif name == "download":
        line((12, 3.5), (12, 15))
        line((7, 10), (12, 15), (17, 10))
        line((4, 15.5), (4, 20), (20, 20), (20, 15.5))
    elif name == "library":
        for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
            rrect(x, y, x + 7, y + 7, 2)
    elif name == "folder":
        line((3, 6), (3, 18), (4, 19), (20, 19), (21, 18), (21, 9), (20, 8),
             (12, 8), (10, 5), (4, 5), (3, 6))
    elif name == "trash":
        line((4, 7), (20, 7))
        line((9, 7), (9, 4.5), (15, 4.5), (15, 7))
        line((6, 7), (7, 20), (17, 20), (18, 7))
        line((10, 11), (10, 16))
        line((14, 11), (14, 16))
    elif name == "search":
        circle(10.5, 10.5, 6.5)
        line((15.5, 15.5), (20.5, 20.5))
    elif name == "sun":
        circle(12, 12, 4)
        for i in range(8):
            a = i * math.pi / 4
            line((12 + 7.5 * math.cos(a), 12 + 7.5 * math.sin(a)),
                 (12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))
    elif name == "moon":
        circle(11.5, 12.5, 8.5, filled=True)
        d.ellipse(((16.5 - 7.5) * u, (7.5 - 7.5) * u, (16.5 + 7.5) * u, (7.5 + 7.5) * u), fill=clear)
    elif name == "monitor":
        rrect(3, 4, 21, 16, 2)
        line((8, 20), (16, 20))
        line((12, 16), (12, 20))
    elif name == "clipboard":
        rrect(5, 5, 19, 21, 2.5)
        d.rectangle((8 * u, 2 * u, 16 * u, 8 * u), fill=clear)
        rrect(9, 3, 15, 7, 1.2)
    elif name == "refresh":
        d.arc((4 * u, 4 * u, 20 * u, 20 * u), start=35, end=325, fill=color, width=w)
        line((19.5, 3.5), (19.5, 8), (15, 8))
    elif name == "x":
        line((6.5, 6.5), (17.5, 17.5))
        line((17.5, 6.5), (6.5, 17.5))
    elif name == "check":
        line((5, 12.5), (10, 17.5), (19, 7))
    elif name == "music":
        line((9, 17.5), (9, 5.5), (20, 3.5), (20, 15.5))
        circle(6.5, 17.5, 2.8, filled=True)
        circle(17.5, 15.5, 2.8, filled=True)
    elif name == "alert":
        circle(12, 12, 9)
        line((12, 7.5), (12, 12.5))
        circle(12, 16.3, 1.2, filled=True)
    elif name == "list":
        for y in (6, 12, 18):
            circle(4.5, y, 1.3, filled=True)
            line((9, y), (20, y))
    else:
        raise ValueError(f"Unknown icon: {name}")

    return img.resize((px * 2, px * 2), Image.LANCZOS)


@lru_cache(maxsize=None)
def icon(name: str, size: int = 18, color: ColorPair = theme.TEXT) -> ctk.CTkImage:
    """CTkImage of an icon, recolored automatically for light/dark mode."""
    light, dark = color
    return ctk.CTkImage(render_icon(name, size, light), render_icon(name, size, dark), size=(size, size))
