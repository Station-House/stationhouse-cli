"""Leads run projects (STA-304 to STA-312): about, milestones, task new, offers, moderation, admin migrate-overview."""
import json
import shlex
import sys

import pytest

from stationhouse_cli import cli, leads

B = "/api/v1/board"
P = f"{B}/projects/conspiracybench"

ADA = {"memberId": "m-ada-0001", "name": "Ada Tester"}
BEN = {"memberId": "m-ben-0002", "name": "Ben Tester"}
CAL = {"memberId": "m-cal-0003", "name": "Cal Tester"}
LIN = {"memberId": "m-lin-0004", "name": "Lin Tester"}

T1 = "8b11d0f4-1111-4111-8111-111111111111"
T2 = "8c22e0a5-2222-4222-8222-222222222222"
POST = "5d2e7c01-3333-4333-8333-333333333333"
COMMENT = "9f00aa11-4444-4444-8444-444444444444"

ABOUT_BODY = ("## Research question\n\nDo judges agree with people on the Berg baseline, and where don't they?\n\n"
              "## Why it matters\n\nBecause.\n")


def about(version=4, by=LIN, at="2026-11-08T10:00:00Z", can_edit=True, body=ABOUT_BODY):
    page = {"id": "page-about", "projectId": "conspiracybench", "kind": "about", "title": "About", "body": body,
            "version": version, "status": "published", "hidden": False, "authorId": by["memberId"],
            "createdAt": at, "updatedAt": at}
    return {"about": {"projectId": "conspiracybench", "page": page, "body": body, "canEdit": can_edit,
                      "summary": None, "saved": {"by": by, "at": at}}}


def milestone(mid, title, position, done=0, total=0, due=None, completed=None, version=1):
    return {"id": mid, "projectId": "conspiracybench", "title": title, "summary": "", "notes": "", "version": version,
            "dueOn": due, "position": position, "completedAt": completed, "tasks": {"done": done, "total": total}}


M1 = milestone("ms-1", "Berg baseline", 1, done=1, total=2, due="2026-11-20")
M2 = milestone("ms-2", "Mini Eval", 2, total=15)
M3 = milestone("ms-3", "Write-up", 3)


def rail(*ms):
    return {"rail": {"projectId": "conspiracybench", "milestones": list(ms), "currentId": ms[0]["id"] if ms else None,
                     "canEdit": True}}


def task(tid, title, state="open", milestone_id=None, offer=None, owners=()):
    t = {"id": tid, "projectId": "conspiracybench", "title": title, "state": state, "owners": list(owners),
         "milestoneId": milestone_id, "parentTaskId": None, "authorId": LIN["memberId"], "willTake": False,
         "createdAt": "2026-11-01T00:00:00Z", "updatedAt": "2026-11-01T00:00:00Z",
         "subtasks": {"done": 0, "total": 0, "tasks": []}}
    if offer:
        t["offer"] = offer
    return t


def tab(groups, proposals=()):
    return {"tasks": {"projectId": "conspiracybench", "groups": groups, "proposals": list(proposals), "canCreate": True,
                      "canPropose": True, "newDraftSeenBy": "leads"}}


def view(tid, title, state="open", offer=None, people=()):
    return {"task": {"task": {**task(tid, title, state), "body": "", "version": 1}, "milestone": None, "milestones": [],
                     "feed": [], "canEdit": True, "people": list(people), "offer": offer, "canOffer": offer is None}}


def offer_view(member=ADA, status="pending"):
    return {"member": member, "status": status, "offeredBy": BEN, "offeredAt": "2026-11-10T00:00:00Z",
            "expiresAt": "2026-11-24T00:00:00Z", "decidedAt": None, "reason": None, "canAnswer": False, "canWithdraw": True}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(leads, "_interactive", lambda args: True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)


def answers(monkeypatch, *replies):
    queue = list(replies)
    prompts = []

    def fake(prompt=""):
        prompts.append(prompt)
        return queue.pop(0)
    monkeypatch.setattr("builtins.input", fake)
    return prompts


