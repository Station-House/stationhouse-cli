import json
from datetime import datetime, timedelta, timezone

from stationhouse_cli import chat, cli, inbox

NOW = datetime.now(timezone.utc)
MARIN, CB, SA = "marin-neuron-atlas", "conspiracybench", "llm-self-attribution"


def ago(minutes):
    return (NOW - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def item(id, minutes, unread=True, **extra):
    return {"id": id, "source": "project", "kind": "mention", "filter": "mentions", "project": MARIN, "unread": unread,
            "at": ago(minutes), "label": "Mention", "title": f"Ben Tester: @ada can you check {id}?", "context": "Marin Neuron Atlas",
            "url": f"/projects/{MARIN}/posts/p1#c-{id}", "external": False, "addressed": True, **extra}


HF = dict(source="hf", kind="reply", filter="hf", project=CB, label="Reply · Hugging Face", title="Cy Tester replied on “Judge selection” (#41)",
          url="https://huggingface.co/spaces/Station-house/ConspiracyBench/discussions/41", external=True)
PR = dict(source="github", kind="pr-feedback", filter="github", project=SA, label="PR feedback · GitHub", url="https://github.com/x/y/pull/212", external=True)


def view(*items, sources=None, unread=None):
    """The Inbox as the platform answers it: newest first, read and unread mixed."""
    items = sorted(items, key=lambda i: i["at"], reverse=True)
    return {"items": items, "unread": sum(1 for i in items if i["unread"]) if unread is None else unread,
            "counts": {"all": len(items)}, "sources": sources or {"hf": "ok", "github": "ok"}}


INBOX = view(item("m1", 12), item("hf41", 60, **HF), item("c3", 120, kind="comment", filter="replies", label="Comments", bundled=3, project=SA,
                                                            title="3 new comments on “Write the scorer README”"),
             item("pr212", 180, **PR), item("own", 300, kind="owner_added", filter="tasks", label="Added to a task", title="Ben Tester added you as a co-owner"),
             item("old1", 60 * 30, unread=False, kind="post_published", filter="posts", label="New post", title="Cy Tester posted “Layer 12”", addressed=False))


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_inbox_lists_the_unread_numbered_with_kind_project_and_age(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    code, out, _ = run(capsys, "inbox")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "Inbox · 5 unread · 6 in all"
    assert "Unread" in lines and "Earlier" not in lines
    assert any(line.split()[:4] == ["1", "Mention", "marin", "12m"] for line in lines)
    assert any(line.split()[:5] == ["2", "Reply", "·", "HF", "conspiracybench"] for line in lines)
    assert any(line.split()[:3] == ["3", "Comments", "(3)"] for line in lines)
    assert any(line.split()[:5] == ["4", "PR", "·", "GitHub", "llm"] for line in lines)
    assert any(line.split()[:4] == ["5", "Added", "to", "task"] for line in lines)
    assert "Layer 12" not in out
    assert "stationhouse inbox open 2" in out and "stationhouse inbox read 2" in out and "stationhouse inbox --all" in out
    # Every project, whichever is picked (conftest picks conspiracybench): a reply doesn't care.
    assert api.calls[0]["path"] == "/api/v1/me/inbox"


def test_inbox_all_adds_earlier_numbered_after_the_unread(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    _, out, _ = run(capsys, "inbox", "--all")
    earlier = out.split("\nEarlier\n")[1]
    assert earlier.split()[:3] == ["6", "New", "post"] and "Layer 12" in earlier


def test_inbox_filters_by_project_and_kind_and_says_so(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("m1", 12)))
    api.routes[("GET", f"/api/v1/projects/{MARIN}")] = (200, {"project": {"id": MARIN, "title": "Marin Neuron Atlas"}})
    code, out, _ = run(capsys, "inbox", "--project", MARIN, "--kind", "mentions")
    assert code == 0
    assert out.splitlines()[0] == "Inbox · Marin Neuron Atlas · mentions · 1 unread"
    assert out.splitlines()[1].split()[:4] == ["1", "Mention", "marin", "12m"]
    assert api.calls[0]["path"] == f"/api/v1/me/inbox?project={MARIN}&kind=mentions"


def test_an_unknown_kind_names_the_kinds_without_asking_the_platform(signed_in, api, capsys):
    code, _, err = run(capsys, "inbox", "--kind", "replys")
    assert code == 1 and 'No kind "replys". Kinds: mentions, replies, tasks, posts, hf, github' in err
    assert api.calls == []


def test_inbox_says_when_hugging_face_and_github_didnt_load(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("m1", 12), sources={"hf": "failed", "github": "failed"}))
    _, out, _ = run(capsys, "inbox")
    assert out.splitlines()[0] == "Inbox · 1 unread · Hugging Face and GitHub didn't load, so they're missing."
    assert "Try again in a minute: stationhouse inbox" in out


def test_inbox_says_when_closed_polls_didnt_load(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("m1", 12), sources={"hf": "ok", "github": "ok", "polls": "failed"}))
    _, out, _ = run(capsys, "inbox")
    assert out.splitlines()[0] == "Inbox · 1 unread · Closed polls didn't load, so they're missing."
    assert "Try again in a minute: stationhouse inbox" in out
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("m1", 12), sources={"hf": "failed", "github": "failed", "polls": "failed"}))
    _, out, _ = run(capsys, "inbox")
    assert out.splitlines()[0] == "Inbox · 1 unread · Hugging Face, GitHub and closed polls didn't load, so they're missing."


def test_inbox_with_nothing_unread_points_at_earlier_and_an_empty_one_says_how_to_fill_it(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("old", 90, unread=False)))
    _, out, _ = run(capsys, "inbox")
    assert out.strip() == "Nothing unread. Earlier: stationhouse inbox --all"
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view())
    _, out, _ = run(capsys, "todo")
    assert out.startswith("Your Inbox is empty.")


