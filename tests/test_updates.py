"""Project updates from the CLI (STA-287): a lead posts one from a file, stdin or their editor, with a
status or the website's default; edits never email again; delete asks first; anyone reads them."""
import io
import sys

import pytest

from stationhouse_cli import cli

UPDATES = "/api/v1/projects/marin-neuron-atlas/updates"
UPDATE = {
    "id": "u-1", "projectId": "marin-neuron-atlas", "title": "Berg baseline is in",
    "text": "Berg baseline is in\n\nWe ran the full probe set.", "status": "on_track",
    "authorId": "sub-ada", "authorName": "Ada Tester", "postedAt": "2026-11-08T10:00:00.000Z",
    "editedAt": None, "version": 1, "comments": 3, "recipients": 12,
    "href": "/projects/private/marin-neuron-atlas/posts/updates/u-1",
}


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setenv("STATIONHOUSE_PROJECT", "marin-neuron-atlas")


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_posts_from_a_file_with_a_status(signed_in, api, pinned, capsys, tmp_path):
    api.routes[("POST", UPDATES)] = (201, {"update": UPDATE})
    f = tmp_path / "update.md"
    f.write_text("Berg baseline is in\n\nWe ran the full probe set.\n")
    code, out, _ = run(capsys, "update", "post", "--status", "on-track", "--file", str(f))
    assert code == 0
    assert api.calls[-1]["body"] == {"text": "Berg baseline is in\n\nWe ran the full probe set.\n", "status": "on_track"}
    assert "Published." in out and out.strip().endswith("/projects/private/marin-neuron-atlas/posts/updates/u-1")


def test_posts_from_stdin_without_a_status_leaving_it_to_the_server(signed_in, api, pinned, capsys, monkeypatch):
    api.routes[("POST", UPDATES)] = (201, {"update": UPDATE})
    monkeypatch.setattr(sys, "stdin", io.StringIO("Short one: the 32B run is going.\n"))
    code, out, _ = run(capsys, "update", "post", "marin-neuron-atlas", "--file", "-")
    assert code == 0 and "Published." in out
    assert api.calls[-1]["body"] == {"text": "Short one: the 32B run is going.\n"}


def test_none_is_no_status_and_a_wrong_word_names_the_choices(signed_in, api, pinned, capsys, monkeypatch):
    api.routes[("POST", UPDATES)] = (201, {"update": {**UPDATE, "status": None}})
    monkeypatch.setattr(sys, "stdin", io.StringIO("A note"))
    assert run(capsys, "update", "post", "--status", "none", "--file", "-")[0] == 0
    assert api.calls[-1]["body"] == {"text": "A note", "status": None}
    code, _, err = run(capsys, "update", "post", "--status", "sideways", "--file", "-")
    assert code == 1 and "none, on-track, at-risk, off-track" in err


def test_opens_the_editor_without_a_file(signed_in, api, pinned, capsys, monkeypatch, tmp_path):
    api.routes[("POST", UPDATES)] = (201, {"update": UPDATE})
    editor = tmp_path / "fake-editor"
    editor.write_text("#!/bin/sh\nprintf 'Written in the editor\\n\\nMore.\\n' > \"$1\"\n")
    editor.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.delenv("VISUAL", raising=False)
    code, out, _ = run(capsys, "update", "post", "--status", "at-risk")
    assert code == 0 and "saved, 28 characters." in out
    assert api.calls[-1]["body"] == {"text": "Written in the editor\n\nMore.\n", "status": "at_risk"}


def test_an_empty_update_is_never_posted(signed_in, api, pinned, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("  \n\n"))
    code, _, err = run(capsys, "update", "post", "--file", "-")
    assert code == 1 and "empty" in err
    assert not [c for c in api.calls if c["method"] == "POST"]


def test_a_member_who_isnt_a_lead_is_told_so(signed_in, api, pinned, capsys, monkeypatch):
    api.routes[("POST", UPDATES)] = (403, {"error": "Only the project's leads can post its updates."})
    monkeypatch.setattr(sys, "stdin", io.StringIO("Mine"))
    code, _, err = run(capsys, "update", "post", "--file", "-")
    assert code == 1 and "Only the project's leads can post its updates." in err


def test_a_lead_on_a_project_not_on_project_management_is_told_why(signed_in, api, pinned, capsys, monkeypatch):
    why = "Project updates by leads start when this project moves to Project management."
    api.routes[("POST", UPDATES)] = (403, {"error": why})
    monkeypatch.setattr(sys, "stdin", io.StringIO("Our first update"))
    code, _, err = run(capsys, "update", "post", "--file", "-")
    assert code == 1 and why in err


