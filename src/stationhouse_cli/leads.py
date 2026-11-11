"""Leads run projects (STA-304 to STA-311): a project's About, milestones, offers and moderation.

Every call is under /api/v1/board/ (docs/API.md, "Project management"): the site's own board routes,
with its contract and errors. Writes are the project's leads' (and admins'); anyone else gets the
server's 403 message, shown as it is.

Board ids (tasks, posts, comments, milestones) are UUIDs. Tasks are shown and taken by their first 8
characters, resolved against the project's Tasks tab and your offers; posts and comments take their
full id (no v1 route lists them). Milestones are numbered by their place on the rail, from 1.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import date, datetime, timezone

from . import projects
from .client import ApiError, request

BOARD = "/api/v1/board"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SHORT = 8

STATE_LABELS = {"draft": "Draft", "proposed": "Proposed", "open": "Open", "claimed": "Claimed", "doing": "Doing",
                "in_review": "In review", "completed": "Completed", "declined": "Declined"}
# A milestone's tasks that completing it leaves behind: anything still being worked on or waiting for someone.
NOT_OPEN = {"completed", "declined", "draft", "proposed"}


# ---------------------------------------------------------------- helpers

def _q(part: str) -> str:
    return urllib.parse.quote(str(part), safe="")


def _project_path(project: str, suffix: str = "") -> str:
    return f"{BOARD}/projects/{_q(project)}{suffix}"


def _emit(args, data, human):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        human(data)


def _interactive(args) -> bool:
    return not getattr(args, "json", False) and sys.stdin.isatty() and sys.stdout.isatty()


def _name(member) -> str:
    if not member:
        return "someone"
    return member.get("name") or f"Member {member['memberId'][:SHORT]}"


def _short(task_id: str) -> str:
    return task_id[:SHORT]


def _parse_time(iso: str):
    if len(iso) == 10:
        return date.fromisoformat(iso)
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _when(iso: str | None) -> str:
    """Nov 8."""
    if not iso:
        return ""
    d = _parse_time(iso)
    return f"{d.strftime('%b')} {d.day}"


def _ago(iso: str) -> str:
    then = _parse_time(iso)
    if not isinstance(then, datetime):
        return _when(iso)
    seconds = (datetime.now(timezone.utc) - then).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago" if days < 14 else _when(iso)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("y", "yes")


# ---------------------------------------------------------------- About (STA-305)

def _about(project: str) -> dict:
    return request("GET", _project_path(project, "/about"))["about"]


def _project_title(project: str) -> str:
    try:
        return (request("GET", projects.project_path(project)) or {}).get("project", {}).get("title") or project
    except ApiError:
        return project


def _lede(body: str, width: int = 100) -> str:
    """The About's first paragraph that isn't a heading, cut to `width`."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    text = next((" ".join(p.split()) for p in paragraphs if not p.startswith("#")), "")
    if len(text) > width:
        return text[:width].rstrip() + "…"
    return text + ("…" if len(paragraphs) > 1 else "")


def _about_header(about: dict, title: str) -> str:
    page, saved = about["page"], about.get("saved")
    by = f" · {_name(saved['by'])}, {_when(saved['at'])}" if saved else ""
    return f"About · {title} · version {page['version']}{by}"


def cmd_about(args):
    project = projects.resolve(args.project)
    about = _about(project)
    title = _project_title(project)

    def human(d):
        a = d["about"]
        if not a.get("page"):
            print(f"{title} has no About yet.")
            if a.get("canEdit"):
                print("Write it: stationhouse about edit  (it starts from the template)")
            return
        print(_about_header(a, title))
        if args.full:
            print("\n" + a["body"].rstrip())
        else:
            print(_lede(a["body"]) + "   (--full for all of it)")
    _emit(args, {"about": about}, human)


def _editor() -> str:
    return os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"


