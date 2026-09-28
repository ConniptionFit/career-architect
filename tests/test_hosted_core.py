"""Tests for the parts the hosted service is built on: text stored in Google Drive, facts fragments, and the
self-contained skills index that scoring and linting run from.

Run: uv run --with pyyaml python -m unittest discover -s tests -v"""
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import career  # noqa: E402
from drive_sim import drive_render as _drive_render  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "data"
TODAY = dt.date(2026, 9, 20)

# The text that was uploaded to Drive as a plain-text Google Doc (a tab stood where TAB is).
_SENT = """---
schema: 1
roles:
  - id: acme-se
    title: "Senior Systems Engineer"
    span: 2019-03..present
    atoms:
      - id: acme-01
        say: 'Managed 1,800 devices in Jamf: enrolled, patched, and retired them.'
        tags: [jamf, mdm, macos]
        status: verified
        nums: {devices: "1,800"}
        note: >
          Folded block with "double quotes", a colon: here, an em dash \u2014 and \u00fc \u2713.
# comment{TAB}with a tab
      - id: acme-02
        say: Led the SCIM rollout (Okta -> Slack) for ~400 users.
        only_for: [scim]
1. numbered-looking line
* bullet-looking line
[link-looking](https://example.com)
    four-space indented line with trailing spaces{TS}

Blank line above. A very long line follows to test wrapping behaviour: lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris.
---
""".replace("{TS}", "   ")

# Captured verbatim from the Drive connector for that document.
# read_file_content -> "fileContent" (the JSON string body): escaped punctuation, a blank line after every line, tab became one space.
_DRIVE_READ_JSON = (r'\\---\n\nschema: 1\n\nroles:\n\n  - id: acme-se\n\n    title: \"Senior Systems Engineer\"\n\n    span: 2019-03..present\n\n    atoms:\n\n'
                    r'      - id: acme-01\n\n        say: '"'"r'Managed 1,800 devices in Jamf: enrolled, patched, and retired them.'"'"r'\n\n        tags: \\[jamf, mdm, macos\\]\n\n'
                    r'        status: verified\n\n        nums: {devices: \"1,800\"}\n\n        note: \\>\n\n'
                    '          Folded block with \\"double quotes\\", a colon: here, an em dash \u2014 and \u00fc \u2713.\\n\\n'
                    r'\\# comment with a tab\n\n      - id: acme-02\n\n        say: Led the SCIM rollout (Okta -\\> Slack) for \\~400 users.\n\n'
                    r'        only\\_for: \\[scim\\]\n\n1\\. numbered-looking line\n\n\\* bullet-looking line\n\n\\[link-looking\\](https://example.com)\n\n'
                    r'    four-space indented line with trailing spaces   \n\n  \n\n'
                    r'Blank line above. A very long line follows to test wrapping behaviour: lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod '
                    r'tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris.\n\n\\---\n\n  ')
