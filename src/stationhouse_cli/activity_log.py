"""`stationhouse activity --member` (STA-383): your own activity log, counts and the date of the last
one, as GET /api/v1/me/activity answers it. --project narrows it to one project, --since sets the
period (all, this-month, this-week or a date). Only you see your log.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

from .client import request

GROUPS = (
    ("Doing the work", ("started", "did", "reviewed")),
    ("Taking part", ("posts", "comments", "replies", "reactions", "votes", "proposals", "papers")),
    ("Running the project", ("updates", "tasksCreated", "ruled", "completedAsLead", "edits")),
)

LABELS = {
    "started": "Started tasks (copies included)",
    "did": "Did tasks (copies included)",
    "reviewed": "Reviewed tasks",
    "posts": "Created posts",
    "comments": "Commented on posts / on tasks",
    "replies": "Replied to comments",
    "reactions": "Reacted",
    "votes": "Voted in polls",
    "papers": "Submitted papers",
    "updates": "Posted project updates",
    "tasksCreated": "Created tasks",
    "ruled": "Ruled on proposals",
    "completedAsLead": "Completed tasks as a lead",
    "edits": "Edited the About or a milestone",
}

# The one-line summary of a single project: the frame's six, then the rest when there are any.
SHORT = (("started", "Started"), ("did", "Did"), ("reviewed", "Reviewed"), ("posts", "Posts"), ("comments", "Comments"), ("reactions", "Reactions"))
SHORT_MORE = (("votes", "Votes"), ("proposals", "Proposed"), ("papers", "Papers"), ("updates", "Updates"), ("tasksCreated", "Created"),
              ("ruled", "Ruled"), ("completedAsLead", "Completed as a lead"), ("edits", "Edits"))


def fetch(project: str | None, since: str | None) -> dict:
    query = {key: value for key, value in (("project", project), ("since", since)) if value}
    path = "/api/v1/me/activity" + (f"?{urllib.parse.urlencode(query)}" if query else "")
    return request("GET", path) or {}


def _day(iso: str | None) -> str:
    if not iso:
        return "—"
    at = datetime.fromisoformat(iso.replace("Z", "+00:00")) if "T" in iso else datetime.fromisoformat(iso)
    return at.strftime("%b %-d")


def _latest(*isos: str | None) -> str | None:
    found = [iso for iso in isos if iso]
    return max(found) if found else None


def _count(counts: dict, key: str) -> tuple[str, int, str | None]:
    """A row's value as printed, its total, and its last date."""
    if key == "comments":
        posts, tasks = counts["postComments"], counts["taskComments"]
        return f"{posts['count']} / {tasks['count']}", posts["count"] + tasks["count"], _latest(posts["last"], tasks["last"])
    entry = counts[key]
    return str(entry["count"]), entry["count"], entry["last"]


def _label(counts: dict, key: str) -> str:
    if key == "proposals":
        n = counts["proposals"]
        return f"Proposed tasks ({n['accepted']} accepted)" if n["count"] else "Proposed tasks"
    return LABELS[key]


def _period(log: dict, today: str) -> str:
    since = log.get("since")
    return "all time" if not since else f"{_day(since)} to {_day(today)}"


def render(data: dict, out=print, today: str | None = None) -> None:
    log = data.get("log") or {}
    counts = log.get("counts") or {}
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    name = log.get("name") or "You"
    nothing = all(entry.get("count", 0) == 0 for entry in counts.values())
    if nothing and not log.get("since") and not log.get("projectId"):
        out("Nothing logged yet. Start a task, review one, or join a discussion.")
        return
    if log.get("projectId"):
        out(f"{name} · {log['projectId']} · {_period(log, today)}")
        if nothing:
            out("  Nothing logged here in that time.")
            return
        parts = [f"{word} {_count(counts, key)[1]}" for key, word in SHORT]
        parts += [f"{word} {total}" for key, word in SHORT_MORE if (total := _count(counts, key)[1]) > 0]
        out("  " + " · ".join(parts))
        return
    out(f"{name} · activity log · {_period(log, today)}")
    for title, keys in GROUPS:
        if title == "Running the project" and not log.get("leads"):
            continue
        out("")
        out(title)
        for key in keys:
            value, _, last = _count(counts, key)
            out(f"  {_label(counts, key):<34}{value:>4}   last {_day(last)}" if last else f"  {_label(counts, key):<34}{value:>4}   —")
    out("")
    out(f"One project: --project <slug> · A period: --since {today[:8]}01 · --json")
