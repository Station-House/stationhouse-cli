"""Project-management tasks in the terminal: how `tasks`, `task <number>`, `claim`, `move` and the
rest print what the platform answers (GET /api/v1/projects/<p>/tasks and friends, `model:
"project_management"`). A task is named by its number in its project (#12), so `task 12` works in the
project you're in and `llm-self-attribution#12` anywhere; `--json` carries the full id too.

Grey in the designs is ANSI dim, on a terminal only: piped, the output is plain text.
"""
import os
import re
import sys
import textwrap
from datetime import datetime

PM = "project_management"

STATE_LABELS = {
    "draft": "Draft", "proposed": "Proposed", "open": "Open", "claimed": "Claimed", "doing": "Doing",
    "in_review": "In review", "completed": "Completed", "declined": "Declined",
}
# The words `move` takes for each state, and what `--state` accepts besides the states' own names.
STATE_W = max(len(label) for label in STATE_LABELS.values())  # the state column's width
STATE_WORDS = {"claimed": "claimed", "doing": "doing", "in_review": "review", "completed": "done", "open": "open"}
STATE_ALIASES = {
    "review": "in_review", "in-review": "in_review", "inreview": "in_review", "done": "completed", "complete": "completed",
    "unclaimed": "open",
}

# `project#12`, `#12` or `12`; anything else (a catalog slug, a UUID) is passed through as it is.
_REF = re.compile(r"^(?:(?P<project>[a-z0-9][a-z0-9-]*)?#)?(?P<number>[1-9][0-9]{0,8})$", re.I)


def split_ref(ref: str) -> tuple[str | None, str]:
    """("llm-self-attribution", "12") for `llm-self-attribution#12`; (None, "12") for `12` or `#12`;
    (None, ref) for anything else."""
    m = _REF.match(ref.strip())
    if not m:
        return None, ref
    return (m.group("project").lower() if m.group("project") else None), m.group("number")


def is_number(ref: str) -> bool:
    return _REF.match(ref.strip()) is not None


def is_pm(data) -> bool:
    return isinstance(data, dict) and (data.get("model") == PM or (isinstance(data.get("task"), dict) and data["task"].get("model") == PM))


def _styled(stream=None) -> bool:
    return (stream or sys.stdout).isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def dim(text: str, stream=None) -> str:
    """Grey in the frames: ANSI dim on a terminal (`stream`, stdout by default), plain when piped."""
    return f"\x1b[2m{text}\x1b[0m" if text and _styled(stream) else text


def person(p: dict | None) -> str:
    if not p:
        return "a member"
    return "you" if p.get("you") else (p.get("name") or "a member")


def people(owners: list) -> str:
    return ", ".join(person(o) for o in owners)


def _day(iso: str) -> str:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"{d.strftime('%b')} {d.day}"


def _due(date: str) -> str:
    d = datetime.fromisoformat(date)
    return f"{d.strftime('%b')} {d.day}"


# ---------------------------------------------------------------- the task list

def parse_states(text: str | None) -> set[str] | None:
    if not text:
        return None
    states = set()
    for word in (w.strip().lower() for w in text.split(",") if w.strip()):
        state = STATE_ALIASES.get(word, word.replace("-", "_"))
        if state not in STATE_LABELS:
            names = ", ".join(sorted({*STATE_WORDS.values(), "unclaimed", "proposed", "draft"}))
            raise ValueError(f"Unknown state {word!r}. Use one of: {names}.")
        states.add(state)
    return states


def match_milestone(milestones: list, text: str) -> list:
    """Milestones whose id is `text`, or whose title starts with it (case-insensitive)."""
    want = text.strip().lower()
    exact = [m for m in milestones if m["id"] == text or m["title"].lower() == want]
    return exact or [m for m in milestones if m["title"].lower().startswith(want)]


