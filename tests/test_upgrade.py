"""`stationhouse upgrade` (alias `self-update`, STA-446): the CLI updates itself from the public mirror,
with the tool that installed it. Every installer call here is faked: nothing is installed."""
import json
import subprocess
import sys

import pytest

from stationhouse_cli import __version__, cli, config, upgrade, versioncheck

NEWEST = "99.0.0"
SOURCE = f"git+{config.MIRROR_URL}@v{NEWEST}"


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


class Installer:
    """upgrade._run (subprocess.run) as upgrade.py calls it: the installer, then the new version's own report."""

    def __init__(self, code=0, after=NEWEST):
        self.calls, self.code, self.after = [], code, after

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if argv[:2] == [sys.executable, "-c"]:  # what the environment has now
            return subprocess.CompletedProcess(argv, 0, stdout=f"{self.after}\n", stderr="")
        return subprocess.CompletedProcess(argv, self.code)

    @property
    def installs(self):
        return [argv for argv, _ in self.calls if argv[:2] != [sys.executable, "-c"]]


@pytest.fixture
def installer(monkeypatch):
    fake = Installer()
    monkeypatch.setattr(upgrade, "_run", fake)
    return fake


@pytest.fixture
def newest(monkeypatch):
    """The newest vX.Y.Z tag on the mirror, as git ls-remote would read it."""
    tag = {"version": NEWEST}
    monkeypatch.setattr(versioncheck, "mirror_latest", lambda: tag["version"])
    return tag


