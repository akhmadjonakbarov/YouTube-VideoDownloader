import customtkinter as ctk

from config import theme


class AutoScrollFrame(ctk.CTkScrollableFrame):
    """A vertical CTkScrollableFrame whose scrollbar only shows when the content overflows.

    (Removing the scrollbar from the layout doesn't reliably hide it in CustomTkinter,
    so it stays in place and is painted in the background colour when not needed.)
    """

    def __init__(self, master, background=theme.BG, **kwargs):
        # No rounded border by default: it adds inner padding that misaligns content.
        kwargs.setdefault("corner_radius", 0)
        kwargs.setdefault("border_width", 0)
        super().__init__(master, **kwargs)
        self._hidden_color = background
        self._button_colors = (self._scrollbar.cget("button_color"), self._scrollbar.cget("button_hover_color"))
        self._scrollbar_visible = True
        self._check_job: str | None = None
        self.bind("<Configure>", self._schedule_check, add="+")
        self._parent_canvas.bind("<Configure>", self._schedule_check, add="+")

    def _schedule_check(self, _event=None):
        if self._check_job is None:
            self._check_job = self.after_idle(self._update_scrollbar)

    def _update_scrollbar(self):
        self._check_job = None
        try:
            first, last = self._parent_canvas.yview()
        except Exception:  # widget is being destroyed
            return
        needed = first > 0.0 or last < 1.0
        if needed == self._scrollbar_visible:
            return
        self._scrollbar_visible = needed
        if needed:
            color, hover = self._button_colors
        else:
            color = hover = self._hidden_color
        self._scrollbar.configure(button_color=color, button_hover_color=hover)

    def scroll_to_top(self):
        self._parent_canvas.yview_moveto(0)
