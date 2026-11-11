"""`stationhouse email` and `stationhouse email set` (STA-286): the copy from the CLI frame
(CLI_stationhouse-email), "already" when a set changes nothing, an unknown kind named, and the
route each calls."""
import json

from stationhouse_cli import cli

PATH = "/api/v1/me/email"


def email(digest=True, activity=True, announcements=False, changed=None, sending=True, address="ada@example.test"):
    body = {"digest": digest, "activity": activity, "announcements": announcements, "address": address,
            "timeZone": "Europe/Berlin", "sending": sending, "projects": {"joined": 2, "followed": 3}}
    if changed is not None:
        body["changed"] = changed
    return body


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_email_lists_the_three_switches_in_the_frames_words(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (200, email())
    code, out, _ = run(capsys, "email")
    assert code == 0
    assert out == (
        "Email for ada@example.test\n"
        "  Daily digest      on    9am Europe/Berlin · new tasks and reminders from 2 projects you've joined\n"
        "  Project activity  on    updates and Inbox news from the 3 projects you follow\n"
        "  Announcements     off   community news from the Stationhouse team\n"
        "  Stop all email from one project: stationhouse unfollow <project>\n"
        "  Change one: stationhouse email set digest|activity|announcements on|off\n"
    )


def test_email_says_when_stationhouse_isnt_sending_yet_and_counts_one_project(signed_in, api, capsys):
    body = email(sending=False)
    body["projects"] = {"joined": 1, "followed": 1}
    api.routes[("GET", PATH)] = (200, body)
    _, out, _ = run(capsys, "email")
    assert "  Stationhouse isn't sending these emails yet. Your choices are saved and apply from the first one.\n" in out
    assert "from 1 project you've joined\n" in out
    assert "from the 1 project you follow\n" in out


def test_email_json_has_the_frames_fields(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (200, email(activity=False, announcements=True))
    _, out, _ = run(capsys, "email", "--json")
    assert json.loads(out) == {"digest": True, "activity": False, "announcements": True,
                               "timeZone": "Europe/Berlin", "sending": True}


def test_set_announcements_on_names_the_address(signed_in, api, capsys):
    api.routes[("PATCH", PATH)] = (200, email(announcements=True, changed=True))
    code, out, _ = run(capsys, "email", "set", "announcements", "on")
    assert code == 0
    assert out == "Announcements on. Community news reaches ada@example.test.\n"
    assert api.calls[-1]["method"] == "PATCH" and api.calls[-1]["path"] == PATH
    assert api.calls[-1]["body"] == {"announcements": True}


def test_set_activity_off_says_mentions_arent_emailed_and_how_to_undo(signed_in, api, capsys):
    api.routes[("PATCH", PATH)] = (200, email(activity=False, changed=True))
    _, out, _ = run(capsys, "email", "set", "activity", "off")
    assert out == ("Project activity off. Updates and Inbox news stay in your Inbox; none of it is emailed.\n"
                   "  Mentions aren't emailed either. Undo: stationhouse email set activity on\n")
    assert api.calls[-1]["body"] == {"activity": False}


def test_set_twice_changes_nothing_and_says_so(signed_in, api, capsys):
    api.routes[("PATCH", PATH)] = (200, email(activity=False, changed=False))
    _, out, _ = run(capsys, "email", "set", "activity", "off")
    assert out == "Project activity was already off. Nothing changed.\n"


def test_set_json_adds_changed(signed_in, api, capsys):
    api.routes[("PATCH", PATH)] = (200, email(digest=False, changed=True))
    _, out, _ = run(capsys, "email", "set", "digest", "off", "--json")
    assert json.loads(out) == {"digest": False, "activity": True, "announcements": False,
                               "timeZone": "Europe/Berlin", "sending": True, "changed": True}


def test_set_digest_off_and_on(signed_in, api, capsys):
    api.routes[("PATCH", PATH)] = (200, email(digest=False, changed=True))
    _, out, _ = run(capsys, "email", "set", "digest", "off")
    assert out == ("Daily digest off. New tasks and reminders stay on Stationhouse; none of it is emailed.\n"
                   "  Undo: stationhouse email set digest on\n")
    api.routes[("PATCH", PATH)] = (200, email(digest=True, changed=True))
    _, out, _ = run(capsys, "email", "set", "digest", "on")
    assert out == "Daily digest on. New tasks and reminders reach ada@example.test at 9am Europe/Berlin.\n"


def test_an_unknown_kind_names_the_valid_ones_without_calling(signed_in, api, capsys):
    calls = len(api.calls)
    code, out, err = run(capsys, "email", "set", "weekly", "off")
    assert code == 2
    assert out == ""
    assert err == 'No kind of email called "weekly". Use digest, activity or announcements.\n'
    assert len(api.calls) == calls


def test_a_value_that_isnt_on_or_off_is_refused(signed_in, api, capsys):
    code, _, err = run(capsys, "email", "set", "digest", "maybe")
    assert code == 2
    assert err == 'Use on or off, not "maybe": stationhouse email set digest on|off\n'


def test_set_without_a_kind_says_how(signed_in, api, capsys):
    code, _, err = run(capsys, "email", "set")
    assert code == 1
    assert err == "error: Which one? stationhouse email set digest|activity|announcements on|off\n"


def test_an_older_server_says_it_doesnt_have_email_yet(signed_in, api, capsys):
    api.routes[("GET", PATH)] = (404, {})
    code, _, err = run(capsys, "email")
    assert code == 1
    assert err == "error: This Station House server doesn't have `email` yet.\n"
