"""Reviews, templates, tags and deadlines from the CLI (STA-376 to STA-382): `task review`, `tasks
--needs-review` and `--tag`, `task start`, `drop`, `archive`, and --tag/--untag/--due/--reviews/
--template on `task new` and `task edit`, printed as the CLI frames word them, from the fixtures the
platform's route tests write (tests/fixtures/v1, `npm run cli:fixtures`).
"""
import json
from pathlib import Path

import pytest

from stationhouse_cli import cli

FIXTURES = Path(__file__).parent / "fixtures" / "v1"
P = "marin-neuron-atlas"
BASE = f"/api/v1/projects/{P}"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def marin(signed_in, api, monkeypatch):
    monkeypatch.setenv("STATIONHOUSE_PROJECT", P)
    api.routes[("GET", f"{BASE}/tasks")] = (200, fixture("tasks-review"))
    api.routes[("GET", BASE)] = (200, {"project": {"id": P, "taskModel": "project_management"}})
    return api


# ---------------------------------------------------------------- reviews (STA-376 to STA-378)

def test_tasks_needs_review_lists_the_ones_you_can_review_with_their_approvals(marin, capsys):
    code, out, _ = run(capsys, "tasks", "--needs-review")
    assert code == 0 and out == (
        "marin-neuron-atlas · 1 task needs a review you can give\n"
        "\n"
        "Baseline evals  (due Nov 21)\n"
        "  #3  In review  Petri seed set v2  eve-tester   0 of 1\n"
        "\n"
        'Review one: stationhouse task review <n> --approve | --request-changes "<note>"\n'
    )


