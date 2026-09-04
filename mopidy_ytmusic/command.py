import os
from pathlib import Path

from mopidy_ytmusic import logger

SETUP_INSTRUCTIONS = (
    "Open Youtube Music, open developer tools (F12), go to Network tab,"
    ' right click on a POST request and choose "Copy request headers". '
    "Then paste (CTRL+SHIFT+V) them here and press CTRL+D."
)


def _setup_auth(filepath):
    """Prompt the user for browser headers and store them in auth.json."""
    from ytmusicapi import setup

    path = Path(filepath)
    print('Using "' + str(path) + '"')
    if path.exists():
        print("File already exists!")
        return 1
    print(SETUP_INSTRUCTIONS)
    try:
        setup(filepath=str(path))
    except Exception:
        logger.exception("YTMusic setup failed")
        return 1
    print("Authentication JSON data saved to {}".format(str(path)))
    print("")
    print("Update your mopidy.conf to reflect the new auth file:")
    print("   [ytmusic]")
    print("   enabled=true")
    print("   auth_json=" + str(path))
    return 0


def _reauth(filepath):
    """Prompt the user for new browser headers and overwrite auth.json."""
    from ytmusicapi import setup

    path = Path(filepath)
    print('Updating credentials in  "' + str(path) + '"')
    print(SETUP_INSTRUCTIONS)
    try:
        setup(filepath=str(path))
    except Exception:
        logger.exception("YTMusic setup failed")
        return 1
    print("Authentication JSON data saved to {}".format(str(path)))
    return 0


def get_command():
    """Return the CLI command for the running Mopidy version.

    - Mopidy >= 4: a Cyclopts app
    - Mopidy 3.x: a legacy mopidy.commands.Command tree
    """
    try:
        from mopidy import commands
    except ImportError:
        # Mopidy >= 4 removed mopidy.commands and uses Cyclopts apps.
        return _build_cyclopts_command()

    class SetupCommand(commands.Command):
        help = "Generate auth.json"

        def run(self, args, config):
            filepath = input(
                "Enter the path where you want to save auth.json "
                "[default=current dir]: "
            )
            if not filepath:
                filepath = os.getcwd()
            return _setup_auth(filepath + "/auth.json")

    class ReSetupCommand(commands.Command):
        help = "Regenerate auth.json"

        def run(self, args, config):
            path = config["ytmusic"]["auth_json"]
            if not path:
                logger.error("auth_json path not defined in config")
                return 1
            return _reauth(str(path))

    class YTMusicCommand(commands.Command):
        def __init__(self):
            super().__init__()
            self.add_child("setup", SetupCommand())
            self.add_child("reauth", ReSetupCommand())

    return YTMusicCommand()


def _build_cyclopts_command():
    """Build the Mopidy >= 4 CLI using Cyclopts."""
    import cyclopts

    app = cyclopts.App(help="YTMusic extension commands.")

    @app.command(help="Generate auth.json.")
    def setup() -> int:
        filepath = input(
            "Enter the path where you want to save auth.json "
            "[default=current dir]: "
        )
        if not filepath:
            filepath = os.getcwd()
        return _setup_auth(filepath + "/auth.json")

    @app.command(help="Regenerate auth.json.")
    def reauth() -> int:
        from mopidy.config import Config

        path = Config.get_global()["ytmusic"]["auth_json"]
        if not path:
            logger.error("auth_json path not defined in config")
            return 1
        return _reauth(str(path))

    return app
