"""The skill as a package: what Obot's skill sync and the Agent Skills standard require, and that its templates work."""
import datetime as dt
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "jobs"
sys.path.insert(0, str(SKILL / "scripts"))
import career  # noqa: E402

NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter(path: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path} has no front matter"
    return yaml.safe_load(m.group(1))


class AgentSkillsSpec(unittest.TestCase):
    def setUp(self):
        self.fm = frontmatter(SKILL / "SKILL.md")

    def test_name_matches_the_directory_and_the_pattern(self):
        self.assertEqual(self.fm["name"], SKILL.name)
        self.assertLessEqual(len(self.fm["name"]), 64)
        self.assertRegex(self.fm["name"], NAME)

    def test_description_and_compatibility_limits(self):
        self.assertTrue(self.fm["description"].strip())
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertLessEqual(len(self.fm.get("compatibility", "")), 500)

    def test_only_specified_fields_and_string_metadata(self):
        self.assertLessEqual(set(self.fm), {"name", "description", "license", "compatibility", "metadata", "allowed-tools"})
        self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in self.fm.get("metadata", {}).items()))

    def test_skill_md_stays_under_500_lines(self):
        self.assertLess(len((SKILL / "SKILL.md").read_text().splitlines()), 500)

    def test_every_file_the_docs_point_to_exists(self):
        missing = []
        for doc in [SKILL / "SKILL.md", *SKILL.glob("*/*.md")]:
            for ref in re.findall(r"`((?:references|workflows|assets|style|scripts)/[A-Za-z0-9_./-]+)`", doc.read_text()):
                if not (SKILL / ref.rstrip(".")).exists():
                    missing.append(f"{doc.relative_to(SKILL)} -> {ref}")
        self.assertEqual(missing, [])

    def test_references_are_one_level_deep(self):
        for doc in SKILL.glob("references/**/*.md"):
            self.assertEqual(doc.parent, SKILL / "references")

    def test_the_route_table_reaches_every_workflow_and_reference(self):
        text = (SKILL / "SKILL.md").read_text()
        for f in [*SKILL.glob("workflows/*.md"), *SKILL.glob("references/*.md")]:
            self.assertIn(f"{f.parent.name}/{f.name}", text, f"SKILL.md never points at {f.name}")


class PublicRepositoryHygiene(unittest.TestCase):
    FORBIDDEN = ("John Powers", "pwrs.dev", "Obsidian Vault", "monstrousmule", "/Users/powers")

    def test_no_personal_details_in_shipped_files(self):
        hits = []
        for path in [*SKILL.rglob("*"), *(ROOT / "mcp-server").rglob("*"), *(ROOT / "tests").rglob("*"), *ROOT.glob("*.md"), ROOT / "setup.sh"]:
            if not path.is_file() or path.suffix in (".pyc", ".skill") or "__pycache__" in path.parts or path == Path(__file__).resolve():
                continue
            text = path.read_text(errors="ignore")
            hits += [f"{path.relative_to(ROOT)}: {w}" for w in self.FORBIDDEN if w in text]
        self.assertEqual(hits, [])


class Templates(unittest.TestCase):
    TODAY = dt.date(2026, 9, 28)

    def test_the_shared_and_role_templates_merge_and_validate(self):
        docs = [(SKILL / "assets" / n).read_text() for n in ("facts-shared.md", "facts-role.md")]
        facts = career.merge_facts(docs)
        self.assertEqual(career.validate(facts, self.TODAY), [])
        self.assertEqual([r["id"] for r in facts["roles"]], ["acme-se"])
        self.assertIn("mdm", career.build_index(facts, self.TODAY))

    def test_the_local_single_file_template_still_validates(self):
        facts = career.parse_block((SKILL / "assets" / "facts.md").read_text())
        self.assertEqual(career.validate({**{"roles": [], "credentials": [], "education": [], "aliases": {}}, **facts}, self.TODAY), [])

    def test_the_profile_template_parses(self):
        prof = career.parse_front((SKILL / "assets" / "profile.md").read_text())
        for key in ("name", "never_claim", "known_gaps", "pending", "rr_master"):
            self.assertIn(key, prof)


if __name__ == "__main__":
    unittest.main()
