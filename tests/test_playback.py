import unittest

from mopidy_ytmusic import playback as playback_lib


class PlaybackTest(unittest.TestCase):
    def test_pick_stream_preference(self):
        formats = [
            {"format_id": "140", "acodec": "mp4a.40.2", "abr": 131},
            {"format_id": "251", "acodec": "opus", "abr": 150},
            {"format_id": "136", "acodec": "none", "abr": None},
        ]
        backend = mock_backend(stream_preference=["141", "251", "140"])
        provider = playback_lib.YTMusicPlaybackProvider.__new__(
            playback_lib.YTMusicPlaybackProvider
        )
        provider.backend = backend
        picked = provider._pick_stream(formats)
        assert picked["format_id"] == "251"

    def test_pick_stream_highest_bitrate(self):
        formats = [
            {"format_id": "140", "acodec": "mp4a.40.2", "abr": 131},
            {"format_id": "251", "acodec": "opus", "abr": 150},
            {"format_id": "136", "acodec": "none", "abr": None},
        ]
        provider = playback_lib.YTMusicPlaybackProvider.__new__(
            playback_lib.YTMusicPlaybackProvider
        )
        provider.backend = mock_backend(stream_preference=[])
        picked = provider._pick_stream(formats)
        assert picked["format_id"] == "251"

    def test_pick_stream_empty(self):
        provider = playback_lib.YTMusicPlaybackProvider.__new__(
            playback_lib.YTMusicPlaybackProvider
        )
        provider.backend = mock_backend(stream_preference=[])
        assert provider._pick_stream([]) is None


def mock_backend(stream_preference):
    class Backend:
        pass

    backend = Backend()
    backend.stream_preference = stream_preference
    return backend
