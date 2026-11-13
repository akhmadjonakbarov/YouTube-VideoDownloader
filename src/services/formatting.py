def format_size(num_bytes: float | None) -> str:
    if num_bytes is None:
        return ""
    mb = num_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    if mb >= 100:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second:
        return ""
    return f"{format_size(bytes_per_second)}/s"


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def quality_tag(height: int | None) -> str:
    """Friendly name for a resolution: 4K, Full HD, ..."""
    if height is None:
        return "Auto"
    if height >= 2160:
        return "4K"
    if height >= 1440:
        return "2K"
    if height >= 1080:
        return "Full HD"
    if height >= 720:
        return "HD"
    return "SD"