# ---------------------------------------------------------------- about

def test_about_shows_the_header_and_the_first_paragraph(signed_in, api, capsys):
    api.routes[("GET", f"{P}/about")] = (200, about())
    api.routes[("GET", "/api/v1/projects/conspiracybench")] = (200, {"project": {"id": "conspiracybench", "title": "Conspiracy Bench"}})
    code, out, _ = run(capsys, "about")
    assert code == 0
    assert out.splitlines()[0] == "About · Conspiracy Bench · version 4 · Lin Tester, Nov 8"
    assert "Do judges agree with people on the Berg baseline" in out and out.rstrip().endswith("…   (--full for all of it)")
    _, out, _ = run(capsys, "about", "--full")
    assert "## Why it matters" in out
    _, out, _ = run(capsys, "about", "--json")
    assert json.loads(out)["about"]["page"]["version"] == 4


def test_about_says_when_there_is_none_yet(signed_in, api, capsys):
    none = about()
    none["about"].update(page=None, saved=None)
    api.routes[("GET", f"{P}/about")] = (200, none)
    _, out, _ = run(capsys, "about")
    assert "conspiracybench has no About yet." in out and "stationhouse about edit" in out


def test_about_earlier_overview_shows_and_sets_who_sees_it(signed_in, api, capsys):
    api.routes[("GET", f"{P}/about")] = (200, about())
    api.routes[("GET", f"{P}/about")][1]["about"]["earlierOverview"] = "members"
    _, out, _ = run(capsys, "about", "earlier-overview")
    assert out.startswith("Members see the earlier overview.")
    hidden = about()
    hidden["about"]["earlierOverview"] = "leads"
    api.routes[("PUT", f"{P}/about/earlier-overview")] = (200, hidden)
    code, out, _ = run(capsys, "about", "earlier-overview", "leads")
    assert code == 0 and out.startswith("The earlier overview is for leads alone.")
    assert api.calls[-1]["body"] == {"visibleTo": "leads"}


def test_about_edit_from_a_file_saves_a_new_version(signed_in, api, capsys, tmp_path):
    f = tmp_path / "about.md"
    f.write_text("## Research question\n\nNew.\n")
    api.routes[("GET", f"{P}/about")] = (200, about())
    api.routes[("PUT", f"{P}/about")] = (200, {"page": {**about()["about"]["page"], "version": 5}})
    code, out, _ = run(capsys, "about", "edit", "--file", str(f))
    assert code == 0 and "Saved version 5. Members see it now." in out
    assert api.calls[-1]["body"] == {"body": "## Research question\n\nNew.\n", "baseVersion": 4}


