from collections.abc import Callable


def bind_hover(widget, on_enter: Callable[[], None], on_leave: Callable[[], None], cursor: str | None = None) -> None:
    """Hover handling for a composite widget.

    Tk sends <Leave> when the pointer moves onto a child widget, which makes simple
    hover effects flicker. Here <Leave> only counts when the pointer really left
    the whole widget (including its children).
    """
    state = {"inside": False}

    def inside(event) -> bool:
        target = widget.winfo_containing(event.x_root, event.y_root)
        while target is not None:
            if target == widget:
                return True
            target = target.master
        return False

    def enter(_event):
        if not state["inside"]:
            state["inside"] = True
            on_enter()

    def leave(event):
        if state["inside"] and not inside(event):
            state["inside"] = False
            on_leave()

    def bind_all(w):
        w.bind("<Enter>", enter, add="+")
        w.bind("<Leave>", leave, add="+")
        if cursor:
            try:
                w.configure(cursor=cursor)
            except Exception:  # some widgets don't take a cursor option
                pass
        for child in w.winfo_children():
            bind_all(child)

    bind_all(widget)


def bind_click(widget, command: Callable[[], None]) -> None:
    """Make a widget and all its children clickable."""
    def click(_event):
        command()

    def bind_all(w):
        w.bind("<Button-1>", click, add="+")
        for child in w.winfo_children():
            bind_all(child)

    bind_all(widget)
