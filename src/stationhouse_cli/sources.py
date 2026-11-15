"""Hugging Face & GitHub in projects (P-STA-25): each project's list of repos, and the threads from them
that show in its Activity and Discussions. Anyone who can see the project reads the list; its leads
add and remove public repos (or one thread from elsewhere) and hide a thread from the project.

  GET    /api/v1/projects/<project>/sources             -> {projectTitle, repos, threads, hidden, canEdit}
  POST   /api/v1/projects/<project>/sources             {link} -> {..., added: {summary, ...}}
  DELETE /api/v1/projects/<project>/sources?ref=        a repo (link or owner/name) or one thread
  POST   /api/v1/projects/<project>/sources/hidden      {ref} hides a thread
  DELETE /api/v1/projects/<project>/sources/hidden?ref= shows it again

A thread is named by its link, as owner/name#44, or as hf#44 / gh#203 in the project's own repos.
`stationhouse open <n>` opens one from the last Hugging Face & GitHub list printed: a row of
`discussions <project> --hf-github`, or a #number from `activity <project> --hf-github`.
"""
import contextlib
import json
import os
import tempfile
import webbrowser
from urllib.parse import quote

from .client import ApiError, request
from .config import config_dir

HF_GITHUB = "Hugging Face & GitHub"
FLAG = "hf-github"
TYPE_LABEL = {"space": "Space", "dataset": "Dataset", "model": "Model", "repo": ""}
FORGE = {"hf": "hf", "github": "gh"}


def _path(project: str, suffix: str = "") -> str:
    return f"/api/v1/projects/{quote(project, safe='')}/sources{suffix}"


def fetch(project: str) -> dict:
    return request("GET", _path(project)) or {}


def add(project: str, link: str) -> dict:
    return request("POST", _path(project), body={"link": link}) or {}


def remove(project: str, ref: str) -> dict:
    return request("DELETE", _path(project), query={"ref": ref}) or {}


def set_hidden(project: str, ref: str, hidden: bool) -> dict:
    if hidden:
        return request("POST", _path(project, "/hidden"), body={"ref": ref}) or {}
    return request("DELETE", _path(project, "/hidden"), query={"ref": ref}) or {}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def counts_line(repo: dict) -> str:
    """"18 discussions · 9 PRs", "64 PRs · 12 issues": what the syncs have read of it, zeros left out."""
    c = repo.get("counts") or {}
    parts = []
    if c.get("discussions"):
        parts.append(_plural(c["discussions"], "discussion", "discussions"))
    if c.get("pullRequests"):
        parts.append(_plural(c["pullRequests"], "PR", "PRs"))
    if c.get("issues"):
        parts.append(_plural(c["issues"], "issue", "issues"))
    if parts:
        return " · ".join(parts)
    return "not read yet" if not repo.get("checkedAt") else "no threads yet"


def render(data: dict, project: str, out=print) -> None:
    out(f"{data.get('projectTitle') or project} · {HF_GITHUB}")
    repos, threads, hidden = data.get("repos") or [], data.get("threads") or [], data.get("hidden") or []
    out("")
    if not repos:
        out("No repos added yet." + (f" Add one: stationhouse sources add {project} <link>" if data.get("canEdit") else ""))
    else:
        out("Repos")
        width = max(len(r["repoId"]) for r in repos)
        for r in repos:
            kind = TYPE_LABEL.get(r.get("repoType"), "")
            out(f"  {FORGE[r['forge']]}  {r['repoId']:<{width}}  {kind:<7}  {counts_line(r)}".rstrip())
    if threads:
        out("Single threads")
        for t in threads:
            out(f"  {FORGE[t['forge']]}  {t['repoId']} #{t['num']}   {t.get('title') or ''}".rstrip())
    if hidden:
        listed = {(r["forge"], r["repoId"].lower()) for r in repos}
        out("Hidden")
        for t in hidden:
            where = f"#{t['num']}" if (t["forge"], t["repoId"].lower()) in listed else f"{t['repoId']} #{t['num']}"
            out(f"  {FORGE[t['forge']]}  {where} {t.get('title') or ''}".rstrip())
    if data.get("canEdit"):
        out("")
        out(f"Leads: stationhouse sources add|remove {project} <link> · hide|show {project} hf#44")


