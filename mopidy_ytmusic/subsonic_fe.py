# OpenSubsonic API server frontend.
#
# Lets Subsonic/OpenSubsonic clients (Nocturne, DSub, Sublime Music, ...)
# control Mopidy and stream its backends (e.g. YouTube Music). Endpoints:
# ping, getLicense, getMusicFolders, getArtists/getIndexes, getArtist,
# getAlbum, getSong, getAlbumInfo2, getArtistInfo2, getCoverArt, stream,
# search3, getPlaylists, getPlaylist, getStarred(2), getRandomSongs,
# getAlbumList2, scrobble.
import threading
from xml.etree import ElementTree as ET

import pykka
import requests
import tornado.ioloop
import tornado.web
from mopidy import core, listener

from mopidy_ytmusic import logger
from mopidy_ytmusic.playback import resolve_stream_url
from mopidy_ytmusic.scrobble_fe import YTMusicScrobbleListener

API_VERSION = "1.16.1"
NS = "http://subsonic.org/restapi"


def _song_id(video_id):
    return f"st_{video_id}"


def _album_id(browse_id):
    return f"al_{browse_id}"


def _artist_id(browse_id):
    return f"ar_{browse_id}"


def _playlist_id(playlist_id):
    return f"pl_{playlist_id}"


def _split(sid):
    """Split a subsonic id of the form <type>_<payload>."""
    kind, _, payload = sid.partition("_")
    return kind, payload


def _largest(thumbnails):
    if not thumbnails:
        return None
    return max(thumbnails, key=lambda t: t.get("width") or 0).get("url")


def _child(container, tag, **attrs):
    """Create a namespaced child element, casting attribute values to str."""
    el = ET.SubElement(container, f"{{{NS}}}{tag}")
    for k, v in attrs.items():
        if v is not None:
            el.set(k, str(v))
    return el


class _Response:
    """Very small builder for the subsonic XML envelope."""

    def __init__(self, method=None):
        ET.register_namespace("", NS)
        self.root = ET.Element(
            f"{{{NS}}}subsonic-response",
            {
                "status": "ok",
                "version": API_VERSION,
                "xmlns": NS,
            },
        )

    def child(self, tag, **attrs):
        return _child(self.root, tag, **attrs)

    def text(self):
        return ET.tostring(self.root, encoding="unicode")


class _ApiError(Exception):
    pass


