import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url):
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
                candidate = parts[1]
    return candidate if candidate and YOUTUBE_ID.fullmatch(candidate) else None


def vimeo_id(url):
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"vimeo.com", "player.vimeo.com"}:
        return None
    digits = [part for part in parsed.path.split("/") if part.isdigit()]
    return digits[0] if digits else None


def embed_url(source, url):
    if source == "youtube":
        video = youtube_id(url)
        return f"https://www.youtube-nocookie.com/embed/{video}?rel=0&modestbranding=1" if video else None
    if source == "vimeo":
        video = vimeo_id(url)
        return f"https://player.vimeo.com/video/{video}?dnt=1" if video else None
    return None
