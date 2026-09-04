import os
from pathlib import Path

from mopidy_ytmusic import logger

SETUP_INSTRUCTIONS = (
    "Open Youtube Music, open developer tools (F12), go to Network tab,"
    ' right click on a POST request and choose "Copy request headers". '
    "Then paste (CTRL+SHIFT+V) them here and press CTRL+D."
)


def _sanitize_auth_json(path):
    """Strip headers that break outgoing API requests.

    ``content-encoding: gzip`` (present in some Chrome "copy request headers"
    blocks) makes YouTube expect a compressed request body and reject our
    request with HTTP 400. ``host``/``content-length`` are request-specific
    and must not be reused either.
    """
    import json

    try:
        with open(path) as file:
            data = json.load(file)
        changed = False
        for bad in ("content-encoding", "content-length", "host"):
            if bad in data:
                data.pop(bad)
                changed = True
        if changed:
            with open(path, "w") as file:
                json.dump(data, file, indent=2)
    except (OSError, ValueError):
        logger.exception("YTMusic failed sanitizing auth headers")


def _write_auth_json(path, headers_raw=None):
    """Run ytmusicapi.setup() and sanitize the resulting auth.json."""
    from ytmusicapi import setup

    setup(filepath=str(path), headers_raw=headers_raw)
    _sanitize_auth_json(path)


def _setup_auth(filepath):
    """Prompt the user for browser headers and store them in auth.json."""
    path = Path(filepath)
    print('Using "' + str(path) + '"')
    if path.exists():
        print("File already exists!")
        return 1
    print(SETUP_INSTRUCTIONS)
    try:
        _write_auth_json(path)
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
    path = Path(filepath)
    print('Updating credentials in  "' + str(path) + '"')
    print(SETUP_INSTRUCTIONS)
    try:
        _write_auth_json(path)
    except Exception:
        logger.exception("YTMusic setup failed")
        return 1
    print("Authentication JSON data saved to {}".format(str(path)))
    return 0


def _oauth_auth(filepath):
    """Run the OAuth device flow and store a long-lived, self-refreshing token.

    The token itself never needs to be re-pasted (ytmusicapi refreshes the
    access token automatically), only this one-time authorization does.
    """
    from ytmusicapi import setup_oauth

    path = Path(filepath)
    print('Using "' + str(path) + '"')
    if path.exists():
        print("File already exists!")
        return 1
    client_id = input("Enter your Google OAuth client_id: ").strip()
    client_secret = input("Enter your Google OAuth client_secret: ").strip()
    if not client_id or not client_secret:
        logger.error("client_id and client_secret are both required")
        return 1
    print("Opening your browser for authorization...")
    try:
        setup_oauth(
            client_id,
            client_secret,
            filepath=str(path),
            open_browser=True,
        )
    except Exception:
        logger.exception("YTMusic OAuth setup failed")
        return 1
    print("OAuth token saved to {}".format(str(path)))
    print("")
    print("Update your mopidy.conf to reflect the new auth file:")
    print("   [ytmusic]")
    print("   enabled=true")
    print("   auth_json=" + str(path))
    print("   oauth_client_id=" + client_id)
    print("   oauth_client_secret=" + client_secret)
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

    class OAuthCommand(commands.Command):
        help = "Authorize once with Google OAuth (token auto-renews)"

        def run(self, args, config):
            filepath = input(
                "Enter the path where you want to save oauth.json "
                "[default=current dir]: "
            )
            if not filepath:
                filepath = os.getcwd()
            return _oauth_auth(filepath + "/oauth.json")

    class YTMusicCommand(commands.Command):
        def __init__(self):
            super().__init__()
            self.add_child("setup", SetupCommand())
            self.add_child("reauth", ReSetupCommand())
            self.add_child("oauth", OAuthCommand())

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

    @app.command(
        help="Authorize once with Google OAuth (token auto-renews afterwards)."
    )
    def oauth() -> int:
        filepath = input(
            "Enter the path where you want to save oauth.json "
            "[default=current dir]: "
        )
        if not filepath:
            filepath = os.getcwd()
        return _oauth_auth(filepath + "/oauth.json")

    return app
