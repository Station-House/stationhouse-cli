from pathlib import Path

from stationhouse_cli.commands import render

COMMANDS_JSON = Path(__file__).resolve().parent.parent / "commands.json"


def test_commands_json_matches_the_parser():
    assert COMMANDS_JSON.read_text(encoding="utf-8") == render(), (
        "cli/commands.json is out of date: run `uv run python -m stationhouse_cli.commands > commands.json` in cli/"
    )