def test_about_edit_in_the_editor(signed_in, api, capsys, tmp_path, monkeypatch):
    script = tmp_path / "ed.py"
    script.write_text("import sys\np = sys.argv[1]\nopen(p, 'a').write('\\nMore.\\n')\n")
    monkeypatch.setenv("EDITOR", f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    api.routes[("GET", f"{P}/about")] = (200, about())
    api.routes[("PUT", f"{P}/about")] = (200, {"page": {**about()["about"]["page"], "version": 5}})
    code, out, _ = run(capsys, "about", "edit")
    assert code == 0 and "Opening version 4 in" in out and "Saved version 5." in out
    assert api.calls[-1]["body"]["body"] == ABOUT_BODY + "\nMore.\n" and api.calls[-1]["body"]["baseVersion"] == 4


def test_about_edit_conflict_says_who_saved_and_saves_nothing(signed_in, api, capsys, tmp_path):
    f = tmp_path / "about.md"
    f.write_text("mine")
    api.routes[("GET", f"{P}/about")] = [(200, about()), (200, about(version=5, by=LIN))]
    api.routes[("PUT", f"{P}/about")] = (409, {"error": "This page changed since you opened it."})
    code, out, _ = run(capsys, "about", "edit", "--file", str(f))
    assert code == 1
    assert "Version 5 changed since you started (Lin Tester, " in out and "Nothing saved." in out
    assert "Compare: stationhouse about diff 5   Save yours anyway: --force (version 6)" in out


def test_about_edit_force_sends_the_latest_version_as_its_base(signed_in, api, capsys, tmp_path):
    f = tmp_path / "about.md"
    f.write_text("mine")
    api.routes[("GET", f"{P}/about")] = [(200, about(version=4)), (200, about(version=5))]
    api.routes[("PUT", f"{P}/about")] = (200, {"page": {**about()["about"]["page"], "version": 6}})
    code, out, _ = run(capsys, "about", "edit", "--file", str(f), "--force")
    assert code == 0 and "Saved version 6." in out
    assert api.calls[-1]["body"] == {"body": "mine", "baseVersion": 5}


def test_a_members_about_edit_gets_the_servers_message(signed_in, api, capsys, tmp_path):
    f = tmp_path / "about.md"
    f.write_text("mine")
    api.routes[("GET", f"{P}/about")] = (200, about(can_edit=False))
    api.routes[("PUT", f"{P}/about")] = (403, {"error": "Only the project's leads can edit its About."})
    code, _, err = run(capsys, "about", "edit", "--file", str(f))
    assert code == 1 and "Only the project's leads can edit its About." in err


def test_about_history_and_diff(signed_in, api, capsys):
    api.routes[("GET", f"{P}/about")] = (200, about(version=5))
    v5 = {"id": "v5", "version": 5, "authorId": BEN["memberId"], "authorName": "Ben Tester", "createdAt": "2026-11-11T09:00:00Z"}
    v4 = {"id": "v4", "version": 4, "authorId": LIN["memberId"], "authorName": "Lin Tester", "createdAt": "2026-11-08T09:00:00Z"}
    api.routes[("GET", f"{B}/pages/page-about/versions")] = (200, {"versions": [v5, v4]})
    _, out, _ = run(capsys, "about", "history")
    assert out.splitlines() == ["5  Ben Tester  Nov 11", "4  Lin Tester  Nov 8"]
    api.routes[("GET", f"{B}/pages/page-about/diff")] = (200, {"diff": {"from": v4, "to": v5, "lines": [
        {"type": "same", "text": "## Research question"}, {"type": "removed", "text": "Old."}, {"type": "added", "text": "New."}]}})
    _, out, _ = run(capsys, "about", "diff", "5")
    assert api.calls[-1]["path"].endswith("/diff?from=4&to=5")
    assert "Version 4 (Lin Tester, Nov 8) → version 5 (Ben Tester, Nov 11)" in out and "- Old." in out and "+ New." in out


# ---------------------------------------------------------------- milestones

def test_milestones_table(signed_in, api, capsys):
    done = {**M1, "completedAt": "2026-11-09T00:00:00Z"}
    api.routes[("GET", f"{P}/milestones")] = (200, rail(done, M2, M3))
    _, out, _ = run(capsys, "milestones")
    lines = out.splitlines()
    assert lines[0].split() == ["#", "Milestone", "Due", "Tasks"]
    assert "Berg baseline  (completed)" in lines[1] and "Nov 20" in lines[1] and lines[1].endswith("1 of 2 done")
    assert lines[2].endswith("0 of 15") and lines[3].endswith("none yet")


def test_milestone_add_before_puts_it_in_order(signed_in, api, capsys):
    new = milestone("ms-new", "Ablations", 4, due="2027-01-10")
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2, M3))
    api.routes[("POST", f"{P}/milestones")] = (200, rail(M1, M2, M3, new))
    api.routes[("PUT", f"{P}/milestones/order")] = (200, rail(M1, M2, {**new, "position": 3}, {**M3, "position": 4}))
    code, out, _ = run(capsys, "milestone", "add", "Ablations", "--due", "2027-01-10", "--before", "3")
    assert code == 0 and out.strip() == "Added 3. Ablations (due Jan 10). Write-up is now 4."
    post = next(c for c in api.calls if c["method"] == "POST")
    assert post["body"] == {"title": "Ablations", "summary": "", "notes": "", "dueOn": "2027-01-10"}
    assert api.calls[-1]["body"] == {"order": ["ms-1", "ms-2", "ms-new", "ms-3"]}