def cmd_about_edit(args):
    project = projects.resolve(args.project)
    about = _about(project)
    page = about.get("page")
    base = page["version"] if page else None
    kept = None  # the temp file an editor session wrote, kept when nothing was saved
    if args.file:
        try:
            body = open(os.path.expanduser(args.file), encoding="utf-8").read()
        except OSError as e:
            raise ApiError(f"Couldn't read {args.file}: {e.strerror or e}") from None
        if args.base is not None:
            base = args.base
    else:
        if not about.get("canEdit"):
            raise ApiError("Only the project's leads can edit its About.")
        if not sys.stdin.isatty():
            raise ApiError("Editing the About opens your editor, which needs a terminal. Or pass --file <markdown file>.")
        fd, kept = tempfile.mkstemp(prefix="about-", suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(about["body"])
        editor = _editor()
        print(f"Opening {'version ' + str(base) if base else 'the template'} in {editor}…", flush=True)
        code = subprocess.call([*shlex.split(editor), kept])
        if code != 0:
            raise ApiError(f"{editor} exited with {code}; nothing saved. Your text is in {kept}.")
        body = open(kept, encoding="utf-8").read()
        if body == about["body"]:
            os.unlink(kept)
            _emit(args, {"saved": False, "page": page}, lambda d: print("No changes; nothing saved."))
            return
    if args.force:
        latest = _about(project).get("page")
        base = latest["version"] if latest else None
    edit = {"body": body, "baseVersion": base}
    try:
        out = request("PUT", _project_path(project, "/about"), edit)
    except ApiError as e:
        if e.status != 409:
            raise
        return _about_conflict(args, project, kept)
    if kept:
        os.unlink(kept)
    _emit(args, out, lambda d: print(f"Saved version {d['page']['version']}. Members see it now."))


def _about_conflict(args, project, kept):
    latest = _about(project)
    page, saved = latest.get("page") or {}, latest.get("saved")
    v = page.get("version", 0)

    def human(_d):
        who = f" ({_name(saved['by'])}, {_ago(saved['at'])})" if saved else ""
        print(f"Version {v} changed since you started{who}. Nothing saved.")
        print(f"Compare: stationhouse about diff {v}   Save yours anyway: --force (version {v + 1})")
        if kept:
            print(f"Your text is in {kept}: stationhouse about edit --file {shlex.quote(kept)} --force")
    _emit(args, {"saved": False, "conflict": True, "latest": latest, "file": kept}, human)
    return 1


def cmd_about_earlier(args):
    project = projects.resolve(args.project)
    if args.visible_to is None:
        about = _about(project)
        _emit(args, {"about": about}, lambda d: print(_earlier_line(d["about"])))
        return
    out = request("PUT", _project_path(project, "/about/earlier-overview"), {"visibleTo": args.visible_to})
    _emit(args, out, lambda d: print(_earlier_line(d["about"])))


def _earlier_line(about) -> str:
    if about.get("earlierOverview") == "leads":
        return "The earlier overview is for leads alone. Show it to members: stationhouse about earlier-overview members"
    return "Members see the earlier overview. Keep it for leads: stationhouse about earlier-overview leads"


def _about_page_id(project: str) -> str:
    page = _about(project).get("page")
    if not page:
        raise ApiError("This project has no About yet, so it has no history.")
    return page["id"]


def cmd_about_history(args):
    page_id = _about_page_id(projects.resolve(args.project))
    out = request("GET", f"{BOARD}/pages/{_q(page_id)}/versions")

    def human(d):
        versions = d.get("versions", [])
        width = max((len(str(v["version"])) for v in versions), default=1)
        for v in versions:
            who = v.get("authorName") or f"Member {v['authorId'][:SHORT]}"
            print(f"{str(v['version']).ljust(width)}  {who}  {_when(v['createdAt'])}")
    _emit(args, out, human)


def _diff_lines(lines, context=2):
    """Changed lines with `context` unchanged lines around them; … where unchanged lines are skipped."""
    changed = [i for i, line in enumerate(lines) if line["type"] != "same"]
    keep = {j for i in changed for j in range(i - context, i + context + 1)}
    out, skipped = [], False
    for i, line in enumerate(lines):
        if i not in keep:
            skipped = True
            continue
        if skipped and out:
            out.append("  …")
        skipped = False
        mark = {"added": "+ ", "removed": "- "}.get(line["type"], "  ")
        out.append(mark + line["text"])
    return out


def cmd_about_diff(args):
    page_id = _about_page_id(projects.resolve(args.project))
    start, end = (args.version - 1, args.version) if args.to is None else (args.version, args.to)
    if start < 1:
        raise ApiError("Version 1 is the first: there's nothing before it. Compare two with --to, "
                       "e.g. stationhouse about diff 1 --to 3")
    out = request("GET", f"{BOARD}/pages/{_q(page_id)}/diff", query={"from": start, "to": end})

    def human(d):
        diff = d["diff"]

        def side(v):
            who = v.get("authorName") or f"Member {v['authorId'][:SHORT]}"
            return f"version {v['version']} ({who}, {_when(v['createdAt'])})"
        print(f"{side(diff['from'])[0].upper()}{side(diff['from'])[1:]} → {side(diff['to'])}")
        lines = _diff_lines(diff.get("lines", []))
        print("\n".join(lines) if lines else "No changes.")
    _emit(args, out, human)


# ---------------------------------------------------------------- Milestones (STA-306)

def _rail(project: str) -> dict:
    return request("GET", _project_path(project, "/milestones"))["rail"]


def _label(rail: dict, milestone_id: str | None) -> str:
    for i, m in enumerate(rail["milestones"], 1):
        if m["id"] == milestone_id:
            return f"{i}. {m['title']}"
    return "No milestone"


def _milestone(rail: dict, n) -> dict:
    ms = rail["milestones"]
    try:
        i = int(n)
    except (TypeError, ValueError):
        raise ApiError(f"{n!r} isn't a milestone number (see `stationhouse milestones`).") from None
    if not 1 <= i <= len(ms):
        have = f"it has {len(ms)}" if ms else "it has none yet"
        raise ApiError(f"There's no milestone {i} in this project: {have} (see `stationhouse milestones`).")
    return ms[i - 1]


def _pick_milestone(rail: dict, which: str) -> dict:
    """A milestone by its number, or by the start of its title."""
    if which.isdigit():
        return _milestone(rail, which)
    hits = [m for m in rail["milestones"] if m["title"].lower().startswith(which.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ApiError(f"No milestone starts with {which!r} (see `stationhouse milestones`).")
    raise ApiError(f"{which!r} could be {', '.join(_label(rail, m['id']) for m in hits)}. Give its number.")


def _due(text: str | None):
    if text is None or text.lower() == "none":
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ApiError(f"{text!r} isn't a date: write it YYYY-MM-DD, or none.") from None
    return text


def _tasks_cell(counts) -> str:
    done, total = counts.get("done", 0), counts.get("total", 0)
    if not total:
        return "none yet"
    return f"{done} of {total} done" if done else f"{done} of {total}"


def cmd_milestones(args):
    rail = _rail(projects.resolve(args.project))

    def human(r):
        ms = r["milestones"]
        if not ms:
            print("No milestones yet.")
            if r.get("canEdit"):
                print('Add one: stationhouse milestone add "<title>" --due YYYY-MM-DD')
            return
        rows = [("#", "Milestone", "Due", "Tasks")]
        for i, m in enumerate(ms, 1):
            title = m["title"] + ("  (completed)" if m.get("completedAt") else "")
            rows.append((str(i), title, _when(m.get("dueOn")), _tasks_cell(m.get("tasks") or {})))
        widths = [max(len(row[c]) for row in rows) for c in range(3)]
        for row in rows:
            print("  ".join(cell.ljust(widths[c]) for c, cell in enumerate(row[:3])) + "  " + row[3])
    _emit(args, rail, human)


def _put_order(project: str, ids) -> dict:
    return request("PUT", _project_path(project, "/milestones/order"), {"order": list(ids)})["rail"]


def cmd_milestone_add(args):
    project = projects.resolve(args.project)
    title = " ".join(args.title)
    due = _due(args.due)
    target = _milestone(_rail(project), args.before) if args.before is not None else None
    rail = request("POST", _project_path(project, "/milestones"),
                   {"title": title, "summary": args.summary or "", "notes": "", "dueOn": due})["rail"]
    new = rail["milestones"][-1]
    if target:
        ids = [m["id"] for m in rail["milestones"] if m["id"] != new["id"]]
        ids.insert(ids.index(target["id"]) if target["id"] in ids else len(ids), new["id"])
        rail = _put_order(project, ids)

    def human(r):
        when = f" (due {_when(due)})" if due else ""
        line = f"Added {_label(r, new['id'])}{when}."
        if target:
            line += f" {target['title']} is now {_label(r, target['id']).split('.')[0]}."
        print(line)
    _emit(args, {"rail": rail}, lambda d: human(d["rail"]))


def cmd_milestone_edit(args):
    if args.title is None and args.due is None and args.summary is None:
        raise ApiError("Nothing to change: give --title, --due or --summary.")
    project = projects.resolve(args.project)
    m = _milestone(_rail(project), args.n)
    edit = {
        "title": " ".join(args.title.split()) if args.title is not None else m["title"],
        "summary": args.summary if args.summary is not None else m.get("summary", ""),
        "notes": m.get("notes", ""),
        "dueOn": _due(args.due) if args.due is not None else m.get("dueOn"),
        "baseVersion": m["version"],
    }
    rail = request("PATCH", f"{BOARD}/milestones/{_q(m['id'])}", edit)["rail"]

    def human(r):
        due = f" (due {_when(edit['dueOn'])})" if edit["dueOn"] else ""
        print(f"Saved {_label(r, m['id'])}{due}.")
    _emit(args, {"rail": rail}, lambda d: human(d["rail"]))


def cmd_milestone_move(args):
    if (args.before is None) == (args.after is None):
        raise ApiError("Where to? Give --before <n> or --after <n>.")
    project = projects.resolve(args.project)
    rail = _rail(project)
    m = _milestone(rail, args.n)
    anchor = _milestone(rail, args.before if args.before is not None else args.after)
    if anchor["id"] == m["id"]:
        raise ApiError("A milestone can't move next to itself.")
    ids = [x["id"] for x in rail["milestones"] if x["id"] != m["id"]]
    at = ids.index(anchor["id"]) + (0 if args.before is not None else 1)
    ids.insert(at, m["id"])
    rail = _put_order(project, ids)
    _emit(args, {"rail": rail}, lambda d: print(f"Moved {m['title']}: it's {_label(d['rail'], m['id'])} now."))


def _next_open(rail: dict, milestone_id: str):
    ms = rail["milestones"]
    at = next(i for i, m in enumerate(ms) if m["id"] == milestone_id)
    return next((m for m in ms[at + 1:] if not m.get("completedAt")), None)


def _open_tasks(project: str, milestone_id: str) -> list:
    tab = request("GET", _project_path(project, "/tasks"))["tasks"]
    group = next((g for g in tab.get("groups", []) if (g.get("milestone") or {}).get("id") == milestone_id), None)
    return [t for t in (group or {}).get("tasks", []) if t.get("state") not in NOT_OPEN]


def cmd_milestone_done(args):
    project = projects.resolve(args.project)
    rail = _rail(project)
    m = _milestone(rail, args.n)
    label = _label(rail, m["id"])
    choice = "leave" if args.leave else "move"
    nxt = _next_open(rail, m["id"])
    if nxt and not (args.move or args.leave or args.yes) and _interactive(args):
        open_tasks = _open_tasks(project, m["id"])
        if open_tasks:
            them = "it" if len(open_tasks) == 1 else "them"
            answer = input(f"{label} has {_plural(len(open_tasks), 'open task')}. Move {them} to "
                           f"{_label(rail, nxt['id'])}? [Y/n, l = leave {them} here] ").strip().lower()
            if answer in ("n", "no"):
                print("Nothing changed.")
                return 1
            choice = "leave" if answer in ("l", "leave") else "move"
    out = request("PUT", f"{BOARD}/milestones/{_q(m['id'])}/completed", {"completed": True, "openTasks": choice})

    def human(d):
        print(f"Completed {label}. Posted to Activity.")
        moved = (d.get("completion") or {}).get("movedTaskIds") or []
        if moved:
            print(f"Moved {_plural(len(moved), 'open task')} to {_label(d['rail'], d['completion'].get('to'))}.")
    _emit(args, out, human)


def cmd_milestone_reopen(args):
    project = projects.resolve(args.project)
    rail = _rail(project)
    m = _milestone(rail, args.n)
    out = request("PUT", f"{BOARD}/milestones/{_q(m['id'])}/completed", {"completed": False})
    _emit(args, out, lambda d: print(f"Reopened {_label(d['rail'], m['id'])}."))


def cmd_milestone_delete(args):
    project = projects.resolve(args.project)
    rail = _rail(project)
    m = _milestone(rail, args.n)
    label = _label(rail, m["id"])
    n = (m.get("tasks") or {}).get("total", 0)
    if not args.yes:
        if not _interactive(args):
            raise ApiError(f"Deleting asks first. Add --yes to delete {label} without asking.")
        moves = "Its 1 task moves" if n == 1 else f"Its {n} tasks move"
        if not _confirm(f"Delete {label}? {moves} to No milestone. [y/N] "):
            print("Not deleted.")
            return 1
    out = request("DELETE", f"{BOARD}/milestones/{_q(m['id'])}")
    _emit(args, out, lambda d: print(f"Deleted {m['title']}." + (f" {_plural(n, 'task')} {'is' if n == 1 else 'are'} in No milestone now." if n else "")))


# ---------------------------------------------------------------- Tasks and offers (STA-307)

def _tasks_tab(project: str) -> dict:
    return request("GET", _project_path(project, "/tasks"))["tasks"]


def _tab_tasks(tab: dict):
    """Every task the Tasks tab lists: each group's, their subtasks, and the proposals."""
    for entry in [t for g in tab.get("groups", []) for t in g.get("tasks", [])] + list(tab.get("proposals", [])):
        yield entry
        yield from (entry.get("subtasks") or {}).get("tasks", [])


def _my_offers(project: str | None) -> dict:
    return request("GET", f"{BOARD}/me/offers", query={"projectId": project} if project else None) or {}


def _offers_project(flag):
    """The project whose offers a lead sees: the one named or picked, else the only one, else none."""
    project = projects.chosen(flag)
    if project:
        return project
    try:
        return projects.resolve(None)
    except ApiError:
        return None


def resolve_task(arg: str, flag: str | None) -> str:
    """A task's full id from its id or the start of it (8 characters are plenty), from your offers and the Tasks tab."""
    if UUID.match(arg):
        return arg
    prefix = arg.lower()
    if len(prefix) < 4:
        raise ApiError(f"{arg!r} is too short: give at least the first 4 characters of the task's id (8 are shown).")
    titles = {}
    offers = _my_offers(projects.chosen(flag))
    for o in offers.get("toYou", []) + offers.get("byLeads", []):
        titles[o["taskId"]] = o["title"]
    hits = [t for t in titles if t.lower().startswith(prefix)]
    project = None
    if len(hits) != 1:
        project = projects.resolve(flag)
        for t in _tab_tasks(_tasks_tab(project)):
            titles[t["id"]] = t["title"]
        hits = [t for t in titles if t.lower().startswith(prefix)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ApiError(f"No task's id starts with {arg} in {project}. Check it on the project's Tasks tab.")
    listed = "\n".join(f"  {_short(t)}  {titles[t]}" for t in hits)
    raise ApiError(f"{arg} could be any of these; give more of its id:\n{listed}")


def _people(project: str | None, task_view: dict | None = None, offers: dict | None = None) -> dict:
    """The members the API names, memberId -> name: the project's people where a route lists them,
    else everyone on its tasks, their offers and proposals."""
    people = {}

    def note(member):
        if member and member.get("memberId"):
            people.setdefault(member["memberId"], member.get("name"))
    if project:
        try:
            # The @ picker's people (leads and joined members), from GET /api/v1/board/projects/:p/mentions.
            suggestions = request("GET", _project_path(project, "/mentions")).get("suggestions") or {}
            for p in suggestions.get("people", []):
                note(p)
        except ApiError:
            pass
        try:
            tab = _tasks_tab(project)
        except ApiError:
            tab = {}
        for t in _tab_tasks(tab):
            for o in t.get("owners", []):
                note(o)
            note((t.get("offer") or {}).get("member"))
            note(t.get("proposer"))
    if task_view:
        for p in task_view.get("people", []):
            note(p)
        for o in task_view.get("task", {}).get("owners", []):
            note(o)
        offer = task_view.get("offer") or {}
        note(offer.get("member"))
        note(offer.get("offeredBy"))
    for o in (offers or {}).get("toYou", []) + (offers or {}).get("byLeads", []):
        note(o.get("member"))
        note(o.get("offeredBy"))
    return people


def resolve_person(arg: str, people: dict) -> tuple[str, str | None]:
    """(memberId, name) for a name, the start of one (any case), or a member id. An unknown one is passed on as a member id."""
    if arg in people:
        return arg, people[arg]
    low = " ".join(arg.split()).lower()
    named = [(mid, n) for mid, n in people.items() if n]
    for match in (lambda n: n.lower() == low, lambda n: n.lower().startswith(low)):
        hits = [(mid, n) for mid, n in named if match(n)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ApiError(f"{arg!r} could be {', '.join(n for _, n in hits)}. Give more of their name.")
    return arg, None


def _unknown_person(arg: str, people: dict, e: ApiError) -> ApiError:
    known = ", ".join(sorted(n for n in people.values() if n)) or "nobody yet"
    return ApiError(f"{e} I don't know anyone called {arg!r} here (I can see: {known}). "
                    "Pass their member id instead.", e.status, e.body)


def _view(out: dict) -> dict:
    return out["task"]


def cmd_task_new(args):
    project = projects.resolve(args.project)
    title = " ".join(args.title)
    rail = _rail(project) if args.milestone else None
    milestone = _pick_milestone(rail, args.milestone) if rail else None
    body = {"title": title, "body": args.body or "", "start": "open"}
    person, people = None, {}
    if args.offer:
        people = _people(project)
        person = resolve_person(args.offer, people)
        body["offerTo"] = person[0]
    try:
        view = _view(request("POST", _project_path(project, "/tasks"), body))
    except ApiError as e:
        if person and person[1] is None and e.status in (400, 404):
            raise _unknown_person(args.offer, people, e) from None
        raise
    task_id = view["task"]["id"]
    if milestone:
        try:
            view = _view(request("PUT", f"{BOARD}/tasks/{_q(task_id)}/milestone", {"milestoneId": milestone["id"]}))
        except ApiError as e:
            raise ApiError(f"Created {_short(task_id)}, but couldn't put it in {_label(rail, milestone['id'])}: {e}") from None

    def human(v):
        t = v["task"]
        where = f" in {_label(rail, milestone['id'])}" if milestone else ""
        offer = v.get("offer")
        offered = f" and offered it to {_name(offer['member'])}" if offer and offer.get("status") == "pending" else ""
        print(f"Created {_short(t['id'])} ({STATE_LABELS.get(t['state'], t['state'])}){where}{offered}.")
        if offered:
            print(f"Withdraw: stationhouse offer withdraw {_short(t['id'])}")
    _emit(args, {"task": view}, lambda d: human(d["task"]))


def cmd_offers(args):
    project = _offers_project(args.project)
    out = _my_offers(project)

    def human(d):
        to_you, by_leads = d.get("toYou", []), d.get("byLeads", [])
        if not to_you and not by_leads:
            print("No offers waiting for you.")
            return
        both = bool(to_you and by_leads)
        if to_you:
            if both:
                print("Offered to you:")
            for o in to_you:
                print(f"{_short(o['taskId'])}  {o['title']}   from {_name(o.get('offeredBy'))} · expires {_when(o['expiresAt'])}")
            print("Answer: stationhouse offer accept <task>, or offer decline <task> -m REASON")
        if by_leads:
            if both:
                print("\nYour project's offers:")
            for o in by_leads:
                status = o.get("status")
                if status == "pending":
                    how = f"waiting · expires {_when(o['expiresAt'])}"
                elif status == "declined":
                    how = f"declined {_when(o.get('decidedAt'))}" + (f": \"{o['reason']}\"" if o.get("reason") else "")
                else:
                    how = f"expired {_when(o['expiresAt'])}"
                print(f"{_short(o['taskId'])}  {o['title']}  {_name(o.get('member'))}  {how}")
    _emit(args, out, human)


OFFER_ACTIONS = ("accept", "decline", "withdraw")


def cmd_offer(args):
    words = args.words
    if words[0] in OFFER_ACTIONS:
        if len(words) != 2:
            raise ApiError(f"Which task? stationhouse offer {words[0]} <task>")
        return {"accept": _offer_accept, "decline": _offer_decline, "withdraw": _offer_withdraw}[words[0]](args, words[1])
    if len(words) < 2:
        raise ApiError("Offer which task to whom? stationhouse offer <task> <person>  (or offer accept|decline|withdraw <task>)")
    return _offer_make(args, words[0], " ".join(words[1:]))


def _offer_path(task_id: str) -> str:
    return f"{BOARD}/tasks/{_q(task_id)}/offer"


def _offer_make(args, task_arg, person_arg):
    task_id = resolve_task(task_arg, args.project)
    view = _view(request("GET", f"{BOARD}/tasks/{_q(task_id)}"))
    people = _people(view["task"].get("projectId") or projects.chosen(args.project), view)
    member_id, name = resolve_person(person_arg, people)
    try:
        view = _view(request("PUT", _offer_path(task_id), {"memberId": member_id}))
    except ApiError as e:
        if name is None and e.status in (400, 404):
            raise _unknown_person(person_arg, people, e) from None
        raise

    def human(v):
        short, offer = _short(task_id), v.get("offer")
        if offer and offer.get("status") == "pending":
            print(f"Offered {short} to {_name(offer['member'])}. Nobody else can claim it until {_when(offer['expiresAt'])}.")
            print(f"Withdraw: stationhouse offer withdraw {short}")
        else:
            print(f"You took {short}: it's {STATE_LABELS.get(v['task']['state'], v['task']['state'])} with you.")
    _emit(args, {"task": view}, lambda d: human(d["task"]))


def _offer_accept(args, task_arg):
    task_id = resolve_task(task_arg, args.project)
    view = _view(request("POST", _offer_path(task_id), {"accept": True}))
    state = STATE_LABELS.get(view["task"]["state"], view["task"]["state"])
    _emit(args, {"task": view}, lambda d: print(f"It's yours: {_short(task_id)} is {state}."))


def _offer_decline(args, task_arg):
    task_id = resolve_task(task_arg, args.project)
    body = {"accept": False}
    if args.message:
        body["reason"] = args.message
    view = _view(request("POST", _offer_path(task_id), body))
    lead = _name((view.get("offer") or {}).get("offeredBy")) if (view.get("offer") or {}).get("offeredBy") else "the lead who offered it"
    _emit(args, {"task": view}, lambda d: print(f"Declined {_short(task_id)}. It's open to everyone again, and {lead} is told."))


def _offer_withdraw(args, task_arg):
    task_id = resolve_task(task_arg, args.project)
    view = _view(request("DELETE", _offer_path(task_id)))
    _emit(args, {"task": view}, lambda d: print(f"Withdrew the offer of {_short(task_id)}. It's open to everyone again."))


# ---------------------------------------------------------------- Moderation (STA-309 to STA-311)

def _full_id(kind: str, arg: str) -> str:
    if not UUID.match(arg):
        raise ApiError(f"Give the {kind}'s full id (from its link on the site, like 5d2e7c01-…); "
                       f"short ids don't work for {kind}s.")
    return arg


def _clip(text: str, width: int = 20) -> str:
    """At most `width` characters, cut at a word."""
    if len(text) <= width:
        return text
    cut = text[:width]
    if text[width] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.") + "…"


def _post_put(arg: str, what: str, body: dict) -> dict:
    post_id = _full_id("post", arg)
    return request("PUT", f"{BOARD}/posts/{_q(post_id)}/{what}", body)


def cmd_post_hide(args):
    body = {"hidden": True}
    if args.message:
        body["note"] = args.message
    out = _post_put(args.post, "hidden", body)

    def human(d):
        post = d["post"]["post"]
        author = _name(post.get("author"))
        tail = f"{author} sees your note." if args.message else f"Only {author} and the leads see it now."
        print(f"Hid \"{post['title']}\". {tail}")
    _emit(args, out, human)


def cmd_post_unhide(args):
    out = _post_put(args.post, "hidden", {"hidden": False})
    _emit(args, out, lambda d: print(f"\"{d['post']['post']['title']}\" shows to everyone again."))


def cmd_post_lock(args):
    body = {"locked": True}
    if args.message:
        body["reason"] = args.message
    out = _post_put(args.post, "locked", body)
    _emit(args, out, lambda d: print(f"Locked comments on \"{_clip(d['post']['post']['title'])}\". "
                                     f"Unlock: stationhouse post unlock {args.post}"))


def cmd_post_unlock(args):
    out = _post_put(args.post, "locked", {"locked": False})
    _emit(args, out, lambda d: print(f"Unlocked comments on \"{_clip(d['post']['post']['title'])}\"."))


def _find_comment(comments, comment_id):
    for c in comments or []:
        if c.get("id") == comment_id:
            return c
        found = _find_comment(c.get("replies"), comment_id)
        if found:
            return found
    return None


def _comment_hidden(args, hidden: bool):
    comment_id = _full_id("comment", args.comment)
    out = request("PUT", f"{BOARD}/comments/{_q(comment_id)}/hidden", {"hidden": hidden})
    c = _find_comment(out.get("comments"), comment_id) or {}
    who = c.get("actorName") or (f"Member {c['actorId'][:SHORT]}" if c.get("actorId") else "the")
    whose = f"{who}'s" if who != "the" else "the"
    if hidden:
        line = f"Hid {whose} comment. They and the leads still see it."
    else:
        line = f"{whose[0].upper()}{whose[1:]} comment shows to everyone again."
    _emit(args, out, lambda d: print(line))


def cmd_comment_hide(args):
    _comment_hidden(args, True)


def cmd_comment_unhide(args):
    _comment_hidden(args, False)


# ---------------------------------------------------------------- Admins: the overview migration (STA-312)

def _headings(markdown: str) -> list[str]:
    return [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]


def _step(step: str, written: str) -> str:
    return {"exists": "already has one, left as it is", "empty": "nothing to write"}.get(step, written)


def cmd_admin_migrate_overview(args):
    out = request("POST", f"/api/admin/projects/{_q(args.project_id)}/overview-migration", {"apply": bool(args.apply)})

    def human(d):
        r = d["report"]
        project, plan = r.get("projectId") or args.project_id, r.get("plan")
        if not plan:
            print(f"{project} has no plan stored or in code: nothing to migrate; it starts empty.")
            return
        if r.get("applied"):
            print(f"Migrated {project}:")
        else:
            print(f"Dry run for {project} (nothing written; --apply to write it):")
        about = plan.get("about") or ""
        sections = " · ".join(_headings(about))
        milestones = plan.get("milestones") or []
        done = sum(1 for m in milestones if m.get("completed"))
        rows = [
            ("Summary", _clip(plan.get("summary") or "(none)", 45)),
            ("About", _step(r.get("about"), f"version 1, {len(about):,} characters" + (f": {sections}" if sections else ""))),
            ("Milestones", _step(r.get("milestones"), f"{len(milestones)}" + (f" ({done} completed)" if done else ""))),
            ("Header links", f"+{r.get('headerLinks', 0)}"),
            ("Earlier overview", {"write": "hidden from members (leads keep it)", "exists": "already for leads alone",
                                  "empty": "no About, so members keep it"}.get(r.get("earlierOverview"), "unchanged")),
        ]
        width = max(len(k) for k, _ in rows)
        for k, v in rows:
            print(f"  {k.ljust(width)}  {v}")
    _emit(args, out, human)


# ---------------------------------------------------------------- the parser

def register(sub, tsub, add, project):
    """Adds the leads' commands to the CLI's parser (cli.build_parser)."""
    ab = project(add("about", cmd_about, "the project's About; `about edit`, `about history`, `about diff` (leads edit it)"))
    ab.add_argument("--full", action="store_true", help="print all of it")
    absub = ab.add_subparsers(dest="about_cmd")

    def about_project(sp):
        # SUPPRESS: `about --project x edit` keeps the x given before the subcommand.
        sp.add_argument("--project", default=argparse.SUPPRESS, help="project id (default: the one from `project use`, or the only one)")
        return sp
    ae = about_project(add("edit", cmd_about_edit, "leads: edit the About in $EDITOR (or from --file) and save it as a new version", under=absub))
    ae.add_argument("--file", help="save this markdown file as the About instead of opening an editor")
    ae.add_argument("--base", type=int, help="with --file: the version your file started from (default: the latest)")
    ae.add_argument("--force", action="store_true", help="save over the latest version, even if someone saved since you started")
    about_project(add("history", cmd_about_history, "the About's versions, newest first", under=absub))
    ae2 = about_project(add("earlier-overview", cmd_about_earlier,
                            "who sees the Overview's earlier overview; leads: `members` shows it to them, `leads` keeps it for leads",
                            under=absub))
    ae2.add_argument("visible_to", nargs="?", choices=["members", "leads"], metavar="members|leads",
                     help="who sees it (leave out to see who does now)")
    ad = about_project(add("diff", cmd_about_diff, "what changed in a version of the About", under=absub))
    ad.add_argument("version", type=int, help="the version to compare with the one before it")
    ad.add_argument("--to", type=int, help="compare VERSION with this version instead")

    project(add("milestones", cmd_milestones, "the project's milestones, in order, with their tasks done"))
    ms = sub.add_parser("milestone", help="leads: add, edit, move, complete or delete a milestone (numbered as `milestones` lists them)")
    msub = ms.add_subparsers(dest="milestone_cmd", required=True)
    ma = project(add("add", cmd_milestone_add, "add a milestone, last unless --before", under=msub))
    ma.add_argument("title", nargs="+")
    ma.add_argument("--due", help="YYYY-MM-DD")
    ma.add_argument("--summary", help="its one-line description")
    ma.add_argument("--before", type=int, metavar="N", help="put it before milestone N")
    me = project(add("edit", cmd_milestone_edit, "change a milestone's title, date or one-liner", under=msub))
    me.add_argument("n", type=int, metavar="N")
    me.add_argument("--title")
    me.add_argument("--due", help="YYYY-MM-DD, or none")
    me.add_argument("--summary", help="its one-line description")
    mm = project(add("move", cmd_milestone_move, "move a milestone before or after another", under=msub))
    mm.add_argument("n", type=int, metavar="N")
    mm.add_argument("--before", type=int, metavar="M")
    mm.add_argument("--after", type=int, metavar="M")
    md = project(add("done", cmd_milestone_done, "complete a milestone; its open tasks move to the next one unless --leave",
                     under=msub))
    md.add_argument("n", type=int, metavar="N")
    how = md.add_mutually_exclusive_group()
    how.add_argument("--move", action="store_true", help="move its open tasks to the next milestone (the default)")
    how.add_argument("--leave", action="store_true", help="leave its open tasks in it")
    md.add_argument("--yes", action="store_true", help="don't ask (moves its open tasks unless --leave)")
    project(add("reopen", cmd_milestone_reopen, "mark a completed milestone not completed", under=msub)).add_argument(
        "n", type=int, metavar="N")
    mdel = project(add("delete", cmd_milestone_delete, "delete a milestone; its tasks go to No milestone", under=msub))
    mdel.add_argument("n", type=int, metavar="N")
    mdel.add_argument("--yes", action="store_true", help="don't ask")

    # `task new --offer` (cmd_task_new below) is registered with the rest of `task new` in cli.py.

    project(add("offers", cmd_offers, "tasks offered to you; for a lead, the offers on your project too"))
    of = project(add("offer", cmd_offer, "offer <task> <person> (leads); offer accept|decline|withdraw <task>"))
    of.add_argument("words", nargs="+", metavar="ARG",
                    help="<task> <person>, or accept <task>, decline <task>, withdraw <task>. A task is its id or its first 8 characters")
    of.add_argument("-m", "--message", metavar="REASON", help="with decline: why (the lead sees it)")

    po = sub.add_parser("post", help="leads: hide or lock a post (its full id, from its link on the site)")
    psub = po.add_subparsers(dest="post_cmd", required=True)
    for name, fn, help, flag in (
        ("hide", cmd_post_hide, "hide a post; only its author and the leads see it", "a note to its author"),
        ("unhide", cmd_post_unhide, "show a hidden post to everyone again", None),
        ("lock", cmd_post_lock, "lock a post's comments; only leads comment while it's locked", "why (shown on the post)"),
        ("unlock", cmd_post_unlock, "let members comment on a post again", None),
    ):
        sp = add(name, fn, help, under=psub)
        sp.add_argument("post", metavar="post-id", help="the post's full id")
        if flag:
            sp.add_argument("-m", "--message", metavar="NOTE", help=flag)

    # `comment hide|unhide <comment-id>` (cmd_comment_hide/unhide below) goes through cli.py's `comment`,
    # which also comments on a task.


def register_admin(admsub, add) -> None:
    """The leads' admin command, under `stationhouse admin` (cli.py owns the group)."""
    mo = add("migrate-overview", cmd_admin_migrate_overview,
             "move a project's admin-edited plan to its leads' About, milestones and links (a dry run unless --apply)",
             under=admsub)
    mo.add_argument("project_id", metavar="project-id")
    mo.add_argument("--apply", action="store_true", help="write it (without this, it only shows what it would write)")
