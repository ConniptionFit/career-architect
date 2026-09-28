"""The connect plugin template (connect/): a launcher skill and the Jobs connector in one installable folder.

The launcher must stay a launcher (it carries no instructions that could go stale), must trigger on the same requests as the real
skill, and the generator must refuse a wrong connector address. No SKILL.md may live outside jobs/, or Obot's skill sync would
discover a second skill called `jobs`."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "jobs" / "scripts"))
import career  # noqa: E402

CONNECT = ROOT / "connect"
LAUNCHER = CONNECT / "skills" / "jobs" / "SKILL.md.template"
HAVE_BASH = shutil.which("bash") is not None


def front(path: Path) -> dict:
    return career.parse_front(path.read_text())


class Template(unittest.TestCase):
    def test_manifests_parse_and_name_the_plugin(self):
        plugin = json.loads((CONNECT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((CONNECT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(plugin["name"], "jobs")
        self.assertNotIn("version", plugin, "leave version out so every commit is an update")
        self.assertEqual([p["name"] for p in market["plugins"]], ["jobs"])
        self.assertEqual(market["plugins"][0]["source"], "./")

    def test_the_connector_entry_is_a_placeholder_http_server_without_secrets(self):
        server = json.loads((CONNECT / ".mcp.json").read_text())["mcpServers"]["jobs"]
        self.assertEqual(server["type"], "http")
        self.assertIn("<vmcp id>", server["url"])
        self.assertEqual(set(server), {"type", "url"}, "no headers or keys: everyone who installs the plugin receives this file")

    def test_the_launcher_triggers_on_the_same_requests_as_the_skill(self):
        self.assertEqual(front(LAUNCHER)["description"], front(ROOT / "jobs" / "SKILL.md")["description"])
        self.assertEqual(front(LAUNCHER)["name"], "jobs")

    def test_the_launcher_only_launches(self):
        body = LAUNCHER.read_text().split("\n---\n", 1)[1]
        self.assertIn("career_architect__guide", body)
        self.assertIn("topic", body)
        self.assertLess(len(body.splitlines()), 20, "instructions belong in jobs/ and are served by the guide tool")
        self.assertNotRegex(body, r"(?i)\bnever_claim\b|\bpwrs\b|google_docs__|reactive_resume__", "nothing that would go stale, nothing deployment specific")

    def test_no_skill_file_exists_outside_the_skill_folder(self):
        found = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("SKILL.md") if ".git" not in p.parts and "jobs" != p.relative_to(ROOT).parts[0]]
        self.assertEqual(found, [])


@unittest.skipUnless(HAVE_BASH, "needs bash")
class Generator(unittest.TestCase):
    def run_make(self, url, target):
        return subprocess.run(["bash", str(CONNECT / "make.sh"), url, str(target)], capture_output=True, text=True)

    def test_it_writes_a_complete_plugin_with_the_address_filled_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plugin"
            done = self.run_make("https://obot.example.com/mcp-connect/vmcpABC123", target)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads((target / ".mcp.json").read_text())["mcpServers"]["jobs"]["url"], "https://obot.example.com/mcp-connect/vmcpABC123")
            skill = target / "skills" / "jobs" / "SKILL.md"
            self.assertEqual(front(skill)["name"], "jobs")
            for name in (".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "README.md", "LICENSE"):
                self.assertTrue((target / name).exists(), name)
            self.assertFalse((target / "skills" / "jobs" / "SKILL.md.template").exists())
            readme = (target / "README.md").read_text()
            self.assertNotIn("For the administrator", readme, "the people who install it are not shown the maintainer's notes")
            self.assertNotIn("template-only", readme)

    def test_it_refuses_a_wrong_address_and_a_used_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("http://obot.example.com/mcp-connect/x", "https://obot.example.com/other/x", "https://obot.example.com/mcp-connect/<vmcp id>",
                        'https://obot.example.com/mcp-connect/x"y'):
                done = self.run_make(bad, Path(tmp) / "new")
                self.assertNotEqual(done.returncode, 0, bad)
                self.assertFalse((Path(tmp) / "new").exists(), bad)
            used = Path(tmp) / "used"
            used.mkdir()
            (used / "file").write_text("x")
            self.assertNotEqual(self.run_make("https://obot.example.com/mcp-connect/ok", used).returncode, 0)


if __name__ == "__main__":
    unittest.main()
