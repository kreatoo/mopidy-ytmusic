import unittest

from mopidy_ytmusic import playback as playback_lib


class PlaybackTest(unittest.TestCase):
    def test_pick_stream_preference(self):
        formats = [
            {"format_id": "140", "acodec": "mp4a.40.2", "abr": 131},
            {"format_id": "251", "acodec": "opus", "abr": 150},
            {"format_id": "136", "acodec": "none", "abr": None},
        ]
        picked = playback_lib._pick_stream(
            formats, stream_preference=["141", "251", "140"]
        )
        assert picked["format_id"] == "251"

    def test_pick_stream_highest_bitrate(self):
        formats = [
            {"format_id": "140", "acodec": "mp4a.40.2", "abr": 131},
            {"format_id": "251", "acodec": "opus", "abr": 150},
            {"format_id": "136", "acodec": "none", "abr": None},
        ]
        picked = playback_lib._pick_stream(formats, stream_preference=[])
        assert picked["format_id"] == "251"

    def test_pick_stream_empty(self):
        assert playback_lib._pick_stream([], stream_preference=[]) is None