def test_edit_sends_the_version_it_started_from_and_says_no_email_goes(signed_in, api, capsys, tmp_path):
    api.routes[("GET", "/api/v1/updates/u-1")] = (200, {"update": UPDATE})
    api.routes[("PATCH", "/api/v1/updates/u-1")] = (200, {"update": {**UPDATE, "version": 2}})
    f = tmp_path / "fixed.md"
    f.write_text("Berg baseline is in\n\nWe ran the whole probe set.")
    code, out, err = run(capsys, "update", "edit", "u-1", "--file", str(f))
    assert code == 0 and "The email already sent isn't changed." in out, err
    assert api.calls[-1]["body"] == {"baseVersion": 1, "text": "Berg baseline is in\n\nWe ran the whole probe set."}
    # The status alone: no editor.
    run(capsys, "update", "edit", "u-1", "--status", "off-track")
    assert api.calls[-1]["body"] == {"baseVersion": 1, "status": "off_track"}
    # The same text again: nothing to save.
    f.write_text(UPDATE["text"])
    code, out, _ = run(capsys, "update", "edit", "u-1", "--file", str(f))
    assert code == 0 and "Nothing changed." in out and api.calls[-1]["method"] == "GET"


def test_delete_needs_yes_without_a_terminal(signed_in, api, capsys, monkeypatch):
    api.routes[("DELETE", "/api/v1/updates/u-1")] = (200, {"ok": True})
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _, err = run(capsys, "update", "delete", "u-1")
    assert code == 1 and "--yes" in err
    code, out, _ = run(capsys, "update", "delete", "u-1", "--yes")
    assert code == 0 and "Deleted." in out and api.calls[-1]["method"] == "DELETE"


def test_show_and_latest(signed_in, api, pinned, capsys):
    api.routes[("GET", "/api/v1/updates/u-1")] = (200, {"update": UPDATE})
    _, out, _ = run(capsys, "update", "show", "u-1")
    assert out.splitlines()[0] == "Berg baseline is in"
    assert "● On track · Ada Tester, lead · Nov 8 · 3 comments" in out
    assert "We ran the full probe set." in out and 'stationhouse comment u-1 "<text>"' in out
    api.routes[("GET", UPDATES)] = (200, {"updates": [UPDATE], "canPost": False, "nextStatus": "on_track"})
    _, out, _ = run(capsys, "update", "latest")
    assert out.splitlines()[0] == "Berg baseline is in"
    api.routes[("GET", UPDATES)] = (200, {"updates": [], "canPost": False, "nextStatus": "on_track"})
    _, out, _ = run(capsys, "update", "latest")
    assert out.strip() == "No updates yet."


ACTIVITY = "/api/v1/projects/marin-neuron-atlas/activity"
FEED = {
    "projectId": "marin-neuron-atlas", "projectTitle": "Marin Neuron Atlas", "postsTab": "Discussions",
    "counts": {"all": 3, "updates": 1, "tasks": 1, "posts": 1, "milestones": 0}, "hasMore": False,
    "canPost": False, "nextStatus": "on_track",
    "items": [
        {"kind": "update", "id": "u-1", "at": UPDATE["postedAt"], "update": UPDATE},
        {"kind": "task_completed", "id": "a-1", "at": "2026-11-07T10:00:00.000Z", "actorId": "sub-ben",
         "actorName": "Ben Tester", "page": {"id": "t-1", "title": "Put error bars on the Berg baseline", "href": "/t"}},
        {"kind": "post_published", "id": "a-2", "at": "2026-10-20T10:00:00.000Z", "actorId": "sub-cy",
         "actorName": "Cy Tester", "page": {"id": "p-1", "title": "Do probes leak the system card?", "href": "/p"}},
    ],
}


def test_activity_groups_by_week_then_month(signed_in, api, pinned, capsys):
    from datetime import datetime, timezone
    from stationhouse_cli import updates
    api.routes[("GET", ACTIVITY)] = (200, FEED)
    lines = []
    updates.render_activity(updates.activity("marin-neuron-atlas"), now=datetime(2026, 11, 8, 20, tzinfo=timezone.utc), out=lines.append)
    text = "\n".join(lines)
    assert lines[0] == "Marin Neuron Atlas · Activity"
    assert "This week\n  Nov 8   UPDATE  ● On track Berg baseline is in" in text
    assert "stationhouse update show u-1" in text
    assert "This week" in text and "October\n  Oct 20  ¶ Cy Tester posted  Do probes leak the system card?  in Discussions" in text
    assert "✓ Ben Tester completed  Put error bars on the Berg baseline" in text
    assert text.endswith("Only some: --updates --tasks --posts --milestones · Older: --all · --json")


def test_activity_flags_become_the_query(signed_in, api, pinned, capsys):
    api.routes[("GET", ACTIVITY)] = (200, {**FEED, "items": []})
    _, out, _ = run(capsys, "activity", "--updates")
    assert api.calls[-1]["path"] == ACTIVITY + "?only=updates" and out.strip() == "No updates yet."
    run(capsys, "activity", "marin-neuron-atlas", "--all", "--json")
    assert api.calls[-1]["path"] == ACTIVITY + "?limit=600"
    with pytest.raises(SystemExit):  # one chip at a time
        run(capsys, "activity", "--tasks", "--posts")