def render_added(data: dict, out=print) -> None:
    added = data.get("added") or {}
    # "Dataset · Station-house/csa-results · 2 discussions, 0 pull requests" -> "Added Station-house/csa-results (Dataset · 2 discussions)."
    parts = (added.get("summary") or "").split(" · ")
    name = parts[1] if len(parts) > 1 else added.get("graphRepo", "it")
    rest = " · ".join([parts[0], *parts[2:]]) if len(parts) > 1 else ""
    rest = rest.replace(", 0 pull requests", "").replace(", 0 discussions", "")
    if added.get("already"):
        out(f"{name} was already in {data.get('projectTitle') or data.get('projectId')}.")
        return
    out(f"Added {name}" + (f" ({rest})." if rest else "."))
    out("Its threads show in Activity and Discussions within 5 minutes.")


def render_removed(data: dict, ref: str, out=print) -> None:
    out(f"Removed {ref} from {data.get('projectTitle') or data.get('projectId')}. Its threads no longer show there.")


def render_hidden(data: dict, project: str, ref: str, out=print) -> None:
    out(f"Hidden from {data.get('projectTitle') or project}. Undo: stationhouse sources show {project} {ref}")


def render_shown(data: dict, project: str, out=print) -> None:
    thread = data.get("thread") or {}
    title = f" “{thread['title']}”" if thread.get("title") else ""
    out(f"Showing{title} in {data.get('projectTitle') or project} again.")


# --- The last list printed, for `stationhouse open <n>` ----------------------------------------------

def _last_path():
    return config_dir() / "last-linked.json"


def remember(source: str, project: str, items: list[dict]) -> None:
    """Keeps the list just printed ({n, num, url}) so `open <n>` finds it. Failing to write is harmless."""
    with contextlib.suppress(OSError):
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".last-linked-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"from": source, "project": project, "items": items}, f)
            os.replace(tmp, _last_path())
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def pick(target: str) -> dict:
    """The thread `open <n>` means: row n of the last Discussions list, or #n of the last Activity list."""
    try:
        last = json.loads(_last_path().read_text())
    except (OSError, ValueError):
        last = None
    if not isinstance(last, dict) or not last.get("items"):
        raise ApiError("Nothing to open yet. List some first: stationhouse discussions <project> --hf-github")
    try:
        n = int(target.lstrip("#"))
    except ValueError:
        raise ApiError(f"Which one? stationhouse open <n>  (a number from the last list, not {target!r})") from None
    key = "n" if last.get("from") == "discussions" else "num"
    found = next((item for item in last["items"] if item.get(key) == n), None)
    if not found:
        again = f"stationhouse {last.get('from', 'discussions')} {last.get('project', '<project>')} --hf-github"
        raise ApiError(f"There's no {n} in the last list. See it again: {again}")
    return found


def open_url(url: str) -> bool:
    with contextlib.suppress(webbrowser.Error):
        return webbrowser.open(url)
    return False


# --- Discussions' Hugging Face & GitHub group --------------------------------------------------------

def short_source(t: dict) -> str:
    """"hf #44", "gh issue #31", "hf ConspiracyBench #57": where a linked thread is, briefly."""
    if t.get("single"):
        return f"{FORGE[t['forge']]} {t['repoId'].split('/')[-1]} #{t['num']}"
    return f"gh issue #{t['num']}" if t["forge"] == "github" else f"hf #{t['num']}"


def render_discussions(data: dict, day, out=print) -> None:
    title = data.get("title") or data.get("scope")
    out(f"{title} · Discussions · {HF_GITHUB}")
    rows = data.get("linked") or []
    out("")
    if not rows:
        out("No Hugging Face discussions or GitHub issues here yet.")
        return
    width = min(max(len(t["title"]) for t in rows), 48)
    where = max(len(short_source(t)) for t in rows)
    for n, t in enumerate(rows, 1):
        name = t["title"] if len(t["title"]) <= 48 else t["title"][:47] + "…"
        replies = _plural(t.get("comments", 0), "reply", "replies")
        closed = "  [closed]" if t.get("status") == "closed" else ""
        here = "  [here]" if t.get("postId") else ""
        out(f"  {n:>2}  {name:<{width}}  {short_source(t):<{where}}  {replies:>10}  {day(t.get('lastActivityAt'))}{closed}{here}")
    out("")
    # A two-way repo's thread has its synced post here (STA-425): it reads like any post.
    synced = [t for t in rows if t.get("postId")]
    if synced:
        out(f"[here]: synced with Stationhouse, read it with stationhouse discussions show {synced[0]['postId']}")
    if len(synced) < len(rows):
        out(f"{'The rest live' if synced else 'These live'} on Hugging Face and GitHub: reply there.")
    out(f"stationhouse open 1  →  {rows[0]['url']}")
    remember("discussions", data.get("scope", ""), [{"n": n, "num": t["num"], "url": t["url"]} for n, t in enumerate(rows, 1)])