def test_milestone_edit_sends_every_field_and_its_version(signed_in, api, capsys):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, {**M2, "version": 3}))
    api.routes[("PATCH", f"{B}/milestones/ms-2")] = (200, rail(M1, {**M2, "title": "Mini eval v2"}))
    code, out, _ = run(capsys, "milestone", "edit", "2", "--title", "Mini eval v2", "--due", "none")
    assert code == 0 and "Saved 2. Mini eval v2." in out
    assert api.calls[-1]["body"] == {"title": "Mini eval v2", "summary": "", "notes": "", "dueOn": None, "baseVersion": 3}


def test_milestone_move_after(signed_in, api, capsys):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2, M3))
    api.routes[("PUT", f"{P}/milestones/order")] = (200, rail(M2, M3, M1))
    _, out, _ = run(capsys, "milestone", "move", "1", "--after", "3")
    assert api.calls[-1]["body"] == {"order": ["ms-2", "ms-3", "ms-1"]} and "it's 3. Berg baseline now" in out


def done_routes(api):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2, M3))
    api.routes[("GET", f"{P}/tasks")] = (200, tab([
        {"milestone": {"id": "ms-1", "title": "Berg baseline", "completed": False},
         "tasks": [task(T1, "Run the judges", "doing", "ms-1"), task(T2, "Old idea", "completed", "ms-1")]}]))
    done = {**M1, "completedAt": "2026-11-10T00:00:00Z"}
    api.routes[("PUT", f"{B}/milestones/ms-1/completed")] = (200, {**rail(done, M2, M3), "completion": {"movedTaskIds": [T1], "to": "ms-2"}})


def test_milestone_done_asks_and_moves_the_open_tasks(signed_in, api, capsys, monkeypatch, tty):
    done_routes(api)
    prompts = answers(monkeypatch, "")
    code, out, _ = run(capsys, "milestone", "done", "1")
    assert code == 0 and prompts == ["1. Berg baseline has 1 open task. Move it to 2. Mini Eval? [Y/n, l = leave it here] "]
    assert api.calls[-1]["body"] == {"completed": True, "openTasks": "move"}
    assert "Completed 1. Berg baseline. Posted to Activity." in out and "Moved 1 open task to 2. Mini Eval." in out


def test_milestone_done_can_leave_them(signed_in, api, capsys, monkeypatch, tty):
    done_routes(api)
    answers(monkeypatch, "l")
    run(capsys, "milestone", "done", "1")
    assert api.calls[-1]["body"] == {"completed": True, "openTasks": "leave"}


def test_milestone_done_without_a_terminal_moves_unless_leave(signed_in, api, capsys):
    done_routes(api)
    run(capsys, "milestone", "done", "1")
    assert api.calls[-1]["body"] == {"completed": True, "openTasks": "move"}
    assert not any(c["path"].endswith("/tasks") for c in api.calls)
    run(capsys, "milestone", "done", "1", "--leave")
    assert api.calls[-1]["body"] == {"completed": True, "openTasks": "leave"}


def test_milestone_delete_confirms(signed_in, api, capsys, monkeypatch, tty):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2, M3))
    api.routes[("DELETE", f"{B}/milestones/ms-3")] = (200, rail(M1, M2))
    prompts = answers(monkeypatch, "n")
    code, out, _ = run(capsys, "milestone", "delete", "3")
    assert prompts == ["Delete 3. Write-up? Its 0 tasks move to No milestone. [y/N] "] and code == 1 and "Not deleted." in out
    assert not any(c["method"] == "DELETE" for c in api.calls)
    answers(monkeypatch, "y")
    code, out, _ = run(capsys, "milestone", "delete", "3")
    assert code == 0 and "Deleted Write-up." in out and api.calls[-1]["method"] == "DELETE"


