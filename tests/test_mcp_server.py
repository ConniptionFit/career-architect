"""Tests for the hosted MCP server (mcp-server/server.py).

Needs Python 3.10+ and the pinned `mcp` package, so it is skipped on older interpreters:
  uv run --python 3.12 --with "mcp==2.2.0" --with pyyaml python -m unittest discover -s tests -v
"""
import asyncio
import http.client
import json
import logging
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
sys.path.insert(0, str(ROOT / "mcp-server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import server as srv
    from mcp.client.client import Client
    HAVE_MCP = True
except ImportError:            # Python < 3.10 or the mcp package is not installed
    HAVE_MCP = False

import career  # noqa: E402
import yaml  # noqa: E402
from drive_sim import drive_render  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "data"
FACTS = career.read_block(FIXTURES / "facts.md")
PROFILE = (FIXTURES / "profile.md").read_text()
TODAY = "2026-09-20"


def fragments() -> dict:
    """The layout kept in Drive: one shared document and one per role, each stored as a Google Doc and read back through the connector."""
    shared = {k: FACTS[k] for k in ("aliases", "credentials", "education") if FACTS.get(k)}
    out = {"shared": yaml.safe_dump(shared, sort_keys=False, allow_unicode=True)}
    for role in FACTS["roles"]:
        out[role["id"]] = yaml.safe_dump({"roles": [role]}, sort_keys=False, allow_unicode=True)
    return {k: drive_render(v) for k, v in out.items()}


def job(name: str, file: str) -> str:
    return drive_render((FIXTURES / "jobs" / name / file).read_text())


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class Tools(unittest.IsolatedAsyncioTestCase):
    async def call(self, name, **args):
        async with Client(srv.server) as c:
            r = await c.call_tool(name, args)
        return r

    async def ok(self, name, **args):
        r = await self.call(name, **args)
        self.assertFalse(r.is_error, r.content[0].text if r.content else r)
        return r.structured_content

    async def fails(self, name, **args):
        r = await self.call(name, **args)
        self.assertTrue(r.is_error, f"{name} should have failed")
        return r.content[0].text

    async def index(self):
        docs = fragments()
        out = await self.ok("build_index", facts_docs=list(docs.values()), today=TODAY)
        self.assertTrue(out["ok"], out)
        return out["skills_md"]

    async def test_tools_are_listed_with_read_only_annotations_and_schemas(self):
        async with Client(srv.server) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        self.assertEqual(set(tools), {"info", "normalize_text", "build_index", "match", "lint_resume", "lint_cover", "resume_patch", "posting"})
        self.assertTrue(all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools.values()))
        self.assertTrue(all(t.description for t in tools.values()))
        self.assertEqual(tools["match"].input_schema["required"], ["skills_md", "profile_md", "requirements"])
        self.assertEqual(tools["lint_resume"].input_schema["required"], ["selection_yaml", "skills_md", "profile_md", "facts_docs"])
        self.assertFalse(tools["info"].annotations.open_world_hint)
        self.assertTrue(tools["posting"].annotations.open_world_hint)                # the one tool that reaches the network

    async def test_info_is_a_health_check(self):
        out = await self.ok("info")
        self.assertEqual((out["name"], out["stateless"]), ("career-architect", True))

    async def test_normalize_text_cleans_drive_output(self):
        text = "aliases:\n  okta: [idp]\n"
        out = await self.ok("normalize_text", text=drive_render(text))
        self.assertEqual(out["text"], text)
        self.assertIn("base64", await self.fails("normalize_text", text="not base64 !!", source="base64"))

    async def test_index_built_from_drive_text_equals_the_one_built_from_the_files(self):
        got = await self.index()
        want = career.render_skills_md(FACTS, career.dt.date.fromisoformat(TODAY))
        self.assertEqual(got, want)

    async def test_build_index_reports_bad_facts_instead_of_an_index(self):
        docs = list(fragments().values())
        out = await self.ok("build_index", facts_docs=docs + [docs[1]], today=TODAY)          # the same role twice
        self.assertFalse(out["ok"])
        self.assertTrue(any("duplicate" in e for e in out["errors"]), out)
        self.assertNotIn("skills_md", out)

    async def test_match_scores_from_the_index_alone(self):
        skills = await self.index()
        out = await self.ok("match", skills_md=drive_render(skills), profile_md=drive_render(PROFILE),
                            requirements="okta:must:3,terraform:must,kubernetes:nice,soc2:nice,sso:must")
        status = {r["requirement"]: r["status"] for r in out["rows"]}
        self.assertEqual(status, {"okta": "met", "terraform": "gap", "kubernetes": "gap", "soc2": "unasked", "sso": "met"})
        self.assertEqual(out["ceiling"], 6)
        self.assertEqual(out["ask"], ["soc2"])
        self.assertIn("nw-06 (unconfirmed)", out["table"])

    async def test_match_needs_a_real_index_and_requirements(self):
        self.assertIn("skills table", await self.fails("match", skills_md="nothing useful", profile_md=PROFILE, requirements="okta:must"))
        skills = await self.index()
        self.assertIn("requirements", await self.fails("match", skills_md=skills, profile_md=PROFILE, requirements=" , "))

    async def test_a_good_resume_selection_passes_with_only_the_cited_fragments(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("lint_resume", selection_yaml=job("good", "selection.yml"), skills_md=drive_render(skills), profile_md=drive_render(PROFILE),
                            facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], today=TODAY)
        self.assertTrue(out["ok"], out["issues"])
        self.assertIn("### IT Systems Engineer, Northwind Logistics (Mar 2021 - Present)", out["resume_text"])
        self.assertNotIn("side-consulting", json.dumps(out))

    async def test_a_bad_selection_reports_the_reasons(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("lint_resume", selection_yaml=job("bad", "selection.yml"), skills_md=skills, profile_md=PROFILE,
                            facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], today=TODAY)
        self.assertFalse(out["ok"])
        messages = " | ".join(i["message"] for i in out["issues"])
        for needle in ("number 2400 is not in the atom", "never_claim hit: 'kubernetes'", "has status unconfirmed", "no atom id",
                       "'Terraform' is not in skills.md", "banned/AI-tell phrase 'Spearheaded'"):
            self.assertIn(needle, messages)

    async def test_an_atom_whose_role_was_not_supplied_says_what_to_pass(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("lint_resume", selection_yaml=job("good", "selection.yml"), skills_md=skills, profile_md=PROFILE,
                            facts_docs=[docs["shared"], docs["northwind-se"]], today=TODAY)          # contoso-helpdesk is cited but missing
        self.assertFalse(out["ok"])
        self.assertTrue(any("pass the role fragment that holds it" in i["message"] for i in out["issues"]), out["issues"])
        self.assertTrue(any("contoso-helpdesk" in i["message"] and "not in the facts you supplied" in i["message"] for i in out["issues"]), out["issues"])

    async def test_a_good_cover_letter_passes_and_comes_back_as_reactive_resume_html(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("lint_cover", cover_yaml=job("good", "cover.yml"), skills_md=skills, profile_md=PROFILE, facts_docs=[docs["shared"], docs["northwind-se"]],
                            posting_text=(FIXTURES / "jobs" / "good" / "jd.md").read_text(), today=TODAY)
        self.assertTrue(out["ok"], out["issues"])
        self.assertEqual(out["name"], "Fabrikam - Systems Engineer - Sam Rivera Cover Letter")
        self.assertIn("<strong>Sam Rivera</strong>", out["recipient_html"])
        self.assertIn("September 20, 2026", out["recipient_html"])
        self.assertTrue(out["content_html"].startswith("<p>Dear Hiring Manager,</p>"))
        self.assertIn("Sam Rivera", out["cover_text"])

    async def test_a_letter_that_invents_a_number_is_caught(self):
        docs, skills = fragments(), await self.index()
        letter = (FIXTURES / "jobs" / "good" / "cover.yml").read_text().replace("across 12 SaaS apps", "across eleven SaaS apps")
        out = await self.ok("lint_cover", cover_yaml=letter, skills_md=skills, profile_md=PROFILE, facts_docs=[docs["shared"], docs["northwind-se"]],
                            posting_text=(FIXTURES / "jobs" / "good" / "jd.md").read_text(), today=TODAY)
        self.assertFalse(out["ok"])
        self.assertTrue(any("number word 'eleven'" in i["message"] for i in out["issues"]))

    async def test_resume_patch_fills_a_duplicate_of_the_master(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("resume_patch", selection_yaml=job("good", "selection.yml"), skills_md=skills, profile_md=PROFILE,
                            facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], today=TODAY)
        self.assertTrue(out["ok"], out.get("issues"))
        ops = {o["path"]: o["value"] for o in out["operations"]}
        self.assertEqual([e["company"] for e in ops["/sections/experience/items"]], ["Northwind Logistics", "Contoso Retail"])
        self.assertEqual(ops["/sections/experience/items"][0]["period"], "Mar 2021 - Present")
        self.assertTrue(ops["/sections/experience/items"][0]["description"].startswith("<ul><li><p>Moved about 1,800 Macs"))
        self.assertEqual(ops["/basics/name"], "Sam Rivera")
        self.assertEqual([c["title"] for c in ops["/sections/certifications/items"]], ["Okta Certified Professional"])
        self.assertEqual(out["resume_name"], "Fabrikam - Systems Engineer - Sam Rivera Resume")
        self.assertEqual(out["resume_name_full"], out["resume_name"])
        self.assertEqual(out["resume_slug"], "fabrikam-systems-engineer")
        self.assertTrue(all(isinstance(o["op"], str) and o["path"].startswith("/") for o in out["operations"]))

    def test_long_names_are_fitted_to_the_64_character_mcp_limit(self):
        long_role = "Senior IT Systems Administrator Automation & AI"
        name = srv.fit_name("Initech", long_role, "Jordan Lee", "Resume")
        self.assertLessEqual(len(name), 64)
        self.assertTrue(name.startswith("Initech - Senior IT Systems"), name)
        self.assertTrue(name.endswith(" - Jordan Lee"), name)                  # company and person survive, the role gives way
        self.assertEqual(srv.fit_name("Fabrikam", "Systems Engineer", "Sam Rivera", "Resume"), "Fabrikam - Systems Engineer - Sam Rivera Resume")
        self.assertLessEqual(len(srv.fit_name("A" * 60, "Role", "B" * 30, "Resume")), 64)

    async def test_resume_patch_uses_the_masters_own_item_shape_when_given(self):
        docs, skills = fragments(), await self.index()
        master = {"data": {"summary": "plain text summary", "sections": {
            "experience": {"items": [{"id": "x", "hidden": False, "company": "", "position": "", "extraField": "keep me", "website": {"url": "u"}}]},
            "skills": {"items": [{"id": "y", "hidden": False, "name": "", "keywords": []}]}}}}
        out = await self.ok("resume_patch", selection_yaml=job("good", "selection.yml"), skills_md=skills, profile_md=PROFILE, master_json=json.dumps(master),
                            facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], today=TODAY)
        ops = {o["path"]: o["value"] for o in out["operations"]}
        self.assertEqual(ops["/sections/experience/items"][0]["extraField"], "keep me")
        self.assertIn("/summary", ops)                                            # a string summary is patched at /summary, not /summary/content

    async def test_resume_patch_refuses_a_selection_with_errors(self):
        docs, skills = fragments(), await self.index()
        out = await self.ok("resume_patch", selection_yaml=job("bad", "selection.yml"), skills_md=skills, profile_md=PROFILE,
                            facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], today=TODAY)
        self.assertFalse(out["ok"])
        self.assertEqual(out["operations"], [])
        self.assertGreater(out["errors"], 3)
        self.assertIn("master_json", await self.fails("resume_patch", selection_yaml=job("good", "selection.yml"), skills_md=skills, profile_md=PROFILE,
                                                      facts_docs=[docs["shared"], docs["northwind-se"], docs["contoso-helpdesk"]], master_json="{not json", today=TODAY))

    async def test_unsafe_or_oversized_input_is_refused_with_a_reason(self):
        skills = await self.index()
        bomb = "a: &a [1, 2, 3]\nb: [*a, *a, *a]\n"
        self.assertIn("aliases", await self.fails("build_index", facts_docs=[bomb]))
        self.assertIn("aliases", await self.fails("lint_resume", selection_yaml=bomb, skills_md=skills, profile_md=PROFILE, facts_docs=["roles: []"]))
        self.assertIn("characters", await self.fails("lint_resume", selection_yaml="x: " + "y" * 300_000, skills_md=skills, profile_md=PROFILE, facts_docs=["roles: []"]))
        self.assertIn("at most", await self.fails("build_index", facts_docs=["roles: []"] * 41))
        self.assertIn("YYYY-MM-DD", await self.fails("build_index", facts_docs=["roles: []"], today="tomorrow"))
        self.assertIn("mapping", await self.fails("lint_resume", selection_yaml="- a list\n", skills_md=skills, profile_md=PROFILE, facts_docs=["roles: []"]))

    async def test_a_crash_leaks_no_document_text_to_the_client_or_the_log(self):
        skills = await self.index()
        with mock.patch.object(career, "lint", side_effect=RuntimeError("secret work history: Acme, 1800 devices")):
            with self.assertLogs("career-mcp", "ERROR") as logged:
                r = await self.call("lint_resume", selection_yaml="summary: x\n", skills_md=skills, profile_md=PROFILE, facts_docs=["roles: []"])
        self.assertTrue(r.is_error)
        self.assertIn("internal error in lint_resume (RuntimeError)", r.content[0].text)
        everything = r.content[0].text + "\n".join(logged.output)
        for secret in ("secret work history", "Acme", "1800"):
            self.assertNotIn(secret, everything)
        self.assertIn("RuntimeError", "\n".join(logged.output))                 # the type and the frames are logged, so it can be debugged


LEVER = {"text": "Systems Engineer", "categories": {"location": "Remote (US)"}, "descriptionPlain": "You will own endpoint management. Reports to the CTO.",
         "lists": [], "additionalPlain": "", "salaryRange": {"min": 130000, "max": 160000, "currency": "USD", "interval": "per-year-salary"}, "createdAt": 1758326400000}


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class Posting(unittest.IsolatedAsyncioTestCase):
    async def test_a_lever_posting_is_read_through_the_allowlisted_fetch(self):
        seen = []

        def fake(url):
            seen.append(url)
            return LEVER

        with mock.patch.object(srv, "_fetch_json", fake):
            async with Client(srv.server) as c:
                r = await c.call_tool("posting", {"url": "https://jobs.lever.co/acme/1234-abcd"})
        self.assertFalse(r.is_error, r.content[0].text)
        out = r.structured_content
        self.assertEqual((out["ats"], out["title"], out["reports_to"]), ("lever", "Systems Engineer", "CTO"))
        self.assertIn("structured: 130000-160000 USD per-year-salary", out["pay"])
        self.assertEqual(seen, ["https://api.lever.co/v0/postings/acme/1234-abcd"])

    async def test_other_sites_are_not_supported_and_reach_nothing(self):
        with mock.patch.object(srv, "_fetch_json", side_effect=AssertionError("must not fetch")):
            async with Client(srv.server) as c:
                r = await c.call_tool("posting", {"url": "https://example.com/careers/1"})
                self.assertTrue(r.is_error)
                self.assertIn("unsupported posting URL", r.content[0].text)
                r = await c.call_tool("posting", {"url": "file:///etc/passwd"})
                self.assertTrue(r.is_error)

    def test_the_fetcher_only_talks_to_the_three_ats_api_hosts_over_https(self):
        if not HAVE_MCP:
            self.skipTest("needs the mcp package")
        for url in ("https://evil.example/x", "http://api.lever.co/v0/postings/a/b", "https://api.lever.co/../etc/passwd",
                    "https://api.lever.co.evil.example/v0/postings/a/b", "https://api.lever.co/v0/postings/a b/c", "https://169.254.169.254/latest/meta-data"):
            with self.assertRaises(Exception, msg=url):
                srv._fetch_json(url)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class Http(unittest.TestCase):
    """The deployed shape: uvicorn, the shared-secret gate, the Host allowlist and the body-size limit."""

    @classmethod
    def setUpClass(cls):
        import uvicorn
        cls.port = free_port()
        cls.hosts = mock.patch.object(srv, "allowed_hosts", [f"127.0.0.1:{cls.port}"])
        cls.hosts.start()
        cls.server = uvicorn.Server(uvicorn.Config(srv.build_app("s3cret"), host="127.0.0.1", port=cls.port, log_level="warning", access_log=False))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        assert cls.server.started, "server did not start"

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.hosts.stop()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **(headers or {})}
        if host:
            h["Host"] = host
        conn.request(method, path, body=json.dumps(body) if isinstance(body, dict) else body, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data

    RPC = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}

    def test_health_check_needs_no_secret(self):
        status, data = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["status"], "ok")

    def test_every_other_path_needs_the_secret(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"X-Career-Token": "wrong"}, {"Authorization": "Basic s3cret"}, {"Authorization": "Bearer "}):
            status, data = self.request("POST", "/mcp", self.RPC, headers)
            self.assertEqual(status, 401, headers)
            self.assertEqual(json.loads(data), {"error": "unauthorized"})
        self.assertEqual(self.request("GET", "/anything-else")[0], 401)

    def test_the_secret_works_as_a_bearer_token_or_a_custom_header(self):
        for headers in ({"Authorization": "Bearer s3cret"}, {"X-Career-Token": "s3cret"}):
            status, data = self.request("POST", "/mcp", self.RPC, headers)
            self.assertEqual(status, 200, data[:200])
            names = {t["name"] for t in json.loads(data)["result"]["tools"]}
            self.assertIn("lint_resume", names)

    def test_a_tool_call_works_end_to_end_over_http(self):
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "info", "arguments": {}}}
        status, data = self.request("POST", "/mcp", call, {"X-Career-Token": "s3cret"})
        self.assertEqual(status, 200, data[:300])
        self.assertEqual(json.loads(data)["result"]["structuredContent"]["name"], "career-architect")

    def test_an_unexpected_host_header_is_refused(self):
        status, _ = self.request("POST", "/mcp", self.RPC, {"X-Career-Token": "s3cret"}, host="evil.example")
        self.assertIn(status, (400, 403, 421))

    def test_an_oversized_body_is_refused(self):
        status, _ = self.request("POST", "/mcp", "x" * (srv.MAX_BODY + 1024), {"X-Career-Token": "s3cret"})
        self.assertIn(status, (400, 413))


