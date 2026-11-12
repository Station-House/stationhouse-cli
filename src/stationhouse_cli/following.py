"""Join & Follow (STA-276–280): join, leave, follow, unfollow, the same two verbs as the website's
project header, and `following`, the list on Preferences · Following.

Join says "I work here" and follows the project too. Follow says "I want to hear about it": without
joining, that's its Project updates alone (STA-388). A member who unfollows stays a member and hears
none of the project's news; mentions of them, and pages they follow (their tasks among them), still
reach them. Leaving keeps the follow. Page follows are separate: you follow a page you wrote, own,
commented on or were mentioned on, and can follow or unfollow one yourself. A project-management
task is a page too: `follow 12` (or `<project>#12`) finds it by its number and follows its page.

The platform's routes (all idempotent; a write answers where you stand now, with `changed`):
  PUT/DELETE /api/v1/projects/<p>/membership   join, leave (a lead's leave is a 409 that says why)
  PUT/DELETE /api/v1/projects/<p>/following    follow, unfollow
  GET/PUT/DELETE /api/v1/pages/<id>/following  a page's follow
  GET /api/v1/me/following                     {projects: [...], pages: [...]}
"""
import difflib
import urllib.parse

from . import pm, projects
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


COMMUNITY = "community"


def member_hears(mode: str) -> str:
    """What a member who follows the project hears of it, by its board mode (STA-388).
    full: posts, tasks and a lead's Project updates reach the Inbox and email; an admin's are emailed.
    discussions: its new posts. off (no board): only an admin's Project updates, by email."""
    if mode == "full":
        return "Its posts and tasks reach your Inbox and email, and so do a lead's Project updates; an admin's are emailed."
    if mode == "discussions":
        return "Its new posts reach your Inbox, and your email unless it's off in Preferences."
    return "Its Project updates are emailed to you."


def render_change(command: str, change: dict, out=print) -> None:
    """What join, leave, follow and unfollow say: the frame's copy, by the project's board mode
    (`mode`: full, discussions or off; an older platform sends none, read as off), and "already"
    when nothing changed. A Follower who hasn't joined hears only of Project updates (STA-388)."""
    title, pid = change.get("title") or change.get("projectId"), change.get("projectId")
    member, following, changed = change.get("member"), change.get("following"), change.get("changed")
    mode = change.get("mode") or "off"
    if command == "join":
        if not changed:
            out(f"You're already a member of {title}.")
        else:
            # Joining always follows: the platform takes back an unfollow left from before.
            out(f"Joined {title}. You follow it too. {member_hears(mode)}")
            out(f"  Stay a member but hear nothing: stationhouse unfollow {pid}")
    elif command == "leave":
        tasks = " Tasks you're on stay yours." if mode == "full" else ""
        if not changed:
            out(f"You're not a member of {title}.")
        elif following and mode == "discussions":
            # Without joining, a project with Discussions only brings nothing: its posts are its members'.
            out(f"Left {title}.{tasks} You still follow it, which without joining brings no news here today.")
            out(f"  Unfollow it: stationhouse unfollow {pid}")
        elif following:
            out(f"Left {title}.{tasks} You still follow it, so its Project updates still reach you.")
            out(f"  Stop hearing about it: stationhouse unfollow {pid}")
        else:
            out(f"Left {title}.{tasks}")
    elif command == "follow":
        if not changed:
            out(f"You already follow {title}.")
        elif pid == COMMUNITY:
            # Community posts aren't emailed one by one: the Daily digest lists the new ones (review-459-b).
            out(f"Following {title}. New posts reach your Inbox, and your Daily digest unless it's off in Preferences.")
        elif member:
            out(f"Following {title}. {member_hears(mode)}")
        elif mode == "full":
            out(f"Following {title} without joining, so you get its Project updates: a lead's in your Inbox and by email, an admin's by email.")
            out(f"  For its task and discussion news too: stationhouse join {pid}")
        elif mode == "discussions":
            out(f"Following {title} without joining, which brings you no news here today.")
            out(f"  To hear of its new posts: stationhouse join {pid}")
        else:
            out(f"Following {title} without joining, so its Project updates are emailed to you.")
    elif command == "unfollow":
        if not changed:
            out(f"You don't follow {title}.")
        elif member and mode == "off":
            out(f"Stopped following {title}. You're still a member, but its Project updates are no longer emailed to you.")
            out(f"  Follow again: stationhouse follow {pid}")
        elif member:
            out(f"Stopped following {title}. You're still a member.")
            yours = ", your tasks among them" if mode == "full" else ""
            out(f"  You'll still hear when someone mentions you, and about pages you follow{yours}.")
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


def task_command(ref: str, follow: bool) -> dict:
    """Follows or unfollows a project-management task, named by its number (`12`, `#12`,
    `<project>#12`). The task says whether you follow it, so a second run changes nothing and says
    so; otherwise its page's follow changes. Returns the page's follow with `changed` and the task."""
    _, data = projects.task_call("GET", ref)
    if not pm.is_pm(data):
        raise ApiError(f"{ref} isn't a project-management task. Follow its project: stationhouse follow <project>")
    t = data["task"]
    task = {"id": t["id"], "number": t["number"], "title": t["title"], "projectId": t["projectId"]}
    if bool(t.get("following")) == follow:
        return {"following": follow, "changed": False, "task": task}
    path = f"/api/v1/pages/{urllib.parse.quote(t['id'], safe='')}/following"
    try:
        change = request("PUT" if follow else "DELETE", path) or {}
    except ApiError as e:
        if e.status == 404 and not e.body.get("error"):
            raise ApiError("This Station House server can't follow tasks yet.", 404) from None
        raise
    return {**change, "changed": True, "task": task}


def render_task_change(typed: str, follow: bool, change: dict, out=print) -> None:
    task, ref = change["task"], pm.ref_for(typed, change["task"])
    named = pm.named(task)
    if follow and not change.get("changed"):
        out(f"You already follow {named}.")
    elif follow:
        out(f"Following {named}. Its comments and changes reach your Inbox and email.")
        out(f"  Unfollow: stationhouse unfollow {ref}")
    elif not change.get("changed"):
        out(f"You don't follow {named}.")
    else:
        out(f"Stopped following {named}. Mentions still reach you.")
        out(f"  Follow again: stationhouse follow {ref}")


def render_page_change(page_id: str, follow: bool, change: dict, out=print) -> None:
    if follow and not change.get("changed"):
        why = PAGE_REASONS.get(change.get("reason") or "")
        out(f"You already follow page {page_id}" + (f" ({why})." if why else "."))
    elif follow:
        out(f"Following page {page_id}. New replies reach your Inbox, and on a project your email too.")
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
