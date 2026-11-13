"""A quick, proxy-aware check that the internet (YouTube) is reachable."""
import socket
import urllib.request
from urllib.parse import urlparse

CHECK_HOST = ("www.youtube.com", 443)


def _target() -> tuple[str, int]:
    """Where to open a test connection: the HTTPS proxy if one is configured, else YouTube."""
    proxy = urllib.request.getproxies().get("https")
    if proxy:
        parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        if parsed.hostname:
            return parsed.hostname, parsed.port or 8080
    return CHECK_HOST


def is_online(timeout: float = 3.0) -> bool:
    """True if a TCP connection can be opened (DNS + network work). No data is sent."""
    try:
        with socket.create_connection(_target(), timeout=timeout):
            return True
    except OSError:
        return False
