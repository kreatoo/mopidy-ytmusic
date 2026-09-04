# -*- coding: utf-8 -*-
from setuptools import setup

packages = ["mopidy_ytmusic"]

package_data = {"": ["*"]}

install_requires = [
    "Mopidy>=3.4,<5",
    "ytmusicapi>=1.9,<2",
    "yt-dlp>=2024.1.1",
]

entry_points = {"mopidy.ext": ["ytmusic = mopidy_ytmusic:Extension"]}

setup_kwargs = {
    "name": "mopidy-ytmusic",
    "version": "0.4.0",
    "description": "Mopidy extension for playing music/managing playlists in YouTube Music",
    "long_description": "None",
    "author": "Ozymandias (Tomas Ravinskas)",
    "author_email": "tomas.rav@gmail.com",
    "maintainer": "None",
    "maintainer_email": "None",
    "url": "None",
    "packages": packages,
    "package_data": package_data,
    "install_requires": install_requires,
    "entry_points": entry_points,
    "python_requires": ">=3.10,<4.0",
}


setup(**setup_kwargs)
