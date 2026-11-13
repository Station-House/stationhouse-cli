"""The CLI assumes no project: it asks the platform which ones you can see, works in the one you pick
(or the only one), and follows a task to its own project when you name it from another."""
import builtins

import pytest

from stationhouse_cli import cli
from stationhouse_cli.store import load_settings

CB, CSA = "/api/v1/projects/conspiracybench", "/api/v1/projects/llm-self-attribution"
TWO = {"projects": [{"id": "conspiracybench", "title": "Conspiracy Bench", "summary": "s"},
                    {"id": "llm-self-attribution", "title": "Consciousness Self-Attribution", "summary": "s"}]}


@pytest.fixture
def unpinned(monkeypatch):
    monkeypatch.delenv("STATIONHOUSE_PROJECT", raising=False)


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_lists_projects_and_marks_the_one_you_work_in(signed_in, api, unpinned, capsys):
    api.routes[("GET", "/api/v1/projects")] = (200, TWO)
    api.routes[("GET", CSA)] = (200, {"project": TWO["projects"][1], "overview": None})
    _, out, _ = run(capsys, "projects")
    assert "conspiracybench  Conspiracy Bench" in out and "Pick one to work in" in out
    code, out, _ = run(capsys, "project", "use", "llm-self-attribution")
    assert code == 0 and "Working in llm-self-attribution" in out
    assert load_settings()["project"] == "llm-self-attribution"
    _, out, _ = run(capsys, "projects")
    assert "* llm-self-attribution" in out and "Pick one" not in out


def test_asks_which_project_when_there_are_several_and_none_is_picked(signed_in, api, unpinned, capsys):
    api.routes[("GET", "/api/v1/projects")] = (200, TWO)
    code, _, err = run(capsys, "unclaimed")
    assert code == 1 and "Which project?" in err and "conspiracybench, llm-self-attribution" in err
    assert [c["path"] for c in api.calls] == ["/api/v1/projects"]


def test_uses_the_only_project_without_asking(signed_in, api, unpinned, capsys):
    api.routes[("GET", "/api/v1/projects")] = (200, {"projects": TWO["projects"][1:]})
    api.routes[("GET", f"{CSA}/unclaimed")] = (200, {"tasks": [{"taskId": "csa-mini-eval", "title": "Mini eval", "summary": ""}]})
    code, out, _ = run(capsys, "unclaimed")
    assert code == 0 and "csa-mini-eval" in out


def test_picked_project_then_env_then_flag(signed_in, api, unpinned, capsys, monkeypatch):
    api.routes[("GET", CSA)] = (200, {"project": TWO["projects"][1], "overview": None})
    api.routes[("GET", f"{CSA}/prs")] = (200, {"prs": []})
    api.routes[("GET", f"{CB}/prs")] = (200, {"prs": []})
    run(capsys, "project", "use", "llm-self-attribution")
    run(capsys, "prs")
    monkeypatch.setenv("STATIONHOUSE_PROJECT", "conspiracybench")
    run(capsys, "prs")
    run(capsys, "prs", "--project", "llm-self-attribution")
    assert [c["path"].split("?")[0] for c in api.calls if c["path"].split("?")[0].endswith("/prs")] == [f"{CSA}/prs", f"{CB}/prs", f"{CSA}/prs"]


def test_a_task_in_another_project_is_followed(signed_in, api, capsys):
    # Working in conspiracybench, asking about a CSA task: the platform names its project and the CLI goes there.
    api.routes[("GET", f"{CB}/tasks/csa-mini-eval/people")] = (
        404, {"error": "\"csa-mini-eval\" is in project \"llm-self-attribution\", not \"conspiracybench\".",
              "projectId": "llm-self-attribution", "taskId": "csa-mini-eval"})
    api.routes[("GET", f"{CSA}/tasks/csa-mini-eval/people")] = (200, {"title": "Mini eval", "people": [{"hfUsername": "ada", "stale": False}]})
    code, out, _ = run(capsys, "who", "csa-mini-eval")
    assert code == 0 and "Mini eval" in out and "ada" in out