def filtered(data: dict, states=None, milestone=None, mine=False, everything=False) -> dict:
    """The list narrowed as `tasks` was asked: by state, milestone and mine; Completed only with --all
    (or when asked for by --state). A parent stays when one of its subtasks matches, and the matching
    subtasks are listed under it."""
    narrowed = states is not None or milestone is not None or mine

    def keep(t):
        if states is not None:
            if t["state"] not in states:
                return False
        elif t["state"] == "completed" and not everything:
            return False
        return not mine or t.get("mine")

    groups = []
    for g in data.get("groups", []):
        if milestone is not None and (g["milestone"] or {}).get("id") != milestone:
            continue
        rows = []
        for t in g["tasks"]:
            subs = [s for s in t.get("subtaskRows", []) if keep(s)] if narrowed else []
            if keep(t) or subs:
                rows.append({**t, "shownSubtasks": subs, "matches": keep(t)})
        groups.append({"milestone": g["milestone"], "tasks": rows})
    proposals = data.get("proposals", [])
    if milestone is not None or (states is not None and "proposed" not in states):
        proposals = []
    elif mine:
        proposals = [p for p in proposals if (p.get("proposer") or {}).get("you")]
    return {**data, "groups": groups, "proposals": proposals, "narrowed": narrowed}


def as_json(shown: dict) -> dict:
    """A narrowed list in the platform's shape: each row's `subtaskRows` are the ones that matched."""
    groups = [{"milestone": g["milestone"], "tasks": [{**{k: v for k, v in t.items() if k not in ("shownSubtasks", "matches")}, "subtaskRows": t["shownSubtasks"]}
                                                      for t in g["tasks"]]} for g in shown["groups"] if g["tasks"]]
    return {**{k: v for k, v in shown.items() if k != "narrowed"}, "groups": groups}


def render_list(data: dict, project: str, unclaimed: bool = False) -> None:
    groups = [g for g in data["groups"] if g["tasks"]]
    proposals = data.get("proposals", [])
    # The tasks that answer what was asked: a parent listed only for its subtasks doesn't count.
    count = sum(t.get("matches", True) + len(t["shownSubtasks"]) for g in groups for t in g["tasks"]) + len(proposals)
    print(dim(f"{project} · project management · {count} task{'s' if count != 1 else ''}"))
    if count == 0:
        print()
        if unclaimed or data.get("narrowed"):
            print("No tasks match." if not unclaimed else "Nothing unclaimed right now.")
        else:
            print('No tasks yet. Propose one: stationhouse propose "<title>"')
        return
    tops = [t for g in groups for t in g["tasks"]]
    subs = [s for t in tops for s in t["shownSubtasks"]]
    rows = tops + subs
    # A subtask's number sits two further in, under its parent's, and the columns after it still line up.
    num_w = max([len("#" + str(t["number"])) for t in tops + proposals] + [len("#" + str(s["number"])) + 2 for s in subs])
    state_w = max((len(STATE_LABELS[t["state"]]) for t in rows), default=0)
    title_w = max((len(t["title"]) for t in rows), default=0)

    def line(t, sub=False):
        owners = people(t["owners"]) if t["owners"] else "·"
        counts = t.get("subtasks") or {}
        extra = f"   {counts['done']} of {counts['total']} subtasks" if counts.get("total") else ""
        number = ("  " if sub else "") + "#" + str(t["number"])
        text = f"{number:<{num_w}}  {STATE_LABELS[t['state']]:<{state_w}}  {t['title']:<{title_w}}  {owners}{extra}".rstrip()
        # A parent listed only for its subtasks is there for context: dimmed.
        return "  " + (text if t.get("matches", True) else dim(text))

    for g in groups:
        m = g["milestone"]
        print()
        if m is None:
            print("No milestone")
        else:
            print(m["title"] + (dim(f"  (due {_due(m['dueOn'])})") if m.get("dueOn") else ""))
        for t in g["tasks"]:
            print(line(t))
            for s in t["shownSubtasks"]:
                print(line(s, sub=True))
    if proposals:
        print()
        _print_proposals(proposals, num_w)
    print()
    print(dim("Claim one: stationhouse claim <number>.  More: stationhouse task <number>"))
    if not data.get("narrowed") and not unclaimed:
        print(dim("Only the open ones: stationhouse tasks --state unclaimed (or stationhouse unclaimed)"))


