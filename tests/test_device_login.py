"""`stationhouse login` by device authorization (RFC 8628) against the platform's Better Auth, the
emailed-code fallback, and how the CLI keeps, refreshes and ends the session it gets."""
import base64
import json
import re
import time

import urllib.error

import pytest

from stationhouse_cli import auth, cli, config
from stationhouse_cli.store import load_credentials, save_credentials

CODE = {"device_code": "dev-code-0123456789", "user_code": "WDJBMJHT",
        "verification_uri": "https://app.station-house.net/device",
        "verification_uri_complete": "https://app.station-house.net/device?user_code=WDJBMJHT",
        "expires_in": 600, "interval": 5}
PENDING = (400, {"error": "authorization_pending", "error_description": "Authorization pending"})


def device_code(api, **changes) -> dict:
    """CODE as the fake platform would hand it out: its sign-in page is on the platform itself."""
    return {**CODE, "verification_uri": f"{api.url}/device",
            "verification_uri_complete": f"{api.url}/device?user_code=WDJBMJHT", **changes}


def platform_jwt(exp: float, email: str = "ada@example.com") -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'EdDSA'})}.{b64({'sub': 'usr_1', 'email': email, 'exp': exp, 'iss': 'stationhouse'})}.sig"


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def sleeps(monkeypatch):
    """No real waiting: records each poll's wait instead."""
    waits = []
    monkeypatch.setattr(auth.time, "sleep", waits.append)
    return waits


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url: pytest.fail(f"opened a browser at {url}"))


def calls_to(api, path):
    return [c for c in api.calls if c["path"].split("?")[0] == path]


def test_signs_in_by_approving_in_the_browser_and_keeps_the_session(api, sleeps, capsys):
    jwt = platform_jwt(time.time() + 900)
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api))
    api.routes[("POST", "/api/auth/device/token")] = [
        PENDING, (400, {"error": "slow_down"}), PENDING,
        (200, {"access_token": "session-token", "token_type": "Bearer", "expires_in": 2592000, "scope": ""})]
    api.routes[("GET", "/api/auth/token")] = (200, {"token": jwt})

    code, out, _ = run(capsys, "login")

    assert code == 0
    # The plain page and the code to type there, never the link with the code in it.
    assert f"{api.url}/device" in out and "WDJB-MJHT" in out and "user_code" not in out
    assert "Signed in as ada@example.com." in out
    assert calls_to(api, "/api/auth/device/code")[0]["body"] == {"client_id": "stationhouse-cli"}
    polls = calls_to(api, "/api/auth/device/token")
    assert len(polls) == 4 and all(p["body"] == {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                                 "device_code": "dev-code-0123456789", "client_id": "stationhouse-cli"}
                                   for p in polls)
    # The server's interval, five seconds more after slow_down (RFC 8628 §3.5).
    assert sleeps == [5, 5, 10, 10]
    assert calls_to(api, "/api/auth/token")[0]["headers"]["Authorization"] == "Bearer session-token"
    # The same file a Cognito sign-in writes, so an older CLI still reads it.
    assert load_credentials() == {"provider": "better-auth", "email": "ada@example.com", "access_token": jwt,
                                  "id_token": "", "refresh_token": "session-token", "expires_at": pytest.approx(time.time() + 900, abs=5),
                                  "api_url": api.url}  # the platform that issued the session


def test_a_denied_sign_in_stores_nothing(api, sleeps, capsys):
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api))
    api.routes[("POST", "/api/auth/device/token")] = [PENDING, (400, {"error": "access_denied"})]
    code, _, err = run(capsys, "login")
    assert code == 1 and "denied" in err
    assert load_credentials() is None


def test_an_expired_code_says_to_start_again(api, sleeps, capsys):
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api))
    api.routes[("POST", "/api/auth/device/token")] = (400, {"error": "expired_token"})
    code, _, err = run(capsys, "login")
    assert code == 1 and "expired" in err and "stationhouse login" in err
    assert load_credentials() is None


def test_gives_up_when_the_code_runs_out_while_still_pending(api, monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(auth.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api, expires_in=12))
    api.routes[("POST", "/api/auth/device/token")] = PENDING
    code, _, err = run(capsys, "login")
    assert code == 1 and "expired" in err
    assert len(calls_to(api, "/api/auth/device/token")) == 3  # at 5s, 10s and 15s


