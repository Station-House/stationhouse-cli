"""The minimum CLI version: the header on every call, the 426 block, and the cached check before every
command (versioncheck.py)."""
import io
import json

import pytest

from stationhouse_cli import __version__, cli, config, versioncheck

UPGRADE = f"This version ({__version__}) is no longer supported. Update: {config.UPGRADE_COMMAND}"
BLOCKED = (426, {"error": "too old", "minimum": "99.0.0", "latest": "99.0.0"})


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def checking(monkeypatch):
    """The version check on, as members run it (conftest turns it off for every other test)."""
    monkeypatch.delenv("STATIONHOUSE_NO_VERSION_CHECK")


def cached():
    return json.loads(config.version_check_path().read_text())


def headers(call):
    return {k.lower(): v for k, v in call["headers"].items()}


# --- the header, and the platform's 426 ---

def test_every_platform_call_says_which_cli_made_it(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/claims")] = (200, {"claims": []})
    run(capsys, "mine")
    assert headers(api.calls[0])["x-stationhouse-cli-version"] == __version__


def test_a_426_blocks_the_command_with_the_update_line(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/claims")] = BLOCKED
    code, out, err = run(capsys, "mine")
    assert code == 1 and out == ""
    assert err.strip() == UPGRADE


def test_a_426_blocks_signing_in_too(api, capsys):
    api.routes[("POST", "/api/auth/device/code")] = BLOCKED
    code, _, err = run(capsys, "login", "--no-browser")
    assert code == 1 and err.strip() == UPGRADE
    assert headers(api.calls[0])["x-stationhouse-cli-version"] == __version__


def test_a_426_ends_the_chat_rather_than_answering(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/agent/chat")] = BLOCKED
    code, _, err = run(capsys, "ask", "what", "could", "I", "do?")
    assert code == 1 and UPGRADE in err


# --- the cached check before every command ---

def test_below_the_minimum_even_local_commands_are_blocked(checking, api, capsys):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": "99.0.0", "latest": "99.0.0"})
    for argv in (("--version",), ("help",), ("design", "guide")):
        code, out, err = run(capsys, *argv)
        assert (code, out, err.strip()) == (1, "", UPGRADE), argv
    # Asked once; the next commands used the cached answer.
    assert [c["path"] for c in api.calls] == ["/api/cli/version"]
    assert headers(api.calls[0])["x-stationhouse-cli-version"] == __version__


def test_the_version_route_answering_426_blocks_as_well(checking, api, capsys):
    api.routes[("GET", "/api/cli/version")] = BLOCKED
    code, _, err = run(capsys, "design", "guide")
    assert code == 1 and err.strip() == UPGRADE
    assert cached()["minimum"] == "99.0.0"


def test_at_or_above_the_minimum_runs(checking, api, capsys):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": __version__, "latest": __version__})
    with pytest.raises(SystemExit) as e:  # argparse's --version exits 0 after printing
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"stationhouse-cli {__version__}"


def test_no_minimum_set_blocks_nothing(checking, api, capsys):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": __version__})
    code, out, _ = run(capsys, "design", "guide")
    assert code == 0 and out


def test_the_answer_is_kept_an_hour(checking, api):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": __version__})
    versioncheck.check(now=1_000_000)
    versioncheck.check(now=1_000_000 + 3599)
    assert len(api.calls) == 1
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": "99.0.0", "latest": "99.0.0"})
    with pytest.raises(cli.UpgradeRequired):
        versioncheck.check(now=1_000_000 + 3600, out=io.StringIO())
    assert len(api.calls) == 2


def test_offline_fails_open(checking, monkeypatch, capsys):
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")  # nothing listens there
    code, out, _ = run(capsys, "design", "guide")
    assert code == 0 and out
    assert cached().get("minimum") is None


def test_a_failed_ask_waits_ten_minutes_before_asking_again(checking, api, monkeypatch):
    asks = []
    monkeypatch.setattr(versioncheck, "_ask", lambda: asks.append(1))  # None: the ask failed
    versioncheck.check(now=1_000_000)
    versioncheck.check(now=1_000_000 + 599)  # offline help/--version don't each wait the timeout
    assert len(asks) == 1
    versioncheck.check(now=1_000_000 + 600)
    assert len(asks) == 2
    # Once an ask works, the hour applies again and the failure is forgotten.
    monkeypatch.setattr(versioncheck, "_ask", lambda: asks.append(1) or {"minimum": None, "latest": __version__})
    versioncheck.check(now=1_000_000 + 1200)
    assert "failed_at" not in cached() and len(asks) == 3
    versioncheck.check(now=1_000_000 + 1200 + 3599)
    assert len(asks) == 3


def test_offline_keeps_the_last_answer(checking, api, monkeypatch, capsys):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": "99.0.0", "latest": "99.0.0"})
    with pytest.raises(cli.UpgradeRequired):
        versioncheck.check(now=1_000_000, out=io.StringIO())
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")
    # Past the hour, and the platform can't be asked: the last answer stands.
    with pytest.raises(cli.UpgradeRequired):
        versioncheck.check(now=1_000_000 + 7200, out=io.StringIO())


@pytest.mark.parametrize("answer", [(500, {}), (404, {}), (200, ["not", "an", "object"]),
                                    (200, {"minimum": "soon", "latest": "later"})])
def test_a_broken_answer_blocks_nothing(checking, api, capsys, answer):
    api.routes[("GET", "/api/cli/version")] = answer
    code, _, err = run(capsys, "design", "guide")
    assert code == 0 and "no longer supported" not in err and "is out" not in err


def test_the_design_gate_hook_skips_the_check(checking, api, capsys, tmp_path, monkeypatch):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": "99.0.0", "latest": "99.0.0"})
    monkeypatch.chdir(tmp_path)
    for argv in (("design", "gate", "--hook"), ("--json", "design", "gate", "--hook")):
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        run(capsys, *argv)
    assert not any(c["path"] == "/api/cli/version" for c in api.calls)


def test_a_newer_version_is_mentioned_once_a_day(checking, api):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": "99.0.0"})
    out = io.StringIO()
    versioncheck.check(now=1_000_000, out=out)
    versioncheck.check(now=1_000_000 + 4000, out=out)  # asked again, not told again
    assert out.getvalue().count("stationhouse-cli 99.0.0 is out") == 1
    assert config.UPGRADE_COMMAND in out.getvalue()
    versioncheck.check(now=1_000_000 + 86_400, out=out)
    assert out.getvalue().count("stationhouse-cli 99.0.0 is out") == 2


def test_the_notice_goes_to_stderr(checking, api, capsys):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": "99.0.0"})
    _, out, err = run(capsys, "design", "guide")
    assert "is out" not in out and "stationhouse-cli 99.0.0 is out" in err


def test_no_notice_when_up_to_date(checking, api):
    api.routes[("GET", "/api/cli/version")] = (200, {"minimum": None, "latest": __version__})
    out = io.StringIO()
    versioncheck.check(now=1_000_000, out=out)
    assert out.getvalue() == ""


def test_versions_compare_as_numbers():
    assert versioncheck.below("0.2.0", "0.10.0")
    assert not versioncheck.below("0.10.0", "0.2.0")
    assert not versioncheck.below("0.2.0", "0.2.0")
    assert not versioncheck.below("0.2.0", None) and not versioncheck.below("0.2.0", "0.2")


# --- the admin command ---

@pytest.fixture
def released(monkeypatch):
    """The newest vX.Y.Z tag on the public mirror, as `admin cli-min-version` reads it."""
    tag = {"version": "0.2.0"}
    monkeypatch.setattr(versioncheck, "mirror_latest", lambda: tag["version"])
    return tag


def test_admin_cli_min_version_shows_sets_and_clears(signed_in, api, capsys, released):
    path = "/api/admin/config"
    api.routes[("GET", path)] = (200, {"key": "CLI_MIN_VERSION", "value": ""})
    api.routes[("PUT", path)] = (200, {"key": "CLI_MIN_VERSION", "value": "0.2.0"})
    api.routes[("DELETE", path)] = (200, {"key": "CLI_MIN_VERSION", "value": ""})

    code, out, _ = run(capsys, "admin", "cli-min-version")
    assert code == 0 and "No minimum" in out
    assert api.calls[-1]["path"] == f"{path}?key=CLI_MIN_VERSION"

    code, out, _ = run(capsys, "admin", "cli-min-version", "0.2.0")
    assert code == 0 and "CLIs below 0.2.0 are blocked." in out
    assert api.calls[-1]["body"] == {"key": "CLI_MIN_VERSION", "value": "0.2.0"}

    code, out, _ = run(capsys, "--json", "admin", "cli-min-version", "--clear")
    assert code == 0 and json.loads(out) == {"minimum": None}
    assert api.calls[-1]["method"] == "DELETE"


def test_admin_cli_min_version_refuses_one_above_the_newest_release(signed_in, api, capsys, released):
    api.routes[("PUT", "/api/admin/config")] = (200, {"key": "CLI_MIN_VERSION", "value": "0.3.0"})
    code, _, err = run(capsys, "admin", "cli-min-version", "0.3.0")
    assert code == 1 and "newest release members can install is 0.2.0" in err and "--force" in err
    released["version"] = None  # the mirror couldn't be read
    code, _, err = run(capsys, "admin", "cli-min-version", "0.2.0")
    assert code == 1 and "Found no release" in err
    assert api.calls == []
    code, out, _ = run(capsys, "admin", "cli-min-version", "0.3.0", "--force")
    assert code == 0 and "CLIs below 0.3.0 are blocked." in out
    assert api.calls[-1]["body"] == {"key": "CLI_MIN_VERSION", "value": "0.3.0"}


def test_mirror_latest_reads_the_highest_release_tag(monkeypatch):
    import subprocess
    listing = "".join(f"{'a' * 40}\trefs/tags/{t}\n" for t in ("v0.1.0", "v0.10.0", "v0.2.0", "vnext"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    assert versioncheck.mirror_latest() == "0.10.0"

    def offline(*a, **k):
        raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(subprocess, "run", offline)
    assert versioncheck.mirror_latest() is None


def test_admin_cli_min_version_refuses_a_non_version(signed_in, api, capsys):
    code, _, err = run(capsys, "admin", "cli-min-version", "latest")
    assert code == 1 and "isn't a version" in err
    assert api.calls == []


def test_admin_cli_min_version_shows_the_platforms_refusal(signed_in, api, capsys, released):
    api.routes[("PUT", "/api/admin/config")] = (403, {"error": "Admins only."})
    code, _, err = run(capsys, "admin", "cli-min-version", "0.2.0")
    assert code == 1 and "Admins only." in err