def _print_proposals(proposals: list, num_w: int) -> None:
    print(f"Proposed ({len(proposals)}), waiting for a lead")
    pw = max(len(p["title"]) for p in proposals)
    for p in proposals:
        by = f"by {person(p.get('proposer'))}" + (", will take it" if p.get("willTake") else "")
        number = "#" + str(p["number"])
        print(f"  {number:<{num_w}}  {p['title']:<{pw}}  {by}")


def render_proposals(data: dict, project: str) -> None:
    """`task proposals` on a project-management project: the Proposed group, and a lead's next steps."""
    proposals = data.get("proposals", [])
    if not proposals:
        print(f"No proposals waiting in {project}.")
        return
    _print_proposals(proposals, max(len(f"#{p['number']}") for p in proposals))
    print()
    print(dim("Decide: stationhouse task approve <number>, task send-back <number> -m \"…\", task decline <number> --reason \"…\""))


# ---------------------------------------------------------------- one task

def _wrap(text: str, width: int) -> list[str]:
    out = []
    for para in text.splitlines() or [""]:
        out.extend(textwrap.wrap(para, width) or [""])
    return out


def _feed_lines(entry: dict, date_w: int, reply: bool = False) -> list[str]:
    day = f"{_day(entry['at']):<{date_w}}"
    if entry["kind"] == "comment":
        body = entry.get("body")
        text = f"{person(entry['by'])}: {' '.join(body.split()) if body is not None else '(comment removed)'}"
    else:
        text = entry["text"]
    lead = f"  {day}  " + ("↳ " if reply else "")
    wrapped = textwrap.wrap(text, 64) or [""]
    out = [lead + wrapped[0]] + [" " * len(lead) + rest for rest in wrapped[1:]]
    for r in entry.get("replies", []) if not reply else []:
        out.extend(_feed_lines(r, date_w, reply=True))
    return out


def _you_can(task: dict) -> str:
    can = task.get("can") or {}
    parts = []
    states = [STATE_WORDS[s] for s in can.get("states", []) if s in STATE_WORDS]
    if states:
        parts.append("move it to " + ", ".join(states))
    if can.get("claim"):
        parts.append("claim")
    if can.get("release"):
        parts.append("release")
    if can.get("propose"):
        parts.append("propose")
    if can.get("decide"):
        parts.extend(["approve", "send back", "decline"])
    if can.get("reopen"):
        parts.append("reopen")
    parts.append("comment")  # follow/unfollow join these with the task follow command (STA-324, after #441)
    return "You can: " + " · ".join(parts)


def render_task(data: dict, whole_feed: bool = False) -> None:
    t = data["task"]
    print(t["title"])
    meta = [f"#{t['number']}", STATE_LABELS[t["state"]]]
    if t.get("milestone"):
        meta.append(t["milestone"]["title"])
    meta.append(t["projectId"])
    print(dim(" · ".join(meta)))
    if t.get("parent"):
        print(f"Part of: {t['parent']['title']}")
    if t["state"] in ("draft", "proposed", "declined") and t.get("proposal"):
        p = t["proposal"]
        print(f"Proposed by {person(p['proposer'])}" + (", who will take it" if p.get("willTake") else ""))
        if p.get("declined"):
            print(f"Declined: {p['declined']['reason']}")
    else:
        print(f"Owners: {people(t['owners']) if t['owners'] else 'nobody yet'}")
    print(dim(t["url"]))
    if t.get("body", "").strip():
        print()
        for row in _wrap(t["body"].strip(), 76):
            print(f"  {row}".rstrip())
    subs = t.get("subtaskRows") or []
    if subs:
        print()
        print(f"Subtasks ({t['subtasks']['done']} of {t['subtasks']['total']} done)")
        num_w = max(len("#" + str(s["number"])) for s in subs)
        title_w = max(len(s["title"]) for s in subs)
        for s in subs:
            number = "#" + str(s["number"])
            if s["state"] == "completed":
                print(f"  ✓ {number:<{num_w}}  {s['title']}")
            else:
                print(f"    {number:<{num_w}}  {s['title']:<{title_w}}  {STATE_LABELS[s['state']]}")
    feed = t.get("feed") or []
    shown = feed if whole_feed else feed[-5:]
    if shown:
        print()
        print("Activity" if whole_feed else "Latest")
        date_w = max(len(_day(e["at"])) for e in shown)
        for e in shown:
            for row in _feed_lines(e, date_w):
                print(row)
    print()
    print(dim(_you_can(t)))


