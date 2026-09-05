import hashlib
import random
import threading
import time
from datetime import datetime, timezone

import pykka
import requests
from mopidy import backend
from ytmusicapi.continuations import get_continuations
from ytmusicapi.navigation import (
    CAROUSEL_TITLE,
    NAVIGATION_BROWSE_ID,
    SECTION_LIST,
    SINGLE_COLUMN_TAB,
    TITLE,
    TITLE_TEXT,
    nav,
)
from ytmusicapi.ytmusic import YTMusic

from mopidy_ytmusic import logger

from .library import YTMusicLibraryProvider
from .playback import YTMusicPlaybackProvider
from .playlist import YTMusicPlaylistsProvider
from .repeating_timer import RepeatingTimer
from .scrobble_fe import YTMusicScrobbleListener

_shared_api = None
_api_lock = threading.Lock()


def set_shared_api(api):
    """Expose the backend's YTMusic client to other actors (radio frontend)."""
    global _shared_api
    with _api_lock:
        _shared_api = api


def get_shared_api():
    """Return the backend's YTMusic client, creating a guest fallback."""
    global _shared_api
    with _api_lock:
        if _shared_api is None:
            from ytmusicapi.ytmusic import YTMusic

            _shared_api = YTMusic()
        return _shared_api


class YTMusicBackend(
    pykka.ThreadingActor, backend.Backend, YTMusicScrobbleListener
):
    def __init__(self, config, audio):
        super().__init__()
        self.config = config
        self.audio = audio
        self.uri_schemes = ["ytmusic"]
        self.auth = False

        self._auto_playlist_refresh_rate = (
            config["ytmusic"]["auto_playlist_refresh"] * 60
        )
        self._auto_playlist_refresh_timer = None

        self.playlist_item_limit = config["ytmusic"]["playlist_item_limit"]
        self.subscribed_artist_limit = config["ytmusic"][
            "subscribed_artist_limit"
        ]
        self.history = config["ytmusic"]["enable_history"]
        self.liked_songs = config["ytmusic"]["enable_liked_songs"]
        self.mood_genre = config["ytmusic"]["enable_mood_genre"]
        self.enable_radio = config["ytmusic"]["enable_radio"]
        self.stream_preference = config["ytmusic"]["stream_preference"]
        self.verify_track_url = config["ytmusic"]["verify_track_url"]

        if config["ytmusic"]["auth_json"]:
            self._ytmusicapi_auth_json = config["ytmusic"]["auth_json"]
            self.auth = True

        if self.auth:
            self.api = YTMusic(**self._ytmusicapi_kwargs())
        else:
            self.api = YTMusic()
        set_shared_api(self.api)

        self.playback = YTMusicPlaybackProvider(audio=audio, backend=self)
        self.library = YTMusicLibraryProvider(backend=self)
        if self.auth:
            self.playlists = YTMusicPlaylistsProvider(backend=self)

    def _ytmusicapi_kwargs(self):
        """Return YTMusic() keyword args for the configured auth file.

        Two kinds of auth files are supported:

        - Browser headers dump (``mopidy ytmusic setup``): pass the file path.
        - OAuth token file (``mopidy ytmusic oauth``): pass the file path
          together with the configured ``oauth_client_id``/secret so
          ytmusicapi can auto-refresh the access token indefinitely.
        """
        import json

        auth_file = self._ytmusicapi_auth_json
        try:
            with open(auth_file) as file:
                data = json.load(file)
        except (OSError, ValueError):
            logger.warning(
                "YTMusic unable to read auth file %s, "
                "falling back to default headers",
                auth_file,
            )
            return {"auth": str(auth_file)}

        # OAuth token files hold a refresh_token; browser header dumps do not.
        if "refresh_token" in data:
            client_id = self._ytmusic_config("oauth_client_id")
            client_secret = self._ytmusic_config("oauth_client_secret")
            if not client_id or not client_secret:
                logger.error(
                    "ytmusic.auth_json points to an OAuth token file but "
                    "oauth_client_id/oauth_client_secret are not set in the "
                    "[ytmusic] config section"
                )
                return {"auth": str(auth_file)}
            from ytmusicapi import OAuthCredentials

            return {
                "auth": str(auth_file),
                "oauth_credentials": OAuthCredentials(
                    client_id=client_id,
                    client_secret=client_secret,
                ),
            }
        return {"auth": str(auth_file)}

    def _ytmusic_config(self, key):
        """Read a [ytmusic] config value defensively (dict or section)."""
        section = self.config["ytmusic"]
        try:
            return section.get(key, None)
        except AttributeError:
            try:
                return section[key]
            except KeyError:
                return None

    def on_start(self):
        if self._auto_playlist_refresh_rate:
            self._auto_playlist_refresh_timer = RepeatingTimer(
                self._refresh_auto_playlists, self._auto_playlist_refresh_rate
            )
            self._auto_playlist_refresh_timer.start()

    def on_stop(self):
        if self._auto_playlist_refresh_timer:
            self._auto_playlist_refresh_timer.cancel()
            self._auto_playlist_refresh_timer = None

    def _refresh_auto_playlists(self):
        t0 = time.time()
        self._get_auto_playlists()
        t = time.time() - t0
        logger.info("YTMusic Auto Playlists refreshed in %.2fs", t)

    def _get_auto_playlists(self):
        try:
            logger.debug("YTMusic loading auto playlists")
            response = self.api._send_request("browse", {})
            tab = nav(response, SINGLE_COLUMN_TAB)
            browse = parse_auto_playlists(nav(tab, SECTION_LIST))
            if "continuations" in tab["sectionListRenderer"]:
                request_func = lambda additionalParams: self.api._send_request(
                    "browse", {}, additionalParams
                )
                parse_func = lambda contents: parse_auto_playlists(contents)
                browse.extend(
                    get_continuations(
                        tab["sectionListRenderer"],
                        "sectionListContinuation",
                        100,
                        request_func,
                        parse_func,
                    )
                )
            # Delete empty sections
            for i in range(len(browse) - 1, 0, -1):
                if len(browse[i]["items"]) == 0:
                    browse.pop(i)
            logger.info(
                "YTMusic loaded %d auto playlists sections", len(browse)
            )
            self.library.ytbrowse = browse
        except Exception:
            logger.exception("YTMusic failed to load auto playlists")
        return None

    def scrobble_track(self, bId):
        # Called through YTMusicScrobbleListener
        # Let YTMusic know we're playing this track so it will be added to our history.
        CPN_ALPHABET = (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        )
        cpn = "".join(
            (CPN_ALPHABET[random.randint(0, 256) & 63] for _ in range(0, 16))
        )
        try:
            player_response = self.api._send_request(
                "player",
                {
                    "playbackContext": {
                        "contentPlaybackContext": {
                            "signatureTimestamp": _get_datestamp() - 1,
                        },
                    },
                    "videoId": bId,
                    "cpn": cpn,
                },
            )
            params = {
                "cpn": cpn,
                "ver": 2,
                "c": "WEB_REMIX",
            }
            tr = requests.get(
                player_response["playbackTracking"]["videostatsPlaybackUrl"][
                    "baseUrl"
                ],
                params=params,
                headers=self.api.headers,
                proxies=self.api.proxies,
                timeout=10,
            )
            logger.debug("%d code from '%s'", tr.status_code, tr.url)
        except Exception:
            logger.exception("YTMusic scrobble failed for %s", bId)


