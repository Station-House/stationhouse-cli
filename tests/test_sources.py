"""Hugging Face & GitHub in projects from the CLI (P-STA-25, frame C1): `sources` lists a project's
repos, single threads and hidden ones; leads add, remove, hide and show; `activity --hf-github` and
`discussions --hf-github` list what came in, and `open <n>` opens one of them there."""
from datetime import datetime, timezone

import pytest

from stationhouse_cli import cli, discussions, sources, updates

CSA = "llm-self-attribution"
SOURCES = f"/api/v1/projects/{CSA}/sources"
HIDDEN = f"/api/v1/projects/{CSA}/sources/hidden"
LIST = {
    "projectId": CSA, "projectTitle": "Consciousness Self-Attribution", "canEdit": True,
    "repos": [
        {"forge": "hf", "repoType": "space", "repoId": "Station-house/Consciousness-Self-Attribution", "graphRepo": "Station-house/Consciousness-Self-Attribution",
         "counts": {"discussions": 18, "pullRequests": 9, "issues": 0}, "checkedAt": "2026-11-11T10:00:00.000Z"},
        {"forge": "github", "repoType": "repo", "repoId": "Station-House/LLMConsciousnessSelfAttributionRepo", "graphRepo": "github:Station-House/LLMConsciousnessSelfAttributionRepo",
         "counts": {"discussions": 0, "pullRequests": 64, "issues": 12}, "checkedAt": "2026-11-11T10:00:00.000Z"},
        {"forge": "hf", "repoType": "dataset", "repoId": "Station-house/csa-probes", "graphRepo": "datasets/Station-house/csa-probes",
         "counts": {"discussions": 3, "pullRequests": 0, "issues": 0}, "checkedAt": "2026-11-11T10:00:00.000Z"},
    ],
    "threads": [{"forge": "hf", "repoType": "space", "repoId": "Station-house/ConspiracyBench", "num": 57, "title": "Shared judge prompts for both projects?"}],
    "hidden": [{"forge": "github", "repoType": "repo", "repoId": "Station-House/LLMConsciousnessSelfAttributionRepo", "num": 203, "title": "Bump numpy from 1.26 to 2.1"}],
}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_lists_repos_single_threads_and_hidden(signed_in, api, capsys):
    api.routes[("GET", SOURCES)] = (200, LIST)
    code, out, _ = run(capsys, "sources", CSA)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "Consciousness Self-Attribution · Hugging Face & GitHub"
    assert "Repos" in lines
    assert any(line.startswith("  hf  Station-house/Consciousness-Self-Attribution") and line.endswith("Space    18 discussions · 9 PRs") for line in lines)
    assert any(line.startswith("  gh  Station-House/LLMConsciousnessSelfAttributionRepo") and line.endswith("64 PRs · 12 issues") for line in lines)
    assert any(line.endswith("Dataset  3 discussions") for line in lines)
    assert "Single threads\n  hf  Station-house/ConspiracyBench #57   Shared judge prompts for both projects?" in out
    assert "Hidden\n  gh  #203 Bump numpy from 1.26 to 2.1" in out


def test_a_lead_adds_a_repo(signed_in, api, capsys):
    api.routes[("POST", SOURCES)] = (201, {**LIST, "added": {"summary": "Dataset · Station-house/csa-results · 2 discussions, 0 pull requests", "already": False}})
    code, out, _ = run(capsys, "sources", "add", CSA, "https://huggingface.co/datasets/Station-house/csa-results")
    assert code == 0
    assert api.calls[-1]["body"] == {"link": "https://huggingface.co/datasets/Station-house/csa-results"}
    assert out == "Added Station-house/csa-results (Dataset · 2 discussions).\nIts threads show in Activity and Discussions within 5 minutes.\n"


def test_a_private_repo_is_refused_as_the_platform_says(signed_in, api, capsys):
    api.routes[("POST", SOURCES)] = (400, {"error": "Can't read that repo: it's private, or the link is wrong."})
    code, _, err = run(capsys, "sources", "add", CSA, "https://github.com/Station-House/csa-private-notes")
    assert code == 1 and "Can't read that repo: it's private, or the link is wrong." in err