def test_falls_back_to_an_emailed_code_where_the_platform_has_no_device_sign_in(api, monkeypatch, capsys):
    # A platform still signing in with Cognito answers 404 for /api/auth/*.
    seen = {}
    monkeypatch.setattr(cli, "request_email_code", lambda e: seen.update(email=e) or "cognito-session")
    monkeypatch.setattr(cli, "login_with_email_code", lambda e, s, c: seen.update(session=s, code=c) or {"email": e})
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("asked for a password"))
    answers = iter(["Ada@Example.com", "12345678"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code, out, _ = run(capsys, "login")
    assert code == 0 and "email you a code" in out and "Signed in as ada@example.com." in out
    assert seen == {"email": "ada@example.com", "session": "cognito-session", "code": "12345678"}
    assert len(calls_to(api, "/api/auth/device/code")) == 1


def test_an_emailed_code_on_request_skips_the_browser(api, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "request_email_code", lambda e: seen.update(email=e) or "cognito-session")
    monkeypatch.setattr(cli, "login_with_email_code", lambda e, s, c: {"email": e})
    monkeypatch.setattr("builtins.input", lambda prompt="": "12345678")
    code, _, _ = run(capsys, "login", "--email", "Ada@Example.com")
    assert code == 0 and api.calls == [] and seen == {"email": "ada@example.com"}


def test_a_password_on_request_skips_the_browser(api, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli, "login", lambda e, p: seen.update(email=e, password=p) or {"email": e})
    monkeypatch.setattr(cli, "request_email_code", lambda e: pytest.fail("emailed a code"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "ada@example.com")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pw")
    code, _, _ = run(capsys, "login", "--password")
    assert code == 0 and api.calls == [] and seen == {"email": "ada@example.com", "password": "pw"}


def test_unreachable_platform_is_an_error_not_another_sign_in(monkeypatch, capsys):
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(cli, "request_email_code", lambda e: pytest.fail("emailed a code"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": pytest.fail("asked for a password"))
    code, _, err = run(capsys, "login")
    assert code == 1 and "Couldn't reach" in err


def device_session(expires_at: float, api_url: str | None = None) -> dict:
    """A stored device sign-in, issued by `api_url` (by default the platform the CLI talks to now)."""
    return {"provider": "better-auth", "email": "ada@example.com", "access_token": platform_jwt(expires_at),
            "id_token": "", "refresh_token": "session-token", "expires_at": expires_at,
            "api_url": api_url or config.api_url()}


def test_refreshes_an_expiring_jwt_from_the_session(api):
    save_credentials(device_session(time.time() + 10))
    fresh = platform_jwt(time.time() + 900)
    api.routes[("GET", "/api/auth/token")] = (200, {"token": fresh})
    creds = auth.current_credentials()
    assert creds["access_token"] == fresh and creds["refresh_token"] == "session-token"
    assert load_credentials()["access_token"] == fresh
    assert calls_to(api, "/api/auth/token")[0]["headers"]["Authorization"] == "Bearer session-token"


def test_an_ended_session_asks_for_a_new_login(api):
    save_credentials(device_session(0))
    api.routes[("GET", "/api/auth/token")] = (401, {})
    with pytest.raises(auth.AuthError, match="stationhouse login"):
        auth.current_credentials()


def test_a_disabled_account_is_told_so(api):
    save_credentials(device_session(0))
    api.routes[("GET", "/api/auth/token")] = (403, {"code": "ACCOUNT_DISABLED", "message": "This account is disabled."})
    with pytest.raises(auth.AuthError, match="This account is disabled."):
        auth.current_credentials()


def test_api_calls_carry_the_jwt_and_no_id_token(api, capsys):
    save_credentials(device_session(time.time() + 900))
    api.routes[("GET", "/api/v1/me")] = (200, {"hfUsername": "ada"})
    code, out, _ = run(capsys, "whoami")
    assert code == 0 and "ada@example.com" in out
    headers = calls_to(api, "/api/v1/me")[0]["headers"]
    assert headers["Authorization"] == f"Bearer {load_credentials()['access_token']}"
    assert "x-station-house-id-token" not in {k.lower() for k in headers}


def test_logout_ends_the_session_on_the_platform_too(api, capsys):
    save_credentials(device_session(time.time() + 900))
    api.routes[("POST", "/api/auth/sign-out")] = (200, {"success": True})
    assert "Signed out" in run(capsys, "logout")[1]
    assert calls_to(api, "/api/auth/sign-out")[0]["headers"]["Authorization"] == "Bearer session-token"
    assert load_credentials() is None


def test_logout_signs_out_locally_even_offline(monkeypatch, capsys):
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")
    save_credentials(device_session(time.time() + 900))
    assert "Signed out" in run(capsys, "logout")[1]
    assert load_credentials() is None


def test_logout_of_a_cognito_session_stays_local(api, signed_in, capsys):
    assert "Signed out" in run(capsys, "logout")[1]
    assert api.calls == []


def test_tells_the_platform_what_it_is_so_the_page_can_show_it(api, sleeps, capsys):
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api))
    api.routes[("POST", "/api/auth/device/token")] = (400, {"error": "access_denied"})
    code, _, _ = run(capsys, "login", "--no-browser")
    agent = calls_to(api, "/api/auth/device/code")[0]["headers"]["User-Agent"]
    assert code == 1
    assert re.fullmatch(r"stationhouse-cli/\S+ \(.+; Python \d+\.\d+\.\d+\)", agent)


# ---------------------------------------------------------------- the session stays with the platform that issued it

PROD = "https://app.station-house.net"


def test_a_session_from_another_platform_is_never_sent_to_this_one(api, capsys):
    # Signed in to prod, then STATIONHOUSE_API_URL points somewhere else (here the fake platform).
    save_credentials(device_session(time.time() + 10, api_url=PROD))
    with pytest.raises(auth.AuthError, match=r"signed in to https://app\.station-house\.net.*stationhouse login"):
        auth.current_credentials()
    code, _, err = run(capsys, "whoami")
    assert code == 1 and "stationhouse login" in err
    assert api.calls == []  # neither the session (refresh) nor its JWT (the API call) went there


def test_a_session_saved_without_its_platform_asks_for_a_new_login(api):
    creds = device_session(time.time() + 900)
    del creds["api_url"]
    save_credentials(creds)
    with pytest.raises(auth.AuthError, match="stationhouse login"):
        auth.current_credentials()
    assert api.calls == []


def test_logout_leaves_another_platforms_session_alone(api, capsys):
    save_credentials(device_session(time.time() + 900, api_url=PROD))
    code, out, err = run(capsys, "logout")
    assert code == 0 and "Signed out" in out and PROD in err and "wasn't ended" in err
    assert api.calls == [] and load_credentials() is None


@pytest.mark.parametrize("url", ["http://app.station-house.net", "http://192.168.1.20:8787"])
def test_plain_http_is_refused_except_on_localhost(url, monkeypatch, capsys, signed_in):
    monkeypatch.setenv("STATIONHOUSE_API_URL", url)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("sent a request over plain http"))
    code, _, err = run(capsys, "login", "--no-browser")
    assert code == 1 and "isn't https" in err
    code, _, err = run(capsys, "whoami")  # an API call with a stored token, too
    assert code == 1 and "isn't https" in err


def test_https_and_localhost_are_platforms_tokens_may_go_to():
    for url in ("https://app.station-house.net", "http://localhost:8788", "http://127.0.0.1:8788", "http://[::1]:8788"):
        assert auth.secure_platform_url(url) == url


# ---------------------------------------------------------------- polling survives a dropped connection

def flaky(monkeypatch, failures):
    """urlopen that raises each of `failures` in turn for /device/token, then answers normally."""
    real, left = urllib.request.urlopen, list(failures)

    def urlopen(req, *a, **k):
        if req.full_url.endswith("/api/auth/device/token") and left:
            raise left.pop(0)
        return real(req, *a, **k)
    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def test_keeps_polling_through_a_dropped_connection(api, sleeps, monkeypatch, capsys):
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api))
    api.routes[("POST", "/api/auth/device/token")] = [PENDING, (200, {"access_token": "session-token"})]
    api.routes[("GET", "/api/auth/token")] = (200, {"token": platform_jwt(time.time() + 900)})
    flaky(monkeypatch, [TimeoutError("timed out"), urllib.error.URLError("Network is unreachable")])
    code, out, err = run(capsys, "login")
    assert code == 0 and "Signed in as ada@example.com." in out and "Traceback" not in err
    # Waits double while the platform can't be reached, then go back to the interval.
    assert sleeps == [5, 10, 20, 5]
    assert len(calls_to(api, "/api/auth/device/token")) == 2