@pytest.fixture
def tools(monkeypatch):
    """What's on PATH: uv and pipx, unless a test takes one away."""
    found = {"uv": "/home/m/.local/bin/uv", "pipx": "/home/m/.local/bin/pipx"}
    monkeypatch.setattr(versioncheck.shutil, "which", lambda name: found.get(name))
    return found


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The Python environment this CLI runs from: sys.prefix, with the marker its installer left."""
    prefix = tmp_path / "env"
    prefix.mkdir()
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "base_prefix", str(prefix))
    monkeypatch.setattr(upgrade, "_installer", lambda: "uv")

    def installed_by(how):
        if how == "uv":
            (prefix / "uv-receipt.toml").write_text('[tool]\nrequirements = [{ name = "stationhouse-cli" }]\n')
        elif how == "pipx":
            (prefix / "pipx_metadata.json").write_text("{}")
        elif how == "pip":
            monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "python"))  # a venv
            monkeypatch.setattr(upgrade, "_installer", lambda: "pip")
    return installed_by


@pytest.mark.parametrize("how, argv", [
    ("uv", ["/home/m/.local/bin/uv", "tool", "install", "--force", SOURCE]),
    ("pipx", ["/home/m/.local/bin/pipx", "install", "--force", SOURCE]),
    ("pip", [sys.executable, "-m", "pip", "install", "--upgrade", SOURCE]),
])
def test_it_reinstalls_from_the_mirror_with_the_tool_that_installed_it(capsys, installer, newest, tools, env, how, argv):
    env(how)
    code, out, err = run(capsys, "upgrade")
    assert code == 0
    assert installer.installs == [argv]
    assert f"stationhouse-cli {__version__} → {NEWEST}" in out
    # An argv list, never a shell string; and never sudo.
    assert all(not kwargs.get("shell") for _, kwargs in installer.calls)
    assert all("sudo" not in argv for argv, _ in installer.calls)


def test_self_update_is_the_same_command(capsys, installer, newest, tools, env):
    env("uv")
    code, out, _ = run(capsys, "self-update")
    assert code == 0 and installer.installs[0][1:4] == ["tool", "install", "--force"]


def test_on_the_newest_release_it_says_so_and_does_nothing(capsys, installer, newest, tools, env):
    env("uv")
    newest["version"] = __version__
    code, out, _ = run(capsys, "upgrade")
    assert code == 0 and installer.calls == []
    assert out.strip() == f"stationhouse-cli {__version__} is the newest release already."


@pytest.mark.parametrize("how", ["unknown", "pip outside a venv"])
def test_when_it_cant_tell_it_prints_the_command_instead(capsys, installer, newest, tools, env, monkeypatch, how):
    if how == "pip outside a venv":
        monkeypatch.setattr(upgrade, "_installer", lambda: "pip")  # the system Python: no pip, no sudo
    code, out, err = run(capsys, "upgrade")
    assert code == 1 and installer.calls == []
    assert f"uv tool install --force {SOURCE}" in err
    assert "Couldn't tell how stationhouse-cli was installed" in err


def test_a_tool_that_isnt_on_path_any_more_prints_the_command(capsys, installer, newest, tools, env):
    env("pipx")
    del tools["pipx"]
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and installer.calls == []
    assert f"pipx install --force {SOURCE}" in err


def test_a_failed_install_says_so_and_gives_the_command(capsys, newest, tools, env, monkeypatch):
    env("uv")
    failing = Installer(code=2)
    monkeypatch.setattr(upgrade, "_run", failing)
    code, out, err = run(capsys, "upgrade")
    assert code == 1 and "→" not in out
    assert "uv failed (exit 2)" in err and f"uv tool install --force {SOURCE}" in err


def test_an_install_that_changed_nothing_isnt_reported_as_done(capsys, newest, tools, env, monkeypatch):
    env("uv")
    monkeypatch.setattr(upgrade, "_run", Installer(after=__version__))
    code, out, err = run(capsys, "upgrade")
    assert code == 1 and "→" not in out
    assert f"still {__version__}" in err


def test_version_installs_that_release(capsys, installer, newest, tools, env, monkeypatch):
    env("uv")
    installer.after = "0.1.0"
    code, out, _ = run(capsys, "upgrade", "--version", "0.1.0")
    assert code == 0
    assert installer.installs == [["/home/m/.local/bin/uv", "tool", "install", "--force",
                                   f"git+{config.MIRROR_URL}@v0.1.0"]]
    assert f"stationhouse-cli {__version__} → 0.1.0" in out


@pytest.mark.parametrize("bad", ["0.3", "v0.3.0", "0.3.0; echo hi", "latest", "0.3.0 --index-url=x", "../0.3.0",
                                 " 0.3.0", "0.3.0\n", "٠.٣.٠"])  # padding; Arabic-Indic digits
def test_version_must_be_x_y_z_before_anything_runs(capsys, installer, newest, tools, env, bad):
    env("uv")
    code, _, err = run(capsys, "upgrade", "--version", bad)
    assert code == 1 and installer.calls == []
    assert "isn't a version like 0.3.1" in err


def test_check_only_reports(capsys, installer, newest, tools, env):
    env("uv")
    code, out, _ = run(capsys, "upgrade", "--check")
    assert code == 0 and installer.calls == []
    assert out.strip() == f"stationhouse-cli {NEWEST} is out (you have {__version__}). Run `stationhouse upgrade`."
    code, out, _ = run(capsys, "upgrade", "--check", "--json")
    assert json.loads(out) == {"current": __version__, "latest": NEWEST, "newer": True}
    newest["version"] = __version__
    _, out, _ = run(capsys, "upgrade", "--check")
    assert out.strip() == f"stationhouse-cli {__version__} is the newest release."


def test_check_asks_the_platform_when_the_mirror_cant_be_read(capsys, api, installer, newest, tools, env):
    newest["version"] = None  # no git, say
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": "98.0.0"})
    code, out, _ = run(capsys, "upgrade", "--check", "--json")
    assert code == 0 and json.loads(out)["latest"] == "98.0.0"


def test_upgrade_doesnt_repeat_the_newer_version_notice(capsys, api, installer, newest, tools, env, monkeypatch):
    monkeypatch.delenv("STATIONHOUSE_NO_VERSION_CHECK")
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": NEWEST})
    code, out, err = run(capsys, "upgrade", "--check")
    assert code == 0 and "is out" in out and "is out" not in err


def test_no_newest_release_at_all_installs_nothing(capsys, installer, newest, tools, env):
    env("uv")
    newest["version"] = None
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and installer.calls == []
    assert config.UPGRADE_COMMAND in err


@pytest.mark.parametrize("odd", ["1.2.³", "٠.٣.٠", " 99.0.0", "99.0.0 --pre"])  # superscript; Arabic-Indic
def test_a_platform_latest_that_isnt_ascii_x_y_z_is_never_installed(capsys, api, installer, newest, tools, env, odd):
    """review-596 U4: the fallback `latest` meets the same check as --version before it becomes a tag."""
    env("uv")
    newest["version"] = None
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": odd})
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and installer.calls == []
    assert "Couldn't find the newest release" in err


@pytest.mark.parametrize("odd", ["1.2.³", "٠.٣.٠", " 99.0.0", "99.0.0 --pre"])
def test_each_layer_drops_a_latest_that_isnt_ascii_x_y_z(api, monkeypatch, odd):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": odd, "latest": odd})
    assert versioncheck.ask() == {"minimum": None, "latest": None}
    monkeypatch.setattr(versioncheck, "mirror_latest", lambda: None)
    monkeypatch.setattr(versioncheck, "ask", lambda: {"minimum": None, "latest": odd})
    assert upgrade.latest() is None


@pytest.mark.parametrize("odd", ["1.2.³", "٠.٣.٠"])
def test_an_odd_minimum_or_latest_never_breaks_the_version_check(capsys, api, monkeypatch, odd):
    monkeypatch.delenv("STATIONHOUSE_NO_VERSION_CHECK")
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": odd, "latest": odd})
    code, _, err = run(capsys, "design", "guide")
    assert code == 0 and "no longer supported" not in err and "is out" not in err
    assert versioncheck.parse(odd) is None


@pytest.fixture
def windows(monkeypatch, tmp_path):
    """Windows, run from a folder: its search finds programs in the current directory first."""
    monkeypatch.setattr(versioncheck, "WINDOWS", True)
    here = tmp_path / "downloads"
    here.mkdir()
    monkeypatch.chdir(here)
    return here


def test_on_windows_an_installer_in_the_current_directory_is_never_run(capsys, installer, newest, tools, env, windows):
    """review-596 U2: a planted uv.exe in the folder it's run from."""
    env("uv")
    tools["uv"] = str(windows / "uv.exe")
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and installer.calls == []
    assert f"uv tool install --force {SOURCE}" in err


