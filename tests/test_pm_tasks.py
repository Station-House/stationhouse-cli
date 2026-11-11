"""Project-management tasks from the CLI (STA-321 onwards): `tasks`, `task <number>` and `unclaimed`
print the platform's answers as the designs do (briefs: the CLI frames), from the same fixtures the
platform's route tests write (tests/fixtures/v1, `npm run cli:fixtures`), so a change to the API's
shape that would break these fails in the platform's PR. Catalog projects print as before.

The expected text is in tests/expected/<name>.txt; output is plain when piped, as here.
"""
import json
from pathlib import Path

import pytest

from stationhouse_cli import cli

FIXTURES = Path(__file__).parent / "fixtures" / "v1"
EXPECTED = Path(__file__).parent / "expected"
P = "marin-neuron-atlas"
BASE = f"/api/v1/projects/{P}"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def expected(name):
    return (EXPECTED / f"{name}.txt").read_text()


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def marin(signed_in, api, monkeypatch):
    monkeypatch.setenv("STATIONHOUSE_PROJECT", P)
    api.routes[("GET", f"{BASE}/tasks")] = (200, fixture("tasks"))
    api.routes[("GET", f"{BASE}/unclaimed")] = (200, fixture("unclaimed"))
    api.routes[("GET", f"{BASE}/tasks/1")] = (200, fixture("task"))
    api.routes[("GET", f"{BASE}/tasks/99")] = (404, fixture("task-not-found"))
    api.routes[("GET", BASE)] = (200, {"project": {"id": P, "taskModel": "project_management"}})
    return api


# ---------------------------------------------------------------- what they print

def test_tasks_prints_the_list_by_milestone_with_numbers_and_proposals_apart(marin, capsys):
    code, out, _ = run(capsys, "tasks")
    assert code == 0 and out == expected("tasks")


def test_task_number_prints_one_task_with_its_latest_activity(marin, capsys):
    code, out, _ = run(capsys, "task", "1")
    assert code == 0 and out == expected("task")
    assert marin.calls[-1]["path"] == f"{BASE}/tasks/1"


def test_task_feed_prints_all_of_it(marin, capsys):
    code, out, _ = run(capsys, "task", "1", "--feed")
    assert code == 0 and "Activity\n" in out and "ada-tester created it" in out and "Latest" not in out


def test_unclaimed_on_a_project_management_project_is_the_open_tasks(marin, capsys):
    code, out, _ = run(capsys, "unclaimed")
    assert code == 0 and out == expected("unclaimed")


