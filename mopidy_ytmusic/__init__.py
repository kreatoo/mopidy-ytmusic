import logging
import pathlib
import sys
from importlib.metadata import PackageNotFoundError, version

from mopidy import config, ext


def _install_pkg_resources_compat():
    """Provide a minimal ``pkg_resources`` for Mopidy 3.x.

    Mopidy 3.4 (and earlier) imports ``pkg_resources`` at startup, but
    ``pkg_resources`` was removed in setuptools >= 81.  When it is missing we
    install a small shim backed by ``importlib.metadata`` so Mopidy 3.x keeps
    working on current Python environments.  Mopidy 4.x does not need this.
    """
    try:
        import pkg_resources  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    from importlib import metadata

    class DistributionNotFound(Exception):
        pass

    class VersionConflict(Exception):
        pass

    class ResolutionError(Exception):
        pass

    class _Distribution:
        def __init__(self, name):
            self._name = name

        @property
        def version(self):
            try:
                return metadata.version(self._name)
            except PackageNotFoundError as exc:
                raise DistributionNotFound(str(exc)) from exc

    class _EntryPoint:
        def __init__(self, entry_point):
            self._entry_point = entry_point

        @property
        def name(self):
            return self._entry_point.name

        def resolve(self):
            return self._entry_point.load()

    class _Compat:
        @staticmethod
        def get_distribution(name):
            return _Distribution(name)

        @staticmethod
        def iter_entry_points(group):
            return [
                _EntryPoint(ep) for ep in metadata.entry_points(group=group)
            ]

    mod = _Compat()
    mod.DistributionNotFound = DistributionNotFound
    mod.VersionConflict = VersionConflict
    mod.ResolutionError = ResolutionError
    sys.modules["pkg_resources"] = mod


_install_pkg_resources_compat()


try:
    __version__ = version("Mopidy-YTMusic")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

logger = logging.getLogger(__name__)


class Extension(ext.Extension):

    dist_name = "Mopidy-YTMusic"
    ext_name = "ytmusic"
    version = __version__

    def get_default_config(self):
        return config.read(pathlib.Path(__file__).parent / "ext.conf")

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema["auth_json"] = config.Path(optional=True)
        schema["oauth_client_id"] = config.String(optional=True)
        schema["oauth_client_secret"] = config.String(optional=True)
        schema["auto_playlist_refresh"] = config.Integer(
            minimum=0, optional=True
        )
        schema["youtube_player_refresh"] = config.Integer(
            minimum=1, optional=True
        )
        schema["playlist_item_limit"] = config.Integer(minimum=1, optional=True)
        schema["subscribed_artist_limit"] = config.Integer(
            minimum=0, optional=True
        )
        schema["enable_history"] = config.Boolean(optional=True)
        schema["enable_liked_songs"] = config.Boolean(optional=True)
        schema["enable_mood_genre"] = config.Boolean(optional=True)
        schema["enable_scrobbling"] = config.Boolean(optional=True)
        schema["stream_preference"] = config.List(optional=True)
        schema["verify_track_url"] = config.Boolean(optional=True)
        return schema

    def get_command(self):
        from .command import get_command

        return get_command()

    def setup(self, registry):
        from .backend import YTMusicBackend
        from .scrobble_fe import YTMusicScrobbleFE

        registry.add("backend", YTMusicBackend)
        registry.add("frontend", YTMusicScrobbleFE)
