"""Our Research (STA-354): the daily list of research write-ups the platform makes from the week's
discussions, PRs and experiments (GET /api/v1/research). Anyone may read it, signed in or not, where
the server has public reading on; it names no members.
"""
from datetime import datetime

from .client import request

KIND = {"pr": "PR", "discussion": "discussion", "experiment": "experiment"}


def fetch(project: str | None = None) -> dict:
    return request("GET", "/api/v1/research", query={"project": project} if project else None) or {}


def _local(iso: str | None, now: datetime) -> datetime | None:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00")).astimezone(now.tzinfo)
    except ValueError:
        return None


def day_label(iso: str | None, now: datetime | None = None) -> str:
    """Today, Yesterday, then "Mon, Nov 9" (with the year when it isn't this one), in your time."""
    now = now or datetime.now().astimezone()
    at = _local(iso, now)
    if at is None:
        return "Undated"
    days = (now.date() - at.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    label = f"{at.strftime('%a')}, {at.strftime('%b')} {at.day}"
    return label if at.year == now.year else f"{label}, {at.year}"


def render(data: dict, now: datetime | None = None, out=print) -> None:
    """A heading per day, newest first; under it each card: project · kind, the hook, the link."""
    now = now or datetime.now().astimezone()
    cards = data.get("cards") or []
    if not data.get("generatedAt"):
        out("Our Research hasn't been written yet. It's made once a day: try again tomorrow.")
        return
    if not cards:
        out("Nothing in Our Research from this project this week." if data.get("project")
            else "Nothing in Our Research this week.")
        return
    written = day_label(data["generatedAt"], now)
    written = written.lower() if written in ("Today", "Yesterday") else f"on {written}"
    out(f"Our Research: the last {data.get('windowDays') or 7} days, written {written}")
    shown = None
    for card in cards:
        label = day_label(card.get("at"), now)
        if label != shown:
            out("")
            out(label)
            shown = label
        project = card.get("projectTitle") or card.get("projectId") or ""
        out(f"  {project} · {KIND.get(card.get('kind'), card.get('kind') or '')}")
        out(f"    {card.get('hook', '')}")
        if card.get("url"):
            out(f"    {card['url']}")
