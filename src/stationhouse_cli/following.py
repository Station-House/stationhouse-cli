"""Join & Follow (STA-276–280): join, leave, follow, unfollow, the same two verbs as the website's
project header, and `following`, the list on Preferences · Following.

Join says "I work here" and follows the project too. Follow says "I want to hear about it". A member
who unfollows stays a member and hears nothing about the project but mentions of them and tasks that
are theirs. Leaving keeps the follow. Page follows are separate: you follow a page you wrote, own,
commented on or were mentioned on, and can follow or unfollow one yourself.

The platform's routes (all idempotent; a write answers where you stand now, with `changed`):
  PUT/DELETE /api/v1/projects/<p>/membership   join, leave (a lead's leave is a 409 that says why)
  PUT/DELETE /api/v1/projects/<p>/following    follow, unfollow
  GET/PUT/DELETE /api/v1/pages/<id>/following  a page's follow
  GET /api/v1/me/following                     {projects: [...], pages: [...]}
"""
import difflib
import urllib.parse

from . import projects
from .client import ApiError, request

# What each command calls: (path under the project, method).
PROJECT_CALLS = {
    "join": ("/membership", "PUT"),
    "leave": ("/membership", "DELETE"),
    "follow": ("/following", "PUT"),
    "unfollow": ("/following", "DELETE"),
}

# Why a page is followed, as the website's side panel says it (PAGE_FOLLOW_CAPTIONS).
PAGE_REASONS = {
    "wrote": "you wrote this",
    "owner": "you own this task",
    "commented": "you commented",
    "mentioned": "you were mentioned",
    "followed": "you followed this",
}

# How many followed pages `following` lists before "…" (--json has them all).
PAGES_SHOWN = 10


def project_command(command: str, project_id: str) -> dict:
    """Runs join, leave, follow or unfollow; returns the platform's ProjectFollowChange."""
    suffix, method = PROJECT_CALLS[command]
    try:
        return request(method, projects.project_path(project_id, suffix)) or {}
    except ApiError as e:
        raise _no_such_project(e, project_id) from None


def summary(change: dict) -> dict:
    """The --json answer: { project, member, following, reason, changed }."""
    return {"project": change.get("projectId"), "member": bool(change.get("member")),
            "following": bool(change.get("following")), "reason": change.get("reason"),
            "changed": bool(change.get("changed"))}


def render_change(command: str, change: dict, out=print) -> None:
    """What join, leave, follow and unfollow say: the frame's copy, and "already" when nothing changed."""
    title, pid = change.get("title") or change.get("projectId"), change.get("projectId")
    member, following, changed = change.get("member"), change.get("following"), change.get("changed")
    if command == "join":
        if not changed:
            out(f"You're already a member of {title}.")
        elif following:
            out(f"Joined {title}. You follow it too: its posts, tasks and updates reach your Inbox and email.")
            out(f"  Stay a member but hear nothing: stationhouse unfollow {pid}")
        else:
            out(f"Joined {title}. You'd unfollowed it, so only mentions and tasks that are yours reach you.")
            out(f"  Hear about it: stationhouse follow {pid}")
    elif command == "leave":
        if not changed:
            out(f"You're not a member of {title}.")
        elif following:
            out(f"Left {title}. Tasks you're on stay yours. You still follow it.")
            out(f"  Stop hearing about it: stationhouse unfollow {pid}")
        else:
            out(f"Left {title}. Tasks you're on stay yours.")
    elif command == "follow":
        if not changed:
            out(f"You already follow {title}.")
        elif member:
            out(f"Following {title}. Its posts, tasks and updates reach your Inbox and email.")
        else:
            out(f"Following {title}. Its updates reach your Inbox and email. You haven't joined.")
            out(f"  To post or take tasks: stationhouse join {pid}")
    elif command == "unfollow":
        if not changed:
            out(f"You don't follow {title}.")
        elif member:
            out(f"Stopped following {title}. You're still a member.")
            out("  You'll still hear when someone mentions you or about tasks that are yours.")
            out(f"  Follow again: stationhouse follow {pid}")
        else:
            out(f"Stopped following {title}.")
            out(f"  Follow again: stationhouse follow {pid}")


