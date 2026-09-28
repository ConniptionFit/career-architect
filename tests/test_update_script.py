"""deploy/update.sh is the one command that puts a version of the server on the Docker host. It runs there, not in CI, so these
tests only cover what can be checked anywhere: it parses, and it refuses to act outside a compose directory or without a token file."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "update.sh"


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class UpdateScript(unittest.TestCase):
    def run_script(self, cwd, *args, env=None):
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, env=env)

    def test_it_parses(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode, 0)

    def test_it_refuses_outside_a_compose_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_script(tmp)
            self.assertEqual(done.returncode, 2)
            self.assertIn("compose directory", done.stderr)

    def test_it_refuses_without_a_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docker-compose.yaml").write_text("")
            (Path(tmp) / "src" / ".git").mkdir(parents=True)
            done = self.run_script(tmp, env={"PATH": "/usr/bin:/bin", "CAREER_ENV_FILE": str(Path(tmp) / "missing")})
            self.assertEqual(done.returncode, 2)
            self.assertIn("token file", done.stderr)


if __name__ == "__main__":
    unittest.main()
