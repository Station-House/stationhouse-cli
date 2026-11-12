"""Our Research from the CLI (STA-354): `stationhouse research` reads GET /api/v1/research with no sign-in
where the server has public reading on, prints it by day, and asks to sign in where it's off."""
import json
from datetime import datetime, timezone

from stationhouse_cli import cli, research

RESEARCH = "/api/v1/research"
ANSWER = {
    "generatedAt": "2026-11-11T06:00:00.000Z", "windowDays": 7, "project": None,
    "cards": [
        {"id": "thread:hf:Station-house/ConspiracyBench#44", "kind": "pr", "projectId": "conspiracybench",
         "projectTitle": "Conspiracy Bench", "at": "2026-11-11T08:30:00.000Z",
         "hook": "Judge agreement holds at κ .75 until the easy items go, then falls to chance.",
         "url": "https://huggingface.co/datasets/Station-house/ConspiracyBench/discussions/44"},
        {"id": "experiment:e-1", "kind": "experiment", "projectId": "marin-neuron-atlas",
         "projectTitle": "Marin Neuron Atlas", "at": "2026-11-10T12:00:00.000Z",
         "hook": "Ablating one L12 neuron halves refusals while the logit lens shows nothing.",
         "url": "https://app.station-house.net/marin-neuron-atlas/experiments/e-1"},
        {"id": "thread:github:Station-House/marin-neuron-hunt#7", "kind": "discussion", "projectId": "marin-neuron-atlas",
         "projectTitle": "Marin Neuron Atlas", "at": "2026-11-08T09:00:00.000Z",
         "hook": "Is neuron 4410 a date detector, or does it fire on any four-digit number?",
         "url": "https://github.com/Station-House/marin-neuron-hunt/issues/7"},
    ],
}
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def rendered(data) -> str:
    lines = []
    research.render(data, now=NOW, out=lines.append)
    return "\n".join(lines) + "\n"


def test_prints_the_list_by_day_newest_first():
    assert rendered(ANSWER) == (
        "Our Research: the last 7 days, written today\n"
        "\n"
        "Today\n"
        "  Conspiracy Bench · PR\n"
        "    Judge agreement holds at κ .75 until the easy items go, then falls to chance.\n"
        "    https://huggingface.co/datasets/Station-house/ConspiracyBench/discussions/44\n"
        "\n"
        "Yesterday\n"
        "  Marin Neuron Atlas · experiment\n"
        "    Ablating one L12 neuron halves refusals while the logit lens shows nothing.\n"
        "    https://app.station-house.net/marin-neuron-atlas/experiments/e-1\n"
        "\n"
        "Sun, Nov 8\n"
        "  Marin Neuron Atlas · discussion\n"
        "    Is neuron 4410 a date detector, or does it fire on any four-digit number?\n"
        "    https://github.com/Station-House/marin-neuron-hunt/issues/7\n"
    )


def test_says_so_before_the_first_run_and_when_a_project_had_nothing():
    assert rendered({"generatedAt": None, "windowDays": 7, "project": None, "cards": []}) == (
        "Our Research hasn't been written yet. It's made once a day: try again tomorrow.\n")
    assert rendered({**ANSWER, "project": "llm-self-attribution", "cards": []}) == (
        "Nothing in Our Research from this project this week.\n")


def test_works_signed_out_without_a_token(api, capsys):
    api.routes[("GET", RESEARCH)] = (200, ANSWER)
    code, out, _ = run(capsys, "research")
    assert code == 0
    assert "Conspiracy Bench · PR" in out and "https://github.com/Station-House/marin-neuron-hunt/issues/7" in out
    assert [c["path"] for c in api.calls] == [RESEARCH]
    assert "authorization" not in {k.lower() for k in api.calls[0]["headers"]}


def test_sends_the_member_token_when_signed_in(signed_in, api, capsys):
    api.routes[("GET", RESEARCH)] = (200, ANSWER)
    assert run(capsys, "research")[0] == 0
    assert api.calls[0]["headers"].get("Authorization") == f"Bearer {signed_in['access_token']}"


def test_project_and_json(api, capsys):
    narrowed = {**ANSWER, "project": "marin-neuron-atlas", "cards": ANSWER["cards"][1:]}
    api.routes[("GET", RESEARCH)] = (200, narrowed)
    code, out, _ = run(capsys, "research", "--project", "marin-neuron-atlas", "--json")
    assert code == 0 and json.loads(out) == narrowed
    assert api.calls[0]["path"] == f"{RESEARCH}?project=marin-neuron-atlas"


def test_ignores_the_project_picked_with_project_use(api, capsys):
    """Our Research is the whole community's: only --project narrows it, never STATIONHOUSE_PROJECT."""
    api.routes[("GET", RESEARCH)] = (200, ANSWER)
    assert run(capsys, "research")[0] == 0
    assert api.calls[0]["path"] == RESEARCH


def test_signed_out_where_public_reading_is_off_asks_to_sign_in(api, capsys):
    api.routes[("GET", RESEARCH)] = (401, {"error": "Sign in required.", "code": "signInRequired"})
    code, out, err = run(capsys, "research")
    assert (code, out) == (1, "")
    assert err == "Sign in to read Our Research: stationhouse login\n(then run stationhouse research again)\n"


def test_an_unknown_project_is_the_platforms_message(api, capsys):
    api.routes[("GET", RESEARCH)] = (404, {"error": "Unknown project."})
    code, _, err = run(capsys, "research", "--project", "nope")
    assert code == 1 and err == "error: Unknown project.\n"
