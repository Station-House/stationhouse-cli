import base64
import http.client
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config
from .store import load_credentials, save_credentials

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REFRESH_MARGIN_SECONDS = 120

# The device sign-in (RFC 8628) against the platform's Better Auth: the CLI's client id there, and
# the grant it polls with.
DEVICE_CLIENT_ID = "stationhouse-cli"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
# What RFC 8628 says to add to the polling interval when the server answers slow_down.
SLOW_DOWN_SECONDS = 5
# Waiting out a dropped connection while polling: the wait doubles, up to this.
MAX_RETRY_SECONDS = 60
TIMEOUT = 30
# Plain http is only for a platform on this machine (local development).
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# A call that never got a whole answer, past what urllib wraps in URLError: a read that timed out, a
# connection dropped or cut short mid-answer, TLS failing mid-stream.
NETWORK_ERRORS = (TimeoutError, ConnectionError, http.client.HTTPException, ssl.SSLError)

# Which service a stored session came from. Credentials written before the device sign-in have no
# "provider" and are Cognito's.
COGNITO = "cognito"
BETTER_AUTH = "better-auth"


class AuthError(Exception):
    pass


class WrongCodeError(AuthError):
    """The emailed code didn't match, and the sign-in can be tried again."""


class PlatformUnreachable(AuthError):
    """The platform didn't answer (no network, a timeout, a dropped connection): worth another try."""


class RedirectRefused(AuthError):
    """The platform answered with a redirect to another server: the CLI doesn't follow it with the
    member's token."""


class DeviceLoginUnavailable(Exception):
    """The platform has no device sign-in (it still signs in with Cognito): use a Cognito sign-in."""


