import base64
import json
import re
import time
import urllib.error
import urllib.request

from . import __version__, config
from .store import load_credentials, save_credentials

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REFRESH_MARGIN_SECONDS = 120

# The device sign-in (RFC 8628) against the platform's Better Auth: the CLI's client id there, and
# the grant it polls with.
DEVICE_CLIENT_ID = "stationhouse-cli"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
# What RFC 8628 says to add to the polling interval when the server answers slow_down.
SLOW_DOWN_SECONDS = 5
TIMEOUT = 30

# Which service a stored session came from. Credentials written before the device sign-in have no
# "provider" and are Cognito's.
COGNITO = "cognito"
BETTER_AUTH = "better-auth"


class AuthError(Exception):
    pass


class DeviceLoginUnavailable(Exception):
    """The platform has no device sign-in (it still signs in with Cognito): use the password sign-in."""


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


def _better_auth_credentials(session_token: str, jwt: str, email: str | None = None) -> dict:
    """The same file as Cognito's, so older CLIs still read it: the platform's 15-minute JWT is the
    access token, and the session it was traded for (good for 30 days, renewed as it's used) stands in
    for the refresh token. There's no ID token: the JWT carries the verified email itself."""
    return {"provider": BETTER_AUTH, "email": _claims(jwt).get("email") or email or "",
            "access_token": jwt, "id_token": "", "refresh_token": session_token, "expires_at": _expiry(jwt)}


def _auth_call(method: str, path: str, body: dict | None = None, bearer: str | None = None) -> tuple[int, dict]:
    """One call to the platform's /api/auth: its status and JSON body ({} when it has none)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "User-Agent": f"stationhouse-cli/{__version__}"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(config.api_url() + "/api/auth" + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except urllib.error.URLError as e:
        raise AuthError(f"Couldn't reach {config.api_url()}: {e.reason}") from None
    try:
        out = json.loads(raw or b"{}")
    except ValueError:
        out = {}
    return status, out if isinstance(out, dict) else {}


def start_device_login() -> dict:
    """Asks the platform for a sign-in code: {device_code, user_code, verification_uri,
    verification_uri_complete, expires_in, interval}. DeviceLoginUnavailable when it has no device
    sign-in yet."""
    status, out = _auth_call("POST", "/device/code", {"client_id": DEVICE_CLIENT_ID})
    if status == 404:
        raise DeviceLoginUnavailable()
    if status != 200 or not out.get("device_code") or not out.get("user_code"):
        raise AuthError(f"Couldn't start signing in: {out.get('error_description') or f'the server answered {status}'}.")
    return out


def wait_for_device_login(code: dict) -> str:
    """Polls until the member approves or denies the code in the browser, or it expires. Returns the
    session token the platform hands over on approval."""
    sleep, clock = time.sleep, time.monotonic
    interval = max(int(code.get("interval") or 5), 1)
    deadline = clock() + int(code.get("expires_in") or 600)
    while True:
        sleep(interval)
        status, out = _auth_call("POST", "/device/token", {
            "grant_type": DEVICE_GRANT_TYPE, "device_code": code["device_code"], "client_id": DEVICE_CLIENT_ID})
        if status == 200 and out.get("access_token"):
            return out["access_token"]
        error = out.get("error")
        if error == "authorization_pending" and clock() < deadline:
            continue
        if error == "slow_down" and clock() < deadline:
            interval += SLOW_DOWN_SECONDS
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
    if status != 200 or not out.get("token"):
        raise AuthError(f"Couldn't refresh your session: the server answered {status}.")
    return out["token"]


def device_login(show_code) -> dict:
    """Signs in by device authorization and stores the result: `show_code(code)` tells the member
    where to approve it. DeviceLoginUnavailable when the platform can't do it yet."""
    code = start_device_login()
    show_code(code)
    session_token = wait_for_device_login(code)
    creds = _better_auth_credentials(session_token, _better_auth_jwt(session_token))
    save_credentials(creds)
    return creds


def sign_out(creds: dict | None) -> None:
    """Ends a device sign-in's session on the platform as well, so the stored token is dead even if the
    file survives somewhere. Best effort: signing out locally never waits on the network."""
    if not creds or creds.get("provider") != BETTER_AUTH:
        return
    try:
        _auth_call("POST", "/sign-out", {}, bearer=creds["refresh_token"])
    except AuthError:
        pass


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
            raise AuthError("Wrong email or password.") from None
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


def refresh(creds: dict) -> dict:
    if creds.get("provider") == BETTER_AUTH:
        new = _better_auth_credentials(creds["refresh_token"], _better_auth_jwt(creds["refresh_token"]), creds["email"])
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
    if creds["expires_at"] - time.time() < REFRESH_MARGIN_SECONDS:
        creds = refresh(creds)
    return creds