class SubsonicHandler(tornado.web.RequestHandler):
    def initialize(self, fe):
        self.fe = fe

    def get(self, method):
        try:
            self._handle(method)
        except _ApiError as e:
            self._error(*e.args)
        except Exception:
            logger.exception("Subsonic request failed")
            self._error(0, "Internal server error")

    def _handle(self, method):
        self._check_auth()

        if method == "ping":
            self.write_response(_Response().text())
            return
        if method in ("getLicense",):
            resp = _Response()
            resp.child("license", valid="true")
            self.write_response(resp.text())
            return
        if method == "getMusicFolders":
            resp = _Response()
            folders = resp.child("musicFolders")
            _child(folders, "musicFolder", id="1", name="Music")
            self.write_response(resp.text())
            return
        if method in ("getArtists", "getIndexes"):
            self._get_artists()
            return
        if method == "getArtist":
            self._get_artist()
            return
        if method == "getAlbum":
            self._get_album()
            return
        if method in ("getSong",):
            self._get_song()
            return
        if method == "getAlbumInfo2":
            self._get_album_info2()
            return
        if method == "getArtistInfo2":
            self._get_artist_info2()
            return
        if method == "getCoverArt":
            self._get_cover_art()
            return
        if method == "stream":
            self._stream()
            return
        if method == "search3":
            self._search3()
            return
        if method in ("getPlaylists", "getPlaylist"):
            self._get_playlist()
            return
        if method in ("getStarred", "getStarred2"):
            resp = _Response()
            resp.child("starred")
            self.write_response(resp.text())
            return
        if method == "getRandomSongs":
            resp = _Response()
            resp.child("randomSongs")
            self.write_response(resp.text())
            return
        if method == "getAlbumList2":
            self._get_album_list2()
            return
        if method == "scrobble":
            self._scrobble()
            return
        self._error(0, f"Method not implemented: {method}")

    # ------------------------------------------------------------------

    def _check_auth(self):
        username = self.get_argument("u", "")
        password = self.get_argument("p", "")
        cfg_user = self.fe.config["ytmusic"]["subsonic_username"]
        cfg_pass = self.fe.config["ytmusic"]["subsonic_password"]
        if not (cfg_user and cfg_pass):
            # No credentials configured: allow anyone (localhost default).
            return
        if username != cfg_user:
            raise _ApiError(40, "Wrong username or password")
        # Subsonic accepts plain passwords or "enc:" + hex(md5(password)).
        import hashlib

        if password == cfg_pass:
            return
        if password.startswith("enc:"):
            digest = hashlib.md5(cfg_pass.encode()).hexdigest()
            if password[4:] == digest:
                return
        raise _ApiError(40, "Wrong username or password")

    def _api(self):
        from mopidy_ytmusic.backend import get_shared_api

        return get_shared_api()

    def _error(self, code, message):
        self.set_status(200)
        ET.register_namespace("", NS)
        root = ET.Element(
            f"{{{NS}}}subsonic-response",
            {"status": "failed", "version": API_VERSION},
        )
        _child(root, "error", code=code, message=message)
        self.set_header("Content-Type", "application/xml")
        self.write(ET.tostring(root, encoding="unicode"))

    def write_response(self, xml_text):
        self.set_header("Content-Type", "application/xml")
        self.write(xml_text)

    # ------------------------------------------------------------------

    def _get_artists(self):
        refs = self.fe.core.library.browse("ytmusic:artist").get() or []
        resp = _Response()
        artists = resp.child("artists")
        index = None
        last_letter = None
        for ref in sorted(refs, key=lambda r: r.name or ""):
            letter = (ref.name or "?")[0].upper()
            if letter != last_letter:
                index = _child(artists, "index", name=letter)
                last_letter = letter
            _id = ref.uri.rsplit(":", 1)[-1]
            _child(index, "artist", id=_artist_id(_id), name=ref.name)
        self.write_response(resp.text())

    def _get_artist(self):
        kind, payload = _split(self.get_argument("id"))
        if kind != "ar":
            raise _ApiError(41, "Not an artist id")
        try:
            data = self._api().get_artist(payload)
        except Exception:
            raise _ApiError(70, "Artist not found")
        resp = _Response()
        artist = resp.child(
            "artist",
            id=self.get_argument("id"),
            name=data.get("name"),
            coverArt=_artist_id(payload),
            artistImageUrl=_largest(data.get("thumbnails")),
        )
        albums = []
        for key in ("albums", "singles"):
            for a in (data.get(key) or {}).get("results") or []:
                albums.append(a)
        seen = set()
        for a in albums:
            if a.get("browseId") in seen:
                continue
            seen.add(a.get("browseId"))
            _child(
                artist,
                "album",
                id=_album_id(a["browseId"]),
                name=a.get("title"),
                artist=data.get("name"),
                artistId=_artist_id(payload),
                year=a.get("year"),
                coverArt=_album_id(a["browseId"]),
            )
        self.write_response(resp.text())

    def _get_album(self):
        kind, payload = _split(self.get_argument("id"))
        if kind != "al":
            raise _ApiError(41, "Not an album id")
        try:
            data = self._api().get_album(payload)
        except Exception:
            raise _ApiError(70, "Album not found")
        album = data
        artists = album.get("artists") or []
        artist_name = artists[0].get("name") if artists else None
        artist_id = artists[0].get("id") if artists else None
        resp = _Response()
        alb = resp.child(
            "album",
            id=self.get_argument("id"),
            name=album.get("title"),
            artist=artist_name,
            artistId=_artist_id(artist_id) if artist_id else None,
            coverArt=self.get_argument("id"),
            songCount=album.get("trackCount"),
        )
        for index, song in enumerate(album.get("tracks") or [], start=1):
            song_artists = song.get("artists") or []
            _child(
                alb,
                "song",
                id=_song_id(song.get("videoId")),
                parent=self.get_argument("id"),
                title=song.get("title"),
                album=album.get("title"),
                artist=(
                    song_artists[0].get("name") if song_artists else artist_name
                ),
                track=song.get("trackNumber") or index,
                duration=song.get("duration_seconds") or 0,
                coverArt=self.get_argument("id"),
            )
        self.write_response(resp.text())

    def _get_song(self):
        kind, payload = _split(self.get_argument("id"))
        if kind != "st":
            raise _ApiError(41, "Not a song id")
        try:
            data = self._api().get_song(payload)
        except Exception:
            raise _ApiError(70, "Song not found")
        details = data.get("videoDetails") or {}
        resp = _Response()
        song = resp.child("song", id=self.get_argument("id"))
        ET.SubElement(song, f"{{{NS}}}title").text = details.get("title")
        ET.SubElement(song, f"{{{NS}}}artist").text = details.get("author")
        ET.SubElement(song, f"{{{NS}}}duration").text = str(
            details.get("lengthSeconds") or 0
        )
        self.write_response(resp.text())

    def _get_album_info2(self):
        kind, payload = _split(self.get_argument("id"))
        info = {}
        if kind == "al":
            try:
                data = self._api().get_album(payload)
                artists = data.get("artists") or []
                info = {
                    "name": data.get("title"),
                    "artist": artists[0].get("name") if artists else None,
                    "coverArt": self.get_argument("id"),
                    "largeImageUrl": _largest(data.get("thumbnails")),
                }
            except Exception:
                pass
        resp = _Response()
        resp.child("albumInfo", **{k: v for k, v in info.items() if v})
        self.write_response(resp.text())

    def _get_artist_info2(self):
        kind, payload = _split(self.get_argument("id"))
        info = {}
        if kind == "ar":
            try:
                data = self._api().get_artist(payload)
                info = {
                    "name": data.get("name"),
                    "artistImageUrl": _largest(data.get("thumbnails")),
                    "biography": data.get("description"),
                }
            except Exception:
                pass
        resp = _Response()
        resp.child("artistInfo2", **{k: v for k, v in info.items() if v})
        self.write_response(resp.text())

    def _get_cover_art(self):
        kind, payload = _split(self.get_argument("id"))
        url = None
        try:
            if kind == "al":
                url = _largest(self._api().get_album(payload).get("thumbnails"))
            elif kind == "ar":
                url = _largest(
                    self._api().get_artist(payload).get("thumbnails")
                )
            elif kind == "st":
                details = (
                    self._api().get_song(payload).get("videoDetails") or {}
                )
                url = _largest(
                    (details.get("thumbnail") or {}).get("thumbnails")
                )
            elif kind == "pl":
                url = _largest(
                    self._api().get_playlist(payload).get("thumbnails")
                )
        except Exception:
            logger.debug("Subsonic cover art lookup failed for %s", payload)
        if not url:
            self.set_status(404)
            self.finish()
            return
        try:
            resp = requests.get(url, timeout=15)
        except Exception:
            self.set_status(500)
            self.finish()
            return
        self.set_header(
            "Content-Type", resp.headers.get("Content-Type", "image/jpeg")
        )
        self.set_header("Cache-Control", "public, max-age=86400")
        self.write(resp.content)

    def _stream(self):
        kind, payload = _split(self.get_argument("id"))
        if kind != "st":
            raise _ApiError(41, "Not a song id")
        url = resolve_stream_url(
            payload,
            self.fe.config["ytmusic"]["stream_preference"],
            False,
        )
        if not url:
            self._error(70, "Could not resolve stream")
            return
        logger.debug("Subsonic streaming %s -> %s", payload, url[:80])
        self.redirect(url, status=302)

    def _search3(self):
        query = self.get_argument("query", "")
        try:
            results = self._api().search(query, limit=20) or []
        except Exception:
            logger.exception("Subsonic search failed")
            results = []
        resp = _Response()
        search = resp.child("searchResult3")
        for r in results:
            if r.get("resultType") == "song":
                _child(
                    search,
                    "song",
                    id=_song_id(r.get("videoId")),
                    title=r.get("title"),
                    artist=(r.get("artists") or [{}])[0].get("name"),
                    album=(r.get("album") or {}).get("name"),
                    duration=r.get("duration_seconds") or 0,
                    coverArt=(
                        _album_id((r.get("album") or {}).get("id"))
                        if (r.get("album") or {}).get("id")
                        else None
                    ),
                )
            elif r.get("resultType") == "album":
                _child(
                    search,
                    "album",
                    id=_album_id(r.get("browseId")),
                    name=r.get("title"),
                    artist=(r.get("artists") or [{}])[0].get("name"),
                    year=r.get("year"),
                    coverArt=_album_id(r.get("browseId")),
                )
            elif r.get("resultType") == "artist":
                _child(
                    search,
                    "artist",
                    id=_artist_id(r.get("browseId")),
                    name=r.get("artist"),
                )
        self.write_response(resp.text())

    def _get_playlist(self):
        playlist_id = self.get_argument("id", None)
        core = self.fe.core
        if playlist_id:
            resp = _Response()
            _, payload = _split(playlist_id)
            pl = core.playlists.lookup(f"ytmusic:playlist:{payload}").get()
            if pl is None:
                raise _ApiError(70, "Playlist not found")
            node = resp.child(
                "playlist",
                id=playlist_id,
                name=pl.name,
                owner=self.fe.config["ytmusic"]["subsonic_username"] or None,
            )
            for track in pl.tracks:
                artist = (
                    next(iter(track.artists)).name if track.artists else None
                )
                _child(
                    node,
                    "entry",
                    id=_song_id(track.uri.split(":")[-1]),
                    parent=playlist_id,
                    title=track.name,
                    artist=artist,
                    album=track.album.name if track.album else None,
                )
        else:
            refs = core.playlists.as_list().get() or []
            resp = _Response()
            playlists = resp.child("playlists")
            for ref in refs:
                pid = _playlist_id(ref.uri.split(":")[-1])
                _child(playlists, "playlist", id=pid, name=ref.name)
        self.write_response(resp.text())

    def _get_album_list2(self):
        # Home-screen lists; back them with recently played YTM albums.
        albums = {}
        try:
            for h in self._api().get_history() or []:
                album = h.get("album") or {}
                if album.get("id") and album["id"] not in albums:
                    albums[album["id"]] = album.get("name")
                if len(albums) >= 20:
                    break
        except Exception:
            logger.debug("Subsonic getAlbumList2 fell back to empty list")
        resp = _Response()
        node = resp.child("albumList2")
        for bid, name in albums.items():
            _child(
                node,
                "album",
                id=_album_id(bid),
                name=name,
                coverArt=_album_id(bid),
            )
        self.write_response(resp.text())

    def _scrobble(self):
        kind, payload = _split(self.get_argument("id"))
        if kind == "st" and self.get_argument("submission", "true") != "false":
            listener.send(
                YTMusicScrobbleListener, "scrobble_track", bId=payload
            )
        self.write_response(_Response().text())


class YTMusicSubsonicFE(pykka.ThreadingActor, core.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.config = config
        self.core = core
        self._server = None
        self._ioloop = None
        self._thread = None

    def on_start(self):
        if not self.config["ytmusic"]["enable_subsonic"]:
            return
        host = self.config["ytmusic"]["subsonic_host"]
        port = self.config["ytmusic"]["subsonic_port"]
        self._thread = threading.Thread(
            target=self._run_server, args=(host, port), daemon=True
        )
        self._thread.start()
        logger.info("Subsonic server listening on %s:%s", host, port)

    def _run_server(self, host, port):
        self._ioloop = tornado.ioloop.IOLoop.current()
        self._ioloop.make_current()
        app = tornado.web.Application(
            [(r"/rest/(.*)", SubsonicHandler, {"fe": self})]
        )
        try:
            self._server = app.listen(port, address=host)
            self._ioloop.start()
        except Exception:
            logger.exception("Subsonic server failed to start")
            self._ioloop.stop()

    def on_stop(self):
        if not self.config["ytmusic"]["enable_subsonic"]:
            return
        if self._ioloop:
            self._ioloop.add_callback(self._ioloop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
