"""Design tokens shared by all widgets. Color tuples are (light mode, dark mode)."""
import ctypes
import ctypes.util
import sys
import tkinter.font

import customtkinter

from config.paths import resource_path

# --- Neutrals: soft cool greys; dark mode is near-black with a hint of blue ---
BG = ("#F5F5F7", "#0A0A0E")
SIDEBAR = ("#FBFBFD", "#0E0E13")
CARD = ("#FFFFFF", "#141419")
CARD_ALT = ("#F7F7FA", "#1A1A21")       # inset areas inside cards
CARD_HOVER = ("#FAFAFC", "#18181F")
BORDER = ("#E7E7EC", "#23232C")
BORDER_STRONG = ("#D2D2DA", "#34343F")
INPUT = ("#F4F4F7", "#1A1A21")

TEXT = ("#0E0E13", "#F5F5F7")
MUTED = ("#6B6B76", "#9B9BA7")
SUBTLE = ("#A1A1AC", "#5E5E6A")

SECONDARY = ("#F0F0F4", "#202028")
SECONDARY_HOVER = ("#E6E6EC", "#2A2A34")
SEGMENT_SELECTED = ("#FFFFFF", "#30303B")

# --- Brand ---
ACCENT = ("#E5243B", "#F23A4E")
ACCENT_HOVER = ("#C81E33", "#D92F42")
ACCENT_SOFT = ("#FDEDEF", "#2A1419")
ACCENT_TEXT = ("#C81E33", "#FF8D9A")

# --- Status ---
SUCCESS = ("#16A34A", "#4ADE80")
WARNING = ("#C2410C", "#FBBF24")
WARNING_SOFT = ("#FFF7ED", "#261E10")
ERROR = ("#DC2626", "#F87171")

WHITE = ("#FFFFFF", "#FFFFFF")
OVERLAY = ("#0E0E13", "#0A0A0E")

FONTS_DIR = resource_path("assets", "fonts")


def _register_fonts_with_fontconfig(font_files) -> bool:
    """Make bundled fonts usable by Tk on Linux for this process (no install needed)."""
    try:
        library = ctypes.util.find_library("fontconfig")
        if not library:
            return False
        fontconfig = ctypes.CDLL(library)
        fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        added = [fontconfig.FcConfigAppFontAddFile(None, str(f).encode()) for f in font_files]
        return any(added)
    except (OSError, AttributeError):
        return False


def setup_fonts(root) -> None:
    """Pick the best UI font for this OS. Call after the root window exists and
    after customtkinter.set_default_color_theme(), before creating widgets."""
    families = set(tkinter.font.families(root))
    if sys.platform == "darwin":
        preferred = ["SF Pro Display", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue"]
    elif sys.platform == "win32":
        preferred = ["Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"]
    else:
        if "Inter" not in families and _register_fonts_with_fontconfig(FONTS_DIR.glob("Inter-*.otf")):
            families = set(tkinter.font.families(root))
        preferred = ["Inter", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans"]
    family = next((f for f in preferred if f in families), None)
    if family:
        customtkinter.ThemeManager.theme["CTkFont"]["family"] = family


def font(size: int = 13, weight: str = "normal") -> customtkinter.CTkFont:
    return customtkinter.CTkFont(size=size, weight=weight)


def primary(**kwargs) -> dict:
    return {"fg_color": ACCENT, "hover_color": ACCENT_HOVER, "text_color": WHITE, **kwargs}


def secondary(**kwargs) -> dict:
    return {"fg_color": SECONDARY, "hover_color": SECONDARY_HOVER, "text_color": TEXT, **kwargs}


def ghost(**kwargs) -> dict:
    return {"fg_color": "transparent", "hover_color": SECONDARY, "text_color": MUTED, **kwargs}


def card(**kwargs) -> dict:
    return {"fg_color": CARD, "border_color": BORDER, "border_width": 1, "corner_radius": 20, **kwargs}