def test_gives_up_when_the_code_runs_out_while_the_connection_is_down(api, monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(auth.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    api.routes[("POST", "/api/auth/device/code")] = (200, device_code(api, expires_in=12))
    flaky(monkeypatch, [urllib.error.URLError("Network is unreachable")] * 10)
    code, _, err = run(capsys, "login")
    assert code == 1 and "ran out while the connection was down" in err and "stationhouse login" in err
    assert "Traceback" not in err and load_credentials() is None


def test_a_timeout_anywhere_is_a_message_not_a_traceback(monkeypatch, capsys):
    def times_out(args):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr(cli, "cmd_whoami", times_out)
    code, _, err = run(capsys, "whoami")
    assert code == 1 and "didn't answer in time" in err and "Traceback" not in err


def test_an_api_call_that_times_out_says_so(api, signed_in, monkeypatch, capsys):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out")))
    code, _, err = run(capsys, "whoami")
    assert code == 1 and "didn't answer in time" in err


# ---------------------------------------------------------------- smaller things

def test_a_platform_back_on_cognito_asks_for_a_new_login(api):
    save_credentials(device_session(0))
    api.routes[("GET", "/api/auth/token")] = (404, {})
    with pytest.raises(auth.AuthError) as e:
        auth.current_credentials()
    assert "stationhouse login" in str(e.value) and "404" not in str(e.value)


def opened_pages(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    return opened


def test_opens_the_sign_in_page_when_it_is_on_the_platform(api, monkeypatch, capsys):
    opened = opened_pages(monkeypatch)
    cli._show_device_code(device_code(api))
    assert opened == [f"{api.url}/device"] and "Careful" not in capsys.readouterr().err


@pytest.mark.parametrize("page", ["https://evil.example/device", "http://app.station-house.net/device",
                                  "https://app.station-house.net.evil.example/device"])
def test_never_opens_a_sign_in_page_elsewhere(page, monkeypatch, capsys):
    monkeypatch.setenv("STATIONHOUSE_API_URL", PROD)
    opened = opened_pages(monkeypatch)
    cli._show_device_code({**CODE, "verification_uri": page})
    err = capsys.readouterr().err
    assert opened == [] and "wasn't opened" in err and f"{PROD}/device" in err
