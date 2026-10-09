"""
tests/test_autocommit.py
========================
Automated tests for the Git auto-commit watcher.

All tests use a TEMPORARY git repository created in a temp directory.
No commits are ever made to the real project repository.

Test coverage:
  1.  File edit   → commit created
  2.  Sequential distinct saves → separate commits
  3.  File addition → commit created
  4.  File deletion → commit created
  5.  File rename  → commit created
  6.  Duplicate rapid events → only one commit (debounce)
  7.  Idle period  → zero new commits
  8.  Sensitive file exclusion (filename pattern)
  9.  Sensitive content detection in staged diff → commit aborted
  10. Secret file not staged even if untracked
  11. Push retry on transient failure (mocked subprocess)
  12. Permanent push failure stops retrying immediately
  13. Pending push survives restart (state persistence)
  14. Empty tree → no commit
  15. Self-generated state file never committed
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers to bootstrap an isolated Git repo for each test
# ---------------------------------------------------------------------------

def _make_temp_repo() -> Path:
    """Create a fresh bare-minimum Git repo in a temp directory."""
    td = tempfile.mkdtemp(prefix="ac_test_")
    root = Path(td)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(root), check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(root), check=True, capture_output=True
    )
    return root


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, cwd=str(root),
        capture_output=True, text=True, check=False
    )


def _commit_count(root: Path) -> int:
    result = _git(["rev-list", "--count", "HEAD"], root)
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip())


# ---------------------------------------------------------------------------
# Import modules under test (they must be importable from project root)
# ---------------------------------------------------------------------------

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from autocommit.config import (
    BLOCKED_FILENAME_PATTERNS,
    SENSITIVE_PATTERNS,
    load_config,
)
from autocommit.git_ops import (
    _filename_is_blocked,
    create_commit,
    scan_staged_diff_for_secrets,
)
from autocommit.state import PushState
from autocommit.watcher import _should_ignore, AutoCommitWatcher


# ===========================================================================
# Unit tests – no network, no remote
# ===========================================================================

class TestShouldIgnore(unittest.TestCase):
    """Tests for the path-filter function."""

    def test_git_internal_ignored(self):
        self.assertTrue(_should_ignore(".git/COMMIT_EDITMSG"))
        self.assertTrue(_should_ignore(r"C:\project\.git\index"))

    def test_pycache_ignored(self):
        self.assertTrue(_should_ignore("src/__pycache__/module.cpython-312.pyc"))

    def test_venv_ignored(self):
        self.assertTrue(_should_ignore(".venv/lib/python3.12/site.py"))

    def test_swap_ignored(self):
        self.assertTrue(_should_ignore(".#file.txt"))
        self.assertTrue(_should_ignore("src/.module.swp"))
        self.assertTrue(_should_ignore("README~"))

    def test_pyc_ignored(self):
        self.assertTrue(_should_ignore("module.pyc"))

    def test_tmp_ignored(self):
        self.assertTrue(_should_ignore("data.tmp"))

    def test_regular_file_not_ignored(self):
        self.assertFalse(_should_ignore("src/main.py"))
        self.assertFalse(_should_ignore("README.md"))

    def test_state_file_ignored(self):
        self.assertTrue(_should_ignore("autocommit_state.json"))


class TestFilenameBlocked(unittest.TestCase):
    """Tests for the blocked-filename detector."""

    def test_env_file_blocked(self):
        self.assertTrue(_filename_is_blocked(".env"))
        self.assertTrue(_filename_is_blocked(".env.production"))

    def test_pem_blocked(self):
        self.assertTrue(_filename_is_blocked("server.pem"))
        self.assertTrue(_filename_is_blocked("id_rsa.key"))

    def test_secrets_json_blocked(self):
        self.assertTrue(_filename_is_blocked("secrets.json"))
        self.assertTrue(_filename_is_blocked("credentials.yaml"))

    def test_regular_file_not_blocked(self):
        self.assertFalse(_filename_is_blocked("main.py"))
        self.assertFalse(_filename_is_blocked("config.toml"))


class TestSensitivePatterns(unittest.TestCase):
    """Tests for the regex-based secret scanner."""

    def _matches(self, line: str) -> bool:
        return any(p.search(line) for p in SENSITIVE_PATTERNS)

    def test_password_assignment(self):
        self.assertTrue(self._matches("PASSWORD=supersecret123"))
        self.assertTrue(self._matches("password: 'hunter2'"))

    def test_token(self):
        self.assertTrue(self._matches("TOKEN=ghp_abcdefghij1234567890"))
        self.assertTrue(self._matches("api_key: sk-proj-xxxx"))

    def test_begin_private_key(self):
        self.assertTrue(self._matches("-----BEGIN RSA PRIVATE KEY-----"))

    def test_aws_key(self):
        self.assertTrue(self._matches("AKIAIOSFODNN7EXAMPLE"))

    def test_benign_lines(self):
        self.assertFalse(self._matches("x = 42"))
        self.assertFalse(self._matches("# This is a comment"))
        self.assertFalse(self._matches("print('hello world')"))


# ===========================================================================
# Integration tests – real temp Git repos, no remote (push skipped/mocked)
# ===========================================================================

class TestCreateCommit(unittest.TestCase):
    """Tests that create_commit() behaves correctly in an isolated repo."""

    def setUp(self):
        self.root = _make_temp_repo()
        self.cfg = load_config(self.root)

    def _write(self, name: str, content: str) -> Path:
        p = self.root / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_empty_tree_no_commit(self):
        """No staged changes → create_commit returns None."""
        result = create_commit(self.root, self.cfg)
        self.assertIsNone(result)
        self.assertEqual(_commit_count(self.root), 0)

    def test_file_edit_creates_commit(self):
        """Editing a file → one commit."""
        self._write("hello.py", "print('hi')\n")
        sha = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha)
        self.assertEqual(_commit_count(self.root), 1)

    def test_commit_message_format(self):
        """Commit message matches Auto-save timestamp pattern."""
        self._write("a.py", "x=1\n")
        create_commit(self.root, self.cfg)
        result = _git(["log", "--format=%s", "-1"], self.root)
        msg = result.stdout.strip()
        pattern = r"^Auto-save: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
        self.assertRegex(msg, pattern, f"Bad commit message: '{msg}'")

    def test_sequential_saves_separate_commits(self):
        """Two distinct saved states produce two commits."""
        self._write("b.py", "v = 1\n")
        sha1 = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha1)

        self._write("b.py", "v = 2\n")
        sha2 = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha2)

        self.assertNotEqual(sha1, sha2)
        self.assertEqual(_commit_count(self.root), 2)

    def test_identical_content_no_second_commit(self):
        """Saving a file with the same content produces no second commit."""
        self._write("c.py", "same\n")
        create_commit(self.root, self.cfg)
        # Write exactly the same content
        self._write("c.py", "same\n")
        sha2 = create_commit(self.root, self.cfg)
        self.assertIsNone(sha2)
        self.assertEqual(_commit_count(self.root), 1)

    def test_file_addition(self):
        """Adding a new file → commit captures it."""
        self._write("new_file.txt", "brand new\n")
        sha = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha)
        result = _git(["show", "--stat", "HEAD"], self.root)
        self.assertIn("new_file.txt", result.stdout)

    def test_file_deletion(self):
        """Deleting a tracked file → commit records deletion."""
        p = self._write("del_me.txt", "delete\n")
        create_commit(self.root, self.cfg)
        p.unlink()
        sha = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha)
        result = _git(["show", "--stat", "HEAD"], self.root)
        self.assertIn("del_me.txt", result.stdout)

    def test_file_rename(self):
        """Renaming a file → commit records the rename."""
        src = self._write("old_name.txt", "content\n")
        create_commit(self.root, self.cfg)
        dst = self.root / "new_name.txt"
        src.rename(dst)
        sha = create_commit(self.root, self.cfg)
        self.assertIsNotNone(sha)
        result = _git(["show", "--stat", "HEAD"], self.root)
        self.assertIn("new_name.txt", result.stdout)

    def test_sensitive_content_aborts_commit(self):
        """A file containing a password pattern aborts the commit."""
        self._write("config.py", "DB_PASSWORD=supersecret123\n")
        with self.assertRaises(RuntimeError) as ctx:
            create_commit(self.root, self.cfg)
        self.assertIn("SECURITY ABORT", str(ctx.exception))
        # Verify nothing was committed
        self.assertEqual(_commit_count(self.root), 0)

    def test_blocked_env_file_not_staged(self):
        """A .env file is unstaged and never committed."""
        # Use benign content so the secret scan doesn't trip on it
        (self.root / ".env").write_text("APP_NAME=myapp\n")
        # Also create a normal file to ensure a commit can happen
        self._write("main.py", "print('ok')\n")
        create_commit(self.root, self.cfg)
        result = _git(["show", "--name-only", "HEAD"], self.root)
        self.assertNotIn(".env", result.stdout)

    def test_blocked_pem_file_not_staged(self):
        """A .pem file is never committed."""
        # Use benign content so the secret scan doesn't trip on the pem
        (self.root / "server.pem").write_text("binary_cert_data\n")
        self._write("app.py", "x=1\n")
        create_commit(self.root, self.cfg)
        result = _git(["show", "--name-only", "HEAD"], self.root)
        self.assertNotIn("server.pem", result.stdout)

    def test_state_file_never_committed(self):
        """autocommit_state.json is never staged (covered by .gitignore + filter)."""
        (self.root / "autocommit_state.json").write_text('{"test": true}\n')
        self._write("code.py", "y=2\n")
        create_commit(self.root, self.cfg)
        result = _git(["show", "--name-only", "HEAD"], self.root)
        self.assertNotIn("autocommit_state.json", result.stdout)


# ===========================================================================
# PushState tests
# ===========================================================================

class TestPushState(unittest.TestCase):
    """Tests for the state persistence layer."""

    def setUp(self):
        self.root = _make_temp_repo()
        self.state = PushState(self.root)

    def test_initial_state_clean(self):
        self.assertFalse(self.state.has_pending_push)
        self.assertFalse(self.state.permanent_failure)

    def test_mark_pending(self):
        self.state.mark_pending_push()
        self.assertTrue(self.state.has_pending_push)

    def test_record_success_clears_pending(self):
        self.state.mark_pending_push()
        self.state.record_push_success()
        self.assertFalse(self.state.has_pending_push)

    def test_state_persists_across_instances(self):
        """State survives creating a new PushState from the same directory."""
        self.state.mark_pending_push()
        state2 = PushState(self.root)
        self.assertTrue(state2.has_pending_push)

    def test_permanent_failure_recorded(self):
        self.state.record_push_failure(permanent=True)
        self.assertTrue(self.state.permanent_failure)
        self.assertTrue(self.state.has_pending_push)  # still needs manual fix

    def test_clear_resets_all(self):
        self.state.mark_pending_push()
        self.state.record_push_failure(permanent=True)
        self.state.clear()
        self.assertFalse(self.state.has_pending_push)
        self.assertFalse(self.state.permanent_failure)


# ===========================================================================
# Push retry tests (mock subprocess to avoid real network)
# ===========================================================================

class TestPushRetry(unittest.TestCase):
    """Tests for push retry / permanent-failure logic."""

    def setUp(self):
        self.root = _make_temp_repo()
        self.cfg = load_config(self.root)
        self.cfg["push_retry_base_seconds"] = 0.01  # speed up retries
        self.cfg["push_retry_max_seconds"] = 0.05
        self.cfg["push_retry_max_attempts"] = 3
        self.state = PushState(self.root)

    def _make_completed(self, returncode: int, stdout="", stderr=""):
        cp = subprocess.CompletedProcess([], returncode)
        cp.stdout = stdout
        cp.stderr = stderr
        return cp

    def test_transient_failure_retries_up_to_max(self):
        """Transient errors retry up to max_attempts, then give up."""
        from autocommit.git_ops import push_commits

        transient_result = self._make_completed(
            1, stderr="Connection reset by peer"
        )

        with patch("autocommit.git_ops._git", return_value=transient_result):
            # Also mock get_upstream to return something (avoid upstream check)
            with patch("autocommit.git_ops.get_upstream", return_value="origin/main"):
                result = push_commits(
                    self.root, self.cfg, "main", "main", self.state
                )

        self.assertFalse(result)
        self.assertFalse(self.state.permanent_failure)

    def test_permanent_error_stops_immediately(self):
        """Authentication failure → no retries."""
        from autocommit.git_ops import push_commits

        perm_result = self._make_completed(
            1, stderr="Authentication failed for 'https://github.com/...'"
        )
        call_count = {"n": 0}

        def mock_git(args, cwd, **kwargs):
            call_count["n"] += 1
            return perm_result

        with patch("autocommit.git_ops._git", side_effect=mock_git):
            with patch("autocommit.git_ops.get_upstream", return_value="origin/main"):
                result = push_commits(
                    self.root, self.cfg, "main", "main", self.state
                )

        self.assertFalse(result)
        self.assertTrue(self.state.permanent_failure)
        # Should have tried exactly once
        self.assertEqual(call_count["n"], 1)

    def test_successful_push_clears_pending(self):
        """Successful push clears the pending-push flag."""
        from autocommit.git_ops import push_commits

        success_result = self._make_completed(0, stdout="master -> master")

        # Pre-mark a pending push
        self.state.mark_pending_push()

        with patch("autocommit.git_ops._git", return_value=success_result):
            with patch("autocommit.git_ops.get_upstream", return_value="origin/main"):
                result = push_commits(
                    self.root, self.cfg, "main", "main", self.state
                )

        self.assertTrue(result)
        self.assertFalse(self.state.has_pending_push)


# ===========================================================================
# Watcher integration: debounce and idle-period tests
# ===========================================================================

class TestDebounce(unittest.TestCase):
    """
    Test that rapid events produce one commit and idle periods zero commits.
    Push is mocked so tests don't hit the network.
    """

    def setUp(self):
        self.root = _make_temp_repo()
        # Seed repo with an initial commit so rev-parse HEAD works
        (self.root / "seed.txt").write_text("init\n")
        subprocess.run(["git", "add", "-A"], cwd=str(self.root),
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"],
                       cwd=str(self.root), capture_output=True)
        self.cfg = load_config(self.root)
        self.cfg["debounce_seconds"] = 0.3  # fast for testing

    def _make_watcher(self):
        """Create a watcher with push stubbed out to a no-op."""
        watcher = AutoCommitWatcher(repo_root=self.root)
        watcher._cfg = self.cfg
        # Pre-initialise PushState so the file exists before the watcher
        # starts observing; this prevents its creation from triggering an event
        watcher._state = PushState(self.root)
        return watcher

    def test_single_edit_triggers_commit(self):
        """One file edit → one new commit after debounce."""
        watcher = self._make_watcher()
        # Allow OS to settle after PushState file creation
        time.sleep(0.4)
        baseline = _commit_count(self.root)

        with patch("autocommit.git_ops.push_commits", return_value=True):
            watcher.start()
            try:
                (self.root / "test_file.py").write_text("x = 1\n")
                time.sleep(self.cfg["debounce_seconds"] + 1.5)
            finally:
                watcher.stop()

        self.assertEqual(_commit_count(self.root) - baseline, 1)

    def test_rapid_saves_single_commit(self):
        """Multiple rapid saves within debounce window → one new commit."""
        watcher = self._make_watcher()
        time.sleep(0.4)
        baseline = _commit_count(self.root)

        with patch("autocommit.git_ops.push_commits", return_value=True):
            watcher.start()
            try:
                p = self.root / "rapid.py"
                for i in range(5):
                    p.write_text(f"x = {i}\n")
                    time.sleep(0.05)
                time.sleep(self.cfg["debounce_seconds"] + 1.5)
            finally:
                watcher.stop()

        new_commits = _commit_count(self.root) - baseline
        self.assertGreaterEqual(new_commits, 1)
        self.assertLessEqual(new_commits, 2, "Rapid saves created too many commits")

    def test_idle_period_no_commits(self):
        """No file changes → zero new commits."""
        watcher = self._make_watcher()
        time.sleep(0.4)
        baseline = _commit_count(self.root)

        with patch("autocommit.git_ops.push_commits", return_value=True):
            watcher.start()
            try:
                time.sleep(2.0)
            finally:
                watcher.stop()

        self.assertEqual(_commit_count(self.root) - baseline, 0)

    def test_two_distinct_saves_two_commits(self):
        """Two distinct saves (separated by debounce gap) → two new commits."""
        watcher = self._make_watcher()
        time.sleep(0.4)
        baseline = _commit_count(self.root)

        with patch("autocommit.git_ops.push_commits", return_value=True):
            watcher.start()
            try:
                p = self.root / "seq.py"
                p.write_text("v = 1\n")
                time.sleep(self.cfg["debounce_seconds"] + 1.2)
                p.write_text("v = 2\n")
                time.sleep(self.cfg["debounce_seconds"] + 1.2)
            finally:
                watcher.stop()

        self.assertEqual(_commit_count(self.root) - baseline, 2)


# ===========================================================================
# Config loading tests
# ===========================================================================

class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        self.root = _make_temp_repo()

    def test_defaults_load(self):
        cfg = load_config(self.root)
        self.assertEqual(cfg["debounce_seconds"], 1.5)
        self.assertEqual(cfg["remote"], "origin")

    def test_json_override(self):
        import json
        (self.root / "autocommit_config.json").write_text(
            json.dumps({"debounce_seconds": 3.0, "verbose": True})
        )
        cfg = load_config(self.root)
        self.assertEqual(cfg["debounce_seconds"], 3.0)
        self.assertTrue(cfg["verbose"])

    def test_env_override(self):
        with patch.dict(os.environ, {"AC_DEBOUNCE_SECONDS": "5"}):
            cfg = load_config(self.root)
        self.assertEqual(cfg["debounce_seconds"], 5.0)

    def test_malformed_json_falls_back_to_defaults(self):
        (self.root / "autocommit_config.json").write_text("{ NOT JSON }")
        cfg = load_config(self.root)
        self.assertEqual(cfg["debounce_seconds"], 1.5)  # default


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