def test_milestone_delete_needs_yes_without_a_terminal(signed_in, api, capsys):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2, M3))
    code, _, err = run(capsys, "milestone", "delete", "3")
    assert code == 1 and "--yes" in err and not any(c["method"] == "DELETE" for c in api.calls)


def test_a_members_milestone_change_gets_the_servers_message(signed_in, api, capsys):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1))
    api.routes[("POST", f"{P}/milestones")] = (403, {"error": "Only the project's leads can change its milestones."})
    code, _, err = run(capsys, "milestone", "add", "Ablations")
    assert code == 1 and "Only the project's leads can change its milestones." in err


# ---------------------------------------------------------------- task new and offers

def test_task_new_in_a_milestone_offered_to_someone(signed_in, api, capsys):
    api.routes[("GET", f"{P}/milestones")] = (200, rail(M1, M2))
    api.routes[("GET", f"{P}/tasks")] = (200, tab([{"milestone": None, "tasks": [task(T2, "Other", "claimed", owners=[ADA])]}]))
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [], "byLeads": []})
    api.routes[("POST", f"{P}/tasks")] = (200, view(T1, "Run the judges", offer=offer_view(ADA)))
    api.routes[("PUT", f"{B}/tasks/{T1}/milestone")] = (200, view(T1, "Run the judges", offer=offer_view(ADA)))
    code, out, _ = run(capsys, "task", "new", "Run the judges", "--milestone", "berg", "--offer", "ada")
    assert code == 0
    assert "Created 8b11d0f4 (Open) in 1. Berg baseline and offered it to Ada Tester." in out
    assert "Withdraw: stationhouse offer withdraw 8b11d0f4" in out
    post = next(c for c in api.calls if c["method"] == "POST")
    assert post["body"] == {"title": "Run the judges", "body": "", "start": "open", "offerTo": ADA["memberId"]}
    assert api.calls[-1]["body"] == {"milestoneId": "ms-1"}


def test_task_new_keeps_task_create_and_request(signed_in, api, capsys):
    parser = cli.build_parser()
    assert parser.parse_args(["task", "create", "p", "t", "-s", "s"]).fn is cli.cmd_task_create
    assert parser.parse_args(["task", "request", "t", "-d", "d"]).fn is cli.cmd_task_request
    assert parser.parse_args(["task", "claim", "x"]).fn is cli.cmd_claim


def offer_item(tid, title, member=ADA, status="pending", reason=None, decided=None):
    return {"taskId": tid, "projectId": "conspiracybench", "title": title, "member": member, "status": status,
            "offeredBy": BEN, "offeredAt": "2026-11-10T00:00:00Z", "expiresAt": "2026-11-24T00:00:00Z",
            "decidedAt": decided, "reason": reason}


def test_offers_for_a_member(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [offer_item(T1, "Run the judges")], "byLeads": []})
    _, out, _ = run(capsys, "offers")
    assert "8b11d0f4  Run the judges   from Ben Tester · expires Nov 24" in out and "Offered to you" not in out
    assert api.calls[0]["path"] == f"{B}/me/offers?projectId=conspiracybench"


def test_offers_for_a_lead_shows_both_sections(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [offer_item(T2, "Review the scorer", member=LIN)], "byLeads": [
        offer_item(T1, "Run the judges"),
        offer_item(T2, "Review the scorer", member=CAL, status="declined", reason="No time", decided="2026-11-11T00:00:00Z")]})
    _, out, _ = run(capsys, "offers")
    assert "Offered to you:" in out and "Your project's offers:" in out
    assert "8b11d0f4  Run the judges  Ada Tester  waiting · expires Nov 24" in out
    assert '8c22e0a5  Review the scorer  Cal Tester  declined Nov 11: "No time"' in out


def test_offer_accept_resolves_the_short_id_from_your_offers(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [offer_item(T1, "Run the judges")], "byLeads": []})
    api.routes[("POST", f"{B}/tasks/{T1}/offer")] = (200, view(T1, "Run the judges", "claimed"))
    code, out, _ = run(capsys, "offer", "accept", "8b11d0f4")
    assert code == 0 and out.strip() == "It's yours: 8b11d0f4 is Claimed."
    assert api.calls[-1]["body"] == {"accept": True}