def test_tasks_needs_review_with_nothing_waiting(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks")] = (200, fixture("tasks"))
    _, out, _ = run(capsys, "tasks", "--needs-review")
    assert out == "Nothing needs a review you can give in marin-neuron-atlas.\n"


def test_request_changes_needs_a_note_and_says_whose_approval_it_needs(marin, capsys):
    code, _, err = run(capsys, "task", "review", "3", "--request-changes")
    assert code == 1 and 'Say what to change: --request-changes "<what to change>"' in err
    marin.routes[("POST", f"{BASE}/tasks/3/review")] = (200, fixture("review-changes"))
    _, out, _ = run(capsys, "task", "review", "3", "--request-changes", "Add the seed you used.")
    assert out == ("↺ Asked for changes on #3. It's back in Doing, and eve-tester was told.\n"
                   "  When it's in review again, your approval is the one it needs.\n")
    assert marin.calls[-1]["body"] == {"verdict": "changes_requested", "note": "Add the seed you used."}


def test_approve_with_a_note_completes_it(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/3/review")] = (200, fixture("review-approve"))
    _, out, _ = run(capsys, "task", "review", "3", "--approve", "-m", "Thanks, looks right.")
    assert out == ('✓ Approved #3 "Petri seed set v2".\n'
                   "  1 of 1 approvals, so it's Completed. eve-tester was told.\n")
    assert marin.calls[-1]["body"] == {"verdict": "approved", "note": "Thanks, looks right."}


def test_an_owners_review_is_refused_with_who_can(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/3/review")] = (403, {"error": "You own this task, so you can't review it."})
    marin.routes[("GET", f"{BASE}/tasks/3")] = (200, fixture("review-changes"))
    code, _, err = run(capsys, "task", "review", "3", "--approve")
    assert code == 1 and "You own this task, so you can't review it." in err and "Anyone else in marin-neuron-atlas can." in err


def test_a_task_shows_its_reviews_tags_and_deadline(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks/3")] = (200, fixture("review-changes"))
    _, out, _ = run(capsys, "task", "3")
    assert "#3 · Doing · Baseline evals · marin-neuron-atlas\nQuick · Evals · due Jun 28 · needs 1 approval\n" in out
    assert ("Reviews: 0 of 1 approvals\n"
            "  Nov 10  you asked for changes: Add the seed you used.\n"
            "You asked for changes, so your approval is the one it needs (or a lead's).\n") in out


def test_move_to_review_says_what_it_needs(marin, capsys):
    moved = fixture("review-changes")
    moved["task"] = {**moved["task"], "state": "in_review", "reviewHistory": {**moved["task"]["reviewHistory"], "waitingOn": []}}
    marin.routes[("PUT", f"{BASE}/tasks/3/state")] = (200, {**moved, "from": "doing"})
    _, out, _ = run(capsys, "move", "3", "review")
    assert out == "◕ #3 is In review. It needs 1 approval; marin-neuron-atlas's followers were told.\n"


# ---------------------------------------------------------------- templates (STA-379, STA-380)

def test_a_template_shows_its_copies_and_how_to_start_one(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks/14")] = (200, fixture("template"))
    _, out, _ = run(capsys, "task", "14")
    assert out.startswith("Submit a hillclimbing experiment\n"
                          "#14 · Template · marin-neuron-atlas\n"
                          "2 doing · 0 done · each copy needs 1 review\n")
    assert "Your copies: #16 Claimed, #15 Claimed\nStart your own: stationhouse task start 14\n" in out


def test_task_start_makes_your_copy(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/14/copies")] = (201, fixture("copy-start"))
    _, out, _ = run(capsys, "task", "start", "14")
    assert out == ("→ Started #15, your copy of #14 Submit a hillclimbing experiment. It's Claimed.\n"
                   "  The brief is in it to fill in: stationhouse task edit 15 --body-file notes.md\n"
                   "  When it's done: stationhouse move 15 review\n")


def test_task_start_on_a_task_that_isnt_a_template_points_at_claim(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/3/copies")] = (409, {"error": "Only a template has copies to start. Claim this task instead."})
    marin.routes[("GET", f"{BASE}/tasks/3")] = (200, fixture("review-changes"))
    code, _, err = run(capsys, "task", "start", "3")
    assert code == 1 and "Claim it instead: stationhouse claim 3" in err


def test_task_drop_says_whether_the_copy_is_gone(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/15/drop")] = (200, fixture("drop"))
    _, out, _ = run(capsys, "task", "drop", "15")
    assert out == ("Dropped your copy #15. Nobody had said anything on it, so it's gone.\n"
                   "Start another: stationhouse task start 14\n")


def test_archive_says_what_stays_and_how_to_undo(marin, capsys):
    marin.routes[("PUT", f"{BASE}/tasks/14/archived")] = (200, fixture("archive"))
    _, out, _ = run(capsys, "task", "archive", "14")
    assert out == ("Archived #14: no new copies. The brief, its discussion and its copy stay readable.\n"
                   "Undo: stationhouse task unarchive 14\n")
    assert marin.calls[-1]["body"] == {"archived": True}


# ---------------------------------------------------------------- tags and deadlines (STA-381, STA-382)

def test_tasks_tag_filters_in_any_letter_case(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--tag", "quick")
    assert out.startswith("marin-neuron-atlas · 1 task tagged Quick\n\nBaseline evals  (due Nov 21)\n"
                          "  #3  In review  Petri seed set v2  eve-tester   2 of 3 subtasks   due Jun 28\n")


def test_task_edit_sets_tags_and_clears_the_deadline(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks/3")] = (200, fixture("details"))
    marin.routes[("PUT", f"{BASE}/tasks/3/details")] = (200, fixture("details"))
    _, out, _ = run(capsys, "task", "edit", "3", "--tag", "Quick", "--untag", "Writing", "--due", "none")
    assert marin.calls[-1]["body"] == {"addTags": ["Quick"], "removeTags": ["Writing"], "dueOn": None}
    assert out == "Updated #3: Quick · Evals · due Jun 28 · needs 1 approval\n"


def test_a_members_tag_and_a_past_deadline_are_refused_in_the_clis_words(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks/3")] = (200, fixture("details"))
    marin.routes[("PUT", f"{BASE}/tasks/3/details")] = (403, {"error": "Only the project's leads set tags, deadlines, reviews required and templates."})
    code, _, err = run(capsys, "task", "edit", "3", "--tag", "Quick")
    assert code == 1 and "Only marin-neuron-atlas's leads can change a task's tags, deadline, reviews or template." in err
    marin.routes[("POST", f"{BASE}/tasks")] = (400, {"error": "That date has passed. Pick today or a later date."})
    code, _, err = run(capsys, "task", "new", "Fix the judge seed", "--due", "2026-11-02")
    assert code == 1 and "--due 2026-11-02 has passed. Use today or later, or leave it out." in err


def test_task_new_with_details_and_as_a_template(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks")] = (201, fixture("copy-start") | {"task": fixture("template")["task"]})
    _, out, _ = run(capsys, "task", "new", "Submit a hillclimbing experiment", "--template", "--reviews", "1", "--tag", "Experiment")
    assert marin.calls[-1]["body"] == {"title": "Submit a hillclimbing experiment", "body": "", "start": "open",
                                       "tags": ["Experiment"], "reviewsRequired": 1, "template": True}
    assert out == "Created template #14. Members start their own: stationhouse task start 14\n"
