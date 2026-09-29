"""Run: uv run --with pyyaml python -m unittest discover -s tests -v"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
import career  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "data"
TODAY = "2026-09-20"


def run(data, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = career.main(["--data", str(data), "--today", TODAY, *argv])
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        shutil.copytree(FIXTURES, self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class SkillsAndMatch(Base):
    def test_years_are_a_union_not_a_sum(self):
        code, out, _ = run(self.data, "skills")
        self.assertEqual(code, 0, out)
        table = dict(l.split("|")[:2] for l in (self.data / "skills.md").read_text().splitlines() if "|" in l)
        # contoso 2018-06..2021-02 + northwind 2021-03..present are contiguous = 100 months.
        # 'support' also has an overlapping freelance role that must not add time.
        self.assertEqual(table["support"], "8.3")
        self.assertEqual(table["macos"], "8.3")
        # freelance 2019-01..2020-12 (24) + northwind (67), separated by a gap
        self.assertEqual(table["google-workspace"], "7.6")
        # atom-level span override: 2023-01..2023-06 is 6 months
        self.assertEqual(table["python"], "0.5")

    def test_unconfirmed_atoms_do_not_count(self):
        run(self.data, "skills")
        self.assertNotIn("soc2|", (self.data / "skills.md").read_text())

    def test_validate_catches_duplicate_ids(self):
        p = self.data / "facts.md"
        p.write_text(p.read_text().replace("id: nw-02", "id: nw-01"))
        code, _, err = run(self.data, "skills")
        self.assertEqual(code, 1)
        self.assertIn("duplicate", err)

    def test_match_statuses_and_ceiling(self):
        code, out, _ = run(self.data, "match", "--req", "okta:must:3,terraform:must,kubernetes:nice,soc2:nice,sso:must,python:nice,okta-cert:nice")
        rows = {l.split("|")[0]: l.split("|") for l in out.splitlines() if "|" in l}
        self.assertEqual(rows["okta"][2], "met")
        self.assertEqual(rows["sso"][2], "met")            # alias of okta
        self.assertEqual(rows["terraform"][2], "gap")      # known_gaps
        self.assertEqual(rows["kubernetes"][2], "gap")     # never_claim
        self.assertEqual(rows["soc2"][2], "unasked")       # only an unconfirmed atom: must ask, not assume
        self.assertIn("nw-06 (unconfirmed)", rows["soc2"][5])   # ...and the question can name the atom
        self.assertIn("not in facts", run(self.data, "match", "--req", "scim:must")[1])
        self.assertEqual(rows["okta-cert"][2], "met")
        self.assertIn("ceiling: 6", out)                   # one must-have gap of three

    def test_pending_statement_from_the_profile_is_shown_as_a_question(self):
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("known_gaps: [\"terraform\"]\n", "known_gaps: [\"terraform\"]\npending:\n  fedramp: says they did FedRAMP evidence work; job not recorded yet\n"))
        _, out, _ = run(self.data, "match", "--req", "fedramp:must,okta:must")
        rows = {l.split("|")[0]: l.split("|") for l in out.splitlines() if "|" in l}
        self.assertEqual(rows["fedramp"][2], "unasked")
        self.assertIn("says they did FedRAMP evidence work; job not recorded yet", rows["fedramp"][5])
        self.assertEqual(rows["okta"][2], "met")

    def test_years_floor_caps_at_four(self):
        _, out, _ = run(self.data, "match", "--req", "okta:must:10")
        self.assertIn("short", out)
        self.assertIn("ceiling: 4", out)

    def test_unasked_shows_range(self):
        _, out, _ = run(self.data, "match", "--req", "okta:must,soc2:must")
        self.assertIn("ceiling: 6 (up to 10", out)

    def test_select_ranks_and_excludes_unusable(self):
        _, out, _ = run(self.data, "select", "--tags", "okta,automation")
        self.assertLess(out.index("nw-02"), out.index("nw-05"))
        self.assertNotIn("nw-06", out)
        self.assertIn("[no figure]", run(self.data, "select", "--tags", "onboarding")[1])

    def test_empty_facts_say_so_instead_of_printing_nothing(self):
        p = self.data / "facts.md"
        p.write_text("```yaml\nroles: []\n```\n")
        for cmd in (("select", "--tags", "okta"), ("match", "--req", "okta:must")):
            code, out, err = run(self.data, *cmd)
            self.assertEqual(code, 0)
            self.assertIn("facts.md has no roles yet", err)


class Lint(Base):
    def test_good_selection_has_no_errors(self):
        code, out, _ = run(self.data, "build", "good")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.data / "jobs/good/resume.md").exists())
        self.assertIn("### IT Systems Engineer, Northwind Logistics (Mar 2021 - Present)", (self.data / "jobs/good/resume.md").read_text())

    def test_bad_selection_is_caught(self):
        code, out, _ = run(self.data, "build", "bad")
        self.assertEqual(code, 1)
        for needle in ("number 2400 is not in the atom", "never_claim hit: 'kubernetes'", "has status unconfirmed",
                       "atom nope-99 not in facts.md", "no atom id", "belongs to role contoso-helpdesk",
                       "'Terraform' is not in skills.md", "number 12 is not supported", "Results-driven",
                       "banned/AI-tell phrase 'Spearheaded'", "dash used as punctuation"):
            self.assertIn(needle, out, needle)

    def test_skill_items_may_carry_a_qualifier_and_name_two_skills(self):
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("  - {name: Scripting", "  - {name: Cloud, items: [\"Intune and macOS (general use)\", \"Google Workspace\"]}\n  - {name: Scripting") if "Scripting" in p.read_text()
                     else p.read_text().replace("roles:\n", "  - {name: Cloud, items: [\"Intune and macOS (general use)\", \"Google Workspace\"]}\nroles:\n", 1))
        _, out, _ = run(self.data, "build", "good")
        self.assertNotIn("is not in skills.md", out)
        p.write_text(p.read_text().replace("Intune and macOS (general use)", "Intune and Kubernetes (general use)"))
        code, out, _ = run(self.data, "build", "good")
        self.assertEqual(code, 1)
        self.assertIn("'Kubernetes' (in 'Intune and Kubernetes (general use)') is not in skills.md", out)

    def test_summary_year_claim_must_match_career_length(self):
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("8 years", "15 years"))
        _, out, _ = run(self.data, "build", "good")
        self.assertIn("number 15 is not supported", out)

    def test_embellished_bullet_is_flagged(self):
        # the planted failure from manual testing: an outcome the atom never stated
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("Scripted a reconciliation of Okta users against HR exports in Python.",
                                           "Scripted a reconciliation of Okta users against HR exports so account drift shows up before an audit does."))
        code, out, _ = run(self.data, "build", "good")
        self.assertEqual(code, 0)                                   # a warning: the model must decide, the tool cannot
        self.assertIn("adds wording the atom never used", out)
        self.assertIn("drift", out)

    def test_faithful_rewording_is_not_flagged(self):
        _, out, _ = run(self.data, "build", "good")
        self.assertNotIn("adds wording", out)

    def test_changed_number_word_is_an_error(self):
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("from two days to a few hours", "from five days to a few hours"))
        code, out, _ = run(self.data, "build", "good")
        self.assertEqual(code, 1)
        self.assertIn("number word 'five' is not in the atom", out)

    def test_singular_of_a_known_plural_is_not_an_unknown_term(self):
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("Jamf-managed", "Jamf-managed Mac"))     # facts only say 'Macs'
        _, out, _ = run(self.data, "build", "good")
        self.assertNotIn("term 'Mac'", out)

    def test_letter_sentence_that_adds_a_story_is_flagged(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("I also moved about 1,800 Macs from Kandji to Jamf with no reimaging, which is the part of the work I would bring to your endpoint side.",
                                           "I also moved about 1,800 Macs from Kandji to Jamf with no reimaging, after leadership demanded faster laptop refreshes and a nervous procurement team worried about downtime."))
        _, out, _ = run(self.data, "cover-patch", "good")
        self.assertIn("adds wording the cited atoms never used", out)

    def test_unsupported_claim_in_a_jd_only_paragraph_is_flagged(self):
        # found in manual testing: "the same systems I work in every day" slipped through as if it were about the company
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("I would like to apply for.", "I would like to apply for. That is the same pair of systems I work in every day."))
        _, out, _ = run(self.data, "cover-patch", "good")
        self.assertIn("claim about you in a jd-only paragraph", out)
        self.assertIn("work in every day", out)

    def test_intent_in_a_jd_only_paragraph_is_fine(self):
        _, out, _ = run(self.data, "cover-patch", "good")      # "I would welcome a conversation" / "I would like to apply for"
        self.assertNotIn("claim about you", out)

    def test_letter_number_word_must_come_from_the_atoms(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("across 12 SaaS apps", "across eleven SaaS apps"))
        code, out, _ = run(self.data, "cover-patch", "good")
        self.assertEqual(code, 1)
        self.assertIn("number word 'eleven'", out)
        p.write_text(p.read_text().replace("across eleven SaaS apps", "across twelve SaaS apps"))   # same number, spelled out: fine
        code, out, _ = run(self.data, "cover-patch", "good")
        self.assertEqual(code, 0, out)


class Patch(Base):
    """`patch` and `cover-patch` never touch a network; they print the Reactive Resume JSON Patch operations and
    cover-letter HTML the assistant hands to the Reactive Resume MCP server's own tools."""

    def test_patch_prints_operations_for_a_clean_selection(self):
        code, out, _ = run(self.data, "patch", "good")
        self.assertEqual(code, 0, out)
        doc = json.loads(out[out.index("{"):])
        self.assertEqual(doc["resume_name_full"], "Fabrikam - Systems Engineer - Sam Rivera Resume")
        self.assertEqual(doc["resume_slug"], "fabrikam-systems-engineer")
        ops = {o["path"]: o["value"] for o in doc["operations"]}
        exp = ops["/sections/experience/items"]
        self.assertEqual([e["company"] for e in exp], ["Northwind Logistics", "Contoso Retail"])
        self.assertEqual(exp[0]["period"], "Mar 2021 - Present")
        self.assertTrue((self.data / "jobs/good/resume.md").exists())

    def test_patch_uses_the_master_json_item_shapes(self):
        master = {"data": {"sections": {
            "experience": {"items": [{"id": "x", "hidden": False, "company": "", "position": "", "location": "",
                                       "period": "", "website": {"url": "u", "label": "l", "inlineLink": False}, "description": "", "roles": []}]},
            "skills": {"items": [{"id": "y", "hidden": False, "icon": "star", "iconColor": "", "name": "", "proficiency": "", "level": 3, "keywords": []}]}}}}
        mf = self.tmp / "master.json"
        mf.write_text(json.dumps(master))
        code, out, _ = run(self.data, "patch", "good", "--master-json", str(mf))
        self.assertEqual(code, 0, out)
        doc = json.loads(out[out.index("{"):])
        ops = {o["path"]: o["value"] for o in doc["operations"]}
        self.assertEqual(ops["/sections/skills/items"][0]["icon"], "star")

    def test_patch_refuses_a_dirty_selection(self):
        code, out, _ = run(self.data, "patch", "bad")
        self.assertEqual(code, 1)
        self.assertIn("never_claim hit: 'kubernetes'", out)
        self.assertNotIn('"operations"', out)

    def test_patch_requires_target_company_and_role(self):
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace("target: {company: Fabrikam, role: Systems Engineer}", "target: {company: Fabrikam}"))
        code, _, err = run(self.data, "patch", "good")
        self.assertEqual(code, 1)
        self.assertIn("target.company and target.role", err)

    def test_cover_patch_prints_html_for_a_clean_letter(self):
        code, out, _ = run(self.data, "cover-patch", "good")
        self.assertEqual(code, 0, out)
        doc = json.loads(out[out.index("{"):])
        self.assertEqual(doc["name"], "Fabrikam - Systems Engineer - Sam Rivera Cover Letter")
        self.assertIn("Fabrikam&#x27;s plan to consolidate identity", doc["content_html"])
        self.assertIn("Sam Rivera", doc["recipient_html"])
        self.assertTrue((self.data / "jobs/good/cover.md").exists())

    def test_check_reports_local_setup_without_any_network_call(self):
        code, out, _ = run(self.data, "check")
        self.assertEqual(code, 0, out)
        self.assertIn("rr_master in profile.md: master-1", out)
        self.assertIn("ask the assistant to call the MCP tool `list_resumes`", out)

    def test_check_flags_a_missing_profile_field(self):
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("rr_master: master-1", 'rr_master: ""'))
        code, out, _ = run(self.data, "check")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  rr_master in profile.md", out)


if __name__ == "__main__":
    unittest.main()
