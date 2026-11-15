"""Discussions and Announcements (STA-293): the community's and each project's discussions
(GET/POST /api/v1/discussions/<scope>, GET/DELETE /api/v1/posts/<id>, POST /api/v1/posts/<id>/comments,
PUT/DELETE /api/v1/discussions/<scope>/following) and the announcements the team emails everyone
(GET /api/v1/announcements[/<id|latest>], POST /api/v1/announcements/<id>/comments). A scope is
`community` or a project's id. The platform decides who may read and write; its refusals ("Finish
setting up first: <url>", an unknown category with the valid ones) are printed as they come.
"""
import sys
from datetime import datetime, timezone
from urllib.parse import quote

from .client import ApiError, request

COMMUNITY = "community"
SHOWN = 10


def _q(value: str) -> str:
    return quote(value, safe="")


def day(iso: str | None, now: datetime | None = None) -> str:
    """"today", "yesterday" or "Nov 8": when something happened, as the rows say it."""
    if not iso:
        return ""
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = (now.date() - at.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    label = f"{at.strftime('%b')} {at.day}"
    return label if at.year == now.year else f"{label}, {at.year}"


def _comments(n: int) -> str:
    return f"{n} comment{'s' if n != 1 else ''}"


def _scope_name(data: dict) -> str:
    return "Community discussions" if data.get("scope") == COMMUNITY else f"{data.get('title') or data.get('scope')} discussions"


# Discussions

def fetch(scope: str, all_posts: bool = False) -> dict:
    return request("GET", f"/api/v1/discussions/{_q(scope)}", query={"all": "1"} if all_posts else None)


def in_category(data: dict, category: str | None) -> dict:
    """The list narrowed to one category (by name, any case); an unknown one names the valid ones."""
    if not category:
        return data
    wanted = category.strip().lower()
    names = [c["name"] for c in data.get("categories", [])]
    if wanted not in [n.lower() for n in names]:
        title = "Community" if data.get("scope") == COMMUNITY else data.get("title") or data.get("scope")
        raise ApiError(f'Unknown category "{category}". {title} categories: {", ".join(n.lower() for n in names)}.')
    keep = lambda rows: [p for p in rows if p["category"].lower() == wanted]  # noqa: E731
    return {**data, "posts": keep(data.get("posts", [])), "archived": keep(data.get("archived", [])), "category": category}


def render_list(data: dict, limit: int | None = SHOWN, out=print) -> None:
    posts = data.get("posts", [])
    scope = data["scope"]
    head = [_scope_name(data), f"{len(posts)} post{'s' if len(posts) != 1 else ''}"]
    if data.get("following"):
        head.append("you follow this")
    out(" · ".join(head))
    if not posts and not data.get("archived"):
        out("  Nothing here yet." + (f" Start one: stationhouse discussions new {scope} --category … --title \"…\"" if data.get("canPost") else ""))
    shown = posts if limit is None else posts[:limit]
    rows = shown + [{**p, "title": f"{p['title']} (archived)"} for p in data.get("archived", [])]
    if rows:
        cat = max(len(p["category"]) for p in rows)
        title = min(max(len(p["title"]) for p in rows), 48)
        who = max(len(p["author"]) for p in rows)
        for p in rows:
            name = p["title"] if len(p["title"]) <= 48 else p["title"][:47] + "…"
            mark = "  [hidden]" if p.get("hidden") else ("  [draft]" if p.get("status") == "draft" else "")
            out(f"  {p['category']:<{cat}}  {name:<{title}}  {p['author']:<{who}}  {_comments(p['comments']):>11}  {day(p['lastActivityAt'])}{mark}"
                f"    {p['id']}")
    more = len(posts) - len(shown)
    hints = []
    if more > 0:
        hints.append(f"… {more} more: stationhouse discussions {scope} --all")
    if data.get("archivedCount") and not data.get("archived"):
        hints.append(f"{data['archivedCount']} archived: stationhouse discussions {scope} --all")
    if data.get("linked"):
        n = len(data["linked"])
        hints.append(f"{n} from Hugging Face & GitHub: stationhouse discussions {scope} --hf-github")
    if hints:
        out("  " + " · ".join(hints))
    if not data.get("canPost") and data.get("writeHint"):
        out(data["writeHint"])


def show(post_id: str) -> dict:
    return request("GET", f"/api/v1/posts/{_q(post_id)}")


def _reactions(reactions: list) -> str:
    return "  ".join(f"{r['emoji']} {r['count']}" for r in reactions)


FORGES = {"hf": "Hugging Face", "github": "GitHub"}


def _from_forge(c: dict) -> str | None:
    """The forge a synced post's comment was copied from (STA-425); None for one written here."""
    return FORGES.get(c.get("source") or "stationhouse")


def _render_comments(comments: list, out) -> None:
    def line(c, indent):
        text = " ".join((c.get("body") or "").split())
        forge = _from_forge(c)
        if c.get("deleted"):
            # Taken away there: GitHub deletes a comment, the Hub only hides it.
            text = ("(deleted on GitHub)" if c["source"] == "github" else "(hidden on Hugging Face)") if forge else "(deleted)"
        elif c.get("body") is None:
            text = "(hidden by a lead)"
        elif forge and c.get("editedAt"):
            text += f" (edited on {forge})"
        out(f"{indent}— {c['author']} · {day(c['at'])}: {text}")
    for c in comments:
        line(c, "")
        for r in c.get("replies", []):
            line(r, "  ")


def render_post(data: dict, out=print) -> None:
    p = data["post"]
    out(p["title"])
    meta = [p["category"], p["author"], day(p.get("publishedAt") or p.get("lastActivityAt")), _comments(p["comments"])]
    if p.get("reactions"):
        meta.append(_reactions(p["reactions"]))
    out(" · ".join(m for m in meta if m))
    synced = data.get("synced")
    forge = FORGES.get(synced["source"]) if synced else None
    if synced:
        # A synced post (STA-425): its thread on Hugging Face or GitHub, copied here.
        out(f"Opened on {synced['label']}  →  {synced['url']}")
    if synced and synced.get("gone"):
        gone = "Moved to another repository on GitHub" if synced["gone"] == "transferred" else f"Deleted on {forge}"
        out(f"{gone}: this post is archived here, with what it said.")
    elif p.get("status") == "archived":
        out("Archived: it takes no new comments. Archived posts are listed with --all.")
    if p.get("hidden"):
        out("Hidden by a lead: it's out of the list and search. Only its author and the leads see it.")
    if p.get("status") == "draft":
        out("Draft: only you (and the leads) see it until you publish it on the site.")
    if p.get("body"):
        out(p["body"].rstrip())
    comments = data.get("comments") or []
    if synced:
        # What was said there, then what was said here, which stays here.
        there = [c for c in comments if _from_forge(c)]
        here = [c for c in comments if not _from_forge(c)]
        out("")
        out(f"{synced['label']} · synced")
        _render_comments(there, out)
        if here:
            out("")
            out(f"On Stationhouse · not posted to {forge}")
            _render_comments(here, out)
    elif comments:
        out("")
        _render_comments(comments, out)
    if data.get("canComment"):
        where = f" here (not on {forge})" if synced else ""
        out(f'Reply{where}: stationhouse discussions reply {p["id"]} --body "…"')
    out(p["url"])


def body_from(args) -> str:
    """The text from --body, --body-file (`-` for stdin), or piped stdin; none is an empty body."""
    if getattr(args, "body", None) is not None:
        return args.body
    path = getattr(args, "body_file", None)
    if path:
        if path == "-":
            return sys.stdin.read()
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise ApiError(f"Couldn't read {path}: {e.strerror}") from None
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def create(scope: str, category: str | None, title: str, body: str, draft: bool) -> dict:
    return request("POST", f"/api/v1/discussions/{_q(scope)}",
                   body={"category": category or "", "title": title, "body": body, "draft": draft})


def render_created(data: dict, out=print) -> None:
    p = data["post"]
    where = "Community" if p["scope"] == COMMUNITY else p["scope"]
    if p.get("status") == "draft":
        out(f"Saved as a Draft in {where} · {p['category']}. Publish it on the site:")
        out(p["url"])
        return
    out(f"Published in {where} · {p['category']}")
    out(p["url"])
    out("You follow this post. Replies reach your Inbox.")


def discard(post_id: str) -> dict:
    """Its author discards a Draft they never published (STA-225 P2-11): it's deleted, with its history."""
    return request("DELETE", f"/api/v1/posts/{_q(post_id)}")


def render_discarded(data: dict, out=print) -> None:
    out("Discarded the draft. It's deleted, with its history.")


def reply(post_id: str, body: str, parent: str | None) -> dict:
    return request("POST", f"/api/v1/posts/{_q(post_id)}/comments", body={"body": body, "parentId": parent})


def render_replied(data: dict, out=print) -> None:
    out(f'Replied on "{data["post"]["title"]}"')
    out("You follow this post. Replies reach your Inbox.")


def follow(scope: str, following: bool) -> dict:
    return request("PUT" if following else "DELETE", f"/api/v1/discussions/{_q(scope)}/following")


def render_follow(data: dict, out=print) -> None:
    name = _scope_name(data)
    if data.get("following") and data.get("scope") == COMMUNITY:
        # Community posts aren't emailed one by one: the Daily digest lists the new ones (review-459-b).
        out(f"Following {name}. New posts reach your Inbox, and your Daily digest unless it's off in Preferences.")
    elif data.get("following") and data.get("mode") == "discussions":
        # Discussions only: no Project updates, so following without joining brings nothing (STA-388).
        out(f"Following {name}. Its new posts reach its members' Inbox, and their email unless it's off in Preferences.")
        out(f"Following without joining brings no news here today. To hear of its posts: stationhouse join {data.get('scope')}")
    elif data.get("following") and data.get("mode") == "full":
        # A Follower who hasn't joined hears only of its Project updates (STA-388); its members, of its posts too.
        # A lead's update reaches the Inbox and email; an admin's is an email only.
        out(f"Following {name}. Its Project updates reach you: a lead's in your Inbox and email, an admin's in your email, unless it's off in Preferences.")
        out(f"Members also hear of its new posts and tasks. If you haven't joined: stationhouse join {data.get('scope')}")
    elif data.get("following"):
        # No board ("off", or an older server that sends no mode): only an admin's Project updates,
        # by email, to its members and Followers alike, and no tasks or posts. (A member who follows
        # also gets Poll closed in the Inbox, which this line leaves out.)
        out(f"Following {name}. Its Project updates reach your email, unless it's off in Preferences.")
    else:
        out(f"Stopped following {name}. Posts you wrote or replied to still reach your Inbox.")


# Announcements

def announcements() -> dict:
    return request("GET", "/api/v1/announcements")


def render_announcements(data: dict, limit: int | None = SHOWN, out=print) -> None:
    rows = data.get("announcements", [])
    if not rows:
        out("No announcements yet. When the team emails everyone, the announcement shows here too.")
        return
    shown = rows if limit is None else rows[:limit]
    title = min(max(len(a["title"]) for a in shown), 56)
    for a in shown:
        name = a["title"] if len(a["title"]) <= 56 else a["title"][:55] + "…"
        out(f"  {day(a['sentAt']):<9} {name:<{title}}  {a['sentBy']}    {a['id']}")
    if len(rows) > len(shown):
        out(f"  … {len(rows) - len(shown)} more: stationhouse announcements --all")


def announcement(target: str) -> dict:
    return request("GET", f"/api/v1/announcements/{_q(target)}")


def render_announcement(data: dict, out=print) -> None:
    a = data["announcement"]
    out(f"Announcement · from {a['sentBy']} · {day(a['sentAt'])}" + (f" · {_reactions(a['reactions'])}" if a.get("reactions") else ""))
    out(a["title"])
    if a.get("body"):
        out(a["body"].rstrip())
    if a.get("button"):
        out(f"{a['button']['label']}: {a['button']['url']}")
    if data.get("comments"):
        out("")
        _render_comments(data["comments"], out)
    if data.get("canComment"):
        out(f'Comment: stationhouse announcements comment {a["id"]} --body "…"')
    out(f"Page: {a['url']}")


def comment(target: str, body: str, parent: str | None) -> dict:
    return request("POST", f"/api/v1/announcements/{_q(target)}/comments", body={"body": body, "parentId": parent})


def render_commented(data: dict, out=print) -> None:
    out(f'Commented on "{data["announcement"]["title"]}"')
    out("You follow this announcement. Replies reach your Inbox.")
