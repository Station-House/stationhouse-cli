import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, config
from . import auth
from .auth import NETWORK_ERRORS, current_credentials, secure_platform_url
from .store import load_credentials

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


class SignInRequired(ApiError):
    """A call the platform answered 401 to someone who isn't signed in: an action, or a member-only
    read. Reads of public projects work without signing in (STA-335); this is everything else."""


class NotFound(ApiError):
    """A project or task id the platform doesn't know, or one the caller may not see: it answers both
    alike, so the CLI does too ("Not found: <id>")."""


# The /api/v1 reads that answer without a token (STA-335; docs/contributor-api.md, "Auth"). Signed
# out, only a GET to one of these goes out; everything else stops here, as it did before visitors
# could read anything.
_SEG = r"[^/?]+"
VISITOR_READS = re.compile(
    r"^/api/v1/(?:"
    rf"projects(?:/{_SEG}(?:/(?:tasks(?:/{_SEG}(?:/(?:context|people))?)?|unclaimed|prs"
    rf"|neurons/claims|neurons/{_SEG}/claim))?)?"
    rf"|tasks(?:/unclaimed|/{_SEG}/(?:context|people))?"
    r"|prs"
    r")/?$"
)


def visitor_may(method: str, path: str) -> bool:
    """True for a read anyone may make signed out: a GET to one of VISITOR_READS."""
    return method == "GET" and VISITOR_READS.match(path) is not None


def signed_in() -> bool:
    """True when credentials are stored (they may still need a refresh)."""
    return load_credentials() is not None


def request(method: str, path: str, body: dict | None = None, query: dict | None = None, member_only: bool = False):
    """Call the Station House API as the signed-in member. The access token authorizes the call; for a
    Cognito sign-in, the ID token lets the platform read the member's verified email (the device
    sign-in's token carries it itself). Identity is never taken from the body.

    Signed out, only a read visitors may make goes out, without a token (STA-335); a 401 to it is
    SignInRequired. Any other call stops here with SignInRequired (an action: the command line turns
    it into "Sign in to …"; the design gate and the wizard fail locally, as before), and a
    `member_only` call (the assistant) with AuthError, as before."""
    if member_only or signed_in():
        creds = current_credentials()
    elif visitor_may(method, path):
        creds = None
    else:
        raise SignInRequired("You aren't signed in. Run `stationhouse login`.", 401, {})
    url = secure_platform_url(config.api_url()) + path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Content-Type": "application/json", "User-Agent": config.user_agent(),
               config.VERSION_HEADER: __version__}
    if creds:
        headers["Authorization"] = f"Bearer {creds['access_token']}"
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
            if e.code == 401 and creds is None:
                raise SignInRequired(_message(e.code, body), e.code, body) from None
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
