"""Helpers that imitate the Google Drive connector, shared by the tests."""
import re

_ESCAPE = re.compile(r"([\\\[\]_>~#*])")


def drive_render(text: str) -> str:
    """What `read_file_content` does to a plain-text Google Doc, as observed on the real connector: markdown punctuation is
    backslash-escaped and every line is followed by a blank line (a blank line becomes two spaces)."""
    return "\n\n".join("  " if line == "" else _ESCAPE.sub(r"\\\1", line) for line in text.split("\n"))