def test_hide_shows_the_undo_and_show_brings_it_back(signed_in, api, capsys):
    api.routes[("POST", HIDDEN)] = (200, {**LIST, "thread": LIST["hidden"][0]})
    code, out, _ = run(capsys, "sources", "hide", CSA, "gh#203")
    assert code == 0 and api.calls[-1]["body"] == {"ref": "gh#203"}
    assert out.strip() == f"Hidden from Consciousness Self-Attribution. Undo: stationhouse sources show {CSA} gh#203"
    api.routes[("DELETE", HIDDEN)] = (200, {**LIST, "hidden": [], "thread": LIST["hidden"][0]})
    _, out, _ = run(capsys, "sources", "show", CSA, "gh#203")
    assert api.calls[-1]["path"] == HIDDEN + "?ref=gh%23203"
    assert out.strip() == "Showing “Bump numpy from 1.26 to 2.1” in Consciousness Self-Attribution again."


def test_remove_and_a_missing_argument(signed_in, api, capsys):
    api.routes[("DELETE", SOURCES)] = (200, LIST)
    _, out, _ = run(capsys, "sources", "remove", CSA, "Station-house/csa-probes")
    assert api.calls[-1]["path"] == SOURCES + "?ref=Station-house%2Fcsa-probes"
    assert out.startswith("Removed Station-house/csa-probes from Consciousness Self-Attribution.")
    code, _, err = run(capsys, "sources", "hide", CSA)
    assert code == 1 and "stationhouse sources hide <project> <thread, e.g. hf#44>" in err


ACTIVITY = {
    "projectId": CSA, "projectTitle": "Consciousness Self-Attribution", "postsTab": "Discussions", "hasMore": False,
    "items": [
        {"kind": "linked", "id": "l-1", "at": "2026-11-07T10:00:00.000Z", "event": "pr_merged", "actorName": "Ben Tester", "forge": "github",
         "title": "Error bars on the Berg baseline", "num": 212, "url": "https://github.com/Station-House/LLMConsciousnessSelfAttributionRepo/pull/212"},
        {"kind": "linked", "id": "l-2", "at": "2026-11-06T10:00:00.000Z", "event": "discussion_started", "actorName": "ellie-hf", "forge": "hf",
         "title": "Do judges disagree on borderline probes?", "num": 44, "url": "https://huggingface.co/spaces/Station-house/Consciousness-Self-Attribution/discussions/44"},
    ],
}


def test_activity_hf_github(signed_in, api, capsys, monkeypatch):
    api.routes[("GET", f"/api/v1/projects/{CSA}/activity")] = (200, ACTIVITY)
    lines = []
    updates.render_activity(updates.activity(CSA, "hf-github"), "hf-github", now=datetime(2026, 11, 8, 20, tzinfo=timezone.utc), out=lines.append)
    assert api.calls[-1]["path"].endswith("?only=hf-github")
    assert lines[0] == "Consciousness Self-Attribution · Activity · Hugging Face & GitHub"
    assert "  ↗ Nov 7   Ben Tester merged a pull request  Error bars on the Berg baseline (#212)  github" in lines
    assert "  ↗ Nov 6   ellie-hf started a discussion  Do judges disagree on borderline probes? (#44)  hf" in lines
    assert lines[-1] == "stationhouse open <n> opens one on Hugging Face or GitHub."
    # `open 212` is that pull request.
    opened = []
    monkeypatch.setattr(sources.webbrowser, "open", lambda url: opened.append(url) or True)
    code, out, _ = run(capsys, "open", "212")
    assert code == 0 and opened == [ACTIVITY["items"][0]["url"]]
    assert out.strip() == f"Opened {ACTIVITY['items'][0]['url']} in your browser."


def test_activity_flag_becomes_the_query(signed_in, api, capsys):
    api.routes[("GET", f"/api/v1/projects/{CSA}/activity")] = (200, {**ACTIVITY, "items": []})
    _, out, _ = run(capsys, "activity", CSA, "--hf-github")
    assert api.calls[-1]["path"].endswith("?only=hf-github")
    assert out.strip() == "No Hugging Face or GitHub activity yet."