def render_catalog_task(d: dict) -> None:
    """`task <id>` on a project that still runs catalog tasks: what it is and who is on it."""
    print(f"{d['title']} ({d.get('projectId', '?')}/{d['taskId']})")
    if d.get("summary"):
        print(f"  {d['summary']}")
    if d.get("completionCriteria"):
        print(f"  Done when: {d['completionCriteria']}")
    ppl = d.get("people") or []
    print("  People: " + (", ".join(p["hfUsername"] + (" (you)" if p.get("you") else "") for p in ppl) if ppl else "nobody yet"))


def render_catalog_list(d: dict) -> None:
    """`tasks` on a project that still runs catalog tasks: id, title and who is on each."""
    tasks = [t for t in d.get("tasks", []) if not t.get("closed")]
    if not tasks:
        print("No tasks here yet.")
    for t in tasks:
        ppl = ", ".join(p["hfUsername"] for p in t.get("people", []))
        print(f"{t['taskId']}  {t['title']}" + (f"  ({ppl})" if ppl else ""))


# ---------------------------------------------------------------- claim, release, move (STA-322)

MOVE_WORDS = ("claimed", "doing", "review", "done", "open")


def parse_move(word: str) -> str:
    """The state `move` sets: claimed, doing, review (in-review), done (completed) or open."""
    w = word.strip().lower()
    state = STATE_ALIASES.get(w, w.replace("-", "_"))
    if state not in STATE_WORDS:
        raise ValueError(f"Unknown state {word!r}. Move it to one of: {', '.join(MOVE_WORDS)}.")
    return state


def ref_for(typed: str, task: dict) -> str:
    """How a next command names the task: `project#n` when that's how it was named, else its number."""
    named, _ = split_ref(typed)
    return f"{named}#{task['number']}" if named else str(task["number"])


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def names_pm_task(ref: str) -> bool:
    """True for a reference only a project-management task has: a number (`12`, `#12`, `project#12`)
    or a page's UUID. A catalog task is a slug."""
    return is_number(split_ref(ref)[1]) or bool(_UUID.match(ref.strip()))


def named(task: dict) -> str:
    return _named(task)


def _named(task: dict) -> str:
    return f'#{task["number"]} "{task["title"]}"'


def render_claim(data: dict, typed: str) -> None:
    t = data["task"]
    print(f"You're an owner of {_named(t)}. It's {STATE_LABELS.get(t['state'], t['state'])}.")
    if t.get("following"):
        print("You follow it now, so you'll hear about comments and changes.")
    if "doing" in t.get("can", {}).get("states", []):
        print(dim(f"Next: stationhouse move {ref_for(typed, t)} doing, once you start."))


def render_release(data: dict, typed: str) -> None:
    t = data["task"]
    others = [o for o in t.get("owners", []) if not o.get("you")]
    if t["state"] == "open":
        print(f"You're no longer an owner of {_named(t)}. It's Open again.")
    else:
        print(f"You're no longer an owner of {_named(t)}. It's {STATE_LABELS.get(t['state'], t['state'])}, with {people(others)}.")
    if t.get("following"):
        print(dim("You still follow it."))


# What to do next, once a task is in a state (the frames' grey line under a move).
AFTER_MOVE = {
    "doing": "Next: stationhouse move {ref} review, when it's ready for a lead.",
    "in_review": "A lead completes it, or merging its PR does.",
}


def render_move(data: dict, typed: str) -> None:
    t = data["task"]
    to = STATE_LABELS.get(t["state"], t["state"])
    before = data.get("from")
    if before == t["state"]:
        print(f"{_named(t)} is already {to}.")
        return
    print(f"{_named(t)}: {STATE_LABELS.get(before, before)} → {to}.")
    after = AFTER_MOVE.get(t["state"])
    if after:
        print(dim(after.format(ref=ref_for(typed, t))))