def secure_platform_url(url: str) -> str:
    """`url`, if tokens may be sent to it: https, or http on this machine. AuthError otherwise."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS):
        return url
    raise AuthError(f"{url} isn't https. Station House signs in only over https "
                    "(plain http only for localhost). Check STATIONHOUSE_API_URL.")


def _origin(url: str) -> tuple:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme.lower(), parts.hostname, parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's redirects copy every header, the Authorization with the member's token included, to
    wherever Location points. Only a redirect within the same scheme, host and port is followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != _origin(req.full_url):
            fp.close()
            to = urllib.parse.urlsplit(newurl)
            raise RedirectRefused(f"{config.api_url()} redirected to {to.scheme}://{to.netloc}, another server. "
                                  "The CLI doesn't send your sign-in there. Check STATIONHOUSE_API_URL.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameOriginRedirects)


def open_url(req: urllib.request.Request, timeout: float):
    """urlopen for every call that carries a token: a redirect to another server is RedirectRefused."""
    return _OPENER.open(req, timeout=timeout)


def is_platform_page(url: str) -> bool:
    """Whether `url` is a page on the platform the CLI signs in to, over https (or http on localhost):
    the only kind of sign-in link the CLI opens in a browser."""
    try:
        secure_platform_url(url)
    except AuthError:
        return False
    page, platform = urllib.parse.urlsplit(url), urllib.parse.urlsplit(config.api_url())
    return (page.scheme, page.netloc.lower()) == (platform.scheme, platform.netloc.lower())


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise AuthError("Enter the email address of your Station House account.")
    return email


def _claims(token: str) -> dict:
    """A JWT's payload, unverified: read only for its expiry and email. The platform verifies the token itself."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _expiry(access_token: str) -> float:
    """The access token's `exp`, read only to schedule a refresh."""
    try:
        return float(_claims(access_token)["exp"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def _credentials(email: str, tokens: dict, refresh_token: str) -> dict:
    return {"email": email, "access_token": tokens["access_token"], "id_token": tokens["id_token"],
            "refresh_token": refresh_token, "expires_at": _expiry(tokens["access_token"])}


def _better_auth_credentials(session_token: str, jwt: str, api_url: str, email: str | None = None) -> dict:
    """The same file as Cognito's, so older CLIs still read it: the platform's 15-minute JWT is the
    access token, and the session it was traded for (good for 30 days, renewed as it's used) stands in
    for the refresh token. There's no ID token: the JWT carries the verified email itself. `api_url` is
    the platform that issued the session, the only one it's ever sent to (_same_platform)."""
    return {"provider": BETTER_AUTH, "email": _claims(jwt).get("email") or email or "",
            "access_token": jwt, "id_token": "", "refresh_token": session_token, "expires_at": _expiry(jwt),
            "api_url": api_url}


def _same_platform(creds: dict) -> str:
    """The platform a device sign-in's session came from, if that's still the one the CLI talks to
    (STATIONHOUSE_API_URL). AuthError otherwise, so the session never goes to another host."""
    issued_by = creds.get("api_url")
    if issued_by != config.api_url():
        raise AuthError(f"You're signed in to {issued_by or 'another Station House'}, not {config.api_url()}. "
                        "Run `stationhouse login` to sign in there.")
    return issued_by


def _auth_call(method: str, path: str, body: dict | None = None, bearer: str | None = None) -> tuple[int, dict]:
    """One call to the platform's /api/auth: its status and JSON body ({} when it has none).
    PlatformUnreachable when it doesn't answer."""
    base = secure_platform_url(config.api_url())
    from . import __version__
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": config.user_agent(), config.VERSION_HEADER: __version__}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(base + "/api/auth" + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        try:
            with open_url(req, TIMEOUT) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
    except urllib.error.URLError as e:
        raise PlatformUnreachable(f"Couldn't reach {base}: {e.reason}") from None
    except NETWORK_ERRORS as e:
        raise PlatformUnreachable(f"Couldn't reach {base}: {e or type(e).__name__}") from None
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        out = {}
    out = out if isinstance(out, dict) else {}
    if status == 426:  # below the platform's minimum CLI version: sign-in is blocked too
        from .client import UpgradeRequired  # client imports this module
        raise UpgradeRequired(out)
    return status, out


def start_device_login() -> dict:
    """Asks the platform for a sign-in code: {device_code, user_code, verification_uri,
    verification_uri_complete, expires_in, interval}. DeviceLoginUnavailable when it has no device
    sign-in yet. Only verification_uri is shown: the member types the code there themselves (the page
    ignores a code in the link, against device-code phishing)."""
    status, out = _auth_call("POST", "/device/code", {"client_id": DEVICE_CLIENT_ID})
    if status == 404:
        raise DeviceLoginUnavailable()
    if status != 200 or not out.get("device_code") or not out.get("user_code"):
        raise AuthError(f"Couldn't start signing in: {out.get('error_description') or f'the server answered {status}'}.")
    return out


def wait_for_device_login(code: dict) -> str:
    """Polls until the member approves or denies the code in the browser, or it expires. Returns the
    session token the platform hands over on approval. A dropped connection doesn't end it: it tries
    again, waiting longer each time, until the code runs out."""
    sleep, clock = time.sleep, time.monotonic
    interval = max(int(code.get("interval") or 5), 1)
    deadline = clock() + int(code.get("expires_in") or 600)
    wait = interval
    while True:
        sleep(wait)
        try:
            status, out = _auth_call("POST", "/device/token", {
                "grant_type": DEVICE_GRANT_TYPE, "device_code": code["device_code"], "client_id": DEVICE_CLIENT_ID})
            if status >= 500 and not out.get("error"):  # a gateway or a restart (502, 503, 504), not an answer
                raise PlatformUnreachable(f"{config.api_url()} answered {status}")
        except PlatformUnreachable as e:
            if clock() >= deadline:
                raise AuthError(f"{e}. The code ran out while Station House couldn't be reached: "
                                "run `stationhouse login` again.") from None
            wait = min(wait * 2, MAX_RETRY_SECONDS)
            continue
        wait = interval
        if status == 200 and out.get("access_token"):
            return out["access_token"]
        error = out.get("error")
        if error == "authorization_pending" and clock() < deadline:
            continue
        if error == "slow_down" and clock() < deadline:
            interval += SLOW_DOWN_SECONDS
            wait = interval
            continue
        if error == "access_denied":
            raise AuthError("The sign-in was denied in the browser.")
        if error in ("expired_token", "authorization_pending", "slow_down"):
            raise AuthError("The code expired before it was approved. Run `stationhouse login` again.")
        raise AuthError(f"Couldn't sign in: {out.get('error_description') or error or f'the server answered {status}'}.")


def _better_auth_jwt(session_token: str) -> str:
    """Trades the session for a fresh 15-minute JWT, the token every API call carries."""
    status, out = _auth_call("GET", "/token", bearer=session_token)
    if status == 401:
        raise AuthError("Your session has expired. Run `stationhouse login`.")
    if status == 403:  # e.g. the account was disabled: the platform says why
        raise AuthError(out.get("message") or "Station House refused to sign you in.")
    if status == 404:  # the platform signs in with Cognito again (rolled back)
        raise AuthError("This Station House doesn't take this sign-in anymore. Run `stationhouse login`.")
    if status != 200 or not out.get("token"):
        raise AuthError(f"Couldn't refresh your session: the server answered {status}.")
    return out["token"]


def device_login(show_code) -> dict:
    """Signs in by device authorization and stores the result: `show_code(code)` tells the member
    where to approve it. DeviceLoginUnavailable when the platform can't do it yet."""
    platform = config.api_url()
    code = start_device_login()
    show_code(code)
    session_token = wait_for_device_login(code)
    creds = _better_auth_credentials(session_token, _better_auth_jwt(session_token), platform)
    save_credentials(creds)
    return creds


def sign_out(creds: dict | None) -> str | None:
    """Ends a device sign-in's session on the platform as well, so the stored token is dead even if the
    file survives somewhere. Best effort: signing out locally never waits on the network. Returns a
    note for the member when the session was left alone: it's only ever sent to the platform that
    issued it."""
    if not creds or creds.get("provider") != BETTER_AUTH:
        return None
    try:
        _same_platform(creds)
    except AuthError:
        return (f"Your session at {creds.get('api_url') or 'another Station House'} wasn't ended there, since "
                f"this command would talk to {config.api_url()}. It ends when it expires.")
    try:
        _auth_call("POST", "/sign-out", {}, bearer=creds["refresh_token"])
    except AuthError:
        pass
    return None


def login(email: str, password: str) -> dict:
    """Sign in to the Station House Cognito pool with SRP (the password is never sent) and store the
    result. For members who joined before the device sign-in, until Cognito is switched off."""
    email = normalize_email(email)
    from pycognito import Cognito
    from pycognito.exceptions import ForceChangePasswordException

    user = Cognito(config.USER_POOL_ID, config.CLIENT_ID, user_pool_region=config.REGION, username=email)
    try:
        user.authenticate(password=password)
    except ForceChangePasswordException:
        raise AuthError("This account must set a new password first. Sign in on the Station House website.") from None
    except Exception as e:  # botocore ClientError: wrong password, unconfirmed account, unknown user
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("NotAuthorizedException", "UserNotFoundException"):
            raise AuthError("Wrong email or password. Accounts don't always have a password: "
                            "`stationhouse login` emails you a code instead.") from None
        if code == "UserNotConfirmedException":
            raise AuthError("This account's email isn't confirmed yet. Confirm it on the Station House website.") from None
        raise AuthError(f"Couldn't sign in: {code or type(e).__name__}") from None
    creds = _credentials(email, {"access_token": user.access_token, "id_token": user.id_token}, user.refresh_token)
    save_credentials(creds)
    return creds


def _cognito_post(target: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"https://cognito-idp.{config.REGION}.amazonaws.com/", method="POST", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": f"AWSCognitoIdentityProviderService.{target}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _sign_in_post(target: str, body: dict) -> dict:
    """_cognito_post for the email-code steps: failures come back as AuthError, named by Cognito's error code."""
    try:
        return _cognito_post(target, {"ClientId": config.CLIENT_ID, **body})
    except urllib.error.HTTPError as e:
        try:
            code = str(json.loads(e.read()).get("__type", "")).split("#")[-1]
        except ValueError:
            code = ""
        if code == "CodeMismatchException":
            raise WrongCodeError("That code isn't right.") from None
        if code in ("NotAuthorizedException", "ExpiredCodeException"):
            raise AuthError("That code has expired or the sign-in has timed out. "
                            "Run `stationhouse login` for a new one.") from None
        if code == "UserNotConfirmedException":
            raise AuthError("This account's email isn't confirmed yet. Confirm it on the Station House website.") from None
        if code in ("LimitExceededException", "TooManyRequestsException"):
            raise AuthError("Too many sign-in attempts. Wait a few minutes and try again.") from None
        raise AuthError(f"Couldn't sign in: {code or e.code}") from None
    except (urllib.error.URLError, ValueError) as e:
        raise AuthError(f"Couldn't reach the sign-in service: {e!r}") from None


def request_email_code(email: str) -> str:
    """Email a sign-in code to an existing Cognito account, as the website did before Better Auth. Returns the
    session that confirms it. For members who joined before the device sign-in, until Cognito is switched off."""
    email = normalize_email(email)
    out = _sign_in_post("InitiateAuth", {
        "AuthFlow": "USER_AUTH", "AuthParameters": {"USERNAME": email, "PREFERRED_CHALLENGE": "EMAIL_OTP"}})
    # Cognito offers the factors instead when it won't pick the preferred one.
    if out.get("ChallengeName") == "SELECT_CHALLENGE" and "EMAIL_OTP" in out.get("AvailableChallenges", []):
        out = _sign_in_post("RespondToAuthChallenge", {
            "ChallengeName": "SELECT_CHALLENGE", "Session": out["Session"],
            "ChallengeResponses": {"USERNAME": email, "ANSWER": "EMAIL_OTP"}})
    if out.get("ChallengeName") != "EMAIL_OTP":
        # Also what Cognito answers for an email with no account, without saying so.
        raise AuthError(f"Couldn't send a sign-in code to {email}. If you joined recently, run `stationhouse login` "
                        "on its own and approve it in your browser. If you haven't joined yet, join at "
                        f"{config.DEFAULT_API_URL}/login. If your account has a password, try "
                        "`stationhouse login --password`.")
    return out["Session"]


def login_with_email_code(email: str, session: str, code: str) -> dict:
    """Finish request_email_code's sign-in with the code from the email, and store the result."""
    email = normalize_email(email)
    code = "".join((code or "").split())
    if not code:
        raise WrongCodeError("Enter the code from the email.")
    out = _sign_in_post("RespondToAuthChallenge", {
        "ChallengeName": "EMAIL_OTP", "Session": session,
        "ChallengeResponses": {"USERNAME": email, "EMAIL_OTP_CODE": code}}).get("AuthenticationResult") or {}
    if not out.get("AccessToken"):
        raise AuthError("Sign-in didn't finish. Run `stationhouse login` again.")
    creds = _credentials(email, {"access_token": out["AccessToken"], "id_token": out["IdToken"]}, out["RefreshToken"])
    save_credentials(creds)
    return creds


def refresh(creds: dict) -> dict:
    if creds.get("provider") == BETTER_AUTH:
        platform = _same_platform(creds)
        new = _better_auth_credentials(creds["refresh_token"], _better_auth_jwt(creds["refresh_token"]), platform,
                                       creds["email"])
        save_credentials(new)
        return new
    try:
        out = _cognito_post("InitiateAuth", {
            "AuthFlow": "REFRESH_TOKEN_AUTH", "ClientId": config.CLIENT_ID,
            "AuthParameters": {"REFRESH_TOKEN": creds["refresh_token"]}})["AuthenticationResult"]
    except urllib.error.HTTPError:
        raise AuthError("Your session has expired. Run `stationhouse login`.") from None
    except (urllib.error.URLError, KeyError, ValueError) as e:
        raise AuthError(f"Couldn't refresh your session: {e!r}") from None
    tokens = {"access_token": out["AccessToken"], "id_token": out["IdToken"]}
    new = _credentials(creds["email"], tokens, out.get("RefreshToken", creds["refresh_token"]))
    save_credentials(new)
    return new


def current_credentials() -> dict:
    """The stored credentials with a fresh access token, or AuthError telling the user to log in."""
    creds = load_credentials()
    if creds is None:
        raise AuthError("You aren't signed in. Run `stationhouse login`.")
    if creds.get("provider") == BETTER_AUTH:
        _same_platform(creds)  # its JWT goes only to the platform that issued it, like the session
    if creds["expires_at"] - time.time() < REFRESH_MARGIN_SECONDS:
        creds = refresh(creds)
    return creds
