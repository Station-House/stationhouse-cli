"""The CLI's commands as its parser has them, for the platform's copy (cli/commands.json).

The platform reads cli/commands.json (src/lib/stationhouse-cli.ts) to know which `stationhouse ...`
commands exist, so the web assistant never points a member at one the CLI doesn't have.
tests/test_commands_json.py fails when the file and the parser disagree; regenerate it with

    uv run python -m stationhouse_cli.commands > commands.json
"""
import argparse
import json

from .cli import build_parser


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)  # noqa: SLF001


def command_tree(parser=None) -> dict[str, list[str]]:
    """Every top-level command (aliases included) and the subcommands under it, sorted."""
    sub = _subparsers(parser or build_parser())
    tree = {}
    for name, sp in sub.choices.items():
        nested = _subparsers(sp)
        tree[name] = sorted(nested.choices) if nested else []
    return dict(sorted(tree.items()))


def render() -> str:
    return json.dumps({"commands": command_tree()}, indent=2) + "\n"


if __name__ == "__main__":
    print(render(), end="")