def page_command(page_id: str, follow: bool) -> dict:
    """Follows or unfollows a page by hand. Reads it first, so a second run changes nothing and says so.
    Returns the page's follow ({following, reason, unfollowed, projectFollowing, others}) with `changed`."""
    path = f"/api/v1/pages/{urllib.parse.quote(page_id, safe='')}/following"
    try:
        before = request("GET", path) or {}
        if bool(before.get("following")) == follow:
            return {**before, "changed": False}
        return {**(request("PUT" if follow else "DELETE", path) or {}), "changed": True}
    except ApiError as e:
        if e.status == 404 and not e.body.get("error"):
            raise ApiError("This Station House server can't follow pages yet.", 404) from None
        raise


def render_page_change(page_id: str, follow: bool, change: dict, out=print) -> None:
    if follow and not change.get("changed"):
        why = PAGE_REASONS.get(change.get("reason") or "")
        out(f"You already follow page {page_id}" + (f" ({why})." if why else "."))
    elif follow:
        out(f"Following page {page_id}. New replies reach your Inbox and email.")
        out(f"  Unfollow: stationhouse unfollow --page {page_id}")
    elif not change.get("changed"):
        out(f"You don't follow page {page_id}.")
    else:
        out(f"Stopped following page {page_id}. Mentions still reach you.")
        out(f"  Follow again: stationhouse follow --page {page_id}")


def fetch() -> dict:
    """{projects: [ProjectStanding], pages: [FollowedPage]}: everything you joined or follow."""
    try:
        return request("GET", "/api/v1/me/following") or {}
    except ApiError as e:
        if e.status == 404 and not e.body.get("error"):
            raise ApiError("This Station House server doesn't have `following` yet.", 404) from None
        raise


def standing_label(p: dict) -> str:
    """member · following, member · not following, lead · following, or follower."""
    if not p.get("member"):
        return "follower"
    role = "lead" if p.get("lead") else "member"
    return f"{role} · {'following' if p.get('following') else 'not following'}"


def render_list(data: dict, out=print) -> None:
    rows = sorted(data.get("projects") or [], key=lambda p: p["projectId"])
    out("Projects")
    if not rows:
        out("  None yet. Follow one: stationhouse follow <project>")
    width = max((len(p["projectId"]) for p in rows), default=0) + 4
    for p in rows:
        out(f"  {p['projectId']:<{width}}{_fit(p.get('title') or '', 32):<36}{standing_label(p)}")
    pages = data.get("pages") or []
    out(f"Pages ({len(pages)})")
    if not pages:
        out("  None yet. You follow a page you write, comment on or are mentioned on.")
        return
    shown = pages[:PAGES_SHOWN]
    pw = max(len(p["projectId"]) for p in shown) + 3
    for p in shown:
        why = PAGE_REASONS.get(p.get("reason"), "")
        out(f"  {_fit(p.get('title') or '', 34):<37}{p['projectId']:<{pw}}{why:<21}{p['pageId']}")
    if len(pages) > len(shown):
        out(f"  … {len(pages) - len(shown)} more (stationhouse following --json lists them all)")
    out("  Unfollow one: stationhouse unfollow --page <id>")


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _no_such_project(e: ApiError, project_id: str) -> ApiError:
    """A project you can't see is a 403: say so, with the nearest id you can see. Other errors pass."""
    if e.status != 403:
        return e
    try:
        ids = [p["id"] for p in projects.list_projects()]
    except ApiError:
        ids = []
    if project_id in ids:  # it exists, so the platform's own reason stands
        return e
    near =[i for i in ids if i.startswith(project_id)] or difflib.get_close_matches(project_id, ids, n=1)
    hint = f" Did you mean {near[0]}?" if near else ""
    return ApiError(f'No project "{project_id}".{hint} See: stationhouse projects', 403, e.body)