def test_an_explicit_project_is_not_overridden(signed_in, api, capsys):
    api.routes[("POST", f"{CB}/tasks/csa-mini-eval/claim")] = (
        404, {"error": "\"csa-mini-eval\" is in project \"llm-self-attribution\", not \"conspiracybench\".",
              "projectId": "llm-self-attribution", "taskId": "csa-mini-eval"})
    code, _, err = run(capsys, "claim", "csa-mini-eval", "--project", "conspiracybench")
    assert code == 1 and "is in project \"llm-self-attribution\"" in err
    assert not [c for c in api.calls if c["path"].startswith(CSA)]


def test_task_commands_work_with_no_project_picked(signed_in, api, unpinned, capsys):
    api.routes[("GET", "/api/v1/projects")] = (200, TWO)
    api.routes[("GET", f"{CB}/tasks/csa-mini-eval/context")] = (
        404, {"error": "elsewhere", "projectId": "llm-self-attribution", "taskId": "csa-mini-eval"})
    api.routes[("GET", f"{CSA}/tasks/csa-mini-eval/context")] = (200, {
        "task": {"taskId": "csa-mini-eval", "projectId": "llm-self-attribution", "title": "Mini eval"},
        "parent": None, "subtasks": [], "people": [], "threads": [], "mentions": []})
    code, out, _ = run(capsys, "context", "csa-mini-eval")
    assert code == 0 and "Mini eval (llm-self-attribution/csa-mini-eval)" in out


def test_project_clear(signed_in, api, unpinned, capsys):
    api.routes[("GET", CSA)] = (200, {"project": TWO["projects"][1], "overview": None})
    run(capsys, "project", "use", "llm-self-attribution")
    _, out, _ = run(capsys, "project", "clear")
    assert "Forgot your project" in out and "project" not in load_settings()


def test_switching_project_inside_the_chat(signed_in, api, unpinned, capsys, monkeypatch):
    api.routes[("GET", CSA)] = (200, {"project": TWO["projects"][1], "overview": None})
    api.routes[("POST", "/api/v1/agent/chat")] = (200, {"reply": "ok", "suggestedActions": [], "taskIds": []})
    lines = ["hi", "/project use llm-self-attribution", "hi again"]
    monkeypatch.setattr(builtins, "input", lambda prompt="": lines.pop(0) if lines else (_ for _ in ()).throw(EOFError))
    cli.main([])
    sent = [c["body"]["project"] for c in api.calls if c["path"] == "/api/v1/agent/chat"]
    assert sent == [None, "llm-self-attribution"]
    assert "All your projects" in capsys.readouterr().out


ABOUT = {"summary": "How hard is it to teach a model something that it should not know?",
         "currentMilestone": "Experiments to decide finetuning recipe"}


def test_project_on_full_reads_its_about_summary_and_current_milestone(signed_in, api, unpinned, capsys):
    """STA-415: a project on full answers with its board's About (`about`); its earlier overview may be
    kept to leads (null for a member), and the CLI shows the About's summary and the milestone it's on."""
    api.routes[("GET", CB)] = (200, {"project": TWO["projects"][0], "overview": None, "about": ABOUT})
    code, out, _ = run(capsys, "project", "show", "conspiracybench")
    assert code == 0
    assert out.splitlines() == [
        "Conspiracy Bench (conspiracybench)",
        "  How hard is it to teach a model something that it should not know?",
        "  Now: Experiments to decide finetuning recipe",
    ]


def test_project_on_full_says_so_before_its_about_is_written(signed_in, api, unpinned, capsys):
    api.routes[("GET", CB)] = (200, {"project": TWO["projects"][0], "overview": None, "about": {"summary": None, "currentMilestone": None}})
    _, out, _ = run(capsys, "project", "show", "conspiracybench")
    assert out.splitlines() == ["Conspiracy Bench (conspiracybench)", "  No About or milestone on its board yet."]


def test_project_off_the_board_reads_its_overview_as_before(signed_in, api, unpinned, capsys):
    overview = {"researchQuestion": "What makes LLMs self-attribute?", "currentMilestone": "Phase 1", "resources": []}
    api.routes[("GET", CSA)] = (200, {"project": TWO["projects"][1], "overview": overview, "about": None})
    _, out, _ = run(capsys, "project", "show", "llm-self-attribution")
    assert out.splitlines() == ["Consciousness Self-Attribution (llm-self-attribution)", "  What makes LLMs self-attribute?", "  Now: Phase 1"]
