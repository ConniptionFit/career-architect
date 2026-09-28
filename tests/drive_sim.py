"""Helpers that imitate what the Google Drive and Google Docs tools do to a plain-text Google Doc, shared by the tests."""
import re

_ESCAPE = re.compile(r"([\\\[\]_>~#*])")


def drive_render(text: str) -> str:
    """What Claude's own Drive connector (`read_file_content`) does to a plain-text Google Doc, as observed on the real connector:
    markdown punctuation is backslash-escaped and every line is followed by a blank line (a blank line becomes two spaces)."""
    return "\n\n".join("  " if line == "" else _ESCAPE.sub(r"\\\1", line) for line in text.split("\n"))


def docs_render(text: str) -> str:
    """What `get_document` of the Obot Google Docs server returns for a document whose body is `text` inserted as plain
    paragraphs (read from the server's converter, obot-platform/google-mcp docs/app/documents.py): the body opens with a
    section break, rendered as a `---` line; a text paragraph is its line plus a newline, an empty one is a bare newline;
    nothing is escaped; the result is right-trimmed."""
    parts = ["\n---\n"]
    for line in text.split("\n"):
        parts.append("\n" if not line.strip() else line + "\n")
    return "".join(parts).rstrip()
