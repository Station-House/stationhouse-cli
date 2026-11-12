import io

from stationhouse_cli import cli

CATEGORIES = [{"id": "t1", "name": "Ideas", "count": 1}, {"id": "t2", "name": "Questions", "count": 1},
              {"id": "t3", "name": "Links", "count": 0}, {"id": "t4", "name": "Other", "count": 0}]


def row(pid, title, category="Ideas", **extra):
    return {"id": pid, "title": title, "category": category, "author": "ben-sample", "comments": 6,
            "lastActivityAt": "2026-11-08T10:00:00.000Z", "status": "published", "hidden": False,
            "url": f"https://app.station-house.net/community/posts/{pid}", **extra}


def listing(**extra):
    return {"scope": "community", "title": "Community", "following": True, "canPost": True, "writeHint": None,
            "categories": CATEGORIES, "posts": [row("7f3a", "A shared eval harness for steering vectors"),
                                                row("9c21", "How do I link my Hugging Face account?", "Questions")],
            "archivedCount": 1, "archived": [], **extra}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_lists_the_community_with_who_follows_and_where_the_archived_are(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/discussions/community")] = (200, listing())
    code, out, _ = run(capsys, "discussions", "community")
    assert code == 0
    assert "Community discussions · 2 posts · you follow this" in out
    assert "A shared eval harness for steering vectors" in out and "6 comments" in out and "7f3a" in out
    assert "1 archived: stationhouse discussions community --all" in out
    assert api.calls[0]["path"] == "/api/v1/discussions/community"


def test_all_asks_for_the_archived_and_a_category_narrows_the_list(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/discussions/community")] = (200, listing(archived=[row("aa11", "Old thread", status="archived")]))
    code, out, _ = run(capsys, "discussions", "community", "--all", "--category", "questions")
    assert code == 0
    assert api.calls[0]["path"] == "/api/v1/discussions/community?all=1"
    assert "How do I link my Hugging Face account?" in out
    assert "A shared eval harness" not in out and "Old thread" not in out


def test_an_unknown_category_lists_the_valid_ones(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/discussions/community")] = (200, listing())
    code, _, err = run(capsys, "discussions", "community", "--category", "results")
    assert code == 1
    assert 'Unknown category "results". Community categories: ideas, questions, links, other.' in err


def test_new_publishes_under_the_category_and_says_who_hears(signed_in, api, capsys, tmp_path):
    q = tmp_path / "q.md"
    q.write_text("A few tasks need an hour on one A100.")
    api.routes[("POST", "/api/v1/discussions/community")] = (201, {
        "post": {**row("9c21", "Is there a shared GPU queue for small runs?", "Questions"), "scope": "community", "body": "…",
                 "publishedAt": "2026-11-10T10:00:00.000Z", "reactions": []}, "comments": [], "canComment": True})
    code, out, _ = run(capsys, "discussions", "new", "community", "--category", "questions",
                       "--title", "Is there a shared GPU queue for small runs?", "--body-file", str(q))
    assert code == 0
    assert out.splitlines() == ["Published in Community · Questions", "https://app.station-house.net/community/posts/9c21",
                                "You follow this post. Replies reach your Inbox."]
    assert api.calls[0]["body"] == {"category": "questions", "title": "Is there a shared GPU queue for small runs?",
                                    "body": "A few tasks need an hour on one A100.", "draft": False}


def test_new_before_onboarding_prints_where_to_finish(signed_in, api, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    api.routes[("POST", "/api/v1/discussions/community")] = (403, {"error": "Finish setting up first: https://app.station-house.net/onboarding"})
    code, _, err = run(capsys, "discussions", "new", "community", "--title", "Hello")
    assert code == 1 and "Finish setting up first: https://app.station-house.net/onboarding" in err


def test_show_prints_the_post_its_comments_and_how_to_reply(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/posts/7f3a")] = (200, {
        "post": {**row("7f3a", "A shared eval harness for steering vectors"), "scope": "community",
                 "body": "Three projects now measure steering the same way.", "publishedAt": "2026-11-08T10:00:00.000Z",
                 "reactions": [{"emoji": "👍", "count": 4}]},
        "comments": [{"id": "c1", "author": "ada-tester", "at": "2026-11-08T11:00:00.000Z", "body": "Would this cover CSA too?",
                      "deleted": False, "hidden": False,
                      "replies": [{"id": "c2", "author": "ben-sample", "at": "2026-11-09T11:00:00.000Z", "body": "Yes.",
                                   "deleted": False, "hidden": False, "replies": []}]}],
        "canComment": True})
    code, out, _ = run(capsys, "discussions", "show", "7f3a")
    assert code == 0
    assert "Ideas · ben-sample · " in out and "6 comments · 👍 4" in out
    assert "— ada-tester · " in out and "Would this cover CSA too?" in out and "  — ben-sample · " in out
    assert 'Reply: stationhouse discussions reply 7f3a --body "…"' in out


def test_show_says_a_post_is_hidden_or_archived(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/posts/aa11")] = (200, {
        "post": {**row("aa11", "Old thread", status="archived", hidden=True), "scope": "community", "body": "",
                 "publishedAt": None, "reactions": []}, "comments": [], "canComment": False})
    _, out, _ = run(capsys, "discussions", "show", "aa11")
    assert "Hidden by a lead" in out and "Archived: it takes no new comments" in out
    assert "Reply:" not in out


def test_reply_and_follow(signed_in, api, capsys):
    api.routes[("POST", "/api/v1/posts/7f3a/comments")] = (200, {"post": {"title": "A shared eval harness"}, "comments": [], "canComment": True})
    api.routes[("PUT", "/api/v1/discussions/community/following")] = (200, {"scope": "community", "title": "Community", "following": True})
    _, out, _ = run(capsys, "discussions", "reply", "7f3a", "--body", "I'm in.")
    assert 'Replied on "A shared eval harness"' in out
    assert api.calls[0]["body"] == {"body": "I'm in.", "parentId": None}
    _, out, _ = run(capsys, "discussions", "follow", "community")
    assert "Following Community discussions. New posts reach your Inbox, and your Daily digest unless it's off in Preferences." in out
    # A full board's: its Project updates reach a Follower; its posts and tasks, its members (STA-388).
    api.routes[("PUT", "/api/v1/discussions/llm-self-attribution/following")] = (
        200, {"scope": "llm-self-attribution", "title": "LLM Self-Attribution", "following": True, "mode": "full"})
    _, out, _ = run(capsys, "discussions", "follow", "llm-self-attribution")
    assert out.endswith("Following LLM Self-Attribution discussions. Its Project updates reach you: a lead's in your Inbox and email, "
                        "an admin's in your email, unless it's off in Preferences.\n"
                        "Members also hear of its new posts and tasks. If you haven't joined: stationhouse join llm-self-attribution\n")
    # Discussions only (Marin): no Project updates, so following without joining brings nothing; joining brings its posts.
    api.routes[("PUT", "/api/v1/discussions/marin/following")] = (200, {"scope": "marin", "title": "Marin", "following": True, "mode": "discussions"})
    _, out, _ = run(capsys, "discussions", "follow", "marin")
    assert out.endswith("Following Marin discussions. Its new posts reach its members' Inbox, and their email unless it's off in Preferences.\n"
                        "Following without joining brings no news here today. To hear of its posts: stationhouse join marin\n")
    assert "Project update" not in out and "task" not in out
    # No board (off: Conspiracy Bench, CSA, Admin-made projects): only an admin's Project updates, by email,
    # whether or not they join; no tasks or posts. (A member who follows also gets Poll closed in the Inbox.)
    api.routes[("PUT", "/api/v1/discussions/conspiracybench/following")] = (
        200, {"scope": "conspiracybench", "title": "Conspiracy Bench", "following": True, "mode": "off"})
    _, out, _ = run(capsys, "discussions", "follow", "conspiracybench")
    assert out.endswith("Following Conspiracy Bench discussions. Its Project updates reach your email, unless it's off in Preferences.\n")
    assert not any(word in out for word in ("task", "post", "join"))


def test_json_prints_what_the_platform_answered(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/discussions/community")] = (200, listing())
    code, out, _ = run(capsys, "discussions", "community", "--json")
    assert code == 0 and '"scope": "community"' in out


ANNOUNCEMENT = {"id": "a12", "title": "A new project opens Monday: Marin Neuron Atlas", "sentBy": "Ada Tester",
                "sentAt": "2026-11-10T09:00:00.000Z", "comments": 0, "firstLine": "We're mapping…",
                "url": "https://app.station-house.net/community/announcements/a12"}


def test_announcements_list_show_latest_and_comment(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/announcements")] = (200, {"announcements": [ANNOUNCEMENT]})
    api.routes[("GET", "/api/v1/announcements/latest")] = (200, {
        "announcement": {**ANNOUNCEMENT, "body": "We're mapping what individual neurons respond to.",
                         "button": {"label": "Have a look", "url": "https://app.station-house.net/projects/marin"},
                         "reactions": []}, "comments": [], "canComment": True})
    api.routes[("POST", "/api/v1/announcements/latest/comments")] = (200, {"announcement": {**ANNOUNCEMENT}, "comments": [], "canComment": True})
    _, out, _ = run(capsys, "announcements")
    assert "A new project opens Monday: Marin Neuron Atlas" in out and "Ada Tester" in out
    _, out, _ = run(capsys, "announcements", "show", "latest")
    assert out.splitlines()[0].startswith("Announcement · from Ada Tester · ")
    assert "Have a look: https://app.station-house.net/projects/marin" in out
    assert "Page: https://app.station-house.net/community/announcements/a12" in out
    _, out, _ = run(capsys, "announcements", "comment", "--body", "Signed up.")
    assert out.splitlines() == ['Commented on "A new project opens Monday: Marin Neuron Atlas"',
                                "You follow this announcement. Replies reach your Inbox."]


def test_no_announcements_yet(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/announcements")] = (200, {"announcements": []})
    _, out, _ = run(capsys, "announcements")
    assert "No announcements yet." in out