def test_inbox_json_numbers_the_items(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    _, out, _ = run(capsys, "inbox", "--json")
    data = json.loads(out)
    assert [i["n"] for i in data["items"]] == [1, 2, 3, 4, 5, 6]
    assert data["items"][0]["id"] == "m1" and data["items"][5]["id"] == "old1" and data["unread"] == 5


def test_inbox_read_by_number_and_all_with_undo(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 1, "inbox": INBOX})
    code, out, _ = run(capsys, "inbox", "read", "2")
    assert code == 0 and out.strip() == "Marked 1 as read. Undo: stationhouse inbox unread --last"
    assert api.calls[-1]["body"] == {"ids": ["hf41"]}

    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 5, "inbox": INBOX})
    _, out, _ = run(capsys, "inbox", "read", "--all")
    assert out.strip() == "Marked 5 as read. Undo: stationhouse inbox unread --last"
    assert api.calls[-1]["body"] == {"all": True}

    api.routes[("POST", "/api/v1/me/inbox/unread")] = (200, {"changed": 5, "inbox": INBOX})
    _, out, _ = run(capsys, "inbox", "unread", "--last")
    assert out.strip() == "Marked 5 as unread."
    assert api.calls[-1]["body"] == {"last": True}


def test_inbox_done_still_works_as_read(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 1, "inbox": INBOX})
    code, out, _ = run(capsys, "inbox", "done", "#4")
    assert code == 0 and "Marked 1 as read." in out
    assert api.calls[-1]["body"] == {"ids": ["pr212"]}
    code, _, err = run(capsys, "inbox", "done", "99")
    assert code == 1 and "Nothing in your Inbox is 99" in err
    code, _, err = run(capsys, "inbox", "done")
    assert code == 1 and "Which one?" in err


def test_inbox_done_takes_a_pr_or_discussion_number_that_isnt_a_list_number(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 1, "inbox": INBOX})
    code, out, _ = run(capsys, "inbox", "done", "212")
    assert code == 0 and "Marked 1 as read." in out
    assert api.calls[-1]["body"] == {"ids": ["pr212"]}
    _, _, _ = run(capsys, "inbox", "read", "#41")
    assert api.calls[-1]["body"] == {"ids": ["hf41"]}
    # A list number wins over a PR number.
    run(capsys, "inbox", "done", "2")
    assert api.calls[-1]["body"] == {"ids": ["hf41"]}
    posts = len([c for c in api.calls if c["method"] == "POST"])
    code, _, err = run(capsys, "inbox", "done", "348")
    assert code == 1 and "Nothing in your Inbox is 348. Use the list number: run stationhouse inbox" in err
    assert len([c for c in api.calls if c["method"] == "POST"]) == posts


def test_inbox_done_with_a_number_two_threads_share_asks_for_the_list_number(signed_in, api, capsys):
    other = dict(PR, url="https://github.com/x/z/pull/212")
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view(item("pr212", 180, **PR), item("z212", 200, **other), *[item(f"m{n}", n) for n in range(1, 4)]))
    code, _, err = run(capsys, "inbox", "done", "212")
    assert code == 1 and "Use the list number: run stationhouse inbox" in err


def test_inbox_open_opens_the_link_and_marks_it_read(signed_in, api, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True, raising=False)
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 1, "inbox": INBOX})
    code, out, _ = run(capsys, "inbox", "open", "2")
    assert code == 0 and opened == [HF["url"]]
    assert out.strip() == "Opened huggingface.co/…/discussions/41 in your browser. Marked read."
    assert api.calls[-1]["body"] == {"ids": ["hf41"]}


def test_inbox_open_prints_the_link_where_there_is_no_browser(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    api.routes[("POST", "/api/v1/me/inbox/read")] = (200, {"changed": 1, "inbox": INBOX})
    _, out, _ = run(capsys, "inbox", "open", "1")
    assert out.strip() == f"Open it here: {api.url}/projects/{MARIN}/posts/p1#c-m1 Marked read."


def test_inbox_against_an_older_server(signed_in, api, capsys):
    code, _, err = run(capsys, "inbox")
    assert code == 1 and "doesn't have the Inbox yet" in err


def test_a_question_starting_with_inbox_still_goes_to_the_assistant(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/agent/chat")] = (200, {"reply": "Answer Cy on #41 first.", "suggestedActions": [], "taskIds": []})
    code, out, _ = run(capsys, "inbox", "what", "needs", "me?")
    assert code == 0 and "Answer Cy on #41 first" in out


def test_chat_greeting_nudges_when_the_inbox_has_unread(signed_in, api):
    api.routes[("GET", "/api/v1/me/inbox")] = (200, INBOX)
    assert "Your Inbox has 5 unread: /inbox" in cli._inbox_line(CB)
    api.routes[("GET", "/api/v1/me/inbox")] = (200, view())
    assert cli._inbox_line(None) == ""
    del api.routes[("GET", "/api/v1/me/inbox")]
    assert cli._inbox_line(None) == ""  # an older server: no nudge, no error
    assert "/inbox" in chat.HELP


def test_age_reads_like_the_page():
    now = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert inbox.age("2026-11-10T11:59:30Z", now) == "just now"
    assert inbox.age("2026-11-10T11:48:00.000Z", now) == "12m"
    assert inbox.age("2026-11-10T09:00:00Z", now) == "3h"
    assert inbox.age("2026-11-07T12:00:00Z", now) == "3d"
    assert inbox.age("2026-10-27T12:00:00Z", now) == "Oct 27"