def claim_hint(message: str, task: dict) -> str | None:
    """The CLI's line under a refused claim: where to join, or who owns it."""
    if message.startswith("Join this project"):
        return f"Join: {task['projectUrl']}" if task.get("projectUrl") else None
    others = [o for o in task.get("owners", []) if not o.get("you")]
    return f"Its owners: {people(others)}" if others else None


def release_hint(message: str, task: dict) -> str | None:
    others = [o for o in task.get("owners", []) if not o.get("you")]
    return f"Its owners: {people(others)}" if others else None


def move_hint(target: str, task: dict) -> str | None:
    """The CLI's line under a refused move: the states the caller can pick from where it is."""
    states = task.get("can", {}).get("states", [])
    words = [STATE_WORDS.get(s, s) for s in states]
    line = f"You can move it to: {', '.join(words)}." if words else ""
    if target == "completed" and "completed" not in states:
        line = f"{line} Merging its PR completes it too.".strip()
    return line or None


# ---------------------------------------------------------------- proposals and the leads' actions (STA-323)

def render_proposed(data: dict, project: str, typed: str) -> None:
    t = data["task"]
    print(f"Proposed {_named(t)} in {project}.")
    if (t.get("proposal") or {}).get("willTake"):
        print("A lead approves it, sends it back with a comment, or declines it. You said you'll take it,")
        print("so once it's approved you're its owner.")
    else:
        print("A lead approves it, sends it back with a comment, or declines it.")
    print(dim(f"Follow it: stationhouse task {typed}"))


def _in_milestone(t: dict) -> str:
    return f" It's in {t['milestone']['title']}." if t.get("milestone") else ""


def render_new(data: dict, project: str, typed: str) -> None:
    """`task new`: a Draft (for its author, and a lead's for the leads too) or, with --open, an Open task."""
    t = data["task"]
    if t["state"] == "open":
        print(f"Opened {_named(t)} in {project}.{_in_milestone(t)}")
        print(dim(f"Anyone who joined can claim it: stationhouse claim {typed}"))
        return
    print(f"Wrote {_named(t)} in {project}. It's a Draft.{_in_milestone(t)}")
    if t.get("can", {}).get("propose"):
        print(dim(f"Propose it to the leads: stationhouse propose --draft {typed}"))
    elif "open" in t.get("can", {}).get("states", []):
        print(dim(f"Open it: stationhouse task open {typed}"))


def render_decision(action: str, data: dict, typed: str) -> None:
    """What a lead's action did: open, approve, send-back, decline, reopen."""
    t = data["task"]
    state = STATE_LABELS.get(t["state"], t["state"])
    proposer = person((t.get("proposal") or {}).get("proposer") or t.get("author"))
    ref = ref_for(typed, t)
    if action == "open":
        print(f"Opened {_named(t)}.{_in_milestone(t)} Anyone who joined can claim it.")
    elif action == "approve":
        owners = [o for o in t.get("owners", [])]
        who = f", with {people(owners)} as its owner" if owners else ""
        print(f"Approved {_named(t)}. It's {state}{who}.{_in_milestone(t)}")
    elif action == "send-back":
        print(f"Sent {_named(t)} back to {proposer} as a Draft, with your comment.")
        print(dim(f"They can propose it again: stationhouse propose --draft {ref}"))
    elif action == "decline":
        declined = (t.get("proposal") or {}).get("declined") or {}
        dup = declined.get("duplicateOf")
        print(f"Declined {_named(t)}" + (f", as a duplicate of \"{dup['title']}\"." if dup else "."))
        print(dim(f"Changed your mind? stationhouse task reopen {ref}"))
    elif action == "reopen":
        print(f"Reopened {_named(t)}. It's {state} again, waiting for a lead.")


# ---------------------------------------------------------------- mine (STA-325)

