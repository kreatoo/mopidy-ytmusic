import requests
import yt_dlp
from mopidy import backend

from mopidy_ytmusic import logger

_ydl = None


def get_ydl():
    """Return a reuseable YoutubeDL instance (player JS is cached)."""
    global _ydl
    if _ydl is None:
        _ydl = yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["music", "android", "ios", "tv"],
                    },
                },
            }
        )
    return _ydl


def resolve_stream_url(bId, stream_preference, verify_track_url):
    """Resolve a playable stream URL for a YouTube Music video id."""
    try:
        info = get_ydl().extract_info(
            f"https://music.youtube.com/watch?v={bId}", download=False
        )
    except Exception:
        logger.exception("YTMusic failed to resolve stream for %s", bId)
        return None
    formats = info.get("formats") or []
    stream = _pick_stream(formats, stream_preference)
    if stream is None:
        logger.error("YTMusic no playable stream found for %s", bId)
        return None
    url = stream.get("url")
    if not url:
        logger.error("YTMusic stream for %s has no url", bId)
        return None
    if verify_track_url:
        try:
            response = requests.head(url, timeout=10)
            if response.status_code in (401, 403):
                logger.error(
                    "YTMusic stream URL rejected with HTTP %d",
                    response.status_code,
                )
                return None
        except Exception:
            logger.exception("YTMusic failed verifying track URL")
            return None
    return url


def _pick_stream(formats, stream_preference):
    """Pick the best audio format honoring the itag stream preference."""
    audio = [f for f in formats if (f.get("acodec") or "none") != "none"]
    if stream_preference:
        for itag in stream_preference:
            for f in audio:
                if f.get("format_id") == str(itag):
                    logger.debug("YTMusic found preferred stream %s", itag)
                    return f
    if audio:
        return max(audio, key=lambda f: f.get("abr") or 0)
    return formats[0] if formats else None


class YTMusicPlaybackProvider(backend.PlaybackProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_id = None

    def translate_uri(self, uri):
        logger.debug('YTMusic PlaybackProvider.translate_uri "%s"', uri)

        if "ytmusic:track:" not in uri:
            return None

        try:
            bId = uri.split(":")[2]
            self.last_id = bId
            return self._get_track(bId)
        except Exception as e:
            logger.error('translate_uri error "%s"', str(e))
            return None

    def _get_track(self, bId):
        url = self._resolve_stream_url(bId)
        if url is None:
            return None
        logger.debug("YTMusic resolved %s -> %s", bId, url)
        return url

    def _resolve_stream_url(self, bId):
        return resolve_stream_url(
            bId, self.backend.stream_preference, self.backend.verify_track_url
        )
