"""`stationhouse activity --member` (STA-383): your own activity log as the CLI frame (2114:6611)
prints it, from the fixture the platform's route test writes (tests/fixtures/v1/activity-member.json).
"""
import json
from pathlib import Path

from stationhouse_cli import activity_log, cli

FIXTURES = Path(__file__).parent / "fixtures" / "v1"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def lines(data, today="2026-11-12"):
    printed = []
    activity_log.render(data, out=printed.append, today=today)
    return printed


def test_member_log_prints_each_group_with_counts_and_last_dates(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/activity")] = (200, fixture("activity-member"))
    code, out, _ = run(capsys, "activity", "--member")
    assert code == 0
    assert api.calls[-1]["path"] == "/api/v1/me/activity"
    assert out.splitlines()[0] == "bo-tester · activity log · all time"
    assert "Doing the work" in out and "Taking part" in out and "Running the project" not in out
    assert "  Reviewed tasks                       1   last Nov 8" in out
    assert "  Commented on posts / on tasks     0 / 1   last Nov 7" in out
    assert "  Proposed tasks (0 accepted)          1   last Nov 7" in out
    assert "  Submitted papers                     0   —" in out
    assert out.rstrip().endswith("--json")


def test_member_log_for_one_project_and_a_period_is_one_line(signed_in, api, capsys):
    data = fixture("activity-member")
    data["log"].update(projectId="conspiracy-bench", since="2026-11-01", period="month")
    api.routes[("GET", "/api/v1/me/activity")] = (200, data)
    code, _, _ = run(capsys, "activity", "--member", "--project", "conspiracy-bench", "--since", "this-month")
    assert code == 0 and api.calls[-1]["path"] == "/api/v1/me/activity?project=conspiracy-bench&since=this-month"
    assert lines(data) == [
        "bo-tester · conspiracy-bench · Nov 1 to Nov 12",
        "  Started 1 · Did 0 · Reviewed 1 · Posts 0 · Comments 1 · Reactions 0 · Proposed 1",
    ]


def test_a_lead_sees_running_the_project_and_an_empty_log_says_how_to_start():
    data = fixture("activity-member")
    data["log"]["leads"] = True
    assert "Running the project" in lines(data)
    for entry in data["log"]["counts"].values():
        entry.update(count=0, last=None)
    assert lines(data) == ["Nothing logged yet. Start a task, review one, or join a discussion."]


def test_since_without_member_says_what_it_is_for(signed_in, api, capsys):
    code, _, err = run(capsys, "activity", "--since", "this-week")
    assert code != 0 and "--since is for your own log" in err