def test_off_windows_the_same_path_is_used(capsys, installer, newest, tools, env, windows, monkeypatch):
    monkeypatch.setattr(versioncheck, "WINDOWS", False)
    env("uv")
    tools["uv"] = str(windows / "uv")
    code, _, _ = run(capsys, "upgrade")
    assert code == 0 and installer.installs[0][0] == str(windows / "uv")


def test_on_windows_git_in_the_current_directory_is_never_run(windows, monkeypatch):
    ran = []
    monkeypatch.setattr(versioncheck.shutil, "which", lambda name: str(windows / f"{name}.exe"))
    monkeypatch.setattr(versioncheck.subprocess, "run", lambda *a, **k: ran.append(a))
    assert versioncheck.mirror_latest() is None and ran == []


def test_json_says_what_changed(capsys, installer, newest, tools, env):
    env("uv")
    code, out, _ = run(capsys, "upgrade", "--json")
    assert code == 0 and json.loads(out) == {"from": __version__, "to": NEWEST, "installer": "uv"}
    # The installer's own output goes to stderr, so stdout stays JSON.
    assert installer.calls[0][1].get("stdout") == 2


def test_it_reminds_claude_code_users_to_refresh_the_plugin(capsys, installer, newest, tools, env):
    env("uv")
    _, out, _ = run(capsys, "upgrade")
    assert "/plugin marketplace update stationhouse-cli" in out


# --- below the platform's minimum ---

@pytest.fixture
def blocked(monkeypatch, api):
    monkeypatch.delenv("STATIONHOUSE_NO_VERSION_CHECK")
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": "99.0.0", "latest": "99.0.0"})


@pytest.mark.parametrize("argv", [("upgrade",), ("self-update",), ("--json", "upgrade")])
def test_upgrade_runs_below_the_minimum(capsys, blocked, installer, newest, tools, env, argv):
    env("uv")
    code, out, err = run(capsys, *argv)
    assert code == 0 and len(installer.installs) == 1
    assert "no longer supported" not in err


def test_version_and_help_run_below_the_minimum_and_say_to_upgrade(capsys, blocked):
    with pytest.raises(SystemExit) as done:
        run(capsys, "--version")
    assert done.value.code == 0
    out = capsys.readouterr()
    assert f"stationhouse-cli {__version__}" in out.out and "Run `stationhouse upgrade`" in out.err
    for argv in (("help",), ("--help",), ("task", "--help")):
        with pytest.raises(SystemExit) as done:
            run(capsys, *argv)
        assert done.value.code == 0
        assert "usage: stationhouse" in capsys.readouterr().out


def test_other_commands_stop_and_point_at_upgrade(capsys, blocked):
    code, out, err = run(capsys, "design", "guide")
    assert code == 1 and out == ""
    assert err.strip() == (f"This version ({__version__}) is no longer supported. Run `stationhouse upgrade` "
                           f"(or: {config.UPGRADE_COMMAND})")
