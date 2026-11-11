import json

import pytest

from stationhouse_cli import cli
from stationhouse_cli.store import load_credentials

TASKS = {"tasks": [{"taskId": "add-question", "title": "Add a question", "summary": "Write one."}]}
PEOPLE = {"taskId": "add-question", "title": "Add a question",
          "people": [{"hfUsername": "ada", "prNums": [12], "stale": False},
                     {"hfUsername": "bob", "stale": True}]}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- signed out (STA-335)

def test_reads_work_signed_out_without_a_token(api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/unclaimed")] = (200, TASKS)
    code, out, _ = run(capsys, "unclaimed")
    assert code == 0 and "add-question  Add a question" in out
    assert "authorization" not in {k.lower() for k in api.calls[0]["headers"]}


def test_whoami_signed_out_says_whether_this_server_reads_signed_out(api, capsys):
    """Public reading is a switch on the server (#457): whoami asks once, without a token."""
    api.routes[("GET", "/api/v1/projects")] = (200, {"projects": []})
    code, out, _ = run(capsys, "whoami")
    assert (code, out) == (0, "Not signed in. Public reads work on this server; sign in to act: stationhouse login\n")
    assert [c["path"] for c in api.calls] == ["/api/v1/projects"]
    assert "authorization" not in {k.lower() for k in api.calls[0]["headers"]}
    _, out, _ = run(capsys, "whoami", "--json")
    assert json.loads(out) == {"signedIn": False, "publicReads": True}

    api.routes[("GET", "/api/v1/projects")] = (401, {"error": "Sign in required."})
    code, out, _ = run(capsys, "whoami")
    assert (code, out) == (0, "Not signed in, and this server doesn't have public reading on: sign in to read or act: stationhouse login\n")
    _, out, _ = run(capsys, "whoami", "--json")
    assert json.loads(out) == {"signedIn": False, "publicReads": False}

    api.routes[("GET", "/api/v1/projects")] = (503, {"error": "Down for a moment."})
    code, out, _ = run(capsys, "whoami")
    assert (code, out) == (0, "Not signed in. Reads work signed out only where the server has public reading on; sign in to act: stationhouse login\n")


def test_updates_and_activity_signed_out_say_what_to_sign_in_for_without_calling(api, capsys, monkeypatch):
    """#444's commands are members only, like the site's Activity. `update post` asks before the editor opens."""
    from stationhouse_cli import updates
    monkeypatch.setattr(updates, "read_text", lambda *a, **k: pytest.fail("the editor opened signed out"))
    for argv, doing in [
        (["activity", "llm-self-attribution"], "see the activity in llm-self-attribution"),
        (["update", "latest", "llm-self-attribution"], "read the latest update in llm-self-attribution"),
        (["update", "show", "u-1"], "read update u-1"),
        (["update", "post", "llm-self-attribution"], "post an update to llm-self-attribution"),
        (["update", "edit", "u-1", "--status", "at-risk"], "edit update u-1"),
        (["update", "delete", "u-1", "--yes"], "delete update u-1"),
    ]:
        code, _, err = run(capsys, *argv)
        assert (argv, code, err.splitlines()[0]) == (argv, 1, f"Sign in to {doing}: stationhouse login")
    assert not api.calls


def test_an_action_signed_out_says_what_to_sign_in_for_and_to_run_it_again_without_calling(api, capsys):
    code, out, err = run(capsys, "claim", "add-question")
    assert code == 1 and out == ""
    assert err == "Sign in to claim add-question: stationhouse login\n(then run stationhouse claim add-question again)\n"
    assert not api.calls


def test_a_member_only_read_signed_out_asks_to_sign_in_without_calling(api, capsys):
    code, _, err = run(capsys, "mine")
    assert code == 1 and err.startswith("Sign in to see your tasks: stationhouse login\n")
    assert not api.calls


def test_join_and_follow_signed_out_say_what_to_sign_in_for_without_calling(api, capsys):
    code, _, err = run(capsys, "join", "llm-self-attribution")
    assert code == 1 and err.startswith("Sign in to join llm-self-attribution: stationhouse login\n")
    code, _, err = run(capsys, "follow", "--page", "p-1")
    assert code == 1 and err.startswith("Sign in to follow page p-1: stationhouse login\n")
    code, _, err = run(capsys, "following")
    assert code == 1 and err.startswith("Sign in to see what you follow: stationhouse login\n")
    assert not api.calls


def test_project_management_writes_signed_out_ask_to_sign_in_without_calling(api, capsys):
    """#452's task commands: every write signs in first, before the network (STA-335). Only visitor
    reads go out (the project's task model)."""
    from stationhouse_cli.client import visitor_may
    import json
    from pathlib import Path
    pm = Path(__file__).parent / "fixtures" / "v1"
    base = "/api/v1/projects/llm-self-attribution"
    api.routes[("GET", base)] = (200, {"project": {"id": "llm-self-attribution", "taskModel": "project_management"}})
    # Edit and milestone read first (visitor GETs, which go out), then sign in before writing.
    api.routes[("GET", f"{base}/tasks/12")] = (200, json.loads((pm / "task.json").read_text()))
    api.routes[("GET", f"{base}/tasks")] = (200, json.loads((pm / "tasks.json").read_text()))
    for argv, doing in [
        (["move", "12", "doing"], "move 12"),
        (["comment", "12", "hello"], "comment on 12"),
        (["propose", "A", "new", "idea"], "propose a task"),
        (["task", "new", "A", "title"], "write a task"),
        (["task", "decline", "12", "--reason", "Duplicate"], "decline 12"),
        (["unassign", "12", "ada"], "change who's on 12"),
        (["task", "edit", "12", "--title", "T"], "edit 12"),
        (["task", "milestone", "12", "Elicitation"], "move 12 to a milestone"),
    ]:
        code, _, err = run(capsys, *argv, "--project", "llm-self-attribution")
        assert (argv, code, err.splitlines()[0]) == (argv, 1, f"Sign in to {doing}: stationhouse login")
    assert all(visitor_may(c["method"], c["path"].split("?")[0]) for c in api.calls)
    assert all("authorization" not in {k.lower() for k in c["headers"]} for c in api.calls)


def test_a_project_management_task_list_is_a_visitor_read(api, capsys):
    """GET …/tasks is documented as open to visitors: it goes out, without a token."""
    api.routes[("GET", "/api/v1/projects/llm-self-attribution")] = (200, {"project": {"id": "llm-self-attribution", "taskModel": "project_management"}})
    api.routes[("GET", "/api/v1/projects/llm-self-attribution/tasks")] = (200, {"model": "project_management", "milestones": [], "proposed": []})
    run(capsys, "tasks", "--project", "llm-self-attribution")
    assert any(c["path"].startswith("/api/v1/projects/llm-self-attribution/tasks") for c in api.calls)
    assert all("authorization" not in {k.lower() for k in c["headers"]} for c in api.calls)


def test_lead_helpers_let_sign_in_through_instead_of_reading_nothing(api):
    """leads.py's broad `except ApiError` would take a signed-out caller's SignInRequired for "no
    people" or "no project": it passes through, so the command says "Sign in to …"."""
    import pytest
    from stationhouse_cli import leads
    from stationhouse_cli.client import SignInRequired
    with pytest.raises(SignInRequired):
        leads._people("llm-self-attribution")  # the @ picker's people: a member-only read
    assert not api.calls
    api.routes[("GET", "/api/v1/projects/llm-self-attribution")] = (401, {"error": "Sign in required."})
    with pytest.raises(SignInRequired):
        leads._project_title("llm-self-attribution")


def test_a_public_read_answering_401_signed_out_still_asks_to_sign_in(api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/unclaimed")] = (401, {"error": "Sign in required."})
    code, _, err = run(capsys, "unclaimed")
    assert code == 1 and err.startswith("Sign in to ")
    assert "authorization" not in {k.lower() for k in api.calls[0]["headers"]}


VISITOR_READS = [
    "/api/v1/projects", "/api/v1/projects/p", "/api/v1/projects/p/tasks", "/api/v1/projects/p/tasks/t",
    "/api/v1/projects/p/tasks/t/context", "/api/v1/projects/p/tasks/t/people", "/api/v1/projects/p/unclaimed",
    "/api/v1/projects/p/prs", "/api/v1/projects/p/neurons/claims", "/api/v1/projects/p/neurons/L40-N1/claim",
    "/api/v1/tasks", "/api/v1/tasks/unclaimed", "/api/v1/tasks/t/context", "/api/v1/tasks/t/people", "/api/v1/prs",
]
MEMBER_CALLS = [
    ("GET", "/api/v1/me"), ("GET", "/api/v1/me/claims"), ("GET", "/api/v1/proposals"), ("GET", "/api/v1/design/sessions"),
    ("GET", "/api/v1/design/repos"), ("POST", "/api/v1/design/gate-events"), ("POST", "/api/v1/design/sessions"),
    ("POST", "/api/v1/projects/p/tasks/t/claim"), ("PUT", "/api/v1/projects/p/neurons/L40-N1/claim"),
    ("DELETE", "/api/v1/projects/p/neurons/L40-N1/claim"), ("POST", "/api/v1/agent/chat"), ("PUT", "/api/admin/config"),
]


def test_signed_out_only_the_documented_visitor_reads_go_out():
    """docs/contributor-api.md, "Auth": these GETs, and nothing else, may go without a token."""
    from stationhouse_cli.client import visitor_may
    assert all(visitor_may("GET", p) for p in VISITOR_READS)
    assert not any(visitor_may(m, p) for m, p in MEMBER_CALLS)


def test_signed_out_the_design_gate_and_wizard_fail_locally(api):
    """Their calls need a member: signed out they stop before the network, as before STA-335."""
    import pytest
    from stationhouse_cli import wizard
    from stationhouse_cli.client import SignInRequired, request
    with pytest.raises(SignInRequired):
        request("POST", "/api/v1/design/gate-events", {"event": "x"})
    with pytest.raises(SignInRequired):
        wizard.find("Station-House/marin-neuron-hunt", "my-branch")
    assert not api.calls


def test_a_private_or_unknown_project_is_not_found(api, capsys):
    api.routes[("GET", "/api/v1/projects/secret-proj")] = (404, {"error": "Unknown project."})
    code, out, err = run(capsys, "project", "show", "secret-proj")
    assert (code, out, err) == (1, "", "Not found: secret-proj\n")
    code, _, err = run(capsys, "project", "use", "secret-proj")
    assert (code, err) == (1, "Not found: secret-proj\n")


def test_an_unknown_task_is_not_found(api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/nope/people")] = (404, {"error": "Unknown task."})
    code, _, err = run(capsys, "who", "nope")
    assert (code, err) == (1, "Not found: nope\n")


def test_a_signed_in_401_is_still_a_session_problem(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/claims")] = (401, {"error": "Sign in required.", "code": "signInRequired"})
    code, _, err = run(capsys, "mine")
    assert code == 1 and err == "error: Sign in required.\n"


def test_unclaimed_human_and_json(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/unclaimed")] = (200, TASKS)
    code, out, _ = run(capsys, "unclaimed")
    assert code == 0 and "add-question  Add a question" in out and "Write one." in out
    # --json works before and after the subcommand
    for argv in (("--json", "unclaimed"), ("unclaimed", "--json")):
        _, out, _ = run(capsys, *argv)
        assert json.loads(out) == TASKS
    assert api.calls[0]["path"] == "/api/v1/projects/conspiracybench/unclaimed"


def test_requests_carry_both_tokens(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/claims")] = (200, {"claims": []})
    run(capsys, "mine")
    h = {k.lower(): v for k, v in api.calls[0]["headers"].items()}
    assert h["authorization"] == f"Bearer {signed_in['access_token']}"
    assert h["x-station-house-id-token"] == "id.tok.en"


def test_who_lists_people_with_staleness(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/add-question/people")] = (200, PEOPLE)
    _, out, _ = run(capsys, "who", "add-question")
    assert "ada  (active, #12)" in out and "bob  (stale)" in out


CONTEXT = {
    "task": {"taskId": "add-question", "projectId": "conspiracybench", "title": "Add a question", "completionCriteria": "c"},
    "parent": {"taskId": "dataset", "title": "Build the dataset"},
    "subtasks": [{"taskId": "add-question-es", "title": "Spanish questions"}],
    "people": [
        {"user": "ada", "claim": {"status": "ACTIVE", "source": "SELF", "released": False}, "threads": 0, "comments": 0},
        {"user": "melover24", "claim": None, "threads": 1, "comments": 3},
        {"user": "bob", "claim": {"status": "CLOSED", "source": "PR", "released": True}, "threads": 0, "comments": 1},
    ],
    "threads": [{
        "repo": "Station-house/ConspiracyBench", "num": 62, "kind": "PR", "title": "Add Stage 2 pilot", "status": "merged",
        "url": "https://huggingface.co/spaces/Station-house/ConspiracyBench/discussions/62", "author": "melover24",
        "lastActivityAt": "2026-10-03T22:23:17.000Z", "commentCount": 7,
        "recentComments": [{"author": "stationhouse", "at": "2026-10-03T22:23:17.000Z", "text": "looking good.\nmerging now."}],
    }],
    "mentions": [],
}


def test_context_shows_the_task_neighbourhood(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/add-question/context")] = (200, CONTEXT)
    code, out, _ = run(capsys, "context", "add-question")
    assert code == 0
    assert "part of: dataset" in out and "subtask: add-question-es" in out
    assert "ada  (on it)" in out and "melover24  (1 PR/thread, 3 comments)" in out and "bob  (released, 1 comment)" in out
    assert "PR #62  Add Stage 2 pilot  [merged] by melover24, 7 comments" in out
    assert "stationhouse: looking good. merging now." in out  # newlines folded
    _, out, _ = run(capsys, "context", "add-question", "--json")
    assert json.loads(out) == CONTEXT


def test_context_for_a_task_nothing_has_touched(signed_in, api, capsys):
    empty = {**CONTEXT, "parent": None, "subtasks": [], "people": [], "threads": []}
    api.routes[("GET", "/api/v1/projects/conspiracybench/tasks/add-question/context")] = (200, empty)
    _, out, _ = run(capsys, "context", "add-question")
    assert "Nobody on it yet." in out and "PRs and discussions" not in out


def test_prs_lists_what_needs_review(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/projects/conspiracybench/prs")] = (200, {"project": "conspiracybench", "prs": [
        {"repo": "Station-house/ConspiracyBench", "num": 258, "title": "Add pressure turns", "author": "vivek",
         "taskId": "expand-existing-questions", "reviewers": [],
         "url": "https://huggingface.co/spaces/Station-house/ConspiracyBench/discussions/258"},
        {"repo": "Station-house/ConspiracyBench", "num": 260, "title": "Fix scorer", "author": "ada", "taskId": None,
         "reviewers": ["bob"], "url": None}]})
    code, out, _ = run(capsys, "prs")
    assert code == 0
    assert "#258  Add pressure turns  [expand-existing-questions]" in out and "by vivek, no review yet" in out
    assert "#260  Fix scorer" in out and "commented on by bob" in out
    assert api.calls[0]["path"] == "/api/v1/projects/conspiracybench/prs?limit=10"


def test_claim_sends_only_the_task_and_lists_others(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/claim")] = (200, {"people": [{"hfUsername": "me", "you": True}, {"hfUsername": "ada"}]})
    code, out, _ = run(capsys, "claim", "add-question")
    assert code == 0 and "You're on add-question" in out and "ada" in out and "me " not in out
    assert api.calls[0]["body"] is None  # the task is in the path; identity comes from the token, never the body


def test_release_and_assign(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/release")] = (200, {"ok": True})
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/assign")] = (200, {"ok": True})
    assert run(capsys, "release", "add-question")[0] == 0
    code, out, _ = run(capsys, "assign", "add-question", "@ada")
    assert code == 0 and "Assigned ada" in out
    assert api.calls[-1]["body"] == {"hfUsername": "ada"}


def test_assign_refused_for_non_admin_shows_server_message(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/assign")] = (403, {"error": "Admins only."})
    code, _, err = run(capsys, "assign", "add-question", "ada")
    assert code == 1 and "Admins only." in err


def test_claim_without_verified_handle_shows_server_message(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/projects/conspiracybench/tasks/add-question/claim")] = (409, {"error": "Verify your Hugging Face username first."})
    code, _, err = run(capsys, "claim", "add-question")
    assert code == 1 and "Verify your Hugging Face username" in err


def test_missing_route_says_not_supported_yet(signed_in, api, capsys):
    code, _, err = run(capsys, "unclaimed")
    assert code == 1 and "doesn't support that yet" in err


def test_unreachable_server_is_a_clear_error(signed_in, monkeypatch, capsys):
    monkeypatch.setenv("STATIONHOUSE_API_URL", "http://127.0.0.1:9")
    code, _, err = run(capsys, "unclaimed")
    assert code == 1 and "Couldn't reach" in err


def test_bad_task_id_rejected_before_any_request(signed_in, api, capsys):
    code, _, err = run(capsys, "claim", "../admin")
    assert code == 2 and "isn't a valid task id" in err and api.calls == []


def test_login_stores_credentials_and_never_prints_the_password(monkeypatch, capsys):
    from stationhouse_cli import auth, cli as climod
    monkeypatch.setattr(climod, "login", lambda e, p: auth.save_credentials(
        {"email": e, "access_token": "a", "id_token": "i", "refresh_token": "r", "expires_at": 1}) or
        {"email": e})
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "Sup3r-Secret!")
    code, out, err = run(capsys, "login", "--email", "Laura@Example.com", "--password")
    assert code == 0 and "laura@example.com" in out
    assert "Sup3r-Secret!" not in out + err
    assert load_credentials()["email"] == "laura@example.com"


def _email_code_login(monkeypatch, typed, expected="12345678"):
    """`login` against a stand-in for the code steps; returns the codes it was given."""
    from stationhouse_cli import auth, cli as climod
    tried = []

    def confirm(email, session, code):
        assert session == "sess"
        tried.append(code)
        if code != expected:
            raise auth.WrongCodeError("That code isn't right.")
        return {"email": email}
    monkeypatch.setattr(climod, "request_email_code", lambda e: "sess")
    monkeypatch.setattr(climod, "login_with_email_code", confirm)
    answers = iter(typed)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("asked for a password")))
    return tried


def test_login_signs_in_with_an_emailed_code_and_no_password(monkeypatch, capsys):
    tried = _email_code_login(monkeypatch, ["12345678"])
    code, out, _ = run(capsys, "login", "--email", "Laura@Example.com")
    assert code == 0 and tried == ["12345678"]
    assert "sign-in code" in out and "Signed in as laura@example.com" in out


def test_login_lets_a_mistyped_code_be_retried(monkeypatch, capsys):
    tried = _email_code_login(monkeypatch, ["00000000", "12345678"])
    code, out, err = run(capsys, "login", "--email", "laura@example.com")
    assert code == 0 and "Try again" in err and "Signed in" in out and len(tried) == 2


def test_login_gives_up_after_three_wrong_codes(monkeypatch, capsys):
    tried = _email_code_login(monkeypatch, ["1", "2", "3", "12345678"])
    code, _, err = run(capsys, "login", "--email", "laura@example.com")
    assert code == 1 and tried == ["1", "2", "3"] and "for a new one" in err


def test_login_rejects_non_email_without_prompting(monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("prompted")))
    code, _, err = run(capsys, "login", "--email", "nope")
    assert code == 1 and "email address" in err


def test_logout(signed_in, capsys):
    assert "Signed out" in run(capsys, "logout")[1]
    assert "weren't signed in" in run(capsys, "logout")[1]


def test_skills_install_copies_the_skill(tmp_path, capsys):
    code, out, _ = run(capsys, "skills-install", "--dir", str(tmp_path))
    assert code == 0
    text = (tmp_path / "stationhouse" / "SKILL.md").read_text()
    assert text.startswith("---\nname: stationhouse")