# download_file_content(exportMimeType=text/plain) -> "content": UTF-8 with a BOM and CRLF, tab expanded to spaces, no final newline.
_DRIVE_DOWNLOAD_B64 = (
    "77u/LS0tDQpzY2hlbWE6IDENCnJvbGVzOg0KICAtIGlkOiBhY21lLXNlDQogICAgdGl0bGU6ICJTZW5pb3IgU3lzdGVtcyBFbmdpbmVlciINCiAgICBzcGFuOiAyMDE5LTAzLi5wcmVzZW50DQog"
    "ICAgYXRvbXM6DQogICAgICAtIGlkOiBhY21lLTAxDQogICAgICAgIHNheTogJ01hbmFnZWQgMSw4MDAgZGV2aWNlcyBpbiBKYW1mOiBlbnJvbGxlZCwgcGF0Y2hlZCwgYW5kIHJldGlyZWQgdGhl"
    "bS4nDQogICAgICAgIHRhZ3M6IFtqYW1mLCBtZG0sIG1hY29zXQ0KICAgICAgICBzdGF0dXM6IHZlcmlmaWVkDQogICAgICAgIG51bXM6IHtkZXZpY2VzOiAiMSw4MDAifQ0KICAgICAgICBub3Rl"
    "OiA+DQogICAgICAgICAgRm9sZGVkIGJsb2NrIHdpdGggImRvdWJsZSBxdW90ZXMiLCBhIGNvbG9uOiBoZXJlLCBhbiBlbSBkYXNoIOKAlCBhbmQgw7wg4pyTLg0KIyBjb21tZW50ICAgICAgICB3"
    "aXRoIGEgdGFiDQogICAgICAtIGlkOiBhY21lLTAyDQogICAgICAgIHNheTogTGVkIHRoZSBTQ0lNIHJvbGxvdXQgKE9rdGEgLT4gU2xhY2spIGZvciB+NDAwIHVzZXJzLg0KICAgICAgICBvbmx5"
    "X2ZvcjogW3NjaW1dDQoxLiBudW1iZXJlZC1sb29raW5nIGxpbmUNCiogYnVsbGV0LWxvb2tpbmcgbGluZQ0KW2xpbmstbG9va2luZ10oaHR0cHM6Ly9leGFtcGxlLmNvbSkNCiAgICBmb3VyLXNw"
    "YWNlIGluZGVudGVkIGxpbmUgd2l0aCB0cmFpbGluZyBzcGFjZXMgICANCg0KDQpCbGFuayBsaW5lIGFib3ZlLiBBIHZlcnkgbG9uZyBsaW5lIGZvbGxvd3MgdG8gdGVzdCB3cmFwcGluZyBiZWhh"
    "dmlvdXI6IGxvcmVtIGlwc3VtIGRvbG9yIHNpdCBhbWV0IGNvbnNlY3RldHVyIGFkaXBpc2NpbmcgZWxpdCBzZWQgZG8gZWl1c21vZCB0ZW1wb3IgaW5jaWRpZHVudCB1dCBsYWJvcmUgZXQgZG9s"
    "b3JlIG1hZ25hIGFsaXF1YSB1dCBlbmltIGFkIG1pbmltIHZlbmlhbSBxdWlzIG5vc3RydWQgZXhlcmNpdGF0aW9uIHVsbGFtY28gbGFib3Jpcy4NCi0tLQ==")


class DriveText(unittest.TestCase):
    def test_read_file_content_output_is_restored(self):
        got = career.normalize_drive_text(json.loads('"' + _DRIVE_READ_JSON + '"'), "drive_read")
        self.assertEqual(got, _SENT.replace("{TAB}", " "))

    def test_read_file_content_is_recognised_without_being_told(self):
        got = career.normalize_drive_text(json.loads('"' + _DRIVE_READ_JSON + '"'))
        self.assertEqual(got, _SENT.replace("{TAB}", " "))

    def test_download_file_content_base64_is_decoded(self):
        # The export drops the final newline, expands the tab to spaces and, oddly, adds a second blank line after the line with trailing
        # spaces. Blank lines mean nothing in YAML; `read_file_content` (above) is the exact path and the one the skill prefers.
        want = _SENT.replace("{TAB}", " " * 8).rstrip("\n").replace("spaces   \n\nBlank", "spaces   \n\n\nBlank")
        self.assertEqual(career.normalize_drive_text(_DRIVE_DOWNLOAD_B64, "base64"), want)
        self.assertEqual(career.normalize_drive_text(_DRIVE_DOWNLOAD_B64), want)   # and auto detects it
        self.assertNotIn("\r", career.normalize_drive_text(_DRIVE_DOWNLOAD_B64))
        self.assertFalse(career.normalize_drive_text(_DRIVE_DOWNLOAD_B64).startswith("\ufeff"))

    def test_a_facts_document_survives_the_drive_round_trip(self):
        text = (FIXTURES / "facts.md").read_text()
        self.assertEqual(career.normalize_drive_text(_drive_render(text)), text)
        self.assertEqual(career.parse_block(career.normalize_drive_text(_drive_render(text))), career.parse_block(text))

    def test_clean_text_is_left_alone(self):
        for text in ("a: 1\n\nb: 2\n", "tags: [a, b]\nsay: \"x\"\n", "a\n\nb\n\nc\n\nd\n"):
            self.assertEqual(career.normalize_drive_text(text), text, text)

    def test_ordinary_words_that_look_like_base64_are_not_decoded(self):
        self.assertEqual(career.normalize_drive_text("Hello world this is a test of the thing"), "Hello world this is a test of the thing")

    def test_bad_input_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            career.normalize_drive_text("not base64 !!", "base64")
        with self.assertRaises(ValueError):
            career.normalize_drive_text("x", "carrier-pigeon")

    def test_an_escaped_backslash_comes_back_as_one(self):
        self.assertEqual(career.normalize_drive_text("say: C:\\\\temp\n\n  ", "drive_read"), "say: C:\\temp\n")