def _get_datestamp():
    """Number of days since 1970-01-01 (YouTube signature timestamp)."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - epoch).days


def parse_auto_playlists(res):
    browse = []
    for sect in res:
        car = []
        if "musicImmersiveCarouselShelfRenderer" in sect:
            car = nav(sect, ["musicImmersiveCarouselShelfRenderer"])
        elif "musicCarouselShelfRenderer" in sect:
            car = nav(sect, ["musicCarouselShelfRenderer"])
        else:
            continue
        stitle = nav(car, CAROUSEL_TITLE + ["text"]).strip()
        browse.append(
            {
                "name": stitle,
                "uri": "ytmusic:auto:"
                + hashlib.md5(stitle.encode("utf-8")).hexdigest(),
                "items": [],
            }
        )
        for item in nav(car, ["contents"]):
            brId = nav(
                item,
                ["musicTwoRowItemRenderer"] + TITLE + NAVIGATION_BROWSE_ID,
                True,
            )
            if brId is None or brId == "VLLM":
                continue
            pagetype = nav(
                item,
                [
                    "musicTwoRowItemRenderer",
                    "navigationEndpoint",
                    "browseEndpoint",
                    "browseEndpointContextSupportedConfigs",
                    "browseEndpointContextMusicConfig",
                    "pageType",
                ],
                True,
            )
            ititle = nav(item, ["musicTwoRowItemRenderer"] + TITLE_TEXT).strip()
            if pagetype == "MUSIC_PAGE_TYPE_PLAYLIST":
                if "subtitle" in item["musicTwoRowItemRenderer"]:
                    ititle += " ("
                    for st in item["musicTwoRowItemRenderer"]["subtitle"][
                        "runs"
                    ]:
                        ititle += st["text"]
                    ititle += ")"
                browse[-1]["items"].append(
                    {
                        "type": "playlist",
                        "uri": f"ytmusic:playlist:{brId}",
                        "name": ititle,
                    }
                )
            elif pagetype == "MUSIC_PAGE_TYPE_ARTIST":
                browse[-1]["items"].append(
                    {
                        "type": "artist",
                        "uri": f"ytmusic:artist:{brId}",
                        "name": ititle + " (Artist)",
                    }
                )
            elif pagetype == "MUSIC_PAGE_TYPE_ALBUM":
                artist = nav(
                    item,
                    ["musicTwoRowItemRenderer", "subtitle", "runs", -1, "text"],
                    True,
                )
                ctype = nav(
                    item,
                    ["musicTwoRowItemRenderer", "subtitle", "runs", 0, "text"],
                    True,
                )
                if artist is not None:
                    browse[-1]["items"].append(
                        {
                            "type": "album",
                            "uri": f"ytmusic:album:{brId}",
                            "name": artist
                            + " - "
                            + ititle
                            + " ("
                            + ctype
                            + ")",
                        }
                    )
                else:
                    browse[-1]["items"].append(
                        {
                            "type": "album",
                            "uri": f"ytmusic:album:{brId}",
                            "name": ititle + " (" + ctype + ")",
                        }
                    )
    return browse