DISCUSSIONS = {
    "scope": CSA, "title": "Consciousness Self-Attribution", "following": False, "canPost": True, "writeHint": None,
    "categories": [], "posts": [], "archivedCount": 0, "archived": [],
    "linked": [
        {"forge": "hf", "kind": "discussion", "repoId": "Station-house/Consciousness-Self-Attribution", "num": 44, "single": False,
         "title": "Do judges disagree on borderline probes?", "comments": 4, "lastActivityAt": "2026-11-06T10:00:00.000Z", "status": "open",
         "url": "https://huggingface.co/spaces/Station-house/Consciousness-Self-Attribution/discussions/44"},
        {"forge": "github", "kind": "issue", "repoId": "Station-House/LLMConsciousnessSelfAttributionRepo", "num": 31, "single": False,
         "title": "Probe loader fails on Windows paths", "comments": 3, "lastActivityAt": "2026-11-03T10:00:00.000Z", "status": "open",
         "url": "https://github.com/Station-House/LLMConsciousnessSelfAttributionRepo/issues/31"},
        {"forge": "hf", "kind": "discussion", "repoId": "Station-house/ConspiracyBench", "num": 57, "single": True,
         "title": "Shared judge prompts for both projects?", "comments": 9, "lastActivityAt": "2026-10-27T10:00:00.000Z", "status": "open",
         "url": "https://huggingface.co/spaces/Station-house/ConspiracyBench/discussions/57"},
    ],
}


def test_discussions_hf_github_and_open_a_row(signed_in, api, capsys):
    api.routes[("GET", f"/api/v1/discussions/{CSA}")] = (200, DISCUSSIONS)
    code, out, _ = run(capsys, "discussions", CSA, "--hf-github")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "Consciousness Self-Attribution · Discussions · Hugging Face & GitHub"
    assert any(line.startswith("   1  Do judges disagree on borderline probes?") and "hf #44" in line and "4 replies" in line for line in lines)
    assert any(line.startswith("   2  Probe loader fails on Windows paths") and "gh issue #31" in line for line in lines)
    assert any("hf ConspiracyBench #57" in line and "9 replies" in line for line in lines)
    assert lines[-2:] == ["These live on Hugging Face and GitHub: reply there.", f"stationhouse open 1  →  {DISCUSSIONS['linked'][0]['url']}"]
    _, out, _ = run(capsys, "open", "2", "--print")
    assert out.strip() == DISCUSSIONS["linked"][1]["url"]
    code, _, err = run(capsys, "open", "9", "--print")
    assert code == 1 and f"stationhouse discussions {CSA} --hf-github" in err


def test_discussions_hf_github_rows_with_a_synced_post_open_here(signed_in, api, capsys):
    data = {**DISCUSSIONS, "linked": [{**DISCUSSIONS["linked"][0], "postId": "5e5e"}, *DISCUSSIONS["linked"][1:]]}
    api.routes[("GET", f"/api/v1/discussions/{CSA}")] = (200, data)
    code, out, _ = run(capsys, "discussions", CSA, "--hf-github")
    assert code == 0
    lines = out.splitlines()
    assert any(line.startswith("   1  Do judges disagree on borderline probes?") and line.endswith("  [here]") for line in lines)
    assert "[here]: synced with Stationhouse, read it with stationhouse discussions show 5e5e" in lines
    assert lines[-2:] == ["The rest live on Hugging Face and GitHub: reply there.", f"stationhouse open 1  →  {data['linked'][0]['url']}"]


def test_the_plain_list_points_at_them(signed_in, api, capsys):
    lines = []
    discussions.render_list(DISCUSSIONS, out=lines.append)
    assert f"3 from Hugging Face & GitHub: stationhouse discussions {CSA} --hf-github" in "\n".join(lines)


def test_open_before_any_list(signed_in, capsys):
    code, _, err = run(capsys, "open", "1")
    assert code == 1 and "Nothing to open yet." in err


@pytest.mark.parametrize("argv", [["discussions", CSA, "--hf-github", "--category", "questions"]])
def test_hf_github_is_its_own_list(signed_in, api, capsys, argv):
    api.routes[("GET", f"/api/v1/discussions/{CSA}")] = (200, DISCUSSIONS)
    code, _, err = run(capsys, *argv)
    assert code == 1 and "leave out --category" in err
