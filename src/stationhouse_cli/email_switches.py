"""`stationhouse email` (STA-286): the three email switches of Preferences, in the same words.

  stationhouse email                                          what you get, and where it goes
  stationhouse email set <digest|activity|announcements> <on|off>

Setting a switch to what it already is changes nothing and says so. Stopping all email from one
project is `stationhouse unfollow <project>` (Join & Follow), not a switch here.

The platform's routes (a write answers like GET, with `changed`):
  GET   /api/v1/me/email   {digest, activity, announcements, address, timeZone, sending, projects: {joined, followed}}
  PATCH /api/v1/me/email   {<kind>: true | false}
"""
from .client import ApiError, request

PATH = "/api/v1/me/email"

KINDS = ("digest", "activity", "announcements")

NAMES = {"digest": "Daily digest", "activity": "Project activity", "announcements": "Announcements"}

# The columns of the frame: two spaces, the name, on/off, then what it covers.
NAME_WIDTH = 18
STATE_WIDTH = 6


class NotAKind(ApiError):
    """A kind or value that isn't one: said in the frame's words, without the usual "error:"."""


def fetch() -> dict:
    """{digest, activity, announcements, address, timeZone, sending, projects}: your switches now."""
    try:
        return request("GET", PATH) or {}
    except ApiError as e:
        raise _older_server(e) from None


def set_kind(kind: str, value: str) -> dict:
    """Switches one kind on or off; the platform's answer, with `changed`."""
    if kind not in KINDS:
        raise NotAKind(f'No kind of email called "{kind}". Use digest, activity or announcements.')
    if value not in ("on", "off"):
        raise NotAKind(f'Use on or off, not "{value}": stationhouse email set {kind} on|off')
    try:
        return request("PATCH", PATH, {kind: value == "on"}) or {}
    except ApiError as e:
        raise _older_server(e) from None


def summary(data: dict, changed: bool | None = None) -> dict:
    """The --json answer: { digest, activity, announcements, timeZone, sending } (and `changed` after a set)."""
    out = {kind: bool(data.get(kind)) for kind in KINDS}
    out.update(timeZone=data.get("timeZone"), sending=bool(data.get("sending")))
    if changed is not None:
        out["changed"] = changed
    return out


def _projects(count: int, what: str) -> str:
    return f"{count} project{'' if count == 1 else 's'} {what}"


def covers(kind: str, data: dict) -> str:
    """What each switch covers, as one line."""
    projects = data.get("projects") or {}
    if kind == "digest":
        joined = _projects(projects.get("joined", 0), "you've joined")
        return f"9am {data.get('timeZone') or 'UTC'} · new tasks and reminders from {joined}"
    if kind == "activity":
        return f"updates and Inbox news from the {_projects(projects.get('followed', 0), 'you follow')}"
    return "community news from the Stationhouse team"


def render(data: dict, out=print) -> None:
    address = data.get("address")
    out(f"Email for {address}" if address else "Email (no verified address yet)")
    if not data.get("sending"):
        out("  Stationhouse isn't sending these emails yet. Your choices are saved and apply from the first one.")
    for kind in KINDS:
        state = "on" if data.get(kind) else "off"
        out(f"  {NAMES[kind]:<{NAME_WIDTH}}{state:<{STATE_WIDTH}}{covers(kind, data)}")
    out("  Stop all email from one project: stationhouse unfollow <project>")
    out("  Change one: stationhouse email set digest|activity|announcements on|off")


def render_set(kind: str, data: dict, out=print) -> None:
    on = bool(data.get(kind))
    name = NAMES[kind]
    if not data.get("changed"):
        out(f"{name} was already {'on' if on else 'off'}. Nothing changed.")
        return
    address = data.get("address") or "your address"
    undo = f"stationhouse email set {kind} {'off' if on else 'on'}"
    if kind == "digest" and on:
        out(f"Daily digest on. New tasks and reminders reach {address} at 9am {data.get('timeZone') or 'UTC'}.")
    elif kind == "digest":
        out("Daily digest off. New tasks and reminders stay on Stationhouse; none of it is emailed.")
        out(f"  Undo: {undo}")
    elif kind == "activity" and on:
        out(f"Project activity on. Updates and Inbox news from the projects you follow reach {address}.")
    elif kind == "activity":
        out("Project activity off. Updates and Inbox news stay in your Inbox; none of it is emailed.")
        out(f"  Mentions aren't emailed either. Undo: {undo}")
    elif on:
        out(f"Announcements on. Community news reaches {address}.")
    else:
        out("Announcements off. Community news won't reach you by email.")
        out(f"  Undo: {undo}")


def _older_server(e: ApiError) -> ApiError:
    if e.status == 404 and not e.body.get("error"):
        return ApiError("This Station House server doesn't have `email` yet.", 404)
    return e
