import json
import unittest
from unittest import mock

from mopidy_ytmusic import Extension
from mopidy_ytmusic import backend as backend_lib
from mopidy_ytmusic import scrobble_fe


class ExtensionTest(unittest.TestCase):
    @staticmethod
    def get_config():
        config = {}
        config["enabled"] = True
        config["auth_json"] = ""
        config["oauth_client_id"] = ""
        config["oauth_client_secret"] = ""
        config["auto_playlist_refresh"] = 60
        config["youtube_player_refresh"] = 15
        config["playlist_item_limit"] = 1
        config["subscribed_artist_limit"] = 1
        config["enable_history"] = False
        config["enable_liked_songs"] = False
        config["enable_mood_genre"] = True
        config["enable_scrobbling"] = False
        config["enable_radio"] = True
        config["auto_radio"] = True
        config["stream_preference"] = ["141", "251", "140", "250", "249"]
        config["verify_track_url"] = True
        return {"ytmusic": config, "proxy": {}}

    def test_get_default_config(self):
        ext = Extension()
        config = ext.get_default_config()

        assert "[ytmusic]" in config
        assert "enabled = true" in config
        assert "auth_json =" in config
        assert "auto_playlist_refresh = 60" in config
        assert "youtube_player_refresh = 15" in config
        assert "playlist_item_limit = 100" in config
        assert "subscribed_artist_limit = 100" in config
        assert "enable_history = yes" in config
        assert "enable_liked_songs = yes" in config
        assert "enable_mood_genre = yes" in config
        assert "enable_scrobbling = yes" in config
        assert "enable_radio = yes" in config
        assert "auto_radio = yes" in config
        assert "stream_preference = 141, 251, 140, 250, 249" in config
        assert "verify_track_url = yes" in config

    def test_get_config_schema(self):
        ext = Extension()
        schema = ext.get_config_schema()

        assert "enabled" in schema
        assert "auth_json" in schema
        assert "auto_playlist_refresh" in schema
        assert "youtube_player_refresh" in schema
        assert "playlist_item_limit" in schema
        assert "subscribed_artist_limit" in schema
        assert "enable_history" in schema
        assert "enable_liked_songs" in schema
        assert "enable_mood_genre" in schema
        assert "enable_scrobbling" in schema
        assert "enable_radio" in schema
        assert "auto_radio" in schema
        assert "stream_preference" in schema
        assert "verify_track_url" in schema

    def test_get_backend_classes(self):
        registry = mock.Mock()
        ext = Extension()
        ext.setup(registry)

        assert (
            mock.call("backend", backend_lib.YTMusicBackend)
            in registry.add.mock_calls
        )

        assert (
            mock.call("frontend", scrobble_fe.YTMusicScrobbleFE)
            in registry.add.mock_calls
        )

    def test_init_backend(self):
        backend = backend_lib.YTMusicBackend(ExtensionTest.get_config(), None)
        assert backend is not None
        backend.on_start()
        backend.on_stop()

    def test_init_backend_oauth(self):
        # A token file with a refresh_token makes the backend use OAuth.
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "scope": "https://www.googleapis.com/auth/youtube",
                    "token_type": "Bearer",
                    "access_token": "x",
                    "refresh_token": "y",
                    "expires_at": 9999999999,
                    "expires_in": 3600,
                },
                f,
            )
            path = f.name
        cfg = ExtensionTest.get_config()
        cfg["ytmusic"]["auth_json"] = path
        cfg["ytmusic"]["oauth_client_id"] = "id.apps.googleusercontent.com"
        cfg["ytmusic"]["oauth_client_secret"] = "secret"
        backend = backend_lib.YTMusicBackend(config=cfg, audio=None)
        assert backend.api.auth_type.name == "OAUTH_CUSTOM_CLIENT"
        backend.on_stop()

    def test_init_backend_browser(self):
        # A browser-headers dump keeps using plain file-path auth.
        import tempfile

        cookie = (
            "SAPISID=abc; __Secure-3PAPISID=abc; "
            "HSID=abc; SSID=abc; APISID=abc"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "cookie": cookie,
                    "authorization": "SAPISIDHASH x",
                    "x-goog-authuser": "0",
                },
                f,
            )
            path = f.name
        cfg = ExtensionTest.get_config()
        cfg["ytmusic"]["auth_json"] = path
        backend = backend_lib.YTMusicBackend(config=cfg, audio=None)
        assert backend.api.auth_type.name == "BROWSER"
        backend.on_stop()