class StrictYaml(unittest.TestCase):
    def test_aliases_are_refused(self):
        bomb = "a: &a [1, 2, 3]\nb: &b [*a, *a, *a]\nc: [*b, *b, *b]\n"
        with self.assertRaises(yaml.YAMLError):
            career.load_yaml(bomb)

    def test_ordinary_yaml_still_loads(self):
        self.assertEqual(career.load_yaml("a: [1, 2]\nb: {c: d}\n"), {"a": [1, 2], "b": {"c": "d"}})
        self.assertEqual(career.parse_front("---\nname: Sam\n---\n# Body\n"), {"name": "Sam"})


SHARED = "aliases:\n  okta: [idp]\ncredentials:\n  - {name: \"Okta Certified Professional\", issuer: Okta, year: 2023, tags: [okta-cert]}\n"
ROLE_A = """```yaml
roles:
  - id: acme-se
    title: Systems Engineer
    org: Acme
    span: 2021-03..present
    atoms:
      - {id: ac-01, say: "Built Okta automation", tags: [okta, automation], depth: owned, status: verified}
```
"""
ROLE_B = """roles:
  - id: globex-hd
    title: Help Desk
    org: Globex
    span: 2018-06..2021-02
    atoms:
      - {id: gl-01, say: "Supported about 400 users", tags: [support, sso], depth: used, status: verified}
aliases:
  okta: [sso]
"""


class Fragments(unittest.TestCase):
    def test_fragments_merge_into_one_facts_dict(self):
        facts = career.merge_facts([SHARED, ROLE_A, ROLE_B])
        self.assertEqual([r["id"] for r in facts["roles"]], ["acme-se", "globex-hd"])
        self.assertEqual(facts["aliases"]["okta"], ["idp", "sso"])
        self.assertEqual(len(facts["credentials"]), 1)
        self.assertEqual(career.validate(facts, TODAY), [])
        idx = career.build_index(facts, TODAY)
        self.assertEqual(idx["okta"]["years"], 8.3)                        # gl-01 is tagged sso, an alias of okta: the two roles run back to back
        self.assertIn("gl-01", idx["support"]["atoms"])

    def test_the_same_role_or_atom_id_twice_is_reported(self):
        facts = career.merge_facts([ROLE_A, ROLE_A])
        errs = career.validate(facts, TODAY)
        self.assertTrue(any("role id duplicate: acme-se" in e for e in errs), errs)
        self.assertTrue(any("atom id missing or duplicate: ac-01" in e for e in errs), errs)

    def test_a_document_that_is_not_a_mapping_is_refused(self):
        with self.assertRaises(ValueError):
            career.merge_facts(["- just\n- a list\n"])

    def test_ctx_from_data_reads_no_files(self):
        ctx = career.Ctx.from_data({"roles": []}, {"name": "Sam"}, TODAY)
        self.assertEqual(ctx.profile["name"], "Sam")
        self.assertEqual(ctx.facts, {"roles": []})
        self.assertFalse(ctx.root.exists())