@unittest.skipUnless(HAVE_MCP, "needs Python 3.10+ and the mcp package")
class Unsecured(unittest.TestCase):
    def test_without_a_token_the_app_is_not_wrapped(self):
        self.assertNotIsInstance(srv.build_app(None), srv.TokenGate)
        self.assertIsInstance(srv.build_app("x"), srv.TokenGate)

    def test_logging_defaults_to_warning_so_tool_errors_are_not_logged(self):
        import os
        import subprocess
        here = Path(srv.__file__).resolve().parent
        code = "import logging, server; print(logging.getLogger().getEffectiveLevel())"
        for env_level, expect in (("", logging.WARNING), ("DEBUG", logging.DEBUG), ("nonsense", logging.WARNING)):
            env = {k: v for k, v in os.environ.items() if k != "LOG_LEVEL"}
            env["PYTHONPATH"] = os.pathsep.join(sys.path)
            if env_level:
                env["LOG_LEVEL"] = env_level
            out = subprocess.run([sys.executable, "-c", code], cwd=here, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(int(out.stdout.strip().splitlines()[-1]), expect, f"LOG_LEVEL={env_level!r}")

    def test_main_refuses_to_start_without_a_token_unless_explicitly_allowed(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"CAREER_MCP_TOKEN": "", "CAREER_MCP_ALLOW_UNSECURED": ""}), mock.patch("uvicorn.run") as run:
            with self.assertRaises(SystemExit) as cm:
                srv.main()
            self.assertIn("CAREER_MCP_TOKEN is not set", str(cm.exception))
            run.assert_not_called()
        with mock.patch.dict(os.environ, {"CAREER_MCP_TOKEN": "", "CAREER_MCP_ALLOW_UNSECURED": "1"}), mock.patch("uvicorn.run") as run:
            srv.main()
            run.assert_called_once()
        with mock.patch.dict(os.environ, {"CAREER_MCP_TOKEN": "s3cret"}), mock.patch("uvicorn.run") as run:
            srv.main()
            self.assertIsInstance(run.call_args[0][0], srv.TokenGate)


if __name__ == "__main__":
    unittest.main()
