"""Generate the app icon in every format the platforms need.

    python packaging/make_icons.py

Writes to assets/: icon.png (1024 px), icon-256.png (window icon on Linux),
icon.ico (Windows) and icon.icns (macOS).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZE = 1024
TOP, BOTTOM = (248, 113, 113), (220, 38, 38)  # red gradient (light top -> brand red)


def draw_icon(size: int = SIZE) -> Image.Image:
    scale = 4  # draw large, downsample for smooth edges
    n = size * scale
    # macOS-style rounded square with a margin for the drop shadow.
    margin = int(n * 0.09)
    box = (margin, margin, n - margin, n - margin)
    radius = int((box[2] - box[0]) * 0.225)

    gradient = Image.linear_gradient("L").resize((n, n))
    fill = Image.composite(Image.new("RGB", (n, n), BOTTOM), Image.new("RGB", (n, n), TOP), gradient)

    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)

    shadow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    shadow_box = (box[0], box[1] + int(n * 0.012), box[2], box[3] + int(n * 0.012))
    ImageDraw.Draw(shadow).rounded_rectangle(shadow_box, radius=radius, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(n * 0.012))

    icon = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    icon.alpha_composite(shadow)
    tile = fill.convert("RGBA")
    tile.putalpha(mask)
    icon.alpha_composite(tile)

    # White play triangle, optically centred (shifted right a little).
    cx, cy, r = n * 0.53, n * 0.5, n * 0.2
    triangle = [(cx - r * 0.8, cy - r), (cx + r, cy), (cx - r * 0.8, cy + r)]
    play = Image.new("L", (n, n), 0)
    ImageDraw.Draw(play).polygon(triangle, fill=255)
    icon.paste(Image.new("RGBA", (n, n), (255, 255, 255, 255)), (0, 0), play)

    return icon.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    icon = draw_icon()
    icon.save(ASSETS / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon-256.png")
    icon.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(ASSETS / "icon.icns")
    print(f"Icons written to {ASSETS}")


if __name__ == "__main__":
    main()
