import base64
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def jwt(exp: float) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none'})}.{b64({'exp': exp})}.sig"


# The variables git sets for a hook (GIT_DIR, GIT_INDEX_FILE, ...). Run from one, as the platform's
# pre-push hook does, they'd point every `git -C <tmp_path>` in these tests at the enclosing repo:
# `git init` there turned it bare and `git config` gave it the test's identity.
GIT_LOCAL_ENV = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()


@pytest.fixture(autouse=True)
def no_enclosing_repo(monkeypatch):
    for name in GIT_LOCAL_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    # Signed out, reads now go out without a token (STA-335): a test that forgets the `api` fixture
    # must fail fast on a closed local port, never reach the real platform.
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")
    # Most tests work in one project; the tests of picking a project unset this.
    monkeypatch.setenv("STATIONHOUSE_PROJECT", "conspiracybench")
    # The once-an-hour version check would add a call to every test's fake server; its own tests
    # (test_version.py) turn it back on.
    monkeypatch.setenv("STATIONHOUSE_NO_VERSION_CHECK", "1")


@pytest.fixture
def signed_in():
    from stationhouse_cli.store import save_credentials
    creds = {"email": "laura@example.com", "access_token": jwt(time.time() + 3600), "id_token": "id.tok.en",
             "refresh_token": "refresh", "expires_at": time.time() + 3600}
    save_credentials(creds)
    return creds


class FakeApi:
    """Records requests and answers from `routes[(method, path)] = (status, body)`, or
    (status, body, headers), or from a list of them, one per request in turn (the last one repeats)."""

    def __init__(self):
        self.routes, self.calls = {}, []
        api = self

        class H(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                path = self.path.split("?")[0]
                api.calls.append({"method": self.command, "path": self.path, "body": body, "headers": dict(self.headers)})
                answer = api.routes.get((self.command, path), (404, {}))
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                status, out, headers = (*answer, {})[:3]
                data = json.dumps(out).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        # shutdown() waits for serve_forever's next poll: the default 0.5 s, paid by every test.
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setenv("STATIONHOUSE_API_URL", fake.url)
    yield fake
    fake.server.shutdown()


@pytest.fixture
def elsewhere():
    """Another server, not the platform: where a redirect might try to send the member's token."""
    fake = FakeApi()
    yield fake
    fake.server.shutdown()
