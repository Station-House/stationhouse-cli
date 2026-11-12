"""The One Inbox (GET /api/v1/me/inbox, STA-318): the same Inbox as the bell and the Inbox page. Every
project the member follows, plus Hugging Face and GitHub replies to them, with the same kinds and words
as the page's filters. Unread first, then Earlier (with --all), each numbered so `inbox open <n>` and
`inbox read <n>` can name it. Opening or reading one marks it read everywhere: the bell, the page,
Today and here. `inbox unread --last` undoes the last Mark read.
"""
import re
from datetime import datetime, timezone

from . import config
from .client import ApiError, request

KINDS = ("mentions", "replies", "tasks", "posts", "hf", "github")

UNDO = "stationhouse inbox unread --last"


def unknown_kind(kind: str) -> str:
    """Worded as the platform words it, so the page and the CLI say the same."""
    return f'No kind "{kind}". Kinds: {", ".join(KINDS)}'


def fetch(project: str | None = None, kind: str | None = None) -> dict:
    """{items, unread, counts, sources}: the Inbox under these filters, newest first, each item numbered `n`."""
    if kind is not None and kind not in KINDS:
        raise ApiError(unknown_kind(kind), 400)
    query = {k: v for k, v in (("project", project), ("kind", kind)) if v}
    try:
        data = request("GET", "/api/v1/me/inbox", query=query or None) or {}
    except ApiError as e:
        if e.status == 404 and not e.body.get("error"):
            raise ApiError("This Station House server doesn't have the Inbox yet.", 404) from None
        raise
    return numbered(data)


def numbered(data: dict) -> dict:
    """Unread first, then Earlier, each newest first, numbered from 1 in that order: the numbers the
    list shows with or without --all."""
    items = data.get("items") or []
    ordered = [i for i in items if i.get("unread")] + [i for i in items if not i.get("unread")]
    return {**data, "items": [{"n": n, **item} for n, item in enumerate(ordered, 1)]}


