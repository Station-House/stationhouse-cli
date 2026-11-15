"""`stationhouse upgrade` (alias `self-update`, STA-446): the CLI updates itself.

It reinstalls from the public mirror (config.MIRROR_URL), pinned to a release's vX.Y.Z tag, with the
tool that installed it: `uv tool` (the documented way), pipx, or pip in the virtualenv it runs from.
The environment says which: uv leaves uv-receipt.toml in a tool's environment, pipx leaves
pipx_metadata.json, and pip writes "pip" into the package's INSTALLER record. When it can't tell (a
system Python, a development checkout), it prints the command to run rather than guess.

The installer runs from an argv list, never through a shell, and never with sudo. `--version` is
checked as X.Y.Z before it goes anywhere near one. It runs below the platform's minimum version
(versioncheck.exempt), or a CLI that's no longer supported couldn't update itself.
"""
import importlib.metadata
import json
import shlex
import subprocess
import sys
from pathlib import Path

from . import __version__, config, versioncheck
from .client import ApiError

DIST = "stationhouse-cli"
PLUGIN_REFRESH = "/plugin marketplace update stationhouse-cli"


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Every process this module starts (the tests fake this one)."""
    return subprocess.run(argv, **kwargs)  # noqa: S603 - an argv list, never a shell


def _installer() -> str | None:
    """Which tool installed this package, as it recorded it (PEP 376's INSTALLER file)."""
    try:
        return (importlib.metadata.distribution(DIST).read_text("INSTALLER") or "").strip() or None
    except importlib.metadata.PackageNotFoundError:
        return None


def how_installed() -> str | None:
    """"uv", "pipx" or "pip", or None when it can't tell."""
    prefix = Path(sys.prefix)
    if (prefix / "uv-receipt.toml").is_file():
        return "uv"
    if (prefix / "pipx_metadata.json").is_file():
        return "pipx"
    # pip only inside a virtualenv: into a system Python it would need sudo, or be refused (PEP 668).
    if sys.prefix != sys.base_prefix and _installer() == "pip":
        return "pip"
    return None


def source(version: str) -> str:
    return f"git+{config.MIRROR_URL}@v{version}"


def command(how: str, version: str, found=True) -> list[str] | None:
    """The installer's argv; with found=False, as a member would type it. None when the tool isn't
    on PATH any more (or, on Windows, is only in the current directory: versioncheck.which)."""
    tool = versioncheck.which if found else (lambda name: name)
    if how == "uv":
        uv = tool("uv")
        return [uv, "tool", "install", "--force", source(version)] if uv else None
    if how == "pipx":
        pipx = tool("pipx")
        return [pipx, "install", "--force", source(version)] if pipx else None
    if how == "pip":
        return [sys.executable if found else "python", "-m", "pip", "install", "--upgrade", source(version)]
    return None


def latest() -> str | None:
    """The newest release: the mirror's highest vX.Y.Z tag, which is what can be installed. The
    platform's `latest` is main's version, which runs ahead of the mirror between a version bump's
    merge and its tag, so it's asked only when the mirror can't be read (no git, say)."""
    newest = versioncheck.mirror_latest() or (versioncheck.ask() or {}).get("latest")
    return newest if versioncheck.is_version(newest) else None


def _now_installed() -> str | None:
    """The version the environment holds now, asked of its own Python (this process still runs the
    old code)."""
    try:
        out = _run([sys.executable, "-c", f"import importlib.metadata as m; print(m.version({DIST!r}))"],
                             capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    found = out.stdout.strip()
    return found if out.returncode == 0 and versioncheck.parse(found) else None


def cmd_upgrade(args) -> int:
    wanted = args.version
    # Strictly X.Y.Z in ASCII digits: it becomes part of the installer's argument (the tag).
    if wanted is not None and not versioncheck.is_version(wanted):
        raise ApiError(f"{wanted!r} isn't a version like 0.3.1.")
    newest = latest()

    if args.check:
        if newest is None:
            raise ApiError(f"Couldn't find the newest release on {config.MIRROR_URL} or the platform. Try again later.")
        newer = versioncheck.below(__version__, newest)
        data = {"current": __version__, "latest": newest, "newer": newer}
        if args.json:
            print(json.dumps(data, indent=2))
        elif newer:
            print(f"stationhouse-cli {newest} is out (you have {__version__}). Run `stationhouse upgrade`.")
        else:
            print(f"stationhouse-cli {__version__} is the newest release.")
        return 0

    target = wanted or newest
    if target is None:
        raise ApiError(f"Couldn't find the newest release on {config.MIRROR_URL} (is git installed? are you "
                       f"online?). To update anyway: {config.UPGRADE_COMMAND}")
    if target == __version__:
        print(f"stationhouse-cli {__version__} is the newest release already." if wanted is None
              else f"stationhouse-cli {__version__} is installed already.")
        return 0

    how = how_installed()
    argv = command(how, target) if how else None
    if argv is None:
        typed = shlex.join(command(how or "uv", target, found=False))
        why = "Couldn't tell how stationhouse-cli was installed" if how is None else f"{how} isn't on your PATH"
        print(f"{why}, so nothing changed. To update it, run:\n  {typed}", file=sys.stderr)
        return 1

    print(f"Updating stationhouse-cli {__version__} → {target} with {how}…", file=sys.stderr)
    sys.stderr.flush()
    # Its output goes to stderr (fd 2), as it happens, so stdout stays clean for --json.
    done = _run(argv, stdout=2, check=False)
    if done.returncode != 0:
        typed = shlex.join(command(how, target, found=False))
        print(f"{how} failed (exit {done.returncode}), so stationhouse-cli may not have changed. "
              f"To update it yourself, run:\n  {typed}", file=sys.stderr)
        return 1
    now = _now_installed() or target
    if now == __version__:
        print(f"{how} finished, but stationhouse-cli is still {now}.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"from": __version__, "to": now, "installer": how}, indent=2))
    else:
        print(f"stationhouse-cli {__version__} → {now}")
        # The Claude Code plugin's version moves with the CLI's (cli-release.yml checks it).
        print(f"Using the Claude Code plugin? Refresh it too: {PLUGIN_REFRESH}")
    return 0
