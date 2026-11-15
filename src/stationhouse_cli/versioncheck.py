"""Is this CLI still supported, and is there a newer one?

Every call to the platform carries the CLI's version (config.VERSION_HEADER), and the platform
answers 426 to a CLI below the minimum it keeps (CLI_MIN_VERSION, which admins set with
`stationhouse admin cli-min-version`). That reaches every command that calls the platform. This
module covers the ones that don't (help, --version, `design new`, ...): before any command runs,
`check()` asks GET /api/cli/version for {minimum, latest}, at most once an hour, and keeps the answer
in the config directory. Below the minimum, the command doesn't run, but for the ones that must
(`exempt`: `upgrade`, so an unsupported CLI can still update itself, and --version and help, which say
to upgrade on stderr instead). When a newer CLI is out, it says so on stderr, at most once a day.

It never stops a command because it couldn't ask: offline, a slow or broken answer, or a platform
without the route all leave the last answer standing, or nothing if there is none. A failed ask is
remembered for ten minutes, so offline commands don't each wait out the timeout.
STATIONHOUSE_NO_VERSION_CHECK=1 skips it (the release workflow's build check, the tests).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import __version__, auth, config
from .client import UpgradeRequired, upgrade_message

CHECK_EVERY_SECONDS = 60 * 60
NOTICE_EVERY_SECONDS = 24 * 60 * 60
# After an ask that failed (offline, say), wait this long before asking again.
RETRY_FAILED_SECONDS = 10 * 60
# Short: this runs before every command, and a platform that doesn't answer mustn't hold one up.
TIMEOUT = 3


# ASCII digits only: str.isdigit takes superscripts (int() then fails) and other scripts' digits.
VERSION = re.compile(r"([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})")
WINDOWS = os.name == "nt"


def is_version(value) -> bool:
    """Exactly "X.Y.Z" in ASCII digits, nothing around it: safe to put in a tag (upgrade.source)."""
    return isinstance(value, str) and VERSION.fullmatch(value) is not None


def parse(version) -> tuple[int, int, int] | None:
    """(major, minor, patch) for an "X.Y.Z" string (spaces around it allowed), else None."""
    match = VERSION.fullmatch(version.strip()) if isinstance(version, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def which(name: str) -> str | None:
    """`name` on PATH, as shutil.which finds it, but never one in the current directory on Windows,
    where the search (and CreateProcess) looks there first: a folder holding a planted uv.exe or
    git.exe mustn't get it run (review-596 U2)."""
    found = shutil.which(name)
    if found and WINDOWS and os.path.normcase(os.path.dirname(os.path.abspath(found))) == os.path.normcase(os.getcwd()):
        return None
    return found


def below(version: str, other) -> bool:
    """True when `version` is older than `other`; False when either isn't a version."""
    mine, theirs = parse(version), parse(other)
    return mine is not None and theirs is not None and mine < theirs


def _load() -> dict:
    try:
        cached = json.loads(config.version_check_path().read_text())
    except (OSError, ValueError):
        return {}
    return cached if isinstance(cached, dict) else {}


def _save(cached: dict) -> None:
    try:
        d = config.config_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = config.version_check_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(cached))
        os.replace(tmp, config.version_check_path())
    except OSError:
        pass  # a read-only home: ask again next time


def ask() -> dict | None:
    """{minimum, latest} from the platform, or None when it couldn't be had."""
    try:
        url = auth.secure_platform_url(config.api_url()) + "/api/cli/version"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": config.user_agent(),
                                                   config.VERSION_HEADER: __version__})
        try:
            with auth.open_url(req, TIMEOUT) as r:
                out = json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code != 426:
                return None
            out = json.loads(e.read() or b"null")
    except Exception:  # noqa: BLE001 - offline, a timeout, TLS, a redirect, a page that isn't JSON: fail open
        return None
    if not isinstance(out, dict):
        return None
    return {"minimum": out.get("minimum") if is_version(out.get("minimum")) else None,
            "latest": out.get("latest") if is_version(out.get("latest")) else None}


def _within(at, now, seconds) -> bool:
    return isinstance(at, (int, float)) and 0 <= now - at < seconds


def mirror_latest() -> str | None:
    """The newest release members can install: the highest vX.Y.Z tag on the public mirror (what
    cli-release.yml pushes), or None when there's none or it can't be read (no git, offline)."""
    git = which("git")
    if git is None:
        return None
    try:
        out = subprocess.run([git, "ls-remote", "--tags", "--refs", config.MIRROR_URL + ".git", "v*"],
                             capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    versions = [v for line in out.splitlines() if (v := parse(line.rpartition("refs/tags/v")[2]))]
    return ".".join(map(str, max(versions))) if versions else None


UPGRADE_COMMANDS = {"upgrade", "self-update"}


def exempt(argv) -> str | None:
    """Why `argv` runs below the minimum: "upgrade" (it fixes it), "help" or "version" (they only
    print, and say to upgrade); None for every other command."""
    argv = list(argv)
    words = [a for a in argv if not a.startswith("-")]
    if words[:1] and words[0] in UPGRADE_COMMANDS:
        return "upgrade"
    if words[:1] == ["help"] or "-h" in argv or "--help" in argv:
        return "help"
    if not words and "--version" in argv:
        return "version"
    return None


def check(now=None, out=None, argv=()) -> None:
    """Raises UpgradeRequired when this CLI is below the platform's minimum, unless `argv` is exempt;
    prints the newer-version notice when it's due. See the module docstring."""
    if os.environ.get("STATIONHOUSE_NO_VERSION_CHECK"):
        return
    now = time.time() if now is None else now
    out = sys.stderr if out is None else out
    cached = _load()
    if not (_within(cached.get("checked_at"), now, CHECK_EVERY_SECONDS)
            or _within(cached.get("failed_at"), now, RETRY_FAILED_SECONDS)):
        answer = ask()
        if answer is None:
            cached = {**cached, "failed_at": now}  # the last answer, if any, stands
        else:
            cached = {k: v for k, v in cached.items() if k != "failed_at"} | answer | {"checked_at": now}
        _save(cached)
    why = exempt(argv)
    if below(__version__, cached.get("minimum")):
        if why is None:
            raise UpgradeRequired({"minimum": cached["minimum"]})
        if why != "upgrade":
            print(upgrade_message(), file=out)
        return
    if why == "upgrade":
        return  # it says what's newer itself
    due = not _within(cached.get("notified_at"), now, NOTICE_EVERY_SECONDS)
    if due and below(__version__, cached.get("latest")):
        print(f"stationhouse-cli {cached['latest']} is out (you have {__version__}). Run `stationhouse upgrade` "
              f"(or: {config.UPGRADE_COMMAND})", file=out)
        _save({**cached, "notified_at": now})
