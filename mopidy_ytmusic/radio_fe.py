# Endless radio: when the last queued track finishes, keep playing with a
# fresh batch of YouTube Music recommendations (get_watch_playlist radio).
import threading

import pykka
from mopidy import core

from mopidy_ytmusic import logger


class YTMusicRadioFE(pykka.ThreadingActor, core.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self.auto_radio = config["ytmusic"]["auto_radio"]

    def track_playback_ended(self, tl_track, time_position):
        """Queue-exhausted -> continue with a radio batch (in a little while)."""
        if not self.auto_radio:
            return
        track = tl_track.track
        if not track.uri.startswith("ytmusic:track:"):
            return
        threading.Timer(1.5, self._continue_radio, args=(track.uri,)).start()

    def _continue_radio(self, uri):
        bId = uri.split(":")[2]
        try:
            # Only continue if nothing else got queued and playback stopped.
            tl_tracks = self.core.tracklist.get_tl_tracks().get()
            if not tl_tracks or tl_tracks[-1].track.uri != uri:
                return
            if self.core.playback.get_state().get() != "stopped":
                return
        except Exception:
            logger.exception("YTMusic radio failed checking queue")
            return

        logger.info("YTMusic continuing as radio from %s", uri)
        try:
            from .backend import get_shared_api

            res = get_shared_api().get_watch_playlist(
                bId,
                radio=True,
                limit=self.config["ytmusic"]["playlist_item_limit"],
            )
            uris = [
                f"ytmusic:track:{t['videoId']}"
                for t in (res.get("tracks") or [])
                if t.get("videoId") and t["videoId"] != bId
            ]
        except Exception:
            logger.exception("YTMusic radio lookup failed")
            return
        if not uris:
            logger.warning("YTMusic radio returned no tracks")
            return
        try:
            self.core.tracklist.clear().get()
            self.core.tracklist.add(uris=uris).get()
            self.core.playback.play().get()
        except Exception:
            logger.exception("YTMusic radio enqueue failed")