def render_mine(data: dict, everything: bool = False) -> None:
    """The tasks you own, by project, with whoever else owns them; then catalog claims, as before."""
    tasks, claims = data.get("tasks", []), data.get("claims", [])
    if not tasks and not claims:
        print("You're not on any tasks." + ("" if everything else " Find one: stationhouse tasks --state unclaimed"))
        return
    by_project: dict = {}
    for t in tasks:
        by_project.setdefault(t["projectId"], []).append(t)
    num_w = max((len(f"#{t['number']}") for t in tasks), default=0)
    title_w = max((len(t["title"]) for t in tasks), default=0)
    for i, (project, rows) in enumerate(by_project.items()):
        if i:
            print()
        print(project)
        for t in rows:
            others = [o for o in t.get("owners", []) if not o.get("you")]
            number = f"#{t['number']}"
            state = STATE_LABELS.get(t["state"], t["state"])
            line = f"  {number:<{num_w}}  {state:<{STATE_W}}  {t['title']:<{title_w}}"
            print((line + "  " + dim("with " + people(others)) if others else line).rstrip())
    catalog: dict = {}
    for c in claims:
        catalog.setdefault(c.get("projectId") or "", []).append(c)
    for project, rows in catalog.items():
        if tasks or project != next(iter(catalog)):
            print()
        print(f"{project or 'other'} " + dim("(older tasks: your own progress)"))
        for c in rows:
            title = f"  {c['title']}" if c.get("title") else ""
            print(f"  {c['taskId']}{title}  ({c.get('status', 'ACTIVE').lower()}{', stale' if c.get('stale') else ''})")


# ---------------------------------------------------------------- comment (STA-324)

def render_comment(data: dict, reply: bool = False) -> None:
    t = data["task"]
    print(f"{'Replied to a comment' if reply else 'Commented'} on {_named(t)}.")
    if data.get("from") == "claimed" and t["state"] == "doing":
        print(dim("It's Doing now: an owner's comment shows the work has started."))


# ---------------------------------------------------------------- the second wave (STA-327)

def render_owners(data: dict, who: str, added: bool) -> None:
    t = data["task"]
    state = STATE_LABELS.get(t["state"], t["state"])
    owners = t.get("owners", [])
    who = who.lstrip("@")
    first = f"Added {who} as an owner of {_named(t)}." if added else f"Took {who} off {_named(t)}."
    print(f"{first} It's {state}" + (f", owned by {people(owners)}." if owners else ", with no owners."))


def render_milestone(data: dict) -> None:
    t = data["task"]
    where = f"in {t['milestone']['title']}" if t.get("milestone") else "in no milestone"
    print(f"{_named(t)} is {where} now.")


def render_subtask(data: dict, title: str, typed: str) -> None:
    parent = data["task"]
    added = [s for s in parent.get("subtaskRows", []) if s["title"] == title]
    sub = added[-1] if added else None
    if sub is None:
        print(f"Added a subtask to {_named(parent)}.")
        return
    print(f"Added subtask #{sub['number']} \"{sub['title']}\" to {_named(parent)}. It's Open.")
    named_project = split_ref(typed)[0]
    ref = f"{named_project}#{sub['number']}" if named_project else str(sub["number"])
    print(dim(f"Claim it: stationhouse claim {ref}"))


# ---------------------------------------------------------------- explore and find-work (STA-328)

def as_tree(data: dict) -> dict:
    """A project-management task list in the shape `explore` reads (the catalog's tree), so its
    deterministic answers work on both: each task named `#n`, its owners as the people on it."""
    rows = [r for g in data.get("groups", []) for r in g.get("tasks", [])]
    rows += [s for r in list(rows) for s in r.get("subtaskRows", [])]
    number_of = {r["id"]: r["number"] for r in rows}
    tasks = []
    for r in rows:
        tasks.append({
            "taskId": f"#{r['number']}",
            "title": r["title"],
            "summary": STATE_LABELS.get(r["state"], r["state"]) + (f" · {r['milestone']['title']}" if r.get("milestone") else ""),
            "people": [{"hfUsername": o.get("name") or "a member", "you": bool(o.get("you")), "claimed": True, "stale": False}
                       for o in r.get("owners", [])],
            "available": r["state"] not in ("draft", "proposed", "declined"),
            "closed": r["state"] == "completed",
            "mine": bool(r.get("mine")),
            "claimedByYou": bool(r.get("mine")),
            "parentTaskId": f"#{number_of[r['parentId']]}" if r.get("parentId") in number_of else None,
            "childTaskIds": [f"#{s['number']}" for s in r.get("subtaskRows", [])],
        })
    return {"project": (data.get("project") or {}).get("id"), "you": True, "tasks": tasks}
