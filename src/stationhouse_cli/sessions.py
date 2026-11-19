"""`stationhouse sessions` (STA-212): where you're signed in with the CLI, and ending one.

  stationhouse sessions                   your CLI sessions, newest first
  stationhouse sessions revoke <id>       end one (a lost laptop, an approval you didn't mean)

Each `stationhouse login` opens a CLI session that lasts 30 days at most: using it doesn't extend it.
Browser sessions aren't listed; "Sign out everywhere else" on your profile ends those.

The platform's routes:
  GET    /api/v1/me/sessions          {sessions: [{id, createdAt, lastUsedAt, expiresAt, userAgent, ipAddress}]}
  DELETE /api/v1/me/sessions/<id>     {revoked: id}; 404 when it isn't one of yours
"""
import urllib.parse

from .client import request

PATH = "/api/v1/me/sessions"


def fetch() -> list[dict]:
    """Your CLI sessions that haven't ended, newest first. An older platform answers 404 ("doesn't
    support that yet")."""
    return (request("GET", PATH) or {}).get("sessions") or []


def revoke(session_id: str) -> dict:
    """Ends one of your CLI sessions; the platform's answer, {revoked: id}. An id that isn't one of
    yours is a 404 whose message says so."""
    return request("DELETE", f"{PATH}/{urllib.parse.quote(session_id, safe='')}") or {}


def _day(iso: str | None) -> str:
    return (iso or "")[:10] or "?"


def _program(user_agent: str | None) -> str:
    """"stationhouse-cli/0.4.0 (macOS-15.1-arm64; Python 3.12.7)" reads as "stationhouse-cli 0.4.0 · macOS-15.1-arm64"."""
    if not user_agent:
        return "an unknown program"
    name, _, rest = user_agent.partition(" (")
    program = name.replace("/", " ", 1)
    system = rest.split(";")[0].rstrip(")") if rest else ""
    return f"{program} · {system}" if system else program


def render(sessions: list[dict], out=print) -> None:
    if not sessions:
        out("No CLI sessions. `stationhouse login` opens one.")
        return
    out(f"{len(sessions)} CLI session{'' if len(sessions) == 1 else 's'}, newest first:")
    for s in sessions:
        where = f" from {s['ipAddress']}" if s.get("ipAddress") else ""
        out(f"  {s['id']}  {_program(s.get('userAgent'))}")
        out(f"      signed in {_day(s.get('createdAt'))}{where} · last used {_day(s.get('lastUsedAt'))} · ends {_day(s.get('expiresAt'))}")
    out("  End one: stationhouse sessions revoke <id>")


def render_revoked(data: dict, out=print) -> None:
    out(f"Ended CLI session {data.get('revoked')}. An API token it already had stops working within 15 minutes.")
