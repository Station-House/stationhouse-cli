import json
import os
import tempfile

from .config import DEFAULT_API_URL, OLD_DEFAULT_API_URL, api_url, config_dir, credentials_path, settings_path


def save_credentials(creds: dict) -> None:
    """Write the credentials file readable by this user only (0600, in a 0700 directory)."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".credentials-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(creds, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, credentials_path())
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_credentials() -> dict | None:
    try:
        creds = json.loads(credentials_path().read_text())
    except (FileNotFoundError, ValueError):
        return None
    required = ("email", "access_token", "id_token", "refresh_token", "expires_at")
    if not (isinstance(creds, dict) and all(k in creds for k in required)):
        return None
    return _moved(creds)


def _moved(creds: dict) -> dict:
    """A session the old default host issued, as stationhouse.ai's (STA-157): the same platform at its
    new address, so the member stays signed in across the update. Only when the CLI talks to the new
    default; with STATIONHOUSE_API_URL set to anything else the session stays where it was issued
    (auth._same_platform). Saved once, so the file says where it goes; if it can't be written, it's
    carried over again on the next run."""
    if creds.get("api_url") != OLD_DEFAULT_API_URL or api_url() != DEFAULT_API_URL:
        return creds
    creds = {**creds, "api_url": DEFAULT_API_URL}
    try:
        save_credentials(creds)
    except OSError:
        pass
    return creds


def load_settings() -> dict:
    try:
        settings = json.loads(settings_path().read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings: dict) -> None:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(settings, f)
        os.replace(tmp, settings_path())
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def clear_credentials() -> bool:
    try:
        credentials_path().unlink()
        return True
    except FileNotFoundError:
        return False
