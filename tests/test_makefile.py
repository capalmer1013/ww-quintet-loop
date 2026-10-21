"""The Makefile is the project's documentation of how to run it: every quintet flag must be in
`make help`."""

from dataclasses import fields
from pathlib import Path

from quintet import Config

MAKEFILE = (Path(__file__).resolve().parents[1] / "Makefile").read_text()


def test_every_flag_is_in_make_help():
    help_text = MAKEFILE[MAKEFILE.index("help:") : MAKEFILE.index("sync:")]
    for f in fields(Config(argv=[], tempo=60)):
        flag = "--" + f.name.replace("_", "-")
        assert flag in help_text, f"{flag} is missing from make help"
        if isinstance(f.default, bool):
            assert "--no-" + f.name.replace("_", "-") in help_text, f"--no-{flag[2:]} is missing from make help"