def test_offer_decline_with_a_reason(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [offer_item(T1, "Run the judges")], "byLeads": []})
    api.routes[("POST", f"{B}/tasks/{T1}/offer")] = (200, view(T1, "Run the judges", offer=offer_view(ADA, "declined")))
    code, out, _ = run(capsys, "offer", "decline", "8b11", "-m", "No time")
    assert code == 0 and "Declined 8b11d0f4." in out and "Ben Tester is told" in out
    assert api.calls[-1]["body"] == {"accept": False, "reason": "No time"}


def test_offer_to_a_person_by_name(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [], "byLeads": []})
    api.routes[("GET", f"{P}/tasks")] = (200, tab([{"milestone": None, "tasks": [task(T1, "Run the judges")]}]))
    api.routes[("GET", f"{B}/tasks/{T1}")] = (200, view(T1, "Run the judges", people=[ADA, BEN]))
    api.routes[("PUT", f"{B}/tasks/{T1}/offer")] = (200, view(T1, "Run the judges", offer=offer_view(ADA)))
    code, out, _ = run(capsys, "offer", "8b11d0f4", "Ada", "Tester")
    assert code == 0 and "Offered 8b11d0f4 to Ada Tester." in out
    assert api.calls[-1]["body"] == {"memberId": ADA["memberId"]}


def test_an_unknown_short_task_id_says_so(signed_in, api, capsys):
    api.routes[("GET", f"{B}/me/offers")] = (200, {"toYou": [], "byLeads": []})
    api.routes[("GET", f"{P}/tasks")] = (200, tab([{"milestone": None, "tasks": [task(T1, "A"), task(T1[:8] + "-9999-4999-8999-999999999999", "B")]}]))
    code, _, err = run(capsys, "offer", "withdraw", "ffff0000")
    assert code == 1 and "No task's id starts with ffff0000" in err
    code, _, err = run(capsys, "offer", "withdraw", "8b11")
    assert code == 1 and "could be any of these" in err


# ---------------------------------------------------------------- moderation

def post_view(title="Raw judge outputs for the Berg baseline"):
    return {"post": {"post": {"id": POST, "projectId": "conspiracybench", "title": title, "author": CAL, "authorId": CAL["memberId"]},
                     "moderation": {"hidden": None, "locked": None}}}


def test_post_hide_with_a_note(signed_in, api, capsys):
    api.routes[("PUT", f"{B}/posts/{POST}/hidden")] = (200, post_view())
    code, out, _ = run(capsys, "post", "hide", POST, "-m", "Please move these to the dataset repo.")
    assert code == 0 and out.strip() == 'Hid "Raw judge outputs for the Berg baseline". Cal Tester sees your note.'
    assert api.calls[-1]["body"] == {"hidden": True, "note": "Please move these to the dataset repo."}


def test_post_lock_and_a_members_403(signed_in, api, capsys):
    api.routes[("PUT", f"{B}/posts/{POST}/locked")] = (200, post_view())
    _, out, _ = run(capsys, "post", "lock", POST, "-m", "Off topic")
    assert out.strip() == f'Locked comments on "Raw judge outputs…". Unlock: stationhouse post unlock {POST}'
    assert api.calls[-1]["body"] == {"locked": True, "reason": "Off topic"}
    api.routes[("PUT", f"{B}/posts/{POST}/locked")] = (403, {"error": "Only the project's leads can lock a post's comments."})
    code, _, err = run(capsys, "post", "lock", POST)
    assert code == 1 and "Only the project's leads can lock a post's comments." in err


def test_post_ids_must_be_whole(signed_in, api, capsys):
    code, _, err = run(capsys, "post", "hide", "5d2e7c01")
    assert code == 1 and "full id" in err and api.calls == []


