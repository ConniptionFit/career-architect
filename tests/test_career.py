"""Run: uv run --with pyyaml python -m unittest discover -s tests -v"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer
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
        _, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertIn("adds wording the cited atoms never used", out)

    def test_unsupported_claim_in_a_jd_only_paragraph_is_flagged(self):
        # found in manual testing: "the same systems I work in every day" slipped through as if it were about the company
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("I would like to apply for.", "I would like to apply for. That is the same pair of systems I work in every day."))
        _, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertIn("claim about you in a jd-only paragraph", out)
        self.assertIn("work in every day", out)

    def test_intent_in_a_jd_only_paragraph_is_fine(self):
        _, out, _ = run(self.data, "cover", "good", "--dry")      # "I would welcome a conversation" / "I would like to apply for"
        self.assertNotIn("claim about you", out)

    def test_letter_number_word_must_come_from_the_atoms(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("across 12 SaaS apps", "across eleven SaaS apps"))
        code, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertEqual(code, 1)
        self.assertIn("number word 'eleven'", out)
        p.write_text(p.read_text().replace("across eleven SaaS apps", "across twelve SaaS apps"))   # same number, spelled out: fine
        code, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertEqual(code, 0, out)


class FakeRR(BaseHTTPRequestHandler):
    calls: list = []
    uas: list = []
    letters: dict = {}          # saved cover letters (Reactive Resume > Cover Letters), keyed by id
    letter_seq: int = 0
    has_letters: bool = True    # False = an older Reactive Resume without the /cover-letters API
    race: bool = False          # True = someone else saves the letter just before our next PUT (revision conflict)
    mcp_ok: bool = True         # False = the /mcp endpoint answers with a JSON-RPC error
    apps: list = [{"id": "a1", "company": "Fabrikam", "role": "SE", "status": "applied", "salary": "old", "notes": "hand note"}]
    resumes: list = [{"id": "master-1", "slug": "master", "name": "Master", "tags": []}]
    master = {"id": "master-1", "name": "Master", "slug": "master", "tags": [], "data": {
        "summary": {"title": "Summary", "content": ""},
        "basics": {"name": "Sample", "headline": "", "email": "", "phone": "", "location": "", "website": {"url": "", "label": ""}, "customFields": []},
        "metadata": {"template": "onyx", "page": {"format": "a4", "marginX": 14}, "typography": {"body": {"fontSize": 10, "lineHeight": 1.5}},
                     "design": {"colors": {"primary": "red"}}, "layout": {"pages": [{"main": ["summary"], "sidebar": []}]}},
        "sections": {
            "education": {"hidden": True, "items": []}, "certifications": {"hidden": False, "items": []}, "profiles": {"hidden": False, "items": []},
            "experience": {"items": [{"id": "x", "hidden": False, "company": "Sample", "position": "Sample", "location": "",
                                       "period": "", "website": {"url": "u", "label": "l", "inlineLink": False}, "description": "", "roles": []}]},
            "skills": {"items": [{"id": "y", "hidden": False, "icon": "star", "iconColor": "", "name": "", "proficiency": "", "level": 3, "keywords": []}]}},
        "customSections": [{"id": "cs1", "type": "cover-letter", "title": "Cover Letter", "icon": "", "columns": 1, "hidden": False,
                            "keepTogether": False, "startOnNewPage": True,
                            "items": [{"id": "ci1", "hidden": False, "recipient": "", "content": ""}]}]}}

    def log_message(self, *a):
        pass

    def _send(self, obj=None, raw=None, code=200):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/pdf" if raw is not None else "application/json")
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        FakeRR.calls.append((self.command, self.path, self.headers.get("x-api-key"), body))
        FakeRR.uas.append(self.headers.get("User-Agent"))
        return body

    def _letters(self, body):
        """The saved-letters API of Reactive Resume 5.x with revisions (schema read from the live /spec.json). True when it handled the request."""
        path, _, query = self.path.partition("?")
        if "/cover-letters" not in path:
            return False
        if not FakeRR.has_letters:
            self._send({"error": "nf"}, code=404)
            return True
        parts = [x for x in path.split("/cover-letters", 1)[1].split("/") if x]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        store, m = FakeRR.letters, self.command

        def new(doc, resume=None, app=None):
            FakeRR.letter_seq += 1
            lid = f"cl-{FakeRR.letter_seq}"
            store[lid] = {"id": lid, "name": doc.get("name", "x"), "recipient": doc.get("recipient", ""), "content": doc.get("content", ""),
                          "style": {"basics": {}, "picture": {}, "metadata": {"template": "onyx"}, "sectionId": "s1", "itemId": "i1"},
                          "sourceResumeId": resume, "sourceApplicationId": app, "revision": 1,
                          "createdAt": "2026-09-20T00:00:00Z", "updatedAt": "2026-09-20T00:00:00Z"}
            return store[lid]

        if not parts:
            if m == "GET":
                rows = [d for d in store.values()
                        if (not q.get("resumeId") or d["sourceResumeId"] == q["resumeId"])
                        and (not q.get("applicationId") or d["sourceApplicationId"] == q["applicationId"])
                        and (not q.get("search") or q["search"].lower() in d["name"].lower())]
                off, lim = int(q.get("offset", 0)), int(q.get("limit", 50))
                self._send({"items": rows[off:off + lim], "total": len(rows)})
            elif m == "POST":
                doc = json.loads(body)
                self._send(new(doc, doc.get("resumeId"), doc.get("applicationId")))
            return True
        if parts[0] == "import" and m == "POST":
            self._send(new(json.loads(body)["document"]))
            return True
        d = store.get(parts[0])
        if d is None:
            self._send({"error": "nf"}, code=404)
            return True
        act, data = (parts[1] if len(parts) > 1 else ""), (json.loads(body) if body else {})
        if m == "GET" and not act:
            self._send(d)
        elif m == "GET" and act == "export":
            self._send({**{k: d[k] for k in ("name", "recipient", "content", "style")}, "format": "reactive-resume-cover-letter", "version": 1})
        elif m == "POST" and act == "duplicate":
            self._send(new({**d, "name": data.get("name") or d["name"] + " (copy)"}, d["sourceResumeId"], d["sourceApplicationId"]))
        elif m in ("PUT", "DELETE") or act == "refresh-style":
            if FakeRR.race:
                FakeRR.race, d["revision"] = False, d["revision"] + 1     # another tab saved first
            if data.get("expectedRevision") != d["revision"]:
                self._send({"code": "REVISION_CONFLICT", "message": "revision mismatch"}, code=409)
            elif m == "DELETE":
                del store[d["id"]]
                self._send(None)
            else:
                if act == "refresh-style":
                    d["style"]["metadata"]["refreshedFrom"] = data.get("resumeId")
                d.update({k: data[k] for k in ("name", "recipient", "content") if k in data})
                d["revision"] += 1
                self._send(d)
        else:
            self._send({"error": "nf"}, code=404)
        return True

    def do_GET(self):
        self._record()
        if self._letters(b""):
            return
        if self.path == "/api/health":
            self._send({"service": "reactive-resume", "version": "5.3.1", "status": "healthy"})
        elif self.path.endswith("/redirect-me"):
            self.send_response(301)
            self.send_header("Location", "https://elsewhere.example/x")
            self.end_headers()
        elif self.path.endswith(("/resumes/master-1", "/resumes/new-resume-1")):
            self._send(self.master)
        elif "/pdf" in self.path:
            self._send(raw=b"%PDF-1.7 " + (b"cover" if "target=cover-letter" in self.path else b"resume"))
        elif self.path.endswith("/applications/stats"):
            self._send({"total": 3, "byStage": [{"status": "applied", "count": 2}, {"status": "offer", "count": 1}], "bySource": []})
        elif self.path.endswith("/applications"):
            self._send(FakeRR.apps)
        elif "/applications/" in self.path:
            row = [a for a in FakeRR.apps if self.path.endswith("/" + a["id"])]
            self._send(row[0] if row else {"error": "nf"}, code=200 if row else 404)
        elif self.path.endswith("/resumes"):
            self._send(self.resumes)
        else:
            self._send({"error": "nf"}, code=404)

    def do_POST(self):
        body = self._record()
        if self._letters(body):
            return
        if self.path == "/mcp":                       # the Reactive Resume MCP endpoint (JSON-RPC over streamable HTTP)
            msg = json.loads(body or b"{}")
            result = {"initialize": {"serverInfo": {"name": "reactive-resume", "version": "5.3.1"}},
                      "tools/list": {"tools": [{"name": "list_resumes"}, {"name": "read_resume"}]}}.get(msg.get("method"), {})
            self._send({"jsonrpc": "2.0", "id": msg.get("id"), "result": result} if FakeRR.mcp_ok else
                       {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"message": "unauthorized"}})
            return
        if self.path.endswith("/duplicate"):
            self._send("new-resume-1")
        elif self.path.endswith("/applications"):
            row = json.loads(body or b"{}")
            FakeRR.apps.append({"id": "app-1", **row})
            self._send("app-1")
        elif self.path.endswith("/resumes"):
            self._send("created-master-1")
        else:
            self._send({"ok": True})

    def do_PATCH(self):
        self._record()
        self._send({"ok": True})

    def do_PUT(self):
        body = self._record()
        if self._letters(body):
            return
        self._send({"ok": True})

    def do_DELETE(self):
        body = self._record()
        if self._letters(body):
            return
        self._send({"ok": True})


class Api(Base):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeRR)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        super().setUp()
        FakeRR.calls, FakeRR.uas = [], []
        FakeRR.letters, FakeRR.letter_seq, FakeRR.has_letters, FakeRR.race, FakeRR.mcp_ok = {}, 0, True, False, True
        FakeRR.apps = [{"id": "a1", "company": "Fabrikam", "role": "SE", "status": "applied", "salary": "old", "notes": "hand note"}]
        os.environ["RR_URL"], os.environ["RR_API_KEY"] = self.url, "test-key"
        # `career check` looks for the MCP registration in ~/.claude.json: give every test its own HOME so it never reads the developer's
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"reactive-resume": {"type": "http", "url": f"{self.url}/mcp"}}}))
        self._home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ.pop("RR_URL", None)
        os.environ.pop("RR_API_KEY", None)
        if self._home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._home
        super().tearDown()

    def test_push_duplicates_patches_and_saves_pdf(self):
        code, out, err = run(self.data, "push", "good")
        self.assertEqual(code, 0, out + err)
        methods = [(m, p.split("/api/openapi")[-1]) for m, p, _, _ in FakeRR.calls]
        self.assertEqual(methods, [("GET", "/resumes/master-1"), ("POST", "/resumes/master-1/duplicate"),
                                   ("PATCH", "/resumes/new-resume-1"), ("GET", "/resumes/new-resume-1/pdf?target=resume")])
        self.assertTrue(all(k == "test-key" for _, _, k, _ in FakeRR.calls))
        patch = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])
        ops = {o["path"]: o["value"] for o in patch["operations"]}
        exp = ops["/sections/experience/items"]
        self.assertEqual([e["company"] for e in exp], ["Northwind Logistics", "Contoso Retail"])
        self.assertEqual(exp[0]["period"], "Mar 2021 - Present")
        self.assertEqual(exp[1]["period"], "Jun 2018 - Feb 2021")
        self.assertTrue(exp[0]["description"].startswith("<ul><li><p>Moved about 1,800 Macs"))
        self.assertEqual(exp[0]["website"], {"url": "", "label": "", "inlineLink": False})   # template keys kept, sample data cleared
        skl = ops["/sections/skills/items"]
        self.assertEqual(skl[0]["keywords"], ["Okta", "Active Directory"])
        self.assertEqual(skl[0]["icon"], "star")                                                # master's styling preserved
        self.assertTrue(ops["/summary/content"].startswith("<p>IT systems engineer"))
        self.assertEqual((self.data / "jobs/good/resume.pdf").read_bytes()[:4], b"%PDF")

    def test_second_push_updates_in_place(self):
        run(self.data, "push", "good")
        FakeRR.calls = []
        code, out, err = run(self.data, "push", "good")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("duplicate", " ".join(p for _, p, _, _ in FakeRR.calls))

    def test_push_refuses_on_lint_errors(self):
        code, _, err = run(self.data, "push", "bad")
        self.assertEqual(code, 1)
        self.assertEqual(FakeRR.calls, [])          # nothing reached the server

    def test_apply_add_links_resume_and_jd(self):
        run(self.data, "push", "good")
        (self.data / "jobs/good/jd.md").write_text("Great job.")
        FakeRR.calls = []
        code, out, err = run(self.data, "apply", "add", "--company", "Contoso", "--role", "SE", "--status", "applied", "--job", "good")
        self.assertEqual(code, 0, out + err)
        body = json.loads([c for c in FakeRR.calls if c[0] == "POST"][0][3])
        self.assertEqual((body["resumeId"], body["jobDescription"], body["status"]), ("new-resume-1", "Great job.", "applied"))
        code, out, _ = run(self.data, "apply", "set", "--job", "good", "--status", "interview", "--followup", "2026-10-01")
        self.assertEqual(code, 0)
        put = [c for c in FakeRR.calls if c[0] == "PUT"][0]
        self.assertTrue(put[1].endswith("/applications/app-1"))
        self.assertEqual(json.loads(put[3])["followUpAt"], "2026-10-01T09:00:00Z")

    def test_add_updates_the_existing_row_instead_of_duplicating(self):
        code, out, err = run(self.data, "apply", "add", "--company", "Fabrikam", "--role", "Sr. SE", "--status", "saved",
                             "--salary", "$150k", "--notes", "RESEARCH 2026-09-21\nPAY: $150k")
        self.assertEqual(code, 0, out + err)
        self.assertIn("Not creating a new row", out)
        self.assertEqual([c[0] for c in FakeRR.calls if c[0] == "POST"], [])
        body = json.loads([c for c in FakeRR.calls if c[0] == "PUT"][0][3])
        self.assertEqual(body["salary"], "$150k")                   # the request wins over the stale row
        self.assertNotIn("status", body)                           # saved must not demote applied
        self.assertTrue(body["notes"].startswith("hand note"))     # hand-logged context kept

    def test_research_block_replaces_the_previous_one(self):
        from importlib import import_module
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jobs/scripts"))
        c = import_module("career")
        one = c.merge_notes("hand note", "RESEARCH 2026-09-20\nPAY: $100k")
        two = c.merge_notes(one, "RESEARCH 2026-09-21\nPAY: $150k")
        self.assertIn("hand note", two)
        self.assertIn("$150k", two)
        self.assertNotIn("$100k", two)
        self.assertEqual(two.count("RESEARCH 2026"), 1)
        legacy = "hand note\n\nRESEARCH 2026-09-20\nPAY: $100k"      # older block with no end marker
        self.assertNotIn("$100k", c.merge_notes(legacy, "RESEARCH 2026-09-21\nPAY: $150k"))
        self.assertEqual(c.merge_notes("a b", "b"), "a b")           # plain repeats are a no-op

    def test_set_finds_the_row_by_company_and_role(self):
        code, out, err = run(self.data, "apply", "set", "--company", "Fabrikam", "--role", "SE", "--salary", "$160k", "--location", "Remote")
        self.assertEqual(code, 0, out + err)
        put = [c for c in FakeRR.calls if c[0] == "PUT"][0]
        self.assertTrue(put[1].endswith("/applications/a1"))
        self.assertEqual(json.loads(put[3]), {"salary": "$160k", "location": "Remote"})
        code, out, _ = run(self.data, "apply", "set", "--company", "Nobody", "--role", "X", "--salary", "1")
        self.assertEqual(code, 2)

    def test_show_prints_every_field(self):
        code, out, _ = run(self.data, "apply", "show", "--company", "Fabrikam", "--role", "SE")
        self.assertEqual(code, 0)
        self.assertIn("salary: old", out)
        self.assertIn("notes: hand note", out)

    def test_posting_parsers_read_pay_from_each_ats(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "jobs/scripts"))
        import career as c
        ashby = {"jobs": [{"id": "j1", "title": "IT Eng", "location": "Remote", "publishedAt": "2026-01-01",
                           "descriptionHtml": "<p>Reports to the Manager, IT. Base is $117,000 USD and $164,000 USD.</p>",
                           "compensation": {"compensationTierSummary": "$155K - $180K"}}]}
        r = c.parse_posting("https://jobs.ashbyhq.com/acme/j1", fetch=lambda u: ashby)
        self.assertEqual(r["ats"], "ashby")
        self.assertTrue(any("$155K" in x for x in r["pay"]) and any("117,000" in x for x in r["pay"]))
        self.assertEqual(r["reports_to"], "Manager, IT")
        gh = {"title": "SE", "location": {"name": "Remote"}, "first_published": "x", "pay_input_ranges": [],
              "content": '<div class="title">Other US:</div><div class="pay-range"><span>$125,000</span><span class="divider">&mdash;</span><span>$155,000 USD</span></div>'}
        r = c.parse_posting("https://job-boards.greenhouse.io/acme/jobs/9", fetch=lambda u: gh)
        self.assertTrue(any("$125,000 - $155,000 USD" in x for x in r["pay"]))
        lever = {"text": "SE", "categories": {"location": "Remote"}, "salaryRange": {"min": 145000, "max": 200000, "currency": "USD", "interval": "per-year-salary"}, "descriptionPlain": "x"}
        r = c.parse_posting("https://jobs.lever.co/acme/abc", fetch=lambda u: lever)
        self.assertIn("145000-200000", r["pay"][0])
        none = c.parse_posting("https://jobs.ashbyhq.com/acme/j1", fetch=lambda u: {"jobs": [{"id": "j1", "title": "T", "descriptionHtml": "no pay"}]})
        self.assertEqual(none["pay"], [])

    def test_stats_and_resumes(self):
        _, out, _ = run(self.data, "apply", "stats")
        self.assertIn("total: 3", out)
        self.assertIn("applied: 2", out)
        _, out, _ = run(self.data, "resumes")
        self.assertIn("master-1 | master | Master", out)

    def test_missing_key_fails_without_printing_secrets(self):
        os.environ.pop("RR_API_KEY")
        with mock.patch.object(career, "CONF", Path("/nonexistent/rr.env")):
            code, _, err = run(self.data, "resumes")
        self.assertEqual(code, 2)
        self.assertIn("no API key", err)

    # ---- moving the instance (public https domain behind Cloudflare) ----

    def test_named_user_agent_is_sent(self):
        # Cloudflare answers Python's default urllib agent with 403 "Error 1010"; a named agent gets through
        run(self.data, "resumes")
        self.assertTrue(FakeRR.uas and all(u == career.USER_AGENT for u in FakeRR.uas), FakeRR.uas)
        self.assertNotIn("Python-urllib", " ".join(u or "" for u in FakeRR.uas))

    def test_url_normalisation(self):
        n = career.normalize_url
        self.assertEqual(n("resume.example.com"), "https://resume.example.com")
        self.assertEqual(n("http://resume.example.com/"), "https://resume.example.com")          # public http would 301 and break POST/PATCH
        self.assertEqual(n("https://resume.example.com/api/openapi"), "https://resume.example.com")
        self.assertEqual(n("https://resume.example.com:8443/x/"), "https://resume.example.com:8443/x")
        self.assertEqual(n("http://10.0.0.5:3333"), "http://10.0.0.5:3333")                 # private hosts stay http
        self.assertEqual(n("http://localhost:3000/"), "http://localhost:3000")

    def _profile_url(self, value):
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("rr_url: http://127.0.0.1:1", f"rr_url: {value}"))

    def test_profile_url_beats_stale_rr_env(self):
        # after a host move, an old RR_URL left in rr.env must not shadow profile.md
        conf = self.tmp / "rr.env"
        conf.write_text("RR_URL=http://stale.invalid:1\nRR_API_KEY=test-key\n")
        conf.chmod(0o600)
        self._profile_url(self.url)
        with mock.patch.dict(os.environ), mock.patch.object(career, "CONF", conf):
            os.environ.pop("RR_URL"), os.environ.pop("RR_API_KEY")
            code, out, err = run(self.data, "check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("(from profile.md)", out)
        authed = [k for _m, path, k, _b in FakeRR.calls if path != "/api/health"]   # health is deliberately unauthenticated
        self.assertTrue(authed and all(k == "test-key" for k in authed), FakeRR.calls)

    def test_env_url_overrides_profile(self):
        self._profile_url("http://bad.invalid")
        code, out, err = run(self.data, "resumes")          # RR_URL from setUp points at the fake server
        self.assertEqual(code, 0, out + err)

    def test_redirect_is_reported_not_followed(self):
        ctx = career.Ctx(str(self.data), career.dt.date(2026, 9, 20))
        with self.assertRaises(career.ApiError) as cm:
            career.api(ctx, "GET", "/redirect-me")
        self.assertEqual(cm.exception.status, 301)
        self.assertIn("https://elsewhere.example/x", str(cm.exception))
        self.assertIn("rr_url", str(cm.exception))

    def test_cloudflare_block_gets_an_actionable_hint(self):
        e = career.ApiError(403, '{"title":"Error 1010: Access denied","type":"https://developers.cloudflare.com/x"}', "https://h/api/openapi/resumes")
        self.assertIn("Cloudflare blocked", str(e))
        self.assertIn("login proxy", str(career.ApiError(401, "<html>Sign in</html>", "u")))
        hint = str(career.ApiError(401, '{"code":"UNAUTHORIZED","status":401,"message":"Unauthorized"}', "u"))
        self.assertIn("rejected the API key", hint)
        self.assertIn("--rekey", hint)

    def test_job_state_stores_no_url(self):
        run(self.data, "push", "good")
        self.assertEqual(json.loads((self.data / "jobs/good/rr.json").read_text()), {"id": "new-resume-1", "pdf": "Fabrikam - Systems Engineer - Sam Rivera Resume.pdf"})

    def test_check_reports_each_step(self):
        code, out, err = run(self.data, "check")
        self.assertEqual(code, 0, out + err)
        for needle in ("ok    reachable", "5.3.1", "ok    api key", "ok    master"):
            self.assertIn(needle, out)
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("rr_master: master-1", 'rr_master: ""'))
        code, out, _ = run(self.data, "check")
        self.assertEqual(code, 1)
        self.assertIn("rr_master not set", out)

    def test_items_carry_every_field_the_live_schema_requires(self):
        # required keys taken from https://resume.example.com/schema.json (Reactive Resume 5.3.1), even if the master has no items yet
        empty = {"data": {"sections": {"experience": {"items": []}, "skills": {"items": []}}}}
        ctx = career.Ctx(str(self.data), career.dt.date(2026, 9, 20))
        _, sel = career.load_selection(ctx, "good")
        exp, skl = career.build_items(ctx, sel, empty)
        for k in ("id", "hidden", "company", "position", "location", "period", "website", "description", "roles"):
            self.assertIn(k, exp[0], k)
        self.assertEqual(sorted(exp[0]["website"]), ["inlineLink", "label", "url"])
        for k in ("id", "hidden", "icon", "iconColor", "name", "proficiency", "level", "keywords"):
            self.assertIn(k, skl[0], k)


    # ---- migration features: exposure, notes, conditional atoms, framings, profile-driven sections ----

    def test_exposure_atoms_do_not_count_as_years(self):
        run(self.data, "skills")
        table = {l.split("|")[0]: l.split("|") for l in (self.data / "skills.md").read_text().splitlines() if "|" in l}
        self.assertEqual(table["jamf"][1], "5.6")                # nw-01 only; the 2018-2021 POC atom must not stretch it to 8.3
        self.assertEqual(table["workspace-one"][1:4], ["0", "2021-02", "exposure"])
        self.assertEqual(table["networking"][3], "cert")         # degrees contribute tags too
        _, out, _ = run(self.data, "match", "--req", "workspace-one:must,jamf:must:8")
        rows = {l.split("|")[0]: l.split("|") for l in out.splitlines() if "|" in l}
        self.assertEqual(rows["workspace-one"][2], "partial")    # a POC is partial, never met
        self.assertEqual(rows["jamf"][2], "short")               # 5.6 years against an 8 year floor

    def test_no_years_flag_keeps_an_undated_claim_out_of_the_years(self):
        p = self.data / "facts.md"
        p.write_text(p.read_text().replace("tags: [okta, automation, iam, saas], depth: owned", "tags: [okta, automation, iam, saas], depth: owned, no_years: true"))
        run(self.data, "skills")
        table = {l.split("|")[0]: l.split("|") for l in (self.data / "skills.md").read_text().splitlines() if "|" in l}
        self.assertEqual(table["saas"][1], "0")                  # only nw-02 carried saas and it is now undated
        self.assertEqual(table["saas"][4], "1")                  # still counted as evidence

    def test_select_shows_notes_and_hides_conditional_atoms(self):
        _, out, _ = run(self.data, "select", "--tags", "jamf,okta")
        self.assertIn("// Write 1,800 as about 1,800", out)
        self.assertNotIn("nw-07", out)                           # salon atom stays out unless the posting fits
        _, out, _ = run(self.data, "select", "--tags", "salon-industry")
        self.assertIn("nw-07", out)

    def test_conditional_atom_in_a_selection_is_warned(self):
        p = self.data / "jobs/good/selection.yml"
        before = p.read_text()
        p.write_text(before.replace("      - {atom: nw-05,", "      - {atom: nw-07, text: \"Onboarded a salon chain as a support client.\"}\n      - {atom: nw-05,"))
        self.assertNotEqual(before, p.read_text())          # the edit must actually land
        _, out, _ = run(self.data, "build", "good")
        self.assertIn("atom nw-07 is conditional", out)

    def test_title_framing_is_allowed_only_when_facts_list_it(self):
        _, out, _ = run(self.data, "build", "good")
        self.assertIn("### IT Support Engineer, Contoso Retail", (self.data / "jobs/good/resume.md").read_text())
        self.assertNotIn("not the real title", out)
        p = self.data / "jobs/good/selection.yml"
        p.write_text(p.read_text().replace('title: "IT Support Engineer"', 'title: "Chief Technology Officer"'))
        code, out, _ = run(self.data, "build", "good")
        self.assertEqual(code, 1)
        self.assertIn("not the real title or an allowed framing", out)

    def test_push_uses_the_framing_and_fills_profile_sections(self):
        code, out, err = run(self.data, "push", "good")
        self.assertEqual(code, 0, out + err)
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        by = {o["path"]: o["value"] for o in ops}
        self.assertEqual(by["/sections/experience/items"][1]["position"], "IT Support Engineer")
        self.assertEqual((by["/basics/name"], by["/basics/email"], by["/basics/phone"]), ("Sam Rivera", "sam@example.com", "(555) 010-0100"))
        edu = by["/sections/education/items"][0]
        for k in ("id", "hidden", "school", "degree", "area", "grade", "location", "period", "website", "description"):   # live schema's required keys
            self.assertIn(k, edu, k)
        self.assertEqual((edu["school"], edu["degree"]), ("Northwind Tech", "AAS"))
        self.assertIn({"op": "replace", "path": "/sections/education/hidden", "value": False}, ops)     # master hid the section
        cert = by["/sections/certifications/items"][0]
        for k in ("id", "hidden", "title", "issuer", "date", "website", "description"):
            self.assertIn(k, cert, k)
        self.assertEqual(cert["title"], "Okta Certified Professional")
        links = by["/basics/customFields"]
        self.assertEqual([(x["icon"], x["text"], x["link"]) for x in links],
                         [("linkedin-logo", "linkedin.com/in/sam-rivera", "https://www.linkedin.com/in/sam-rivera"),
                          ("github-logo", "github.com/samrivera", "https://github.com/samrivera")])
        for k in ("id", "icon", "text", "link"):                                                          # live schema's required keys
            self.assertIn(k, links[0], k)
        self.assertEqual(by["/sections/profiles/items"], [])
        self.assertIs(by["/sections/profiles/hidden"], True)
        self.assertIn("no other upload needed", out)

    def test_master_create_makes_an_empty_master_only_when_none_exists(self):
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("rr_master: master-1", 'rr_master: ""'))
        saved, FakeRR.resumes = FakeRR.resumes, [{"id": "r9", "slug": "other", "name": "Other resume", "tags": []}]
        try:
            code, out, _ = run(self.data, "master")                       # without --create it lists and explains
            self.assertEqual(code, 1)
            self.assertIn("career master --create", out)
            FakeRR.calls = []
            code, out, err = run(self.data, "master", "--create")
        finally:
            FakeRR.resumes = saved
        self.assertEqual(code, 0, out + err)
        post = [c for c in FakeRR.calls if c[0] == "POST"][0]
        self.assertTrue(post[1].endswith("/api/openapi/resumes"))
        body = json.loads(post[3])
        self.assertEqual((body["name"], body["slug"], body["withSampleData"]), ("Master", "master", False))
        self.assertIn('rr_master: "created-master-1"', p.read_text())
        FakeRR.calls = []
        run(self.data, "master", "--create")                              # a Master exists now (the fake lists one): nothing is created
        self.assertEqual([c for c in FakeRR.calls if c[0] == "POST"], [])

    def test_init_creates_all_three_files(self):
        fresh = self.tmp / "fresh"
        code, out, _ = run(fresh, "init")
        self.assertEqual(code, 0)
        for name in ("profile.md", "facts.md", "rules.md"):
            self.assertTrue((fresh / name).exists(), name)
        run(fresh, "init")                                       # never overwrites
        self.assertIn("kept existing", run(fresh, "init")[1])

    # ---- populating the Master ----

    def test_master_fill_populates_content_cover_section_and_us_defaults(self):
        FakeRR.calls = []
        code, out, err = run(self.data, "master", "--fill", "--from", "good")
        self.assertEqual(code, 0, out + err)
        patch = [(p, b) for m, p, _, b in FakeRR.calls if m == "PATCH"]
        self.assertEqual(len(patch), 1)
        self.assertTrue(patch[0][0].endswith("/resumes/master-1"))                   # the Master itself, not a copy
        ops = json.loads(patch[0][1])["operations"]
        by = {o["path"]: o["value"] for o in ops}
        self.assertEqual([e["company"] for e in by["/sections/experience/items"]], ["Northwind Logistics", "Contoso Retail"])
        self.assertEqual(by["/basics/name"], "Sam Rivera")
        self.assertEqual(by["/metadata/page/format"], "letter")
        self.assertEqual(by["/metadata/typography/body/lineHeight"], 1.25)
        self.assertNotIn("/customSections/-", by)                                    # the fake master already has a cover-letter section
        self.assertIn("Master filled from good", out)

    def test_master_fill_does_not_clobber_a_design_you_changed(self):
        meta = FakeRR.master["data"]["metadata"]
        saved = json.loads(json.dumps(meta))
        meta["page"]["format"], meta["typography"]["body"]["lineHeight"] = "letter", 1.2       # already tuned by the user
        try:
            FakeRR.calls = []
            code, out, _ = run(self.data, "master", "--fill", "--from", "good")
        finally:
            FakeRR.master["data"]["metadata"] = saved
        self.assertEqual(code, 0)
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        self.assertEqual([o for o in ops if o["path"].startswith("/metadata")], [])
        self.assertIn("page settings left as you set them", out)

    def test_master_fill_adds_a_cover_section_when_the_master_has_none(self):
        saved = FakeRR.master["data"]["customSections"]
        FakeRR.master["data"]["customSections"] = []
        try:
            FakeRR.calls = []
            run(self.data, "master", "--fill", "--from", "good")
        finally:
            FakeRR.master["data"]["customSections"] = saved
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        add = [o for o in ops if o["path"] == "/customSections/-"][0]["value"]
        self.assertEqual((add["type"], add["hidden"], add["startOnNewPage"]), ("cover-letter", False, True))
        self.assertEqual(sorted(add["items"][0]), ["content", "hidden", "id", "recipient"])

    def test_master_fill_refuses_a_selection_with_lint_errors(self):
        FakeRR.calls = []
        code, _, err = run(self.data, "master", "--fill", "--from", "bad")
        self.assertEqual(code, 1)
        self.assertEqual([c for c in FakeRR.calls if c[0] == "PATCH"], [])

    def test_push_copies_the_master_design_only_when_asked(self):
        FakeRR.calls = []
        run(self.data, "push", "good")
        plain = [o["path"] for o in json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]]
        self.assertFalse([p for p in plain if p.startswith("/metadata")])           # a per-job template choice is never overwritten
        FakeRR.calls = []
        run(self.data, "push", "good", "--sync-design")
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        synced = {o["path"]: o["value"] for o in ops if o["path"].startswith("/metadata")}
        self.assertEqual(sorted(synced), ["/metadata/design", "/metadata/layout", "/metadata/page", "/metadata/template", "/metadata/typography"])
        self.assertEqual(synced["/metadata/template"], "onyx")

    def test_certifications_keep_full_names_one_per_line(self):
        okta = [{"name": "Okta Certified Professional", "issuer": "Okta", "year": 2023}, {"name": "Okta Certified Administrator", "issuer": "Okta"},
                {"name": "Okta Certified Workflows Specialty", "issuer": "Okta"}, {"name": "Network+", "issuer": "CompTIA"}]
        items = career.cert_items(okta)
        self.assertEqual([i["title"] for i in items], ["Okta Certified Professional", "Okta Certified Administrator",
                                                        "Okta Certified Workflows Specialty", "Network+"])   # full names, input order, never merged
        self.assertEqual([i["issuer"] for i in items], ["", "", "", "CompTIA"])                            # issuer only when the name lacks it
        self.assertEqual(items[0]["date"], "2023")
        for k in ("id", "hidden", "title", "issuer", "date", "website", "description"):
            self.assertIn(k, items[0], k)

    # ---- cover letters ----

    def test_letter_lint_passes_a_good_letter(self):
        code, out, err = run(self.data, "cover", "good", "--dry")
        self.assertEqual(code, 0, out + err)
        self.assertIn("0 error(s)", out)
        text = (self.data / "jobs/good/cover.md").read_text()
        self.assertIn("Dear Hiring Manager,", text)
        self.assertTrue(text.startswith("Sam Rivera\nsam@example.com | (555) 010-0100\nDuluth, MN\n\nSeptember 20, 2026\n"))
        self.assertTrue(text.rstrip().endswith("Sincerely,\nSam Rivera"))

    def test_letter_lint_catches_bad_letters(self):
        code, out, _ = run(self.data, "cover", "bad", "--dry")
        self.assertEqual(code, 1)
        for needle in ("cites no atoms and is not marked jd", "number 2400 is not in the cited atoms", "atom zz-9 not in facts.md",
                       "atom nw-06 has status unconfirmed", "never_claim hit: 'kubernetes'", "I am writing to", "dash used as punctuation",
                       "spearhead"):
            self.assertIn(needle, out, needle)

    def test_letter_year_claims_use_computed_career_length(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("At Northwind I built", "With 20 years behind me I built"))
        _, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertIn("number 20 is not supported", out)

    def test_letter_jd_numbers_only_allowed_in_jd_paragraphs(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("across 12 SaaS apps", "across 400 SaaS apps"))   # 400 is in jd.md but this paragraph cites atoms
        _, out, _ = run(self.data, "cover", "good", "--dry")
        self.assertIn("number 400 is not in the cited atoms", out)

    def test_cover_requires_a_pushed_resume(self):
        code, _, err = run(self.data, "cover", "good")
        self.assertEqual(code, 2)
        self.assertIn("career push", err)

    def test_cover_fills_the_section_and_saves_the_pdf(self):
        run(self.data, "push", "good")
        FakeRR.calls = []
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        methods = [(m, p.split("/api/openapi")[-1]) for m, p, _, _ in FakeRR.calls]
        self.assertEqual(methods, [("GET", "/cover-letters?resumeId=new-resume-1&limit=50&offset=0"), ("POST", "/cover-letters"),   # the saved letter first
                                   ("GET", "/resumes/new-resume-1"), ("PATCH", "/resumes/new-resume-1"),
                                   ("GET", "/resumes/new-resume-1/pdf?target=cover-letter")])
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["path"], "/customSections/0/items")
        item = ops[0]["value"][0]
        self.assertEqual((item["id"], item["hidden"]), ("ci1", False))                      # master's item id and shape reused
        self.assertEqual(item["recipient"], "<p><strong>Sam Rivera</strong><br>sam@example.com | (555) 010-0100<br>Duluth, MN</p>"
                                          "<p>September 20, 2026</p><p>Hiring Manager<br>Fabrikam</p><p></p>")
        self.assertTrue(item["content"].startswith("<p>Dear Hiring Manager,</p><p>Fabrikam&#x27;s plan"))   # html-escaped
        self.assertTrue(item["content"].endswith("<p>Sincerely,<br>Sam Rivera</p>"))
        self.assertEqual((self.data / "jobs/good/cover.pdf").read_bytes(), b"%PDF-1.7 cover")

    def test_cover_stops_before_any_network_call_on_lint_errors(self):
        (self.data / "jobs/bad/rr.json").write_text('{"id": "new-resume-1"}')
        FakeRR.calls = []
        code, _, _ = run(self.data, "cover", "bad")
        self.assertEqual(code, 1)
        self.assertEqual(FakeRR.calls, [])

    def test_cover_adds_a_section_when_the_resume_has_none(self):
        run(self.data, "push", "good")
        saved = FakeRR.master["data"]["customSections"]
        FakeRR.master["data"]["customSections"] = []
        try:
            FakeRR.calls = []
            code, out, err = run(self.data, "cover", "good")
        finally:
            FakeRR.master["data"]["customSections"] = saved
        self.assertEqual(code, 0, out + err)
        self.assertIn("added a cover-letter section", out)
        patches = [json.loads(b)["operations"] for m, _, _, b in FakeRR.calls if m == "PATCH"]
        add = patches[0][0]
        self.assertEqual((add["op"], add["path"], add["value"]["type"]), ("add", "/customSections/-", "cover-letter"))
        self.assertEqual(patches[1][0]["path"], "/customSections/0/items")          # the letter goes into the section just added
        self.assertNotIn("/metadata/layout", json.dumps(patches))                    # not registered in the page layout: keeps it out of resume.pdf

    def test_cover_unhides_a_hidden_section_and_says_so(self):
        run(self.data, "push", "good")
        FakeRR.master["data"]["customSections"][0]["hidden"] = True
        try:
            FakeRR.calls = []
            code, out, _ = run(self.data, "cover", "good")
        finally:
            FakeRR.master["data"]["customSections"][0]["hidden"] = False
        self.assertEqual(code, 0)
        self.assertIn("was hidden in the Master", out)
        ops = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"]
        self.assertIn({"op": "replace", "path": "/customSections/0/hidden", "value": False}, ops)

    def test_cover_attach_uploads_to_the_tracker(self):
        run(self.data, "push", "good")
        run(self.data, "apply", "add", "--company", "Contoso", "--role", "SE", "--job", "good")
        FakeRR.calls = []
        code, out, err = run(self.data, "cover", "good", "--attach")
        self.assertEqual(code, 0, out + err)
        post = [c for c in FakeRR.calls if c[0] == "POST" and "/documents/" in c[1]][0]
        self.assertTrue(post[1].endswith("/applications/app-1/documents/cover-letter"))
        self.assertIn(b"%PDF-1.7 cover", post[3])

    def test_attach_without_tracker_entry_fails_early(self):
        run(self.data, "push", "good")
        FakeRR.calls = []
        code, _, err = run(self.data, "cover", "good", "--attach")
        self.assertEqual(code, 2)
        self.assertIn("career apply add", err)
        self.assertEqual(FakeRR.calls, [])

    # ---- saved cover letters (Reactive Resume > Cover Letters) ----

    LETTER = "Fabrikam - Systems Engineer - Sam Rivera Cover Letter"

    def _ready(self, tracker=False):
        run(self.data, "push", "good")
        if tracker:
            run(self.data, "apply", "add", "--company", "Contoso", "--role", "SE", "--job", "good")
        FakeRR.calls = []

    def _the_letter(self):
        self.assertEqual(len(FakeRR.letters), 1, list(FakeRR.letters))
        return next(iter(FakeRR.letters.values()))

    def _seed(self, name, resume=None, app=None):
        FakeRR.letter_seq += 1
        lid = f"cl-{FakeRR.letter_seq}"
        FakeRR.letters[lid] = {"id": lid, "name": name, "recipient": "<p>R</p>", "content": "<p>Dear X,</p><p>body</p>",
                               "style": {"basics": {}, "picture": {}, "metadata": {}, "sectionId": "s", "itemId": "i"},
                               "sourceResumeId": resume, "sourceApplicationId": app, "revision": 1, "createdAt": "t", "updatedAt": "t"}
        return lid

    def _calls(self, *methods):
        return [(m, p.split("/api/openapi")[-1]) for m, p, _, _ in FakeRR.calls if m in methods]

    def _edit_cover_yml(self):
        p = self.data / "jobs/good/cover.yml"
        p.write_text(p.read_text().replace("about the role.", "about the Systems Engineer role."))

    def test_cover_creates_the_saved_letter_linked_to_resume_and_tracker_row(self):
        self._ready(tracker=True)
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn("created cover letter", out)
        self.assertIn("/dashboard/cover-letters", out)
        d = self._the_letter()
        self.assertEqual((d["name"], d["sourceResumeId"], d["sourceApplicationId"]), (self.LETTER, "new-resume-1", "app-1"))
        item = json.loads([b for m, _, _, b in FakeRR.calls if m == "PATCH"][0])["operations"][0]["value"][0]
        self.assertEqual((d["recipient"], d["content"]), (item["recipient"], item["content"]))          # the same letter as the resume's section
        self.assertEqual(json.loads((self.data / "jobs/good/cover.json").read_text())["id"], d["id"])
        self.assertEqual((self.data / "jobs/good/cover.pdf").read_bytes(), b"%PDF-1.7 cover")            # the PDF flow is unchanged

    def test_cover_without_a_tracker_row_links_only_the_resume(self):
        self._ready()
        run(self.data, "cover", "good")
        d = self._the_letter()
        self.assertEqual((d["sourceResumeId"], d["sourceApplicationId"]), ("new-resume-1", None))

    def test_cover_run_twice_changes_nothing(self):
        self._ready()
        run(self.data, "cover", "good")
        FakeRR.calls = []
        code, out, _ = run(self.data, "cover", "good")
        self.assertEqual(code, 0)
        self.assertIn("already up to date", out)
        self.assertEqual(self._calls("POST", "PUT", "DELETE"), [])
        self.assertEqual(len(FakeRR.letters), 1)
        self.assertEqual(self._the_letter()["revision"], 1)

    def test_cover_updates_the_same_letter_when_cover_yml_changes(self):
        self._ready()
        run(self.data, "cover", "good")
        first = self._the_letter()["id"]
        self._edit_cover_yml()
        FakeRR.calls = []
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn("updated cover letter", out)
        d = self._the_letter()
        self.assertEqual((d["id"], d["revision"]), (first, 2))
        self.assertIn("about the Systems Engineer role.", d["content"])
        put = [c for c in FakeRR.calls if c[0] == "PUT" and "/cover-letters/" in c[1]][0]
        body = json.loads(put[3])
        self.assertEqual(body["expectedRevision"], 1)                     # the revision we read is the one we send
        self.assertNotIn("name", body)                                    # the name is not touched on update
        self.assertEqual([c for c in self._calls("POST") if c[1].endswith("/cover-letters")], [])   # no duplicate

    def test_cover_respects_a_rename_made_in_reactive_resume(self):
        self._ready()
        run(self.data, "cover", "good")
        run(self.data, "letters", "rename", "--job", "good", "--name", "Fabrikam letter, final")
        self._edit_cover_yml()
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self._the_letter()["name"], "Fabrikam letter, final")

    def test_cover_keeps_browser_edits_when_cover_yml_did_not_change(self):
        self._ready()
        run(self.data, "cover", "good")
        d = self._the_letter()
        d["content"] += "<p>PS added in the browser</p>"
        d["revision"] += 1
        FakeRR.calls = []
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn("has edits made in Reactive Resume and was left as is", out)
        self.assertEqual([c for c in self._calls("POST", "PUT", "DELETE") if "/cover-letters" in c[1]], [])
        self.assertIn("PS added in the browser", self._the_letter()["content"])
        self.assertEqual((self.data / "jobs/good/cover.pdf").read_bytes(), b"%PDF-1.7 cover")      # the PDF is still regenerated
        code, out, _ = run(self.data, "cover", "good", "--overwrite")                              # explicit replace
        self.assertEqual(code, 0)
        self.assertNotIn("PS added in the browser", self._the_letter()["content"])

    def test_cover_refuses_to_overwrite_browser_edits_when_cover_yml_also_changed(self):
        self._ready(tracker=True)
        run(self.data, "cover", "good", "--attach")
        d = self._the_letter()
        d["content"] += "<p>PS added in the browser</p>"
        d["revision"] += 1
        self._edit_cover_yml()
        FakeRR.calls = []
        code, out, err = run(self.data, "cover", "good", "--attach")
        self.assertEqual(code, 1)
        self.assertIn("changed in Reactive Resume", err)
        self.assertIn("--overwrite", err)
        self.assertEqual([m for m, _, _, _ in FakeRR.calls if m != "GET"], [])          # nothing written anywhere: no PATCH, PUT, POST or upload
        self.assertFalse(any("/pdf" in p for _, p, _, _ in FakeRR.calls))
        self.assertIn("PS added in the browser", d["content"])
        code, out, err = run(self.data, "cover", "good", "--overwrite")
        self.assertEqual(code, 0, out + err)
        self.assertIn("about the Systems Engineer role.", self._the_letter()["content"])

    def test_cover_does_not_adopt_an_unrecorded_letter_without_overwrite(self):
        self._ready()
        run(self.data, "cover", "good")
        (self.data / "jobs/good/cover.json").unlink()                     # e.g. the job folder was copied to another machine
        code, _, err = run(self.data, "cover", "good")
        self.assertEqual(code, 1)
        self.assertIn("no record of writing it", err)
        self.assertEqual(len(FakeRR.letters), 1)                          # and no second letter was created
        code, out, err = run(self.data, "cover", "good", "--overwrite")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(FakeRR.letters), 1)
        self.assertTrue((self.data / "jobs/good/cover.json").exists())

    def test_cover_recreates_a_letter_deleted_in_reactive_resume(self):
        self._ready()
        run(self.data, "cover", "good")
        old = self._the_letter()["id"]
        FakeRR.letters.clear()
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn("created cover letter", out)
        new = self._the_letter()["id"]
        self.assertNotEqual(new, old)
        self.assertEqual(json.loads((self.data / "jobs/good/cover.json").read_text())["id"], new)

    def test_cover_stops_on_a_revision_conflict_without_overwriting(self):
        self._ready()
        run(self.data, "cover", "good")
        self._edit_cover_yml()
        FakeRR.race = True                                                # another tab saves between our read and our write
        code, _, err = run(self.data, "cover", "good")
        self.assertEqual(code, 1)
        self.assertIn("revision conflict", err)
        self.assertNotIn("about the Systems Engineer role.", self._the_letter()["content"])

    def test_cover_no_saved_leaves_the_list_alone(self):
        self._ready()
        code, out, err = run(self.data, "cover", "good", "--no-saved")
        self.assertEqual(code, 0, out + err)
        self.assertEqual([p for _, p in self._calls("GET", "POST", "PUT") if "/cover-letters" in p], [])
        self.assertEqual(FakeRR.letters, {})
        self.assertTrue((self.data / "jobs/good/cover.pdf").exists())

    def test_cover_still_works_on_an_older_reactive_resume(self):
        self._ready()
        FakeRR.has_letters = False
        code, out, err = run(self.data, "cover", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn("no Cover Letters API", out)
        self.assertEqual((self.data / "jobs/good/cover.pdf").read_bytes(), b"%PDF-1.7 cover")
        self.assertFalse((self.data / "jobs/good/cover.json").exists())
        self.assertIn("not available", run(self.data, "check")[1])

    def test_check_reports_the_mcp_endpoint_and_registration(self):
        code, out, err = run(self.data, "check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ok    mcp endpoint", out)
        self.assertIn("2 tools", out)
        self.assertIn("ok    mcp registration: registered in Claude Code", out)
        self.assertTrue(any(p == "/mcp" and k == "test-key" for _m, p, k, _b in FakeRR.calls))

    def test_check_fails_when_the_mcp_endpoint_rejects_the_key_or_is_not_registered(self):
        FakeRR.mcp_ok = False
        code, out, _ = run(self.data, "check")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  mcp endpoint", out)
        FakeRR.mcp_ok = True
        (self.home / ".claude.json").write_text("{}")
        code, out, _ = run(self.data, "check")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  mcp registration: not registered", out)

    def test_check_reports_the_cover_letters_api(self):
        code, out, err = run(self.data, "check")
        self.assertEqual(code, 0, out + err)
        self.assertIn("ok    cover letters: 0 saved cover letter(s) visible", out)
        self._seed("x")
        self.assertIn("1 saved cover letter(s) visible", run(self.data, "check")[1])

    def test_html_text_turns_letter_html_into_plain_text(self):
        self.assertEqual(career.html_text("<p><strong>Sam</strong><br>a@b.co</p><p>Fabrikam&#x27;s plan &amp; more</p>"), "Sam\na@b.co\n\nFabrikam's plan & more")
        self.assertEqual(career.html_text(None), "")

    def test_letters_ls_lists_filters_and_pages(self):
        a = self._seed("Alpha letter", resume="r1", app="a1")
        self._seed("Beta letter", resume="r2")
        code, out, err = run(self.data, "letters", "ls")
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"{a} | Alpha letter | rev 1 | resume r1 | application a1", out)
        self.assertIn("2 saved cover letter(s) (", out)
        self.assertIn("1 saved", run(self.data, "letters", "ls", "--search", "beta")[1])
        self.assertIn("1 saved", run(self.data, "letters", "ls", "--resume", "r1")[1])
        self.assertIn("1 saved", run(self.data, "letters", "ls", "--application", "a1")[1])
        self.assertTrue(any("search=beta" in p for _, p in self._calls("GET")))
        for i in range(120):
            self._seed(f"bulk {i}")
        FakeRR.calls = []
        code, out, _ = run(self.data, "letters", "ls")
        self.assertIn("122 saved cover letter(s)", out)
        self.assertEqual([p for _, p in self._calls("GET")], ["/cover-letters?limit=50&offset=0", "/cover-letters?limit=50&offset=50", "/cover-letters?limit=50&offset=100"])

    def test_letters_ls_for_a_job_uses_its_resume(self):
        self._ready()
        run(self.data, "cover", "good")
        self._seed("Someone else's", resume="other-resume")
        code, out, err = run(self.data, "letters", "ls", "--job", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn(self.LETTER, out)
        self.assertNotIn("Someone else's", out)
        self.assertEqual(run(self.data, "letters", "ls", "--job", "bad")[0], 2)          # no rr.json or app.json: nothing to link on

    def test_letters_show_prints_text_or_html_and_can_save_it(self):
        self._ready()
        run(self.data, "cover", "good")
        code, out, err = run(self.data, "letters", "show", "--job", "good")
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"{self.LETTER} [", out)
        self.assertIn("rev 1 | resume new-resume-1", out)
        self.assertIn("Dear Hiring Manager,", out)
        self.assertNotIn("<p>", out)
        self.assertIn("<p>Dear Hiring Manager,</p>", run(self.data, "letters", "show", "--job", "good", "--html")[1])
        dest = self.tmp / "letter.txt"
        run(self.data, "letters", "show", self._the_letter()["id"], "-o", str(dest))
        self.assertIn("Fabrikam's plan", dest.read_text())

    def test_letters_commands_need_an_id_or_job_and_report_unknown_ids(self):
        code, _, err = run(self.data, "letters", "show")
        self.assertEqual(code, 2)
        self.assertIn("pass a letter id", err)
        code, _, err = run(self.data, "letters", "show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("404", err)
        code, _, err = run(self.data, "letters", "show", "--job", "good")
        self.assertEqual(code, 2)
        self.assertIn("career cover good", err)

    def test_letters_export_then_import_round_trips(self):
        self._ready()
        run(self.data, "cover", "good")
        dest = self.tmp / "out.json"
        code, out, err = run(self.data, "letters", "export", "--job", "good", "-o", str(dest))
        self.assertEqual(code, 0, out + err)
        doc = json.loads(dest.read_text())
        self.assertEqual((doc["name"], doc["format"]), (self.LETTER, "reactive-resume-cover-letter"))
        code, out, err = run(self.data, "letters", "import", str(dest))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(FakeRR.letters), 2)
        self.assertEqual(sorted(d["name"] for d in FakeRR.letters.values()), [self.LETTER, self.LETTER])

    def test_letters_import_refuses_text_that_breaks_never_claim(self):
        dest = self.tmp / "bad.json"
        dest.write_text(json.dumps({"name": "x", "recipient": "<p>R</p>", "content": "<p>I run Kubernetes clusters.</p>", "style": {}, "format": "f", "version": 1}))
        code, out, err = run(self.data, "letters", "import", str(dest))
        self.assertEqual(code, 1)
        self.assertIn("never_claim hit: 'kubernetes'", out)
        self.assertEqual(FakeRR.letters, {})
        self.assertEqual([c for c in self._calls("POST")], [])

    def test_letters_rename_sends_the_revision_it_read(self):
        lid = self._seed("Old name")
        code, out, err = run(self.data, "letters", "rename", lid, "--name", "New name")
        self.assertEqual(code, 0, out + err)
        body = json.loads([b for m, p, _, b in FakeRR.calls if m == "PUT"][0])
        self.assertEqual(body, {"expectedRevision": 1, "name": "New name"})
        self.assertEqual((FakeRR.letters[lid]["name"], FakeRR.letters[lid]["revision"]), ("New name", 2))

    def test_letters_duplicate_makes_a_copy(self):
        lid = self._seed("Original", resume="r1")
        code, out, err = run(self.data, "letters", "duplicate", lid, "--name", "Copy for Contoso")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(sorted(d["name"] for d in FakeRR.letters.values()), ["Copy for Contoso", "Original"])
        code, out, _ = run(self.data, "letters", "duplicate", lid)
        self.assertIn("Original (copy)", out)

    def test_letters_refresh_style_copies_the_linked_resumes_design(self):
        lid = self._seed("Linked", resume="new-resume-1")
        code, out, err = run(self.data, "letters", "refresh-style", lid)
        self.assertEqual(code, 0, out + err)
        body = json.loads([b for m, p, _, b in FakeRR.calls if m == "POST" and p.endswith("/refresh-style")][0])
        self.assertEqual(body, {"expectedRevision": 1, "resumeId": "new-resume-1"})
        self.assertEqual(FakeRR.letters[lid]["style"]["metadata"]["refreshedFrom"], "new-resume-1")
        unlinked = self._seed("Unlinked")
        code, _, err = run(self.data, "letters", "refresh-style", unlinked)
        self.assertEqual(code, 2)
        self.assertIn("not linked to a resume", err)
        self.assertEqual(run(self.data, "letters", "refresh-style", unlinked, "--resume", "r9")[0], 0)

    def test_letters_delete_needs_yes_and_forgets_the_job_state(self):
        self._ready()
        run(self.data, "cover", "good")
        code, _, err = run(self.data, "letters", "delete", "--job", "good")
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertEqual(len(FakeRR.letters), 1)
        FakeRR.calls = []
        code, out, err = run(self.data, "letters", "delete", "--job", "good", "--yes")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(FakeRR.letters, {})
        self.assertEqual(json.loads([b for m, _, _, b in FakeRR.calls if m == "DELETE"][0]), {"expectedRevision": 1})
        self.assertFalse((self.data / "jobs/good/cover.json").exists())

    def test_letters_delete_stops_on_a_revision_conflict(self):
        lid = self._seed("Keep me")
        FakeRR.race = True
        code, _, err = run(self.data, "letters", "delete", lid, "--yes")
        self.assertEqual(code, 2)
        self.assertIn("409", err)
        self.assertIn(lid, FakeRR.letters)

    def test_several_letters_for_one_job_are_listed_not_guessed(self):
        self._ready()
        run(self.data, "cover", "good")
        (self.data / "jobs/good/cover.json").unlink()
        self._seed("Another draft", resume="new-resume-1")
        self._seed("Yet another", resume="new-resume-1")
        FakeRR.letters[next(iter(FakeRR.letters))]["name"] = "Renamed away"      # no name match left either
        code, _, err = run(self.data, "letters", "show", "--job", "good")
        self.assertEqual(code, 2)
        self.assertIn("more than one saved cover letter", err)
        self.assertIn("Another draft", err)

    def test_check_warns_when_master_lacks_a_cover_letter_section(self):
        saved = FakeRR.master["data"]["customSections"]
        FakeRR.master["data"]["customSections"] = []
        try:
            code, out, _ = run(self.data, "check")
        finally:
            FakeRR.master["data"]["customSections"] = saved
        self.assertEqual(code, 0)                       # a warning, not a failure
        self.assertIn("NO cover-letter section", out)
        self.assertIn("cover-letter section present", run(self.data, "check")[1])

    def test_master_autodetects_and_records_the_id(self):
        p = self.data / "profile.md"
        p.write_text(p.read_text().replace("rr_master: master-1", 'rr_master: ""            # id of your styled Master'))
        code, out, err = run(self.data, "master")
        self.assertEqual(code, 0, out + err)
        text = p.read_text()
        self.assertIn('rr_master: "master-1"', text)
        self.assertIn("# id of your styled Master", text)          # the comment survives
        self.assertEqual(career.read_front(p)["rr_master"], "master-1")
        code, out, _ = run(self.data, "master", "abc-123")
        self.assertIn('rr_master: "abc-123"', p.read_text())
        FakeRR.calls = []
        code, out, _ = run(self.data, "master", "--if-unset")           # setup.sh re-runs must not clobber a chosen master
        self.assertEqual(code, 0)
        self.assertIn("keeping it", out)
        self.assertIn('rr_master: "abc-123"', p.read_text())
        self.assertEqual(FakeRR.calls, [])


if __name__ == "__main__":
    unittest.main()
