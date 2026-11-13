import customtkinter as ctk

from config import theme
from widgets.icons import icon

_KINDS = {
    "success": ("check", theme.SUCCESS),
    "error": ("alert", theme.ERROR),
    "warning": ("alert", theme.WARNING),
    "info": ("download", theme.MUTED),
}


class Toast(ctk.CTkFrame):
    """A small notification that floats in the bottom-right corner of the window."""

    def __init__(self, master):
        super().__init__(master, corner_radius=14, fg_color=theme.CARD, border_width=1, border_color=theme.BORDER)
        self.grid_columnconfigure(2, weight=1)
        self.stripe = ctk.CTkFrame(self, width=4, height=20, corner_radius=2, fg_color=theme.SUCCESS)
        self.stripe.grid(row=0, column=0, sticky="ns", padx=(10, 0), pady=12)
        self.icon_label = ctk.CTkLabel(self, text="", width=22)
        self.icon_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.message_label = ctk.CTkLabel(
            self, text="", anchor="w", justify="left", wraplength=320, font=theme.font(13), text_color=theme.TEXT
        )
        self.message_label.grid(row=0, column=2, sticky="w", padx=(8, 6), pady=12)
        ctk.CTkButton(
            self, text="", image=icon("x", 14, theme.MUTED), width=26, height=26, corner_radius=8,
            command=self.hide, **{k: v for k, v in theme.ghost().items() if k != "text_color"},
        ).grid(row=0, column=3, padx=(0, 8))
        self.hide_job: str | None = None

    def show(self, message: str, kind: str = "info", duration_ms: int = 5000):
        glyph, color = _KINDS.get(kind, _KINDS["info"])
        self.stripe.configure(fg_color=color)
        self.icon_label.configure(image=icon(glyph, 18, color))
        self.message_label.configure(text=message)
        if self.hide_job:
            self.after_cancel(self.hide_job)
        self.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        self.lift()
        self.hide_job = self.after(duration_ms, self.hide)

    def hide(self):
        if self.hide_job:
            self.after_cancel(self.hide_job)
            self.hide_job = None
        self.place_forget()
