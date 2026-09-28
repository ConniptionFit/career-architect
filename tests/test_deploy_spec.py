"""The Jobs virtual MCP server (deploy/jobs-vMCP.json) and the skill must describe the same set of tools.

The vMCP exposes an allowlist; the skill's references say which of those tools to call and how. If one changes without the other,
an agent is told to call a tool that does not exist, or is offered a tool nothing explains. These tests keep them together.

Run: uv run --python 3.12 --with pyyaml --with "mcp==2.2.0" python -m unittest discover -s tests -v"""
import asyncio
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "deploy" / "jobs-vmcp.json").read_text())
SKILL = ROOT / "jobs"
BY_PREFIX = {s["prefix"]: s for s in SPEC["sources"]}
FULL = re.compile(r"\b(" + "|".join(BY_PREFIX) + r")__([a-z][a-z_]*[a-z])\b")          # a source added to the spec is covered without editing this file


def enabled(prefix: str) -> set:
    return set(BY_PREFIX[prefix]["enabled"])


def backticked_first_column(text: str, heading: str) -> set:
    """The tool names in the first column of the markdown table under `heading` (a line of the document)."""
    section = text.split(heading, 1)[1]
    names = set()
    started = False
    for line in section.splitlines():
        if line.startswith("|"):
            started = True
            first = line.split("|")[1]
            names |= set(re.findall(r"`([a-z_]+)`", first))
        elif started:
            break
    return names - {"tool", "purpose"}


class SpecShape(unittest.TestCase):
    def test_every_tool_is_either_enabled_or_disabled_never_both(self):
        for s in SPEC["sources"]:
            self.assertFalse(set(s["enabled"]) & set(s["disabled"]), s["component"])
            self.assertEqual(len(s["enabled"]), len(set(s["enabled"])), s["component"])

    def test_prefixes_and_components_are_unique(self):
        self.assertEqual(len(BY_PREFIX), len(SPEC["sources"]))
        self.assertEqual(len({s["component"] for s in SPEC["sources"]}), len(SPEC["sources"]))
        for s in SPEC["sources"]:
            self.assertEqual(s["prefix"], re.sub(r"[^a-z0-9]+", "_", s["component"].lower()))       # Obot derives the prefix from the component name

    def test_every_enabled_tool_of_a_third_party_source_has_words_for_an_agent(self):
        for prefix in ("google_drive", "google_docs"):
            s = BY_PREFIX[prefix]
            self.assertEqual(set(s["descriptions"]), set(s["enabled"]), prefix)
            for name, text in s["descriptions"].items():
                self.assertGreater(len(text), 40, f"{prefix}__{name}")

    def test_the_documents_quote_the_real_number_of_tools(self):
        total = sum(len(s["enabled"]) for s in SPEC["sources"])
        for doc in ("docs/OPERATIONS.md", "docs/SECURITY.md", "CHANGELOG.md"):
            text = (ROOT / doc).read_text()
            self.assertRegex(text, rf"\b{total} (?:tools|at the time)", f"{doc} should say the Jobs server exposes {total} tools")

    def test_the_vmcp_description_says_when_to_use_it_and_names_every_source(self):
        text = SPEC["description"]
        self.assertLessEqual(len(text), 1200)
        for prefix in BY_PREFIX:
            self.assertIn(prefix + "__", text)
        self.assertIn("job posting", text)
        self.assertIn("jobs", text)

    def test_descriptions_only_name_tools_that_are_enabled(self):
        blob = json.dumps(SPEC)
        for prefix, tool in FULL.findall(blob):
            self.assertIn(tool, enabled(prefix), f"{prefix}__{tool} is named in the spec but not enabled")

    def test_dangerous_capabilities_stay_off(self):
        never = {"google_drive": {"delete_file", "transfer_ownership", "create_permission", "update_permission", "delete_permission", "delete_shared_drive"},
                 "reactive_resume": {"delete_resume", "delete_application", "delete_cover_letter", "bulk_delete_applications", "unlock_resume", "lock_resume",
                                     "import_resume", "attach_application_document", "tailor_resume_for_application", "draft_application_message"},
                 "google_docs": {"delete_content", "batch_update_document"}}
        for prefix, tools in never.items():
            self.assertFalse(tools & enabled(prefix), prefix)


class SkillMatchesSpec(unittest.TestCase):
    def test_every_full_tool_name_in_the_skill_is_exposed(self):
        for path in SKILL.rglob("*.md"):
            for prefix, tool in FULL.findall(path.read_text()):
                self.assertIn(tool, enabled(prefix), f"{path.relative_to(ROOT)} names {prefix}__{tool}, which the Jobs server does not expose")

    def test_storage_protocol_covers_exactly_the_drive_and_docs_tools_that_are_exposed(self):
        text = (SKILL / "references" / "storage.md").read_text()
        used = {(p, t) for p, t in FULL.findall(text)}
        for prefix in ("google_drive", "google_docs"):
            self.assertEqual({t for p, t in used if p == prefix}, enabled(prefix), prefix)

    def test_reactive_resume_reference_covers_exactly_the_exposed_tools(self):
        text = (SKILL / "references" / "reactive-resume.md").read_text()
        writes = backticked_first_column(text, "## Allowed writes")
        reads_line = next(line for line in text.splitlines() if line.startswith("Reads are always fine:"))
        reads = set(re.findall(r"`([a-z_]+)`", reads_line))
        # the create_/update_ row lists three tools in one cell, and the read row is a sentence: both are parsed above
        allowed = writes | reads
        self.assertLessEqual(allowed, enabled("reactive_resume"), f"documented but not exposed: {sorted(allowed - enabled('reactive_resume'))}")
        mentioned = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", text))
        self.assertEqual(enabled("reactive_resume") - mentioned, set(), "exposed but not explained in reactive-resume.md")

    def test_tools_reference_lists_exactly_the_career_architect_tools(self):
        text = (SKILL / "references" / "tools.md").read_text()
        listed = backticked_first_column(text, "| Tool |")
        self.assertEqual(listed, enabled("career_architect"))

    def test_skill_md_names_every_source_prefix(self):
        text = (SKILL / "SKILL.md").read_text()
        for prefix in BY_PREFIX:
            self.assertIn(prefix + "__", text)

    def test_every_exposed_tool_of_every_source_is_explained_somewhere_in_the_skill(self):
        """The rule that makes adding a server safe: a tool nothing in the skill mentions is a tool the agent was never told how to use."""
        docs = "\n".join(p.read_text() for p in SKILL.rglob("*.md"))
        for prefix, source in BY_PREFIX.items():
            for tool in source["enabled"]:
                self.assertTrue(f"{prefix}__{tool}" in docs or re.search(rf"`{tool}`", docs), f"{prefix}__{tool} is exposed but no document in jobs/ mentions it")


@unittest.skipUnless(sys.version_info >= (3, 10), "needs Python 3.10+ and the mcp package")
class ServerMatchesSpec(unittest.TestCase):
    def test_career_architect_source_lists_the_tools_the_server_registers(self):
        try:
            sys.path.insert(0, str(ROOT / "mcp-server"))
            from mcp.client import Client
            import server as srv
        except ImportError:
            self.skipTest("the mcp package is not installed")

        async def names():
            async with Client(srv.server) as c:
                return {t.name for t in (await c.list_tools()).tools}
        self.assertEqual(asyncio.run(names()), enabled("career_architect"))


if __name__ == "__main__":
    unittest.main()
