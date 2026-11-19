"""`stationhouse sessions` and `stationhouse sessions revoke` (STA-212): the list in the CLI's words,
the route each calls, --json, and a revoke of an id that isn't yours said plainly."""
import json

from stationhouse_cli import cli

PATH = "/api/v1/me/sessions"

LAPTOP = {"id": "s-laptop", "createdAt": "2026-11-17T09:00:00.000Z", "lastUsedAt": "2026-11-18T08:00:00.000Z",
          "expiresAt": "2026-12-17T09:00:00.000Z", "userAgent": "stationhouse-cli/0.4.0 (macOS-15.1-arm64; Python 3.12.7)",
          "ipAddress": "203.0.113.7"}
SERVER = {"id": "s-server", "createdAt": "2026-11-01T10:00:00.000Z", "lastUsedAt": "2026-11-02T10:00:00.000Z",
          "expiresAt": "2026-12-01T10:00:00.000Z", "userAgent": None, "ipAddress": None}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_sessions_lists_each_with_program_place_and_dates(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (200, {"sessions": [LAPTOP, SERVER]})
    code, out, _ = run(capsys, "sessions")
    assert code in (0, None)
    assert out == (
        "2 CLI sessions, newest first:\n"
        "  s-laptop  stationhouse-cli 0.4.0 · macOS-15.1-arm64\n"
        "      signed in 2026-11-17 from 203.0.113.7 · last used 2026-11-18 · ends 2026-12-17\n"
        "  s-server  an unknown program\n"
        "      signed in 2026-11-01 · last used 2026-11-02 · ends 2026-12-01\n"
        "  End one: stationhouse sessions revoke <id>\n"
    )


def test_sessions_says_when_there_are_none(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (200, {"sessions": []})
    _, out, _ = run(capsys, "sessions")
    assert out == "No CLI sessions. `stationhouse login` opens one.\n"


def test_sessions_json_is_the_platforms_list(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (200, {"sessions": [LAPTOP]})
    _, out, _ = run(capsys, "sessions", "--json")
    assert json.loads(out) == {"sessions": [LAPTOP]}


def test_revoke_ends_one_by_its_id(signed_in, api, capsys):
    api.routes[("DELETE", f"{PATH}/s-laptop")] = (200, {"revoked": "s-laptop"})
    code, out, _ = run(capsys, "sessions", "revoke", "s-laptop")
    assert code in (0, None)
    assert out == "Ended CLI session s-laptop. An API token it already had stops working within 15 minutes.\n"
    assert any(c["method"] == "DELETE" and c["path"].endswith(f"{PATH}/s-laptop") for c in api.calls)


def test_revoke_of_an_id_that_isnt_yours_says_so(signed_in, api, capsys):
    api.routes[("DELETE", f"{PATH}/nope")] = (404, {"error": "No CLI session of yours has that id. See `stationhouse sessions`."})
    code, _, err = run(capsys, "sessions", "revoke", "nope")
    assert code not in (0, None)
    assert "No CLI session of yours has that id. See `stationhouse sessions`." in err


def test_revoke_needs_an_id(signed_in, api, capsys):
    code, _, err = run(capsys, "sessions", "revoke")
    assert code not in (0, None)
    assert "stationhouse sessions revoke <id>" in err