def age(iso: str, now: datetime | None = None) -> str:
    """12m, 3h, 2d, then the date: the page's words."""
    now = now or datetime.now(timezone.utc)
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    minutes = int((now - then).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 24:
        return f"{minutes // 60}h"
    if minutes < 60 * 24 * 7:
        return f"{minutes // (60 * 24)}d"
    return f"{then.strftime('%b')} {then.day}"


def short_label(item: dict) -> str:
    """The kind as a terminal column fits it: "Reply · HF", "PR · GitHub", "Comments (3)"."""
    if item.get("bundled"):
        return f"Comments ({item['bundled']})"
    return (item.get("label") or "").replace("Hugging Face", "HF").replace("PR feedback", "PR").replace("Added to a task", "Added to task")


def short_project(project: str | None) -> str:
    """A project's id as a column fits it: its first word ("marin" for marin-neuron-atlas)."""
    return (project or "").split("-")[0]


def clip(text: str, width: int = 64) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _rows(items: list[dict], out, columns: list[dict] | None = None) -> None:
    """Numbered rows, their columns as wide as `columns` (every row shown, so Unread and Earlier line up) need."""
    columns = columns or items
    label_w = max(len(short_label(i)) for i in columns)
    project_w = max(len(short_project(i.get("project"))) for i in columns)
    age_w = max(len(age(i["at"])) for i in columns)
    n_w = len(str(max(i["n"] for i in columns)))
    for item in items:
        out(f"  {str(item['n']).rjust(n_w)}  {short_label(item).ljust(label_w)}  {short_project(item.get('project')).ljust(project_w)}  "
            f"{age(item['at']).ljust(age_w)}  {clip(item['title'])}")


def missing(data: dict) -> str | None:
    """What didn't load, as the header says it: "Hugging Face and GitHub", "closed polls", or all three."""
    sources = data.get("sources") or {}
    threads = sources.get("hf") == "failed" or sources.get("github") == "failed"
    polls = sources.get("polls") == "failed"
    if not threads and not polls:
        return None
    what = "Hugging Face, GitHub and closed polls" if threads and polls else "Hugging Face and GitHub" if threads else "Closed polls"
    return f"{what} didn't load, so they're missing."


def failed(data: dict) -> bool:
    return missing(data) is not None


def render(data: dict, out=print, everything: bool = False, project_title: str | None = None, kind: str | None = None) -> None:
    items = data.get("items") or []
    unread = [i for i in items if i.get("unread")]
    earlier = [i for i in items if not i.get("unread")]
    filtered = bool(project_title or kind)
    head = ["Inbox", *([project_title] if project_title else []), *([kind] if kind else []), f"{data.get('unread', len(unread))} unread"]
    if failed(data):
        head.append(missing(data))
    elif not filtered and items:
        head.append(f"{len(items)} in all")

    if not items:
        out(" · ".join(head) if filtered or failed(data) else
            "Your Inbox is empty. Join a project and its news shows up here: its new posts, tasks and closed polls, "
            "whichever it has. Link Hugging Face or GitHub on your Profile and replies to you show up too.")
        if failed(data):
            out("  Try again in a minute: stationhouse inbox")
        return
    if not unread and not everything:
        out(" · ".join(head) if failed(data) else "Nothing unread. Earlier: stationhouse inbox --all")
        if failed(data):
            out("  Try again in a minute: stationhouse inbox")
        return

    out(" · ".join(head))
    shown = items if everything else unread
    if filtered and not everything:
        _rows(shown, out)
    else:
        for title, group in (("Unread", unread), ("Earlier", earlier if everything else [])):
            if group:
                out(f"\n{title}")
                _rows(group, out, shown)
    if failed(data):
        out("\n  Try again in a minute: stationhouse inbox")
    elif not filtered:
        n = shown[min(1, len(shown) - 1)]["n"]
        out(f"\n  Open one:     stationhouse inbox open {n}")
        out(f"  Mark read:    stationhouse inbox read {n}      (or: read --all)")
        if not everything and earlier:
            out("  Earlier too:  stationhouse inbox --all")


THREAD_NUMBER = re.compile(r"/(?:pull|issues|discussions)/(\d+)(?:[/?#]|$)")


def thread_number(item: dict) -> int | None:
    """A Hugging Face or GitHub item's PR, issue or discussion number (212 for …/pull/212)."""
    found = THREAD_NUMBER.search(item.get("url") or "") if item.get("external") else None
    return int(found.group(1)) if found else None


def pick(data: dict, target: str) -> dict:
    """The item `target` names: its number in the list ("2", "#2"), its id, or, when it's no list
    number, the PR or discussion number of the one thread that has it ("212" for PR #212)."""
    items = data.get("items") or []
    exact = [i for i in items if i["id"] == target]
    if exact:
        return exact[0]
    n = target.lstrip("#")
    found = [i for i in items if n.isdigit() and i["n"] == int(n)]
    if found:
        return found[0]
    threads = [i for i in items if n.isdigit() and thread_number(i) == int(n)]
    if len(threads) == 1:
        return threads[0]
    if threads:
        raise ApiError(f"More than one thread in your Inbox is #{n}. Use the list number: run stationhouse inbox")
    raise ApiError(f"Nothing in your Inbox is {target}. Use the list number: run stationhouse inbox")


def url_of(item: dict) -> str:
    """The item's link, the platform's own made whole."""
    url = item.get("url") or ""
    return url if "://" in url else f"{config.api_url()}{url}"


def shown_url(url: str) -> str:
    """huggingface.co/…/discussions/41: where it goes, short enough to read."""
    bare = url.split("://", 1)[-1]
    parts = bare.split("/")
    return bare if len(bare) <= 48 or len(parts) <= 3 else f"{parts[0]}/…/{'/'.join(parts[-2:])}"


def mark_read(target: list[str] | str) -> dict:
    """{changed, inbox}: marks these ids (or "all") read."""
    body = {"all": True} if target == "all" else {"ids": target}
    return request("POST", "/api/v1/me/inbox/read", body) or {}


def mark_unread(target: list[str] | str) -> dict:
    """{changed, inbox}: marks these ids unread, or ("last") undoes the last Mark read."""
    body = {"last": True} if target == "last" else {"ids": target}
    return request("POST", "/api/v1/me/inbox/unread", body) or {}


def marked(changed: int, unread: bool = False) -> str:
    if unread:
        return f"Marked {changed} as unread." if changed else "Nothing to put back."
    return f"Marked {changed} as read. Undo: {UNDO}" if changed else "Already read."
