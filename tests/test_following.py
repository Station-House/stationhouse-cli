"""join, leave, follow, unfollow and following (STA-276–280): the copy from the Join & Follow CLI frame,
"already" when a second run changes nothing, and the routes each calls."""
import json

from stationhouse_cli import cli

MARIN = "marin-neuron-atlas"
CSA = "llm-self-attribution"


def change(project=MARIN, title="Marin Neuron Atlas", member=True, lead=False, following=True, reason="joined", changed=True):
    return {"projectId": project, "title": title, "member": member, "lead": lead, "following": following,
            "reason": reason, "changed": changed}


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_join_follows_too_and_offers_unfollow(signed_in, api, capsys):
    api.routes[("PUT", f"/api/v1/projects/{MARIN}/membership")] = (200, change())
    code, out, _ = run(capsys, "join", MARIN)
    assert code == 0
    assert out == ("Joined Marin Neuron Atlas. You follow it too: its posts, tasks and updates reach your Inbox and email.\n"
                   f"  Stay a member but hear nothing: stationhouse unfollow {MARIN}\n")
    assert api.calls[-1]["method"] == "PUT" and api.calls[-1]["path"] == f"/api/v1/projects/{MARIN}/membership"


def test_join_twice_changes_nothing_and_says_so(signed_in, api, capsys):
    api.routes[("PUT", f"/api/v1/projects/{MARIN}/membership")] = (200, change(changed=False))
    _, out, _ = run(capsys, "join", MARIN)
    assert out == "You're already a member of Marin Neuron Atlas.\n"


def test_follow_without_joining_points_at_join(signed_in, api, capsys):
    api.routes[("PUT", "/api/v1/projects/conspiracybench/following")] = (
        200, change("conspiracybench", "Conspiracy Bench", member=False, reason="followed"))
    # No project named: the one picked (conftest picks conspiracybench).
    _, out, _ = run(capsys, "follow")
    assert out == ("Following Conspiracy Bench. Its updates reach your Inbox and email. You haven't joined.\n"
                   "  To post or take tasks: stationhouse join conspiracybench\n")


def test_unfollow_keeps_a_member_one_and_json_has_the_frames_fields(signed_in, api, capsys):
    api.routes[("DELETE", f"/api/v1/projects/{MARIN}/following")] = (200, change(following=False, reason=None))
    _, out, _ = run(capsys, "unfollow", MARIN)
    assert out == ("Stopped following Marin Neuron Atlas. You're still a member.\n"
                   "  You'll still hear when someone mentions you or about tasks that are yours.\n"
                   f"  Follow again: stationhouse follow {MARIN}\n")
    _, out, _ = run(capsys, "unfollow", MARIN, "--json")
    assert json.loads(out) == {"project": MARIN, "member": True, "following": False, "reason": None, "changed": True}


def test_leave_keeps_the_follow(signed_in, api, capsys):
    api.routes[("DELETE", f"/api/v1/projects/{MARIN}/membership")] = (200, change(member=False, reason="followed"))
    _, out, _ = run(capsys, "leave", MARIN)
    assert out == ("Left Marin Neuron Atlas. Tasks you're on stay yours. You still follow it.\n"
                   f"  Stop hearing about it: stationhouse unfollow {MARIN}\n")


def test_a_lead_cant_leave(signed_in, api, capsys):
    message = "You lead Consciousness Self-Attribution, so you can't leave it. An admin can appoint another lead."
    api.routes[("DELETE", f"/api/v1/projects/{CSA}/membership")] = (409, {"error": message})
    code, _, err = run(capsys, "leave", CSA)
    assert code == 1 and err == f"error: {message}\n"


def test_a_project_you_cant_see_suggests_the_nearest(signed_in, api, capsys):
    api.routes[("PUT", "/api/v1/projects/marin/following")] = (403, {"error": "Forbidden"})
    api.routes[("GET", "/api/v1/projects")] = (200, {"projects": [{"id": MARIN, "title": "Marin Neuron Atlas"},
                                                                   {"id": CSA, "title": "Consciousness Self-Attribution"}]})
    code, _, err = run(capsys, "follow", "marin")
    assert code == 1
    assert err == f'error: No project "marin". Did you mean {MARIN}? See: stationhouse projects\n'
    api.routes[("PUT", "/api/v1/projects/zzz/following")] = (403, {"error": "Forbidden"})
    _, _, err = run(capsys, "follow", "zzz")
    assert err == 'error: No project "zzz". See: stationhouse projects\n'
    # One you can list but may not change: the platform's reason, not "no project".
    api.routes[("PUT", f"/api/v1/projects/{CSA}/following")] = (403, {"error": "Admins only."})
    _, _, err = run(capsys, "follow", CSA)
    assert err == "error: Admins only.\n"


