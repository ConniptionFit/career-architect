"""Direct loading: the checks read a person's records from their GitHub repository by path (mcp-server/records.py).

Runs against tests/github_sim.py, a local stand-in for GitHub's API, so no network or account is needed.
  uv run --python 3.12 --with "mcp==2.2.0" --with pyyaml python -m unittest tests.test_records -v
"""
import base64
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
sys.path.insert(0, str(ROOT / "mcp-server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import server as srv
    import records
    from mcp.server.mcpserver.exceptions import ToolError
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

import career  # noqa: E402
import yaml  # noqa: E402
from github_sim import GitHubSim  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "data"
TODAY = "2026-09-20"
REPO = "jordan-lee/career-records"
TOKEN = "gho_jordan"


def repo_files() -> dict[str, str]:
    """The fixture career in the GitHub layout: plain files, one per role."""
    facts = career.read_block(FIXTURES / "facts.md")
    out = {"profile.md": (FIXTURES / "profile.md").read_text(), "rules.md": (FIXTURES / "rules.md").read_text(),
           "facts/shared.yaml": yaml.safe_dump({k: facts[k] for k in ("aliases", "credentials", "education") if facts.get(k)}, sort_keys=False, allow_unicode=True)}
    for role in facts["roles"]:
        out[f"facts/{role['id']}.yaml"] = yaml.safe_dump({"roles": [role]}, sort_keys=False, allow_unicode=True)
    for f in ("jd.md", "selection.yml"):
        out[f"jobs/good/{f}"] = (FIXTURES / "jobs" / "good" / f).read_text()
    out["jobs/good/cover.yml"] = (FIXTURES / "jobs" / "good" / "cover.yml").read_text()
    return out


class Ctx:
    """What a tool sees of the request: only its headers."""
    def __init__(self, headers=None):
        self.headers = headers or {}


def user(token=TOKEN):
    return Ctx({"X-GitHub-Token": token})


def call(fn, **kw):
    """Run a tool's function as the server would (the guarded wrapper included)."""
    return fn(**kw)


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class UserTokenMode(unittest.TestCase):
    """The gateway forwards the person's own GitHub token; the caller names the repository."""

    def setUp(self):
        self.sim = GitHubSim().__enter__()
        self.files = repo_files()
        self.first = self.sim.add_repo(REPO, self.files, token=TOKEN)
        self.sim.add_repo("someone-else/career-records", {"profile.md": "---\nname: Other\n---\n"}, token="gho_other")
        self.patches = [mock.patch.object(records, "API", self.sim.url),
                        mock.patch.object(srv, "RECORDS", records.Records(records.Config(mode="user_token")))]
        for p in self.patches:
            p.start()
        # the same documents as text, for comparing the two ways in
        self.facts_text = [self.files["facts/shared.yaml"]] + [v for k, v in sorted(self.files.items()) if k.startswith("facts/") and k != "facts/shared.yaml"]
        self.skills_md = call(srv.build_index, facts_docs=self.facts_text, today=TODAY)["skills_md"]
        self.files["skills.md"] = self.skills_md
        self.sim.repos[REPO][-1][1]["skills.md"] = self.skills_md.encode()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.sim.__exit__()

    def test_build_index_reads_a_whole_folder_and_gives_the_same_index_as_text(self):
        out = call(srv.build_index, facts_paths=["facts/"], repo=REPO, today=TODAY, ctx=user())
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["skills_md"], self.skills_md)
        self.assertEqual(out["records_commit"], self.sim.head(REPO))

    def test_match_by_path_equals_match_by_text(self):
        reqs = "okta:must:5,terraform:nice"
        by_text = call(srv.match, skills_md=self.skills_md, profile_md=self.files["profile.md"], requirements=reqs)
        by_path = call(srv.match, skills_path="skills.md", profile_path="profile.md", requirements=reqs, repo=REPO, ctx=user())
        commit = by_path.pop("records_commit")
        self.assertEqual(by_path, by_text)
        self.assertEqual(commit, self.sim.head(REPO))
        self.assertNotIn("records_commit", by_text)

    def test_resume_checks_by_path_equal_the_same_checks_by_text(self):
        roles = ["facts/shared.yaml"] + [k for k in self.files if k.startswith("facts/") and k != "facts/shared.yaml"]
        text = dict(selection_yaml=self.files["jobs/good/selection.yml"], skills_md=self.skills_md, profile_md=self.files["profile.md"],
                    facts_docs=[self.files[k] for k in roles], today=TODAY)
        paths = dict(selection_path="jobs/good/selection.yml", skills_path="skills.md", profile_path="profile.md", facts_paths=roles,
                     today=TODAY, repo=REPO, ctx=user())
        uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")      # new item ids differ on every call
        for tool in (srv.lint_resume, srv.resume_patch):
            a, b = call(tool, **text), call(tool, **paths)
            b.pop("records_commit")
            self.assertEqual(uuid.sub("ID", json.dumps(a)), uuid.sub("ID", json.dumps(b)), tool.__name__)
        a = call(srv.lint_cover, cover_yaml=self.files["jobs/good/cover.yml"], skills_md=self.skills_md, profile_md=self.files["profile.md"],
                 facts_docs=[self.files[k] for k in roles], posting_text=self.files["jobs/good/jd.md"], today=TODAY)
        b = call(srv.lint_cover, cover_path="jobs/good/cover.yml", skills_path="skills.md", profile_path="profile.md", facts_paths=roles,
                 posting_path="jobs/good/jd.md", today=TODAY, repo=REPO, ctx=user())
        b.pop("records_commit")
        self.assertEqual(a, b)

    def test_text_and_paths_mix_for_facts(self):
        """A fragment edited but not saved yet can be checked beside the saved ones."""
        out = call(srv.build_index, facts_docs=[self.files["facts/shared.yaml"]], facts_paths=sorted(k for k in self.files if k.startswith("facts/") and k != "facts/shared.yaml"),
                   repo=REPO, today=TODAY, ctx=user())
        self.assertEqual(out["skills_md"], self.skills_md)

    def test_reads_pin_to_one_commit(self):
        before = call(srv.records_read, paths=["profile.md"], repo=REPO, ctx=user())
        call(srv.records_write, path="profile.md", text=before["files"][0]["text"] + "\nnote\n", sha=before["files"][0]["sha"], repo=REPO, ctx=user())
        pinned = call(srv.records_read, paths=["profile.md"], repo=REPO, ref=before["records_commit"], ctx=user())
        latest = call(srv.records_read, paths=["profile.md"], repo=REPO, ctx=user())
        self.assertEqual(pinned["files"][0]["text"], self.files["profile.md"])
        self.assertTrue(latest["files"][0]["text"].endswith("\nnote\n"))
        self.assertNotEqual(latest["records_commit"], before["records_commit"])

    def test_write_is_one_call_and_refuses_a_stale_sha(self):
        got = call(srv.records_read, paths=["rules.md"], repo=REPO, ctx=user())["files"][0]
        saved = call(srv.records_write, path="rules.md", text="new rules\n", sha=got["sha"], message="Tighten rules", repo=REPO, ctx=user())
        self.assertFalse(saved["created"])
        self.assertEqual(self.sim.file(REPO, "rules.md"), "new rules\n")
        with self.assertRaisesRegex(ToolError, "changed since you read it"):
            call(srv.records_write, path="rules.md", text="other\n", sha=got["sha"], repo=REPO, ctx=user())
        with self.assertRaisesRegex(ToolError, "needs the `sha`"):
            call(srv.records_write, path="rules.md", text="other\n", repo=REPO, ctx=user())
        new = call(srv.records_write, path="jobs/fabrikam-se/jd.md", text="posting\n", repo=REPO, ctx=user())
        self.assertTrue(new["created"])

    def test_list_shows_files_and_folders(self):
        out = call(srv.records_list, repo=REPO, ctx=user())
        kinds = {i["path"]: i["type"] for i in out["items"]}
        self.assertEqual(kinds["facts"], "folder")
        self.assertEqual(kinds["profile.md"], "file")
        roles = call(srv.records_list, folder="facts", repo=REPO, ctx=user())["items"]
        self.assertIn("facts/shared.yaml", {i["path"] for i in roles})

    def test_the_token_decides_which_repository_is_reachable(self):
        with self.assertRaisesRegex(ToolError, "not found"):
            call(srv.records_read, paths=["profile.md"], repo="someone-else/career-records", ctx=user())
        with self.assertRaisesRegex(ToolError, "no GitHub sign-in"):
            call(srv.records_read, paths=["profile.md"], repo=REPO, ctx=Ctx())
        with self.assertRaisesRegex(ToolError, "repo is required"):
            call(srv.records_read, paths=["profile.md"], ctx=user())

    def test_bearer_prefix_is_accepted(self):
        out = call(srv.records_read, paths=["profile.md"], repo=REPO, ctx=Ctx({"x-github-token": f"Bearer {TOKEN}"}))
        self.assertEqual(out["files"][0]["path"], "profile.md")

    def test_only_record_files_inside_the_repository(self):
        for bad in ("../profile.md", "/etc/passwd.md", ".git/config.md", "facts/.hidden.yaml", "run.sh", "a/b/c/d/e/f/g.md", "facts/../x.md"):
            with self.assertRaises(ToolError, msg=bad):
                call(srv.records_read, paths=[bad], repo=REPO, ctx=user())
        with self.assertRaises(ToolError):
            call(srv.records_write, path="workflow.py", text="x", repo=REPO, ctx=user())
        with self.assertRaisesRegex(ToolError, "owner/name"):
            call(srv.records_read, paths=["profile.md"], repo="not a repo", ctx=user())

    def test_status_reports_header_names_never_values(self):
        out = call(srv.records_status, repo=REPO, ctx=Ctx({"X-GitHub-Token": TOKEN, "X-Obot-User-Id": "u-123", "Authorization": "Bearer secret-ish"}))
        self.assertTrue(out["reachable"])
        self.assertEqual(out["commit"], self.sim.head(REPO))
        self.assertEqual(out["headers_seen"], ["authorization", "x-github-token", "x-obot-user-id"])
        self.assertTrue(out["token_header_present"])
        self.assertEqual(out["user_id"], "u-123")
        blob = json.dumps(out)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn("secret-ish", blob)

    def test_a_document_must_come_as_text_or_path(self):
        with self.assertRaisesRegex(ToolError, "skills_md is required"):
            call(srv.match, profile_path="profile.md", requirements="okta:must", repo=REPO, ctx=user())


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class AppMode(unittest.TestCase):
    """The server holds a GitHub App key; the gateway's identity header picks the person's one repository."""

    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()

    def setUp(self):
        self.sim = GitHubSim().__enter__()
        self.sim.add_repo(REPO, {"profile.md": "---\nname: Jordan Lee\n---\n"}, installation=7)
        self.sim.add_repo("sam/career-records", {"profile.md": "---\nname: Sam\n---\n"}, installation=8)
        cfg = records.Config(mode="app", app_id="5827242", app_key=self.pem, repo_map={"u-jordan": REPO, "u-sam": "sam/career-records"})
        self.patches = [mock.patch.object(records, "API", self.sim.url), mock.patch.object(srv, "RECORDS", records.Records(cfg))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.sim.__exit__()

    def test_each_person_reaches_only_their_own_repository(self):
        jordan = call(srv.records_read, paths=["profile.md"], ctx=Ctx({"X-Obot-User-Id": "u-jordan"}))
        sam = call(srv.records_read, paths=["profile.md"], ctx=Ctx({"X-Obot-User-Id": "u-sam"}))
        self.assertIn("Jordan", jordan["files"][0]["text"])
        self.assertIn("Sam", sam["files"][0]["text"])
        with self.assertRaisesRegex(ToolError, "not the one set up"):
            call(srv.records_read, paths=["profile.md"], repo="sam/career-records", ctx=Ctx({"X-Obot-User-Id": "u-jordan"}))
        with self.assertRaisesRegex(ToolError, "no records repository"):
            call(srv.records_read, paths=["profile.md"], ctx=Ctx({"X-Obot-User-Id": "u-stranger"}))
        with self.assertRaisesRegex(ToolError, "no records repository"):
            call(srv.records_read, paths=["profile.md"], ctx=Ctx())

    def test_the_app_signs_a_short_jwt_and_tokens_are_reused(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        for _ in range(3):
            call(srv.records_read, paths=["profile.md"], ctx=Ctx({"X-Obot-User-Id": "u-jordan"}))
        self.assertEqual(len(self.sim.app_jwts), 2, "one installation lookup and one token, then the token is reused")
        header, claims, sig = self.sim.app_jwts[0].split(".")
        pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        self.key.public_key().verify(pad(sig), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
        body = json.loads(pad(claims))
        self.assertEqual(body["iss"], "5827242")
        self.assertLessEqual(body["exp"] - body["iat"], 600)
        token_request = [r for r in self.sim.requests if r[1].endswith("/access_tokens")]
        self.assertEqual(len(token_request), 1)

    def test_config_from_env_validates_the_map(self):
        with tempfile.TemporaryDirectory() as d:
            key, mp = Path(d, "k.pem"), Path(d, "map.json")
            key.write_text(self.pem)
            mp.write_text(json.dumps({"u-1": "a/b"}))
            cfg = records.Config.from_env({"CAREER_RECORDS": "app", "CAREER_GITHUB_APP_ID": "1", "CAREER_GITHUB_APP_KEY_FILE": str(key), "CAREER_RECORDS_MAP": str(mp)})
            self.assertEqual(cfg.repo_map, {"u-1": "a/b"})
            mp.write_text(json.dumps({"u-1": "not a repo"}))
            with self.assertRaises(SystemExit):
                records.Config.from_env({"CAREER_RECORDS": "app", "CAREER_GITHUB_APP_ID": "1", "CAREER_GITHUB_APP_KEY_FILE": str(key), "CAREER_RECORDS_MAP": str(mp)})
        with self.assertRaises(SystemExit):
            records.Config.from_env({"CAREER_RECORDS": "app"})
        with self.assertRaises(SystemExit):
            records.Config.from_env({"CAREER_RECORDS": "maybe"})
        self.assertEqual(records.Config.from_env({}).mode, "off")

    def test_app_mode_refuses_to_start_without_the_gateway_secret(self):
        with mock.patch.dict("os.environ", {"CAREER_MCP_TOKEN": ""}, clear=False), self.assertRaises(SystemExit) as e:
            srv.main()
        self.assertIn("CAREER_MCP_TOKEN", str(e.exception))


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class Off(unittest.TestCase):
    def test_off_by_default_and_text_still_works(self):
        with mock.patch.object(srv, "RECORDS", records.Records(records.Config())):
            with self.assertRaisesRegex(ToolError, "not enabled"):
                call(srv.records_read, paths=["profile.md"], ctx=Ctx())
            self.assertFalse(call(srv.records_status, ctx=Ctx())["reachable"])
            with self.assertRaisesRegex(ToolError, "not enabled"):
                call(srv.match, skills_path="skills.md", profile_path="profile.md", requirements="okta:must", ctx=Ctx())


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class OverHttp(unittest.TestCase):
    """The deployed shape: the gateway's headers reach the tool through uvicorn and the shared-secret gate, and the gate takes
    X-Career-Token even when Authorization carries the person's own GitHub token."""

    def test_headers_reach_the_tool_and_the_secret_wins_over_authorization(self):
        import http.client
        import socket
        import threading
        import time
        import uvicorn
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with GitHubSim() as sim:
            sim.add_repo(REPO, {"profile.md": "---\nname: Jordan\n---\n"}, token=TOKEN)
            with mock.patch.object(records, "API", sim.url), \
                 mock.patch.object(srv, "RECORDS", records.Records(records.Config(mode="user_token", token_header="authorization"))), \
                 mock.patch.object(srv, "allowed_hosts", [f"127.0.0.1:{port}"]):
                server = uvicorn.Server(uvicorn.Config(srv.build_app("s3cret"), host="127.0.0.1", port=port, log_level="warning", access_log=False))
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                try:
                    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "records_status", "arguments": {"repo": REPO}}}
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    conn.request("POST", "/mcp", json.dumps(call), {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                                                                   "X-Career-Token": "s3cret", "Authorization": f"Bearer {TOKEN}", "X-Obot-User-Id": "u-9"})
                    r = conn.getresponse()
                    body = r.read()
                    self.assertEqual(r.status, 200, body[:300])
                    out = json.loads(body)["result"]["structuredContent"]
                    self.assertTrue(out["reachable"], out)
                    self.assertEqual(out["user_id"], "u-9")
                    self.assertNotIn(TOKEN, body.decode())
                finally:
                    server.should_exit = True
                    thread.join(5)


if __name__ == "__main__":
    unittest.main()
