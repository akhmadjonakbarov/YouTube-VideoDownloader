from collections.abc import Callable

import customtkinter as ctk

from config import theme
from services.formatting import truncate
from widgets.hover import bind_click, bind_hover
from widgets.icons import icon

NAV_ITEMS = (("download", "Download", "download"), ("library", "Library", "library"))
THEMES = (("Light", "sun"), ("Dark", "moon"), ("System", "monitor"))


class Sidebar(ctk.CTkFrame):
    """Navigation, a live 'now downloading' card, storage info and the theme switch."""

    def __init__(
        self,
        parent,
        on_navigate: Callable[[str], None],
        on_theme: Callable[[str], None],
        on_open_folder: Callable[[], None],
    ):
        super().__init__(parent, width=248, corner_radius=0, fg_color=theme.SIDEBAR)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.on_navigate = on_navigate
        self.on_theme = on_theme

        # --- Brand ---
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(28, 30))
        ctk.CTkLabel(
            brand, text="", image=icon("play", 17, theme.WHITE), width=38, height=38,
            corner_radius=11, fg_color=theme.ACCENT,
        ).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text="YouTube", anchor="w", font=theme.font(16, "bold"), height=20).grid(
            row=0, column=1, sticky="sw"
        )
        ctk.CTkLabel(
            brand, text="Downloader", anchor="w", text_color=theme.MUTED, font=theme.font(12), height=16
        ).grid(row=1, column=1, sticky="nw")

        # --- Navigation ---
        ctk.CTkLabel(self, text="MENU", anchor="w", text_color=theme.SUBTLE, font=theme.font(11, "bold")).grid(
            row=1, column=0, sticky="ew", padx=26, pady=(0, 8)
        )
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="ew", padx=(0, 14))
        nav.grid_columnconfigure(1, weight=1)
        self.nav_items: dict[str, tuple[ctk.CTkFrame, ctk.CTkButton, str]] = {}
        for row, (key, label, glyph) in enumerate(NAV_ITEMS):
            indicator = ctk.CTkFrame(nav, width=4, height=24, corner_radius=2, fg_color="transparent")
            indicator.grid(row=row, column=0, padx=(0, 10))
            button = ctk.CTkButton(
                nav, text=f" {label}", anchor="w", height=44, corner_radius=12, font=theme.font(14),
                image=icon(glyph, 18, theme.MUTED), compound="left",
                command=lambda k=key: self.on_navigate(k), **theme.ghost(),
            )
            button.grid(row=row, column=1, sticky="ew", pady=2)
            self.nav_items[key] = (indicator, button, glyph)

        # --- Now downloading (row 4, hidden until a download runs) ---
        self.activity = ctk.CTkFrame(self, corner_radius=16, fg_color=theme.CARD, border_width=1,
                                     border_color=theme.BORDER)
        self.activity.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.activity, text="", image=icon("download", 16, theme.ACCENT), width=32, height=32,
                     corner_radius=10, fg_color=theme.ACCENT_SOFT).grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=(12, 0))
        ctk.CTkLabel(self.activity, text="Downloading", anchor="w", font=theme.font(12, "bold")).grid(
            row=0, column=1, sticky="sw", pady=(12, 0)
        )
        self.activity_percent = ctk.CTkLabel(self.activity, text="0%", text_color=theme.ACCENT_TEXT,
                                             font=theme.font(12, "bold"))
        self.activity_percent.grid(row=0, column=2, sticky="se", padx=(0, 14), pady=(12, 0))
        self.activity_title = ctk.CTkLabel(
            self.activity, text="", anchor="w", justify="left", text_color=theme.MUTED, font=theme.font(11)
        )
        self.activity_title.grid(row=1, column=1, columnspan=2, sticky="nw", padx=(0, 14))
        self.activity_bar = ctk.CTkProgressBar(
            self.activity, height=5, corner_radius=3, progress_color=theme.ACCENT, fg_color=theme.SECONDARY
        )
        self.activity_bar.set(0)
        self.activity_bar.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(10, 14))
        bind_click(self.activity, lambda: self.on_navigate("download"))
        bind_hover(self.activity, lambda: self.activity.configure(border_color=theme.BORDER_STRONG),
                   lambda: self.activity.configure(border_color=theme.BORDER), cursor="hand2")

        # --- Storage card ---
        self.storage = ctk.CTkFrame(self, corner_radius=16, fg_color=theme.SECONDARY)
        self.storage.grid(row=5, column=0, sticky="ew", padx=16, pady=(10, 10))
        self.storage.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.storage, text="", image=icon("folder", 16, theme.TEXT), width=32, height=32,
                     corner_radius=10, fg_color=theme.CARD).grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=12)
        ctk.CTkLabel(self.storage, text="Downloads folder", anchor="w", font=theme.font(12, "bold")).grid(
            row=0, column=1, sticky="sw", pady=(12, 0)
        )
        self.storage_label = ctk.CTkLabel(self.storage, text="", anchor="w", justify="left", text_color=theme.MUTED,
                                          font=theme.font(11), wraplength=150)
        self.storage_label.grid(row=1, column=1, sticky="nw", pady=(0, 12))
        bind_click(self.storage, on_open_folder)
        bind_hover(self.storage, lambda: self.storage.configure(fg_color=theme.SECONDARY_HOVER),
                   lambda: self.storage.configure(fg_color=theme.SECONDARY), cursor="hand2")

        # --- Theme switch ---
        switch = ctk.CTkFrame(self, corner_radius=12, fg_color=theme.SECONDARY)
        switch.grid(row=6, column=0, sticky="ew", padx=16, pady=(0, 22))
        self.theme_buttons: dict[str, tuple[ctk.CTkButton, str]] = {}
        for col, (mode, glyph) in enumerate(THEMES):
            switch.grid_columnconfigure(col, weight=1)
            button = ctk.CTkButton(
                switch, text="", width=56, height=32, corner_radius=9,
                image=icon(glyph, 16, theme.MUTED), command=lambda m=mode: self.select_theme(m), **theme.ghost(),
            )
            button.grid(row=0, column=col, sticky="ew", padx=3, pady=3)
            self.theme_buttons[mode] = (button, glyph)

    # ---------- Navigation ----------

    def set_active(self, key: str):
        for name, (indicator, button, glyph) in self.nav_items.items():
            active = name == key
            indicator.configure(fg_color=theme.ACCENT if active else "transparent")
            button.configure(
                fg_color=theme.SECONDARY if active else "transparent",
                text_color=theme.TEXT if active else theme.MUTED,
                image=icon(glyph, 18, theme.ACCENT if active else theme.MUTED),
                font=theme.font(14, "bold" if active else "normal"),
            )

    # ---------- Theme ----------

    def select_theme(self, mode: str):
        for name, (button, glyph) in self.theme_buttons.items():
            active = name == mode
            button.configure(
                fg_color=theme.SEGMENT_SELECTED if active else "transparent",
                image=icon(glyph, 16, theme.TEXT if active else theme.MUTED),
            )
        self.on_theme(mode)

    # ---------- Storage ----------

    def set_storage(self, text: str):
        self.storage_label.configure(text=text)

    # ---------- Activity ----------

    def show_activity(self, title: str):
        self.activity_title.configure(text=truncate(title, 26))
        self.activity_percent.configure(text="0%")
        self.activity_bar.set(0)
        self.activity.grid(row=4, column=0, sticky="sew", padx=16, pady=(0, 0))

    def update_activity(self, fraction: float):
        fraction = max(0.0, min(1.0, fraction))
        self.activity_bar.set(fraction)
        self.activity_percent.configure(text=f"{int(fraction * 100)}%")

    def hide_activity(self):
        self.activity.grid_forget()