def test_follow_a_page_by_hand_and_again(signed_in, api, capsys):
    path = "/api/v1/pages/p-42/following"
    api.routes[("GET", path)] = (200, {"following": False, "reason": None, "unfollowed": False, "projectFollowing": True, "others": 2})
    api.routes[("PUT", path)] = (200, {"following": True, "reason": "followed", "unfollowed": False, "projectFollowing": True, "others": 2})
    _, out, _ = run(capsys, "follow", "--page", "p-42")
    assert out == "Following page p-42. New replies reach your Inbox and email.\n  Unfollow: stationhouse unfollow --page p-42\n"
    assert [c["method"] for c in api.calls] == ["GET", "PUT"]
    api.routes[("GET", path)] = (200, {"following": True, "reason": "mentioned", "unfollowed": False, "projectFollowing": True, "others": 2})
    api.calls.clear()
    _, out, _ = run(capsys, "follow", "--page", "p-42")
    assert out == "You already follow page p-42 (you were mentioned).\n"
    assert [c["method"] for c in api.calls] == ["GET"]


def test_unfollow_a_page(signed_in, api, capsys):
    path = "/api/v1/pages/p-42/following"
    api.routes[("GET", path)] = (200, {"following": True, "reason": "commented", "unfollowed": False, "projectFollowing": False, "others": 0})
    api.routes[("DELETE", path)] = (200, {"following": False, "reason": None, "unfollowed": True, "projectFollowing": False, "others": 0})
    _, out, _ = run(capsys, "unfollow", "--page", "p-42", "--json")
    assert json.loads(out)["unfollowed"] is True and json.loads(out)["changed"] is True
    _, out, _ = run(capsys, "unfollow", "--page", "p-42")
    assert out.startswith("Stopped following page p-42. Mentions still reach you.\n")


def test_a_page_or_a_project_not_both(signed_in, api, capsys):
    code, _, err = run(capsys, "follow", MARIN, "--page", "p-42")
    assert code == 1 and "not both" in err and api.calls == []


def page(n, project=MARIN, reason="mentioned"):
    return {"pageId": f"p-{n}", "projectId": project, "projectTitle": "", "kind": "post", "title": f"Post {n}",
            "reason": reason, "lastActivityAt": "2026-11-10T10:00:00.000Z"}


def test_following_lists_projects_by_id_and_the_newest_pages(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/following")] = (200, {
        "projects": [change(following=False, reason=None),
                     change("conspiracybench", "Conspiracy Bench", member=False, reason="followed"),
                     change(CSA, "Consciousness Self-Attribution", lead=True)],
        "pages": [page(1, reason="mentioned"), page(2, CSA, "owner")] + [page(n) for n in range(3, 13)],
    })
    code, out, _ = run(capsys, "following")
    lines = out.splitlines()
    assert code == 0 and lines[0] == "Projects"
    assert [line.split()[0] for line in lines[1:4]] == ["conspiracybench", CSA, MARIN]
    assert lines[1].endswith("follower")
    assert lines[2].endswith("lead · following")
    assert lines[3].endswith("member · not following")
    assert lines[4] == "Pages (12)"
    assert lines[5].split() == ["Post", "1", MARIN, "you", "were", "mentioned", "p-1"]
    assert "you own this task" in lines[6]
    assert lines[-2] == "  … 2 more (stationhouse following --json lists them all)"
    assert lines[-1] == "  Unfollow one: stationhouse unfollow --page <id>"


def test_following_with_nothing_followed(signed_in, api, capsys):
    api.routes[("GET", "/api/v1/me/following")] = (200, {"projects": [], "pages": []})
    _, out, _ = run(capsys, "following")
    assert out == ("Projects\n  None yet. Follow one: stationhouse follow <project>\n"
                   "Pages (0)\n  None yet. You follow a page you write, comment on or are mentioned on.\n")


def test_an_older_server_says_it_has_no_following_yet(signed_in, api, capsys):
    code, _, err = run(capsys, "following")
    assert code == 1 and "doesn't have `following` yet" in err
