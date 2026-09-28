"""Opt-in check of the cover-letter code against a real Reactive Resume (never runs by default).

    CAREER_LIVE=1 uv run --with pyyaml python -m unittest tests.test_live_cover_letters -v

It reads the URL from $RR_URL or rr_url in your profile.md and the key from ~/.config/career/rr.env, exactly like `career` does.
It only touches letters it creates itself: unlinked, named 'ZZ career-architect live test <id> ...', and deleted again at the end
(also when a check fails). Your real letters, resumes and tracker rows are never read for writing.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import career  # noqa: E402
from test_career import FIXTURES, run  # noqa: E402

LIVE = os.environ.get("CAREER_LIVE") == "1"


@unittest.skipUnless(LIVE, "set CAREER_LIVE=1 to run against a real Reactive Resume")
class LiveCoverLetters(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        shutil.copytree(FIXTURES, self.data)
        self._env = {k: os.environ.get(k) for k in ("RR_URL", "RR_API_KEY")}
        self.real = career.Ctx(None, dt.date.today()).profile          # your real profile.md, read only: the URL and the Master resume id
        if not os.environ.get("RR_URL"):
            self.assertTrue(self.real.get("rr_url"), "no rr_url: set $RR_URL or rr_url in your profile.md")
            os.environ["RR_URL"] = self.real["rr_url"]
        os.environ.pop("RR_API_KEY", None)                   # use ~/.config/career/rr.env, not a leftover fake key
        self.ctx = career.Ctx(str(self.data), dt.date.today())
        self.prefix = f"ZZ career-architect live test {uuid.uuid4().hex[:8]}"

    def tearDown(self):
        try:
            for row in career.list_letters(self.ctx, search=self.prefix):
                if str(row.get("name", "")).startswith(self.prefix):        # only ever delete our own
                    career.api(self.ctx, "DELETE", f"/cover-letters/{row['id']}", {"expectedRevision": row["revision"]})
        finally:
            for k, v in self._env.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _create(self, suffix=""):
        made = career.api(self.ctx, "POST", "/cover-letters", {
            "name": f"{self.prefix}{suffix}", "recipient": "<p>Hiring Manager<br>Test Co</p>",
            "content": "<p>Dear Hiring Manager,</p><p>This is a live test letter &amp; it will be deleted.</p><p>Sincerely,<br>Test</p>"})
        return made if isinstance(made, dict) else career.api(self.ctx, "GET", f"/cover-letters/{made}")

    def test_full_read_write_cycle(self):
        doc = self._create()
        lid = doc["id"]
        for key in ("id", "name", "recipient", "content", "style", "revision", "sourceResumeId", "sourceApplicationId"):
            self.assertIn(key, doc, f"the live API no longer returns '{key}'")
        self.assertEqual(doc["revision"], 1)

        code, out, err = run(self.data, "letters", "ls", "--search", self.prefix)                 # list + search (limit/offset accepted)
        self.assertEqual(code, 0, out + err)
        self.assertIn(lid, out)

        code, out, err = run(self.data, "letters", "show", lid)                                   # read as text
        self.assertEqual(code, 0, out + err)
        self.assertIn("This is a live test letter & it will be deleted.", out)
        self.assertNotIn("<p>", out)

        code, out, err = run(self.data, "letters", "rename", lid, "--name", f"{self.prefix} renamed")   # write with expectedRevision
        self.assertEqual(code, 0, out + err)
        now = career.api(self.ctx, "GET", f"/cover-letters/{lid}")
        self.assertEqual((now["name"], now["revision"]), (f"{self.prefix} renamed", 2))

        with self.assertRaises(SystemExit) as stale:                                              # a stale revision must be refused, and we must say so
            career.write_letter(self.ctx, doc, name=f"{self.prefix} stale")                        # doc still carries revision 1
        self.assertEqual(stale.exception.code, 1)
        self.assertEqual(career.api(self.ctx, "GET", f"/cover-letters/{lid}")["name"], f"{self.prefix} renamed")

        code, out, err = run(self.data, "letters", "duplicate", lid, "--name", f"{self.prefix} copy")
        self.assertEqual(code, 0, out + err)
        names = {r["name"] for r in career.list_letters(self.ctx, search=self.prefix)}
        self.assertEqual(names, {f"{self.prefix} renamed", f"{self.prefix} copy"})

        dest = self.tmp / "export.json"
        code, out, err = run(self.data, "letters", "export", lid, "-o", str(dest))
        self.assertEqual(code, 0, out + err)
        exported = json.loads(dest.read_text())
        self.assertEqual(exported["name"], f"{self.prefix} renamed")
        code, out, err = run(self.data, "letters", "import", str(dest))                           # write from a document
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(career.list_letters(self.ctx, search=self.prefix)), 3)

        master = self.real.get("rr_master")
        if master:                                                                                # style refresh from a real resume
            code, out, err = run(self.data, "letters", "refresh-style", lid, "--resume", master)
            self.assertEqual(code, 0, out + err)

        for row in career.list_letters(self.ctx, search=self.prefix):                             # delete needs --yes, then really deletes
            self.assertEqual(run(self.data, "letters", "delete", row["id"])[0], 2)
            code, out, err = run(self.data, "letters", "delete", row["id"], "--yes")
            self.assertEqual(code, 0, out + err)
        self.assertEqual(career.list_letters(self.ctx, search=self.prefix), [])
        with self.assertRaises(career.ApiError) as gone:
            career.api(self.ctx, "GET", f"/cover-letters/{lid}")
        self.assertEqual(gone.exception.status, 404)

    def test_check_sees_the_cover_letters_api(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                career.main(["--data", str(self.data), "check"])
            except SystemExit:
                pass
        text = out.getvalue()
        self.assertIn("cover letters", text)
        self.assertNotIn("FAIL  cover letters", text)


if __name__ == "__main__":
    unittest.main()