def test_comment_hide_names_its_author(signed_in, api, capsys):
    comments = [{"id": "c-top", "actorId": "m-x", "actorName": "Ben Tester",
                 "replies": [{"id": COMMENT, "actorId": "m-fay", "actorName": "Fay Tester", "replies": []}]}]
    api.routes[("PUT", f"{B}/comments/{COMMENT}/hidden")] = (200, {"comments": comments})
    code, out, _ = run(capsys, "comment", "hide", COMMENT)
    assert code == 0 and out.strip() == "Hid Fay Tester's comment. They and the leads still see it."
    assert api.calls[-1]["body"] == {"hidden": True}
    _, out, _ = run(capsys, "comment", "unhide", COMMENT)
    assert "Fay Tester's comment shows to everyone again." in out


# ---------------------------------------------------------------- admin migrate-overview (STA-312)

MIGRATE = "/api/admin/projects/consciousness-self-attribution/overview-migration"
ABOUT_PLAN = "## Why this project\n\n" + "x" * 2000 + "\n\n## How it runs\n\n## Plan\n\n## Start here\n\n## Reading list\n"


def report(applied=False, plan=True, about="write"):
    return {"report": {"projectId": "consciousness-self-attribution", "applied": applied,
                       "plan": {"summary": "What makes LLMs self-attribute consciousness, and when do they stop?",
                                "about": ABOUT_PLAN,
                                "milestones": [{"title": "A", "completed": True}, {"title": "B", "completed": True},
                                               {"title": "C", "completed": False}, {"title": "D", "completed": False}],
                                "headerLinks": [{"label": "Repo", "url": "https://example.org"}] * 3} if plan else None,
                       "about": about, "milestones": "write", "headerLinks": 3 if plan else 0,
                       "notified": [ADA["memberId"], BEN["memberId"]] if plan else [],
                       "earlierOverview": "write" if plan else "empty"}}


def test_admin_migrate_overview_dry_run(signed_in, api, capsys):
    api.routes[("POST", MIGRATE)] = (200, report())
    code, out, _ = run(capsys, "admin", "migrate-overview", "consciousness-self-attribution")
    assert code == 0 and api.calls[-1]["body"] == {"apply": False}
    lines = out.splitlines()
    assert lines[0] == "Dry run for consciousness-self-attribution (nothing written; --apply to write it):"
    assert "What makes LLMs self-attribute consciousness…" in lines[1]
    assert f"version 1, {len(ABOUT_PLAN):,} characters: Why this project · How it runs · Plan · Start here · Reading list" in lines[2]
    assert lines[3].endswith("4 (2 completed)") and lines[4].endswith("+3") and lines[5].endswith("2 leads")
    assert lines[6].endswith("hidden from members (leads keep it)")


def test_admin_migrate_overview_apply(signed_in, api, capsys):
    api.routes[("POST", MIGRATE)] = (200, report(applied=True, about="exists"))
    _, out, _ = run(capsys, "admin", "migrate-overview", "consciousness-self-attribution", "--apply")
    assert api.calls[-1]["body"] == {"apply": True}
    assert out.startswith("Migrated consciousness-self-attribution:") and "already has one, left as it is" in out
    _, out, _ = run(capsys, "admin", "migrate-overview", "consciousness-self-attribution", "--apply", "--json")
    assert json.loads(out)["report"]["applied"] is True


def test_admin_migrate_overview_with_no_plan(signed_in, api, capsys):
    api.routes[("POST", MIGRATE)] = (200, report(plan=False))
    _, out, _ = run(capsys, "admin", "migrate-overview", "consciousness-self-attribution")
    assert out.strip() == ("consciousness-self-attribution has no plan stored or in code: nothing to migrate; it starts empty.")


def test_admin_migrate_overview_for_a_non_admin(signed_in, api, capsys):
    api.routes[("POST", MIGRATE)] = (403, {"error": "Admins only."})
    code, _, err = run(capsys, "admin", "migrate-overview", "consciousness-self-attribution")
    assert code == 1 and "Admins only." in err
