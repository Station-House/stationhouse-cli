import json
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, config
from . import auth
from .auth import NETWORK_ERRORS, current_credentials, secure_platform_url

# Seconds per call; the push gate lowers it so a slow platform can't stall a push.
TIMEOUT = 60


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        # The server's JSON error body, e.g. {"error", "projectId", "taskId"} for a task asked for
        # under the wrong project, so the caller can follow it.
        self.body = body or {}


class UpgradeRequired(ApiError):
    """The platform answered 426: this CLI is below the minimum it supports (CLI_MIN_VERSION), so
    nothing more should run. main() prints the message and exits 1; an ApiError handler that carries on
    (the chat, the MCP server's tools) shows it."""

    def __init__(self, body: dict | None = None):
        super().__init__(upgrade_message(), 426, body)


def upgrade_message() -> str:
    return f"This version ({__version__}) is no longer supported. Update: {config.UPGRADE_COMMAND}"


def request(method: str, path: str, body: dict | None = None, query: dict | None = None):
    """Call the Station House API as the signed-in member. The access token authorizes the call; for a
    Cognito sign-in, the ID token lets the platform read the member's verified email (the device
    sign-in's token carries it itself). Identity is never taken from the body."""
    creds = current_credentials()
    url = secure_platform_url(config.api_url()) + path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Authorization": f"Bearer {creds['access_token']}",
               "Content-Type": "application/json", "User-Agent": config.user_agent(),
               config.VERSION_HEADER: __version__}
    if creds["id_token"]:
        headers["x-station-house-id-token"] = creds["id_token"]
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers=headers)
    try:
        try:
            with auth.open_url(req, TIMEOUT) as r:  # a redirect to another server isn't followed
                return json.loads(r.read() or "null")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except ValueError:
                body = None
            body = body if isinstance(body, dict) else {}
            if e.code == 426:
                raise UpgradeRequired(body) from None
            raise ApiError(_message(e.code, body), e.code, body) from None
    except urllib.error.URLError as e:
        raise ApiError(f"Couldn't reach {config.api_url()}: {e.reason}") from None
    except TimeoutError:  # the answer didn't come in time (a connect timeout is a URLError, above)
        raise ApiError(f"{config.api_url()} didn't answer in time. Try again.") from None
    except NETWORK_ERRORS as e:  # cut short mid-answer, TLS failing mid-stream
        raise ApiError(f"Couldn't reach {config.api_url()}: {e or type(e).__name__}") from None


def _message(code: int, body: dict) -> str:
    text = body.get("error") or body.get("message")
    if isinstance(text, dict):
        text = text.get("message")
    if not isinstance(text, str):
        text = None
    if code == 401:
        return text or "Not signed in, or your session expired. Run `stationhouse login`."
    if code == 404 and not text:
        return "This Station House server doesn't support that yet."
    return text or f"The server answered {code}."
