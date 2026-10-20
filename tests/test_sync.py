"""Git synchronization safety tests using local temporary repositories only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
ORIGIN = "https://github.com/Tiachi/video-sft-builder.git"


class SyncTests(unittest.TestCase):
    def setUp(self):
        temp_base = PROJECT / "x_temp" / "sync_tests"
        temp_base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="video-sft-sync-test-", dir=temp_base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.writer = self.root / "writer"
        self.receiver = self.root / "receiver"
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        self.bash = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt"
                     else shutil.which("bash"))
        if not self.bash or not Path(self.bash).exists():
            self.skipTest("Bash required for sync helper tests")
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.writer.mkdir()
        self.git(self.writer, "init", "--initial-branch=main")
        self.identity(self.writer)
        script_dir = self.writer / "scripts" / "git"
        script_dir.mkdir(parents=True)
        shutil.copyfile(PROJECT / "scripts/git/sync_pull_ff_only.sh",
                        script_dir / "sync_pull_ff_only.sh")
        self.git(self.writer, "add", "scripts/git/sync_pull_ff_only.sh")
        self.git(self.writer, "commit", "-m", "initial helper")
        self.git(self.writer, "remote", "add", "origin", str(self.remote))
        self.git(self.writer, "push", "origin", "main")
        self.git(self.root, "clone", "-c", "core.autocrlf=false", str(self.remote), str(self.receiver))
        self.identity(self.receiver)
        self.git(self.receiver, "remote", "set-url", "origin", ORIGIN)
        # Preserve canonical identity but route test network operations to local disk.
        self.git(self.receiver, "config", f"url.{self.remote.as_uri()}.insteadOf", ORIGIN)
        self.git(self.receiver, "config", "protocol.file.allow", "always")

    def git(self, cwd, *args):
        result = subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                                text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout.strip()

    def identity(self, repo):
        self.git(repo, "config", "user.name", "Synthetic Test")
        self.git(repo, "config", "user.email", "test@example.invalid")
        self.git(repo, "config", "commit.gpgsign", "false")
        self.git(repo, "config", "core.autocrlf", "false")

    def sync(self, source=False):
        args = ([self.bash, "-c", "source scripts/git/sync_pull_ff_only.sh; code=$?; echo parent_survived; exit $code"]
                if source else [self.bash, "scripts/git/sync_pull_ff_only.sh"])
        return subprocess.run(args, cwd=self.receiver, env=self.env,
                              text=True, capture_output=True, timeout=45)

    def head(self):
        return self.git(self.receiver, "rev-parse", "HEAD")

    def test_fast_forward_and_rerun(self):
        (self.writer / "new.txt").write_text("new revision\n", encoding="utf-8")
        self.git(self.writer, "add", "new.txt")
        self.git(self.writer, "commit", "-m", "next")
        self.git(self.writer, "push", "origin", "main")
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS:", result.stdout)
        self.assertEqual(self.head(), self.git(self.writer, "rev-parse", "HEAD"))
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dirty_preserved(self):
        original = self.head()
        path = self.receiver / "user.txt"
        path.write_text("preserve this\n", encoding="utf-8")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dirty", result.stderr)
        self.assertEqual(self.head(), original)
        self.assertEqual(path.read_text(encoding="utf-8"), "preserve this\n")

    def test_wrong_origin_rejected(self):
        self.git(self.receiver, "remote", "set-url", "origin", "https://github.com/Tiachi/Dataset.git")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin", result.stderr)

    def test_local_ahead_preserved(self):
        path = self.receiver / "local.txt"
        path.write_text("local work\n", encoding="utf-8")
        self.git(self.receiver, "add", "local.txt")
        self.git(self.receiver, "commit", "-m", "local work")
        original = self.head()
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ahead or diverged", result.stderr)
        self.assertEqual(self.head(), original)

    def test_non_main_rejected(self):
        self.git(self.receiver, "switch", "-c", "codex/test")
        result = self.sync()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be on main", result.stderr)

    def test_sourcing_does_not_exit_parent(self):
        result = self.sync(source=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("parent_survived", result.stdout)
        self.assertIn("do not source", result.stderr)


class RecipeTests(unittest.TestCase):
    def test_user_contract_and_pending_values(self):
        cfg = json.loads((PROJECT / "configs/project.example.json").read_text(encoding="utf-8"))
        recipe = cfg["dataset_recipe"]
        self.assertEqual(recipe["language_weights"], {"zh": 3, "en": 7})
        self.assertEqual(recipe["question_type_weights"], {"oe": 7, "mcq": 3})
        self.assertEqual(recipe["mcq_option_count_weights"], {"3": 1, "4": 7, "6": 2})
        self.assertIsNone(recipe["pipeline_weights"])
        self.assertFalse(cfg["pipeline"]["a4_enabled"])
        self.assertFalse(cfg["pipeline"]["a10_enabled"])
        self.assertEqual(cfg["pipeline"]["audit_failure_policy"], "reject")
        self.assertIsNone(cfg["input"]["include_subdirectories"])
        self.assertIsNone(cfg["teacher_api"]["model"])
        self.assertIsNone(cfg["cot"]["method"])


if __name__ == "__main__":
    unittest.main()
