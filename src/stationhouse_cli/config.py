import os
import platform
from pathlib import Path

# Public identifiers of the Station House Cognito pool (the same values the web app ships in
# amplify_outputs.json). They are not secrets: a sign-in still needs a code from the member's inbox, or their password.
USER_POOL_ID = "us-east-1_IVIvCXApg"
CLIENT_ID = "79iirq0u3k2uuqhq3s2tph7ru3"
REGION = "us-east-1"
DEFAULT_API_URL = "https://app.station-house.net"
# Every call to the platform says which CLI made it; the platform answers 426 to one below the
# minimum it supports (src/lib/cli-version.ts). The update command is what that 426 tells members.
VERSION_HEADER = "X-Stationhouse-CLI-Version"
# The public mirror members install from; each release is a vX.Y.Z tag there (cli-release.yml).
MIRROR_URL = "https://github.com/Station-House/stationhouse-cli"
UPGRADE_COMMAND = f"uv tool install --force git+{MIRROR_URL}"


def api_url() -> str:
    return os.environ.get("STATIONHOUSE_API_URL", DEFAULT_API_URL).rstrip("/")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) / "stationhouse" if base else Path.home() / ".config" / "stationhouse"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def settings_path() -> Path:
    """Non-secret preferences (the project you picked with `project use`)."""
    return config_dir() / "settings.json"


def version_check_path() -> Path:
    """The last answer to "is this CLI still supported?" (versioncheck.py), and when it was asked."""
    return config_dir() / "version-check.json"


def project_env() -> str | None:
    """STATIONHOUSE_PROJECT, for scripts and agents that pin a project without touching settings."""
    return os.environ.get("STATIONHOUSE_PROJECT") or None


def user_agent() -> str:
    """What the CLI calls itself to the platform. The device sign-in shows it on /device next to the
    code, so a member can tell their own terminal's request from someone else's."""
    from . import __version__
    return f"stationhouse-cli/{__version__} ({platform.platform(terse=True)}; Python {platform.python_version()})"
