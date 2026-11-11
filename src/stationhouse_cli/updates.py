"""Project updates (STA-287): a project's leads post short Markdown updates, each with an optional status;
its followers get each one by email and in their Inbox, by their settings. Leads post, edit and delete;
anyone who can see the project reads them.

  POST   /api/v1/projects/<project>/updates  {text, status?}
  GET    /api/v1/projects/<project>/updates  -> {updates, canPost, nextStatus}
  GET    /api/v1/updates/<id>
  PATCH  /api/v1/updates/<id>                {text?, status?, baseVersion?}
  DELETE /api/v1/updates/<id>

An update has no title field: its first line is its title.
"""
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
from datetime import datetime

from . import config
from .client import ApiError, request

# The CLI's words for a status, and the API's. "none" is no status.
STATUSES = {"none": None, "on-track": "on_track", "at-risk": "at_risk", "off-track": "off_track"}
LABELS = {"on_track": "On track", "at_risk": "At risk", "off_track": "Off track"}


def _q(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def status_arg(word: str | None):
    """The API's status for the CLI's word; a ValueError names the choices."""
    key = (word or "").strip().lower().replace("_", "-").replace(" ", "-")
    if key not in STATUSES:
        raise ValueError(f"The status is one of {', '.join(STATUSES)}.")
    return STATUSES[key]


def status_word(status) -> str:
    return next(word for word, value in STATUSES.items() if value == status)


def date(iso: str) -> str:
    """"Nov 8", from an ISO time."""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return iso or ""
    return f"{d.strftime('%b')} {d.day}"


def page_url(update: dict) -> str:
    href = update.get("href") or ""
    return config.api_url().rstrip("/") + href if href.startswith("/") else href


# --- writing the text ---------------------------------------------------------------------------

def editor_text(initial: str = "") -> str:
    """Opens $VISUAL / $EDITOR (else vi) on a Markdown file holding `initial`; answers what was saved."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    fd, path = tempfile.mkstemp(prefix="stationhouse-update-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(initial)
        try:
            code = subprocess.call([*shlex.split(editor), path])
        except OSError as e:
            raise ApiError(f"Couldn't open your editor ({editor}): {e}. Set $EDITOR, or pass --file.") from None
        if code != 0:
            raise ApiError(f"Your editor ({editor}) exited with {code}; nothing was saved.")
        with open(path, encoding="utf-8") as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def read_text(file: str | None, initial: str = "", stdin=None) -> tuple[str, bool]:
    """The update's text: from --file (`-` is stdin), else your editor. Answers (text, from_editor)."""
    if file == "-":
        return (stdin or sys.stdin).read(), False
    if file:
        try:
            with open(file, encoding="utf-8") as f:
                return f.read(), False
        except OSError as e:
            raise ApiError(f"Couldn't read {file}: {e.strerror or e}.") from None
    return editor_text(initial), True


# --- calls ----------------------------------------------------------------------------------------

def listing(project: str) -> dict:
    return request("GET", f"/api/v1/projects/{_q(project)}/updates") or {}


def post(project: str, text: str, status=...) -> dict:
    """Posts it; without a status, the server starts it where the website's composer does."""
    body = {"text": text} if status is ... else {"text": text, "status": status}
    return request("POST", f"/api/v1/projects/{_q(project)}/updates", body)["update"]


def show(update_id: str) -> dict:
    return request("GET", f"/api/v1/updates/{_q(update_id)}")["update"]


def edit(update_id: str, body: dict) -> dict:
    return request("PATCH", f"/api/v1/updates/{_q(update_id)}", body)["update"]


def delete(update_id: str) -> None:
    request("DELETE", f"/api/v1/updates/{_q(update_id)}")


# --- showing --------------------------------------------------------------------------------------

def health(update: dict) -> str:
    """"● On track", or "" for no status."""
    return f"● {LABELS[update['status']]}" if update.get("status") in LABELS else ""


def byline(update: dict) -> str:
    parts = [health(update), f"{update.get('authorName') or 'A lead'}, lead", date(update.get("postedAt", ""))]
    n = update.get("comments", 0)
    parts.append(f"{n} comment{'s' if n != 1 else ''}")
    if update.get("editedAt"):
        parts.append("edited")
    return " · ".join(p for p in parts if p)


def body_after_title(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines[1:]).strip("\n")


def render_update(update: dict, out=print) -> None:
    """One update in full: title, status and byline, its text, then how to comment and its page."""
    out(update.get("title", ""))
    out(byline(update))
    rest = body_after_title(update.get("text", ""))
    if rest:
        out("")
        for para in rest.split("\n"):
            out(textwrap.fill(para, 78) if para.strip() else "")
    out("")
    out(f"Comment: stationhouse comment {update['id']} \"<text>\"")
    if page_url(update):
        out(page_url(update))


def render_preview(update: dict, out=print) -> None:
    """The card followers will see: status and author, the title, a few lines of the rest."""
    out("")
    out("  " + " · ".join(p for p in [health(update), f"{update.get('authorName') or 'you'}, lead"] if p))
    out("  " + update.get("title", ""))
    rest = " ".join(body_after_title(update.get("text", "")).split())
    if rest:
        lines = textwrap.wrap(rest, 70)
        for line in lines[:2]:
            out("  " + line)
        if len(lines) > 2:
            out("  …")
    out("")


def preview_title(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip().lstrip("#").strip().strip("*_").strip()
    return ""


# --- Activity (STA-296) ---------------------------------------------------------------------------

FILTERS = ("updates", "tasks", "posts", "milestones")
ALL = 600  # the most the platform answers with


def activity(project: str, only: str | None = None, everything: bool = False) -> dict:
    query = {}
    if only:
        query["only"] = only
    if everything:
        query["limit"] = str(ALL)
    return request("GET", f"/api/v1/projects/{_q(project)}/activity", query=query or None) or {}


def group_label(iso: str, now: datetime | None = None) -> str:
    """This week, Last week (weeks start on Monday, in your time), then the month."""
    now = (now or datetime.now().astimezone())
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(now.tzinfo)
    except ValueError:
        return ""
    today = now.date()
    this_week = today.toordinal() - today.weekday()
    day = at.date().toordinal()
    if day >= this_week:
        return "This week"
    if day >= this_week - 7:
        return "Last week"
    return at.strftime("%B") + ("" if at.year == now.year else f" {at.year}")


def event_line(item: dict, posts_tab: str = "Discussions") -> str:
    kind = item.get("kind")
    page = (item.get("page") or {}).get("title", "")
    who = item.get("actorName") or "Someone"
    if kind == "task_completed":
        return f"✓ {who} completed  {page}"
    if kind == "post_published":
        return f"¶ {who} posted  {page}  in {posts_tab}"
    if kind == "milestone_reached":
        return f"◆ Milestone reached  {page}"
    if kind == "milestone_started":
        return f"◆ Milestone started  {page}"
    return page


def render_activity(data: dict, only: str | None = None, now: datetime | None = None, out=print) -> None:
    items = data.get("items") or []
    if not items:
        out("No updates yet." if only == "updates" else "Nothing has happened here yet.")
        return
    out(f"{data.get('projectTitle') or data.get('projectId')} · Activity")
    group = None
    for item in items:
        label = group_label(item.get("at", ""), now)
        if label != group:
            out("")
            out(label)
            group = label
        when = date(item.get("at", "")).ljust(6)
        if item.get("kind") == "update":
            u = item["update"]
            out(f"  {when}  UPDATE  {' '.join(p for p in [health(u), u.get('title', '')] if p)}")
            n = u.get("comments", 0)
            out(f"  {'':6}          {u.get('authorName') or 'A lead'} · {n} comment{'s' if n != 1 else ''} · stationhouse update show {u['id']}")
        else:
            out(f"  {when}  {event_line(item, data.get('postsTab') or 'Discussions')}")
    if data.get("hasMore"):
        out("  …")
    out("")
    out("Only some: --updates --tasks --posts --milestones · Older: --all · --json")
