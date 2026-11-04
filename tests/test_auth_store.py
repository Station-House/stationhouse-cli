import io
import json
import stat
import time
import urllib.error

import pytest

from stationhouse_cli import auth, config
from stationhouse_cli.store import clear_credentials, load_credentials, save_credentials
from conftest import jwt


def test_credentials_file_is_private():
    save_credentials({"email": "a@b.co", "access_token": "x", "id_token": "y", "refresh_token": "z", "expires_at": 1})
    assert stat.S_IMODE(config.credentials_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(config.config_dir().stat().st_mode) == 0o700


def test_incomplete_or_corrupt_credentials_read_as_signed_out():
    assert load_credentials() is None
    config.config_dir().mkdir(parents=True)
    config.credentials_path().write_text("not json")
    assert load_credentials() is None
    config.credentials_path().write_text(json.dumps({"email": "a@b.co"}))
    assert load_credentials() is None


def test_clear_credentials():
    save_credentials({"email": "a@b.co", "access_token": "x", "id_token": "y", "refresh_token": "z", "expires_at": 1})
    assert clear_credentials() is True
    assert clear_credentials() is False


@pytest.mark.parametrize("bad", ["", "nobody", "a@b", "a b@c.co", None])
def test_normalize_email_rejects_non_emails(bad):
    with pytest.raises(auth.AuthError):
        auth.normalize_email(bad)


def test_normalize_email_lowercases_and_trims():
    assert auth.normalize_email("  Laura@Example.COM ") == "laura@example.com"


def _cognito_failure(code):
    return urllib.error.HTTPError("https://cognito", 400, "Bad Request", {},
                                  io.BytesIO(json.dumps({"__type": code, "message": "no"}).encode()))


def test_email_code_sign_in_asks_for_email_otp_and_stores_the_tokens(monkeypatch):
    calls = []
    answers = iter([
        {"ChallengeName": "EMAIL_OTP", "Session": "s1"},
        {"AuthenticationResult": {"AccessToken": jwt(12345), "IdToken": "id", "RefreshToken": "ref"}},
    ])
    monkeypatch.setattr(auth, "_cognito_post", lambda target, body: calls.append((target, body)) or next(answers))

    session = auth.request_email_code("Laura@Example.com")
    creds = auth.login_with_email_code("Laura@Example.com", session, " 1234 5678\n")

    assert calls[0] == ("InitiateAuth", {
        "ClientId": config.CLIENT_ID, "AuthFlow": "USER_AUTH",
        "AuthParameters": {"USERNAME": "laura@example.com", "PREFERRED_CHALLENGE": "EMAIL_OTP"}})
    assert calls[1] == ("RespondToAuthChallenge", {
        "ClientId": config.CLIENT_ID, "ChallengeName": "EMAIL_OTP", "Session": "s1",
        "ChallengeResponses": {"USERNAME": "laura@example.com", "EMAIL_OTP_CODE": "12345678"}})
    assert creds["expires_at"] == 12345 and load_credentials() == creds


def test_email_code_is_chosen_when_cognito_offers_the_factors(monkeypatch):
    calls = []
    answers = iter([
        {"ChallengeName": "SELECT_CHALLENGE", "Session": "s1", "AvailableChallenges": ["PASSWORD_SRP", "EMAIL_OTP"]},
        {"ChallengeName": "EMAIL_OTP", "Session": "s2"},
    ])
    monkeypatch.setattr(auth, "_cognito_post", lambda target, body: calls.append(body) or next(answers))
    assert auth.request_email_code("a@b.co") == "s2"
    assert calls[1]["ChallengeResponses"] == {"USERNAME": "a@b.co", "ANSWER": "EMAIL_OTP"}


def test_email_with_no_code_factor_is_pointed_at_joining_and_password(monkeypatch):
    # Cognito's real answer for an email with no account (checked against the live pool).
    monkeypatch.setattr(auth, "_cognito_post", lambda target, body: {
        "ChallengeName": "SELECT_CHALLENGE", "Session": "s1", "AvailableChallenges": ["PASSWORD_SRP", "PASSWORD"]})
    with pytest.raises(auth.AuthError, match="join at .*--password"):
        auth.request_email_code("a@b.co")


@pytest.mark.parametrize("code,error,message", [
    ("CodeMismatchException", auth.WrongCodeError, "isn't right"),
    ("ExpiredCodeException", auth.AuthError, "for a new one"),
    ("NotAuthorizedException", auth.AuthError, "for a new one"),
    ("UserNotConfirmedException", auth.AuthError, "isn't confirmed"),
    ("LimitExceededException", auth.AuthError, "Too many"),
    ("InternalErrorException", auth.AuthError, "InternalErrorException"),
])
def test_cognito_errors_on_the_code_become_plain_messages(monkeypatch, code, error, message):
    def fail(target, body):
        raise _cognito_failure(code)
    monkeypatch.setattr(auth, "_cognito_post", fail)
    with pytest.raises(error, match=message):
        auth.login_with_email_code("a@b.co", "s1", "12345678")
    assert load_credentials() is None


def test_empty_code_is_a_retry_and_never_calls_cognito(monkeypatch):
    monkeypatch.setattr(auth, "_cognito_post", lambda target, body: pytest.fail("called Cognito"))
    with pytest.raises(auth.WrongCodeError):
        auth.login_with_email_code("a@b.co", "s1", "  ")


def test_expiry_read_from_token_and_garbage_is_expired():
    assert auth._expiry(jwt(12345)) == 12345
    assert auth._expiry("garbage") == 0.0


def test_not_signed_in_tells_the_user_to_log_in():
    with pytest.raises(auth.AuthError, match="stationhouse login"):
        auth.current_credentials()


def test_fresh_token_is_not_refreshed(signed_in, monkeypatch):
    monkeypatch.setattr(auth, "_cognito_post", lambda *a: pytest.fail("refreshed a fresh token"))
    assert auth.current_credentials()["access_token"] == signed_in["access_token"]


def test_expiring_token_is_refreshed_and_stored(signed_in, monkeypatch):
    save_credentials({**signed_in, "expires_at": time.time() + 10})
    new = jwt(time.time() + 3600)
    seen = {}

    def post(target, body):  # the shape Cognito's InitiateAuth really returns (no RefreshToken on refresh)
        seen.update(target=target, body=body)
        return {"AuthenticationResult": {"AccessToken": new, "IdToken": "new-id", "ExpiresIn": 3600}}
    monkeypatch.setattr(auth, "_cognito_post", post)
    creds = auth.current_credentials()
    assert creds["access_token"] == new and creds["refresh_token"] == "refresh"
    assert load_credentials()["id_token"] == "new-id"
    assert seen["body"]["AuthFlow"] == "REFRESH_TOKEN_AUTH" and seen["body"]["AuthParameters"] == {"REFRESH_TOKEN": "refresh"}


def test_rejected_refresh_asks_for_a_new_login(signed_in, monkeypatch):
    save_credentials({**signed_in, "expires_at": 0})

    def boom(*a):
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)
    monkeypatch.setattr(auth, "_cognito_post", boom)
    with pytest.raises(auth.AuthError, match="expired"):
        auth.current_credentials()