class SkillsIndex(unittest.TestCase):
    def setUp(self):
        self.facts = career.read_block(FIXTURES / "facts.md")
        self.profile = career.read_front(FIXTURES / "profile.md")
        self.text = career.render_skills_md(self.facts, TODAY)
        self.parsed = career.parse_skills_md(self.text)

    def test_the_index_parses_back_to_what_it_was_built_from(self):
        built = career.build_index(self.facts, TODAY)
        self.assertEqual(set(self.parsed["idx"]), set(built))
        for tag, e in built.items():
            p = self.parsed["idx"][tag]
            self.assertEqual((p["years"], p["last"], p["depth"], p["cred"], p["atoms"]), (e["years"], e["last"], e["depth"], e["cred"], e["atoms"][:3]), tag)
        self.assertEqual(self.parsed["aliases"], {"okta": ["idp", "sso"]})
        self.assertEqual(self.parsed["pending"]["soc2"], ["nw-06 (unconfirmed)"])
        roles = self.facts["roles"]
        self.assertEqual(self.parsed["career_months"], career.union_months([career.span_months(r["span"], TODAY) for r in roles]))

    def test_the_index_says_which_role_holds_which_atom(self):
        by_id = {r["id"]: r for r in self.parsed["roles"]}
        self.assertEqual(list(by_id), [r["id"] for r in self.facts["roles"]])
        for r in self.facts["roles"]:
            self.assertEqual(by_id[r["id"]]["atoms"], [a["id"] for a in r["atoms"]])
            self.assertEqual((by_id[r["id"]]["title"], by_id[r["id"]]["org"], by_id[r["id"]]["span"]), (r["title"], r.get("org", ""), r["span"]))
        self.assertEqual(career.parse_skills_md("# Skills index\ntag|yrs|last|depth|atoms\nokta|3|2026-01|owned|2\n")["roles"], [])   # an older index has none

    def test_the_cli_writes_the_same_index(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(FIXTURES, tmp / "d")
            self.assertEqual(career.main(["--data", str(tmp / "d"), "--today", "2026-09-20", "skills"]), 0)
            self.assertEqual((tmp / "d" / "skills.md").read_text(), self.text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_scoring_from_the_index_equals_scoring_from_the_facts(self):
        amap = career.alias_map(self.facts)
        for req in ("okta:must:3,terraform:must,kubernetes:nice,soc2:nice,sso:must,python:nice,okta-cert:nice",
                    "okta:must:10", "okta:must,soc2:must", "scim:must,windows:nice,networking:must"):
            want = career.match_table(career.build_index(self.facts, TODAY), amap, self.profile, career.pending_from_facts(self.facts, amap), req)[3]
            got = career.match_table(self.parsed["idx"], self.parsed["amap"], self.profile, self.parsed["pending"], req)[3]
            self.assertEqual(got, want, req)

    def test_an_index_written_before_the_evidence_column_still_scores(self):
        old = "# Skills index\ntag|yrs|last|depth|atoms\n-|-|-|-|-\nokta|8.3|present|owned|3\nokta-cert|0|2023|cert|0\n"
        p = career.parse_skills_md(old)
        table = career.match_table(p["idx"], p["amap"], {}, {}, "okta:must:5,okta-cert:must")[3]
        self.assertIn("okta|must|met|8.3|owned", table)
        self.assertIn("okta-cert|must|met|-|cert", table)


def _selection(job: str) -> dict:
    return yaml.safe_load((FIXTURES / "jobs" / job / "selection.yml").read_text())


class LintFromTheIndex(unittest.TestCase):
    """The hosted service never receives the whole facts: it gets skills.md plus the roles a document cites."""

    def setUp(self):
        self.facts = career.read_block(FIXTURES / "facts.md")
        self.profile = career.read_front(FIXTURES / "profile.md")
        self.full = career.Ctx.from_data(self.facts, self.profile, TODAY)
        self.parsed = career.parse_skills_md(career.render_skills_md(self.facts, TODAY))

    def subset(self, role_ids, cited_atoms=()):
        owners = {r["id"] for r in self.facts["roles"] for a in r.get("atoms") or [] if a["id"] in set(cited_atoms)}
        roles = [r for r in self.facts["roles"] if r["id"] in set(role_ids) | owners]
        facts = career.merge_facts([{"roles": roles}, {"aliases": self.parsed["aliases"]}])
        return career.Ctx.from_data(facts, self.profile, TODAY)

    def errors(self, issues):
        return sorted(i for i in issues if i[0] == "E")

    def test_a_good_resume_selection_passes_from_the_index(self):
        sel = _selection("good")
        ctx = self.subset({r["id"] for r in sel["roles"]})
        got = career.lint(ctx, sel, idx=self.parsed["idx"], career_months=self.parsed["career_months"])
        self.assertEqual(self.errors(got), [])
        self.assertEqual(self.errors(career.lint(self.full, sel)), [])

    def test_a_bad_resume_selection_gets_the_same_errors(self):
        sel = _selection("bad")
        cited = [b.get("atom") for r in sel["roles"] for b in r.get("bullets") or []]
        ctx = self.subset({r["id"] for r in sel["roles"]}, cited)
        got = career.lint(ctx, sel, idx=self.parsed["idx"], career_months=self.parsed["career_months"])
        self.assertEqual(self.errors(got), self.errors(career.lint(self.full, sel)))
        self.assertGreater(len(self.errors(got)), 5)

    def test_the_career_length_comes_from_the_index_not_from_the_roles_supplied(self):
        roles = {r["id"]: r for r in self.facts["roles"] if r["id"] == "northwind-se"}          # 5.6 years of a 8.3-year career
        allowed, total = career.year_allowed(self.full, roles, {})
        self.assertEqual(allowed, {5.0, 6.0})
        allowed, total = career.year_allowed(self.full, roles, {}, self.parsed["career_months"])
        self.assertEqual(allowed, {8.0})
        self.assertAlmostEqual(total, self.parsed["career_months"] / 12)
        # and through lint: with a thin index no skill happens to allow "8 years", so only the career length can
        sel = _selection("good")
        sel = {**sel, "roles": [r for r in sel["roles"] if r["id"] == "northwind-se"]}
        ctx = self.subset({"northwind-se"})
        thin = {"okta": dict(self.parsed["idx"]["okta"], years=1.0)}
        self.assertTrue(any("number 8 is not supported" in i[2] for i in career.lint(ctx, sel, idx=thin)))
        self.assertFalse(any("number 8 is not supported" in i[2] for i in career.lint(ctx, sel, idx=thin, career_months=self.parsed["career_months"])))
        claim = {**sel, "summary": sel["summary"].replace("8 years", "15 years")}
        self.assertTrue(any("number 15 is not supported" in i[2] for i in career.lint(ctx, claim, idx=thin, career_months=self.parsed["career_months"])))

    def test_a_skill_missing_from_the_index_is_still_an_error(self):
        sel = _selection("good")
        sel = {**sel, "skills": sel["skills"] + [{"name": "Cloud", "items": ["Terraform"]}]}
        ctx = self.subset({r["id"] for r in sel["roles"]})
        got = career.lint(ctx, sel, idx=self.parsed["idx"], career_months=self.parsed["career_months"])
        self.assertTrue(any("'Terraform' is not in skills.md" in i[2] for i in got), got)

    def test_a_cover_letter_checks_out_from_the_index_and_the_posting_text(self):
        job = FIXTURES / "jobs" / "good"
        letter = yaml.safe_load((job / "cover.yml").read_text())
        jd = (job / "jd.md").read_text()
        ctx = self.subset({"northwind-se"})
        got = career.lint_letter(ctx, letter, None, idx=self.parsed["idx"], career_months=self.parsed["career_months"], jd=jd)
        self.assertEqual(self.errors(got), [])
        self.assertEqual(self.errors(career.lint_letter(self.full, letter, job)), [])

    def test_a_letter_error_is_reported_the_same_way(self):
        job = FIXTURES / "jobs" / "good"
        letter = yaml.safe_load((job / "cover.yml").read_text().replace("across 12 SaaS apps", "across eleven SaaS apps"))
        jd = (job / "jd.md").read_text()
        got = career.lint_letter(self.subset({"northwind-se"}), letter, None, idx=self.parsed["idx"], career_months=self.parsed["career_months"], jd=jd)
        self.assertTrue(any("number word 'eleven'" in i[2] for i in got), got)

    def test_a_letter_without_a_posting_text_says_so(self):
        letter = yaml.safe_load((FIXTURES / "jobs" / "good" / "cover.yml").read_text())
        got = career.lint_letter(self.subset({"northwind-se"}), letter, None, idx=self.parsed["idx"], career_months=self.parsed["career_months"], jd="")
        self.assertTrue(any("no jd.md" in i[2] for i in got), got)


if __name__ == "__main__":
    unittest.main()