def test_tasks_state_unclaimed_is_the_same_list(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--state", "unclaimed")
    assert out == expected("unclaimed").replace("Nothing unclaimed", "No tasks match")


def test_json_is_the_platforms_answer(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--json")
    assert json.loads(out) == fixture("tasks")
    _, out, _ = run(capsys, "task", "1", "--json")
    assert json.loads(out)["task"]["id"] == fixture("task")["task"]["id"]


# ---------------------------------------------------------------- naming a task

def test_task_number_is_task_show_and_task_claim_is_still_its_subcommand():
    parser = cli.build_parser()
    assert cli._task_show(parser, ["task", "12"]) == ["task", "show", "12"]
    assert cli._task_show(parser, ["task", "claim", "12"]) == ["task", "claim", "12"]
    assert cli._task_show(parser, ["task", "--help"]) == ["task", "--help"]


def test_project_hash_number_goes_to_that_project(marin, capsys, monkeypatch):
    monkeypatch.setenv("STATIONHOUSE_PROJECT", "conspiracybench")
    code, _, _ = run(capsys, "task", f"{P}#1")
    assert code == 0 and marin.calls[-1]["path"] == f"{BASE}/tasks/1"


def test_a_number_with_no_project_picked_asks_which(signed_in, api, capsys, monkeypatch):
    monkeypatch.delenv("STATIONHOUSE_PROJECT")
    api.routes[("GET", "/api/v1/projects")] = (200, {"projects": [{"id": P, "title": "Marin"}, {"id": "conspiracybench", "title": "CB"}]})
    code, _, err = run(capsys, "task", "1")
    assert code == 1 and "Which project?" in err


def test_an_unknown_number_is_the_platforms_error(marin, capsys):
    code, _, err = run(capsys, "task", "99")
    assert code == 1 and err == "error: No such task.\n"


# ---------------------------------------------------------------- filters

def test_state_filter_lists_matching_subtasks_under_a_dimmed_parent(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--state", "open")
    assert "    #8   Open       Llama run" in out and "5 tasks" in out


def test_milestone_matches_the_start_of_a_title(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--milestone", "elic")
    assert "Elicitation" in out and "Baseline" not in out and "Proposed" not in out


def test_milestone_that_matches_none_or_two_says_so(marin, capsys):
    tasks = fixture("tasks")
    tasks["milestones"].append({"id": "m3", "title": "Elicitation round 2", "dueOn": None, "completed": False})
    marin.routes[("GET", f"{BASE}/tasks")] = (200, tasks)
    code, _, err = run(capsys, "tasks", "--milestone", "zzz")
    assert code == 1 and "No milestone matches 'zzz'" in err
    code, _, err = run(capsys, "tasks", "--milestone", "elic")
    assert code == 1 and "matches Elicitation, Elicitation round 2" in err


def test_mine_lists_only_yours(marin, capsys):
    _, out, _ = run(capsys, "tasks", "--mine")
    assert "#1 " in out and "#2 " not in out and "Re-run Petri" in out and "base-model" not in out


def test_an_unknown_state_names_the_ones_there_are(marin, capsys):
    code, _, err = run(capsys, "tasks", "--state", "finished")
    assert code == 1 and "Unknown state 'finished'" in err


# ---------------------------------------------------------------- catalog projects, as before

CATALOG_TREE = {"project": "conspiracybench", "you": "me", "tasks": [
    {"taskId": "add-question", "title": "Add a question", "closed": False, "people": [{"hfUsername": "ada"}]},
    {"taskId": "old", "title": "Old", "closed": True, "people": []},
]}


def test_tasks_on_a_catalog_project_lists_the_catalog(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks")] = (200, CATALOG_TREE)
    code, out, _ = run(capsys, "tasks")
    assert code == 0 and out == "add-question  Add a question  (ada)\n"


def test_catalog_unclaimed_prints_as_before(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/unclaimed")] = (200, {"tasks": [{"taskId": "add-question", "title": "Add a question", "summary": "Write one."}]})
    _, out, _ = run(capsys, "unclaimed")
    assert out == "add-question  Add a question\n    Write one.\n"


def test_task_on_a_catalog_project_shows_the_catalog_task(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/add-question")] = (200, {
        "projectId": "conspiracybench", "taskId": "add-question", "title": "Add a question", "summary": "Write one.",
        "completionCriteria": "Merged.", "people": [{"hfUsername": "me", "you": True}]})
    code, out, _ = run(capsys, "task", "add-question")
    assert code == 0 and "Add a question (conspiracybench/add-question)" in out and "me (you)" in out


# ---------------------------------------------------------------- claim, release, move (STA-322)

def test_claim_says_you_own_it_and_follow_it_and_what_comes_next(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/2/claim")] = (200, fixture("claim"))
    code, out, _ = run(capsys, "claim", "2")
    assert code == 0 and out == (
        'You\'re an owner of #2 "Add error bars to the Berg replication". It\'s Claimed.\n'
        "You follow it now, so you'll hear about comments and changes.\n"
        "Next: stationhouse move 2 doing, once you start.\n")


def test_claim_named_by_project_says_the_next_command_the_same_way(marin, capsys, monkeypatch):
    monkeypatch.setenv("STATIONHOUSE_PROJECT", "conspiracybench")
    marin.routes[("POST", f"{BASE}/tasks/2/claim")] = (200, fixture("claim"))
    _, out, _ = run(capsys, "task", "claim", f"{P}#2")
    assert f"Next: stationhouse move {P}#2 doing" in out


def test_a_refused_claim_is_the_boards_message_then_where_to_join(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/2/claim")] = (403, fixture("claim-not-joined"))
    marin.routes[("GET", f"{BASE}/tasks/2")] = (200, fixture("release"))
    code, _, err = run(capsys, "claim", "2")
    assert code == 1 and err == (
        "error: Join this project to claim its tasks.\n"
        "       Join: http://localhost/projects/private/marin-neuron-atlas\n")


def test_a_claim_on_an_owned_task_names_its_owners(marin, capsys):
    taken = fixture("task")
    taken["task"]["owners"] = [{"memberId": "sub-eve", "name": "eve-tester"}]
    marin.routes[("POST", f"{BASE}/tasks/4/claim")] = (409, fixture("claim-taken"))
    marin.routes[("GET", f"{BASE}/tasks/4")] = (200, taken)
    _, _, err = run(capsys, "claim", "4")
    assert err == (
        "error: Only an Open task can be claimed, and this task is Claimed. Its owners can add you as a co-owner.\n"
        "       Its owners: eve-tester\n")


def test_release_and_its_unclaim_alias_put_it_back_to_open(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/2/release")] = (200, fixture("release"))
    for verb in ("release", "unclaim"):
        code, out, _ = run(capsys, verb, "2")
        assert code == 0 and out == (
            'You\'re no longer an owner of #2 "Add error bars to the Berg replication". It\'s Open again.\n'
            "You still follow it.\n")


def test_release_leaving_others_on_it_says_who(marin, capsys):
    kept = fixture("task")
    kept["task"]["owners"] = [{"memberId": "sub-ada", "name": "ada-tester"}]
    marin.routes[("POST", f"{BASE}/tasks/1/release")] = (200, kept)
    _, out, _ = run(capsys, "release", "1")
    assert out.startswith('You\'re no longer an owner of #1 "Run the direct-ask baseline on 3 models". It\'s Doing, with ada-tester.\n')


def test_move_says_from_and_to_and_what_comes_next(marin, capsys):
    marin.routes[("PUT", f"{BASE}/tasks/1/state")] = (200, fixture("move"))
    code, out, _ = run(capsys, "move", "1", "review")
    assert code == 0 and out == (
        '#1 "Run the direct-ask baseline on 3 models": Doing → In review.\n'
        "A lead completes it, or merging its PR does.\n")
    assert marin.calls[-1]["body"] == {"state": "in_review"}


def test_a_refused_move_lists_the_states_you_can_pick(marin, capsys):
    marin.routes[("PUT", f"{BASE}/tasks/1/state")] = (403, fixture("move-leads-only"))
    marin.routes[("GET", f"{BASE}/tasks/1")] = (200, fixture("move"))
    code, _, err = run(capsys, "move", "1", "done")
    assert code == 1 and err == (
        "error: Only the project's leads can move a task from In review to Completed.\n"
        "       You can move it to: claimed, doing. Merging its PR completes it too.\n")
    assert marin.calls[-2]["body"] == {"state": "completed"}


def test_move_to_a_state_there_isnt_says_which_there_are(marin, capsys):
    code, _, err = run(capsys, "move", "1", "sideways")
    assert code == 1 and err == "error: Unknown state 'sideways'. Move it to one of: claimed, doing, review, done, open.\n"


def test_move_json_is_the_platforms_answer(marin, capsys):
    marin.routes[("PUT", f"{BASE}/tasks/1/state")] = (200, fixture("move"))
    _, out, _ = run(capsys, "move", "1", "review", "--json")
    assert json.loads(out) == fixture("move")


def test_catalog_claim_and_its_refusal_print_as_before(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/claim")] = (200, {"taskId": "add-question", "people": [{"hfUsername": "me", "you": True}]})
    _, out, _ = run(capsys, "claim", "add-question")
    assert out == "You're on add-question.\n"
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/claim")] = (409, {"error": "This task is full."})
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/add-question")] = (200, {"projectId": "conspiracybench", "taskId": "add-question"})
    code, _, err = run(capsys, "claim", "add-question")
    assert code == 1 and err == "error: This task is full.\n"


# ---------------------------------------------------------------- propose and the leads' actions (STA-323)

def test_propose_with_take_prints_the_frame(marin, capsys, tmp_path):
    idea = tmp_path / "idea.md"
    idea.write_text("Same items, base vs chat.")
    marin.routes[("POST", f"{BASE}/tasks")] = (201, fixture("propose"))
    code, out, _ = run(capsys, "propose", "Compare against a base model", "--body-file", str(idea), "--take")
    assert code == 0 and out == (
        f'Proposed #14 "Compare against a base model" in {P}.\n'
        "A lead approves it, sends it back with a comment, or declines it. You said you'll take it,\n"
        "so once it's approved you're its owner.\n"
        "Follow it: stationhouse task 14\n")
    assert marin.calls[-1]["body"] == {"title": "Compare against a base model", "body": "Same items, base vs chat.",
                                       "start": "proposed", "willTake": True}


def test_propose_a_draft_by_its_number(marin, capsys):
    proposed = fixture("propose")
    proposed["task"]["proposal"]["willTake"] = False
    marin.routes[("POST", f"{BASE}/tasks/15/propose")] = (200, proposed)
    code, out, _ = run(capsys, "propose", "--draft", "15")
    assert code == 0 and "declines it.\nFollow it" in out and marin.calls[-1]["body"] == {"willTake": False}


def test_propose_on_a_catalog_project_points_at_a_request(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench")] = (200, {"project": {"id": "conspiracybench", "taskModel": "catalog"}})
    code, _, err = run(capsys, "propose", "An idea")
    assert code == 1 and err == (
        "error: conspiracybench hasn't moved to project management yet.\n"
        '       Ask for a task there: stationhouse task request "<title>" -d "<why>"\n')


def test_task_request_on_a_project_management_project_points_at_propose(marin, capsys):
    code, _, err = run(capsys, "task", "request", "An idea", "-d", "Because.")
    assert code == 1 and err == (
        f"error: {P} runs project management: propose the task to its leads instead.\n"
        '       stationhouse propose "An idea" -b "<what and why>"\n')


def test_task_new_writes_a_draft_and_says_how_to_propose_it(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks")] = (201, fixture("task-new"))
    code, out, _ = run(capsys, "task", "new", "Tidy the notebook")
    assert code == 0 and out == (
        f'Wrote #15 "Tidy the notebook" in {P}. It\'s a Draft.\n'
        "Propose it to the leads: stationhouse propose --draft 15\n")
    assert marin.calls[-1]["body"] == {"title": "Tidy the notebook", "body": "", "start": "draft"}


def test_task_new_open_in_a_milestone(marin, capsys):
    opened = fixture("open")
    marin.routes[("POST", f"{BASE}/tasks")] = (201, opened)
    marin.routes[("PUT", f"{BASE}/tasks/{opened['task']['id']}/milestone")] = (200, opened)
    code, out, _ = run(capsys, "task", "new", "Pick the judge model", "--open", "--milestone", "base")
    assert code == 0 and out == (
        f'Opened #14 "Pick the judge model" in {P}. It\'s in Baseline evals.\n'
        "Anyone who joined can claim it: stationhouse claim 14\n")
    assert marin.calls[-1]["body"] == {"milestoneId": fixture("tasks")["milestones"][0]["id"]}


def test_task_new_says_the_draft_exists_when_its_milestone_fails(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks")] = (201, fixture("task-new"))
    new_id = fixture("task-new")["task"]["id"]
    marin.routes[("PUT", f"{BASE}/tasks/{new_id}/milestone")] = (503, {"error": "Couldn't set the milestone right now."})
    code, out, err = run(capsys, "task", "new", "Tidy the notebook", "--milestone", "base")
    assert code == 1
    # The task was written: say so, and how to finish the job.
    assert out.startswith(f'Wrote #15 "Tidy the notebook" in {P}. It\'s a Draft.\n')
    assert err == ("error: Draft #15 was created without its milestone (Baseline evals): Couldn't set the milestone right now.\n"
                   '       Set it: stationhouse task milestone 15 "Baseline evals"\n')


def test_task_proposals_on_a_project_management_project(marin, capsys):
    code, out, _ = run(capsys, "task", "proposals")
    assert code == 0 and out.startswith(
        "Proposed (2), waiting for a lead\n"
        "  #12  Add a base-model comparison      by eve-tester, will take it\n"
        "  #13  Re-run Petri with the new judge  by you\n")


def test_approve_by_number_into_a_milestone(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/12/approve")] = (200, fixture("approve"))
    code, out, _ = run(capsys, "task", "approve", "12", "--milestone", "elic")
    assert code == 0 and out == 'Approved #12 "Add a base-model comparison". It\'s Claimed, with eve-tester as its owner. It\'s in Elicitation.\n'
    assert marin.calls[-1]["body"] == {"milestoneId": fixture("tasks")["milestones"][1]["id"]}


def test_catalog_approve_by_proposal_id_is_unchanged(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/proposals/approve")] = (200, {"taskId": "new-sub", "claimed": False})
    _, out, _ = run(capsys, "task", "approve", "prop-abc123")
    assert out.startswith("Created new-sub.") and api.calls[-1]["body"] == {"proposalId": "prop-abc123"}


def test_send_back_decline_and_reopen(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/13/send-back")] = (200, fixture("send-back"))
    _, out, _ = run(capsys, "task", "send-back", "13", "-m", "Say which judge.")
    assert out == ('Sent #13 "Re-run Petri with the new judge" back to bo-tester as a Draft, with your comment.\n'
                   "They can propose it again: stationhouse propose --draft 13\n")
    assert marin.calls[-1]["body"] == {"comment": "Say which judge."}

    marin.routes[("POST", f"{BASE}/tasks/12/decline")] = (200, fixture("decline"))
    _, out, _ = run(capsys, "task", "decline", "12", "--reason", "Petri v2 covers it.", "--duplicate-of", "#3")
    assert out == ('Declined #12 "Add a base-model comparison", as a duplicate of "Petri seed set v2".\n'
                   "Changed your mind? stationhouse task reopen 12\n")
    assert marin.calls[-1]["body"] == {"reason": "Petri v2 covers it.", "duplicateOf": "#3"}
    # This project's task by its project's name is fine; another project's is refused before any call.
    run(capsys, "task", "decline", "12", "--reason", "Covered.", "--duplicate-of", "marin-neuron-atlas#3")
    assert marin.calls[-1]["body"] == {"reason": "Covered.", "duplicateOf": "marin-neuron-atlas#3"}
    calls = len(marin.calls)
    code, _, err = run(capsys, "task", "decline", "12", "--reason", "Covered there.", "--duplicate-of", "llm-self-attribution#5")
    assert code == 1 and len(marin.calls) == calls
    assert err == ("error: The duplicate must be a task in marin-neuron-atlas, the proposal's project: llm-self-attribution#5 "
                   "is in llm-self-attribution. Decline it without --duplicate-of, and say where in --reason.\n")

    marin.routes[("POST", f"{BASE}/tasks/12/reopen")] = (200, fixture("reopen"))
    _, out, _ = run(capsys, "task", "reopen", "12")
    assert out == 'Reopened #12 "Add a base-model comparison". It\'s Proposed again, waiting for a lead.\n'


def test_task_open_opens_a_draft(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/14/open")] = (200, fixture("open"))
    _, out, _ = run(capsys, "task", "open", "14")
    assert out == 'Opened #14 "Pick the judge model". It\'s in Baseline evals. Anyone who joined can claim it.\n'


# ---------------------------------------------------------------- mine (STA-325)

CLAIMS = {"claims": [{"projectId": "conspiracybench", "taskId": "add-question", "title": "Add a question", "status": "ACTIVE", "stale": False}]}


def test_mine_lists_your_tasks_by_project_then_catalog_claims(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/tasks")] = (200, fixture("mine"))
    api.routes[("GET", "/api/v1/me/claims")] = (200, CLAIMS)
    code, out, _ = run(capsys, "mine")
    assert code == 0 and out == (
        f"{P}\n"
        "  #1  Doing      Run the direct-ask baseline on 3 models  with ada-tester\n"
        "\n"
        "conspiracybench (older tasks: your own progress)\n"
        "  add-question  Add a question  (active)\n")
    _, out, _ = run(capsys, "mine", "--json")
    assert json.loads(out) == {"tasks": fixture("mine")["tasks"], "claims": CLAIMS["claims"]}


def test_mine_all_asks_for_completed_ones_too(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/tasks")] = (200, {"tasks": []})
    api.routes[("GET", "/api/v1/me/claims")] = (200, {"claims": []})
    _, out, _ = run(capsys, "mine", "--all")
    assert "all=1" in api.calls[0]["path"] and out == "You're not on any tasks.\n"


def test_mine_without_a_verified_handle_still_lists_your_tasks(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/tasks")] = (200, fixture("mine"))
    api.routes[("GET", "/api/v1/me/claims")] = (409, {"error": "Verify your Hugging Face username first."})
    code, out, _ = run(capsys, "mine")
    assert code == 0 and out.startswith(P) and "older tasks" not in out


def test_mine_without_a_verified_handle_or_tasks_says_youre_on_none(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/tasks")] = (200, {"tasks": []})
    api.routes[("GET", "/api/v1/me/claims")] = (409, {"error": "Verify your Hugging Face username first."})
    code, out, _ = run(capsys, "mine")
    assert code == 0 and out.startswith("You're not on any tasks.")


def test_mine_on_an_older_platform_is_the_claims_as_before(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/claims")] = (409, {"error": "Verify your Hugging Face username first."})
    code, _, err = run(capsys, "mine")
    assert code == 1 and err == "error: Verify your Hugging Face username first.\n"


# ---------------------------------------------------------------- comment (STA-324)

def test_comment_hide_without_an_id_asks_for_one(marin, capsys):
    # `comment` comments on a task, and leads' `comment hide|unhide <comment-id>` (STA-311) shares it.
    calls = len(marin.calls)
    code, _, err = run(capsys, "comment", "hide")
    assert code == 1 and len(marin.calls) == calls
    assert err == "error: Say which comment: stationhouse comment hide <comment-id> (its full id).\n"


def test_comment_posts_it_and_says_when_the_task_started(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/2/comments")] = (200, fixture("comment"))
    code, out, _ = run(capsys, "comment", "2", "Starting", "with", "the", "Berg", "CSV.")
    assert code == 0 and out == (
        'Commented on #2 "Add error bars to the Berg replication".\n'
        "It's Doing now: an owner's comment shows the work has started.\n")
    assert marin.calls[-1]["body"] == {"body": "Starting with the Berg CSV."}


def test_comment_reads_stdin_and_replies(marin, capsys, monkeypatch):
    import io
    marin.routes[("POST", f"{BASE}/tasks/2/comments")] = (200, {**fixture("comment"), "from": "doing"})
    monkeypatch.setattr("sys.stdin", io.StringIO("Line one\nLine two\n"))
    _, out, _ = run(capsys, "comment", "2", "-", "--reply-to", "c-1")
    assert out == 'Replied to a comment on #2 "Add error bars to the Berg replication".\n'
    assert marin.calls[-1]["body"] == {"body": "Line one\nLine two\n", "replyTo": "c-1"}


def test_an_empty_comment_is_refused_here(marin, capsys):
    code, _, err = run(capsys, "comment", "2")
    assert code == 1 and err.startswith("error: Say something")


# ---------------------------------------------------------------- cliUpdateRequired (STA-326)

def test_the_update_message_is_printed_as_the_platform_says_it(marin, capsys):
    marin.routes[("GET", f"{BASE}/tasks")] = (409, fixture("cli-update-required"))
    code, _, err = run(capsys, "tasks")
    assert code == 1 and err == f"error: {fixture('cli-update-required')['error']}\n"


def test_this_cli_is_new_enough_for_project_management():
    from stationhouse_cli import __version__, config
    assert tuple(int(n) for n in __version__.split(".")[:2]) >= (0, 3)
    assert config.user_agent().startswith(f"stationhouse-cli/{__version__} ")


# ---------------------------------------------------------------- the second wave (STA-327)

def test_assign_by_number_adds_an_owner(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/2/owners")] = (200, fixture("assign"))
    code, out, _ = run(capsys, "assign", "2", "@eve-tester")
    assert code == 0 and out == 'Added eve-tester as an owner of #2 "Add error bars to the Berg replication". It\'s Claimed, owned by eve-tester.\n'
    assert marin.calls[-1]["body"] == {"who": "@eve-tester"}


def test_assign_on_a_catalog_task_is_the_admins_as_before(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/assign")] = (200, {})
    _, out, _ = run(capsys, "assign", "add-question", "@ada")
    assert out == "Assigned ada to add-question.\n" and api.calls[-1]["body"] == {"hfUsername": "ada"}


def test_unassign_takes_an_owner_off(marin, capsys):
    marin.routes[("DELETE", f"{BASE}/tasks/2/owners/eve-tester")] = (200, fixture("unassign"))
    _, out, _ = run(capsys, "unassign", "2", "eve-tester")
    assert out == 'Took eve-tester off #2 "Add error bars to the Berg replication". It\'s Claimed, owned by bo-tester.\n'


def test_task_edit_sends_the_version_it_read(marin, capsys):
    task = fixture("task")
    marin.routes[("PATCH", f"{BASE}/tasks/1")] = (200, task)
    code, out, _ = run(capsys, "task", "edit", "1", "--title", "Run the direct-ask baseline on 3 models")
    assert code == 0 and out == 'Saved #1 "Run the direct-ask baseline on 3 models".\n'
    assert marin.calls[-1]["body"] == {"title": "Run the direct-ask baseline on 3 models", "body": task["task"]["body"],
                                       "baseVersion": task["task"]["version"]}


def test_task_edit_needs_something_to_change(marin, capsys):
    code, _, err = run(capsys, "task", "edit", "1")
    assert code == 1 and "Say what to change" in err


def test_task_milestone_by_title_or_none(marin, capsys):
    marin.routes[("PUT", f"{BASE}/tasks/6/milestone")] = (200, fixture("milestone"))
    _, out, _ = run(capsys, "task", "milestone", "6", "elic")
    assert out == '#6 "Collect failure cases from the discussions" is in Elicitation now.\n'
    assert marin.calls[-1]["body"] == {"milestoneId": fixture("tasks")["milestones"][1]["id"]}
    run(capsys, "task", "milestone", "6", "none")
    assert marin.calls[-1]["body"] == {"milestoneId": None}


def test_task_subtask_adds_one_and_says_how_to_claim_it(marin, capsys):
    marin.routes[("POST", f"{BASE}/tasks/3/subtasks")] = (200, fixture("subtask"))
    _, out, _ = run(capsys, "task", "subtask", "3", "Seeds", "D")
    assert out == ('Added subtask #14 "Seeds D" to #3 "Petri seed set v2". It\'s Open.\n'
                   "Claim it: stationhouse claim 14\n")
    assert marin.calls[-1]["body"] == {"title": "Seeds D", "body": ""}


def test_task_subtask_on_a_catalog_task_points_at_task_create(signed_in, api, capsys):
    code, _, err = run(capsys, "task", "subtask", "add-question", "More")
    assert code == 1 and "stationhouse task create add-question" in err


# ---------------------------------------------------------------- explore and find-work (STA-328)

def test_explore_answers_from_a_project_management_list(marin, capsys):
    code, out, _ = run(capsys, "explore", "who is on the petri seed set?")
    assert code == 0 and out.startswith("#3  Petri seed set v2  [3 subtasks]\n    In review · Baseline evals\n    On it: eve-tester (active)")


def test_explore_unclaimed_lists_the_open_tasks_nobody_owns(marin, capsys):
    _, out, _ = run(capsys, "explore", "what is unclaimed?")
    assert "open tasks nobody is on" in out and "#2  Add error bars" in out and "#4 " not in out


def test_explore_mine_on_a_project_management_project(marin, capsys):
    _, out, _ = run(capsys, "explore", "what am I working on?")
    assert out.startswith("You're on 1 task.\n#1  Run the direct-ask baseline on 3 models")


def test_find_work_on_a_project_management_project_is_the_unclaimed_list(marin, capsys):
    code, out, _ = run(capsys, "find-work")
    assert code == 0 and out == expected("unclaimed") + "find-work is now: stationhouse tasks --state unclaimed (or stationhouse unclaimed)\n"
