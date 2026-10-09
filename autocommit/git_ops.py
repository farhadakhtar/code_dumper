"""
autocommit/git_ops.py
=====================
All Git operations for the auto-commit watcher.

Key design decisions
--------------------
- All Git commands are invoked via subprocess with argument lists (no shell=True).
- A threading.Lock serialises every Git operation so concurrent filesystem
  events cannot create competing commits or corrupt repository state.
- The module uses only subprocess + standard library so it works without
  GitPython if needed, but GitPython is used for diff scanning.
- Push uses bounded exponential back-off; permanent errors are classified
  and never retried.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from autocommit.config import (
    BLOCKED_FILENAME_PATTERNS,
    SELF_GENERATED_FILES,
    SENSITIVE_PATTERNS,
    load_config,
)
from autocommit.state import PushState

log = logging.getLogger("autocommit.git_ops")

# ---------------------------------------------------------------------------
# Permanent push-error signals – never retry these
# ---------------------------------------------------------------------------
_PERMANENT_PUSH_ERRORS: list[str] = [
    "error: failed to push some refs",      # non-fast-forward
    "rejected",                              # remote rejected
    "Authentication failed",
    "Permission denied",
    "Repository not found",
    "remote: Repository not found",
    "does not appear to be a git repository",
    "CONFLICT",
]

_GIT_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: Path, check: bool = True, capture: bool = True
         ) -> subprocess.CompletedProcess:
    """Run a git sub-command with argument list (never shell=True)."""
    log.debug("Running: %s", " ".join(args))
    result = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=capture,
        text=True,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _git(args: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    return _run(["git"] + args, cwd=cwd, **kwargs)


# ---------------------------------------------------------------------------
# Repository introspection
# ---------------------------------------------------------------------------

def get_current_branch(repo_root: Path) -> str:
    # rev-parse fails on repos with no commits; fall back to symbolic-ref
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root, check=False)
    if result.returncode == 0:
        branch = result.stdout.strip()
        if branch and branch != "HEAD":
            return branch
    # Fallback for empty repos
    result2 = _git(
        ["symbolic-ref", "--short", "HEAD"], repo_root, check=False
    )
    if result2.returncode == 0:
        return result2.stdout.strip()
    return "main"  # ultimate fallback


def has_commits(repo_root: Path) -> bool:
    result = _git(["rev-parse", "HEAD"], repo_root, check=False)
    return result.returncode == 0


def get_remote_default_branch(repo_root: Path, remote: str) -> Optional[str]:
    """Try to determine the remote's default branch from symbolic-ref."""
    result = _git(
        ["symbolic-ref", f"refs/remotes/{remote}/HEAD"],
        repo_root, check=False
    )
    if result.returncode == 0:
        # e.g. refs/remotes/origin/main  →  main
        ref = result.stdout.strip()
        parts = ref.split("/")
        if len(parts) >= 3:
            return parts[-1]
    return None


def get_upstream(repo_root: Path, branch: str) -> Optional[str]:
    result = _git(
        ["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
        repo_root, check=False
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# Branch / upstream safety check
# ---------------------------------------------------------------------------

def ensure_branch_and_upstream(repo_root: Path, cfg: dict) -> tuple[str, str]:
    """
    Return (local_branch, remote_branch) after ensuring a safe upstream.

    Rules (no destructive operations):
    - If target_branch is set in config, use it; else use current branch.
    - If current branch has no upstream yet, set it to origin/<remote_branch>.
    - Never rename, delete, or reset any branch.
    - Logs a warning if local branch name differs from remote default.
    """
    remote = cfg["remote"]
    current = get_current_branch(repo_root)

    # Determine which remote branch to target
    target = cfg.get("target_branch") or ""
    if not target:
        # Try the remote's default branch
        remote_default = get_remote_default_branch(repo_root, remote)
        if remote_default and remote_default != current:
            log.warning(
                "Local branch '%s' differs from remote default '%s'. "
                "Watcher will push to '%s/%s'. "
                "If that is wrong, set target_branch in autocommit_config.json.",
                current, remote_default, remote, remote_default
            )
            target = remote_default
        else:
            target = current

    upstream = get_upstream(repo_root, current)
    if upstream is None:
        # First push will set the upstream
        log.info(
            "Branch '%s' has no upstream; will set '%s/%s' on first push.",
            current, remote, target
        )

    return current, target


# ---------------------------------------------------------------------------
# Secret scanning
# ---------------------------------------------------------------------------

def _filename_is_blocked(rel_path: str) -> bool:
    basename = Path(rel_path).name
    if basename in SELF_GENERATED_FILES:
        return True
    for pat in BLOCKED_FILENAME_PATTERNS:
        if pat.search(basename):
            return True
    return False


def scan_staged_diff_for_secrets(repo_root: Path) -> list[str]:
    """
    Return a list of warning strings if the staged diff contains secrets.
    An empty list means the staged content is clean.
    """
    result = _git(["diff", "--cached", "--unified=0"], repo_root, check=False)
    if result.returncode != 0 or not result.stdout:
        return []

    warnings: list[str] = []
    for lineno, line in enumerate(result.stdout.splitlines(), 1):
        # Only inspect added lines (+) in the diff
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for pat in SENSITIVE_PATTERNS:
            if pat.search(line):
                # Redact the line – never log the actual secret
                warnings.append(
                    f"Line {lineno}: possible secret matched pattern "
                    f"'{pat.pattern[:40]}…'"
                )
                break
    return warnings


# ---------------------------------------------------------------------------
# Staging helpers
# ---------------------------------------------------------------------------

def _unstage_blocked_files(repo_root: Path) -> list[str]:
    """
    Check the index for files that must never be committed; unstage them
    and return their relative paths.
    """
    result = _git(
        ["diff", "--cached", "--name-only"],
        repo_root, check=False
    )
    if result.returncode != 0:
        return []

    blocked: list[str] = []
    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        basename = Path(rel).name
        # Check both filename patterns and self-generated file list
        if _filename_is_blocked(rel) or basename in SELF_GENERATED_FILES:
            # Use 'git rm --cached' which works even with no prior commits;
            # 'git restore --staged' requires a HEAD commit to exist.
            _git(["rm", "--cached", "-f", "--", rel], repo_root, check=False)
            log.warning("Unstaged blocked file: %s", rel)
            blocked.append(rel)
    return blocked


def stage_all_changes(repo_root: Path) -> bool:
    """
    Stage all tracked and untracked changes (respects .gitignore).
    Returns True if there is anything staged to commit.
    """
    with _GIT_LOCK:
        # git add -A  stages new, modified, and deleted files
        _git(["add", "-A"], repo_root)

        # Remove any blocked files from the index
        _unstage_blocked_files(repo_root)

        # Check if there's anything staged
        result = _git(
            ["diff", "--cached", "--quiet"],
            repo_root, check=False
        )
        return result.returncode != 0  # returncode 1 → changes present


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

def create_commit(repo_root: Path, cfg: dict) -> Optional[str]:
    """
    Stage all changes, scan for secrets, and create a commit if the index
    is non-empty.

    Returns the new commit SHA on success, None if nothing to commit, and
    raises RuntimeError if a secret is detected.

    Order of operations (important for correctness):
      1. git add -A  – stage everything that isn't gitignored
      2. Unstage blocked filenames (.env, *.pem, etc.)
      3. Check if anything remains staged
      4. Scan the (now clean) diff for secret content
      5. Commit
    """
    with _GIT_LOCK:
        # Step 1: stage everything
        _git(["add", "-A"], repo_root)

        # Step 2: unstage blocked files BEFORE secret scan so their
        # content never appears in the diff we inspect
        _unstage_blocked_files(repo_root)

        # Step 3: anything left to commit?
        staged_result = _git(
            ["diff", "--cached", "--quiet"], repo_root, check=False
        )
        if staged_result.returncode == 0:
            log.debug("Nothing staged – skipping commit.")
            return None

        # Step 4: secret scan on the already-filtered diff
        warnings = scan_staged_diff_for_secrets(repo_root)
        if warnings:
            # Unstage everything and abort
            _git(["reset", "HEAD"], repo_root, check=False)
            msg = (
                "SECURITY ABORT: staged diff contains possible secrets. "
                "Nothing was committed.\n" + "\n".join(warnings)
            )
            raise RuntimeError(msg)

        # Step 5: commit
        now = datetime.now()
        message = now.strftime(cfg["commit_message_template"])

        result = _git(["commit", "-m", message], repo_root)
        # Extract SHA from output
        sha_match = re.search(r'\b([0-9a-f]{7,40})\b', result.stdout)
        sha = sha_match.group(1) if sha_match else "unknown"
        log.info("Committed %s: %s", sha, message)
        return sha


# ---------------------------------------------------------------------------
# Push (with bounded exponential back-off)
# ---------------------------------------------------------------------------

def _is_permanent_push_error(stderr: str, stdout: str) -> bool:
    combined = (stderr or "") + (stdout or "")
    return any(sig in combined for sig in _PERMANENT_PUSH_ERRORS)


def push_commits(
    repo_root: Path,
    cfg: dict,
    local_branch: str,
    remote_branch: str,
    state: PushState,
) -> bool:
    """
    Push local_branch to remote/remote_branch.

    Uses exponential back-off for transient failures. Permanent errors
    are logged and the function returns False without retrying.

    Returns True on success, False if push ultimately failed.
    """
    remote = cfg["remote"]
    base = cfg["push_retry_base_seconds"]
    cap = cfg["push_retry_max_seconds"]
    max_attempts = cfg["push_retry_max_attempts"]

    # Determine whether we need to set upstream (-u flag)
    upstream = get_upstream(repo_root, local_branch)
    need_set_upstream = upstream is None

    attempt = 0
    delay = base

    while True:
        attempt += 1
        if max_attempts and attempt > max_attempts:
            log.error(
                "Push gave up after %d attempts. Local commits are safe.",
                max_attempts
            )
            state.record_push_failure()
            return False

        try:
            with _GIT_LOCK:
                args = ["push"]
                if need_set_upstream:
                    args += ["-u", remote, f"{local_branch}:{remote_branch}"]
                else:
                    args += [remote, f"{local_branch}:{remote_branch}"]

                result = _git(args, repo_root, check=False)

            if result.returncode == 0:
                log.info(
                    "Pushed %s → %s/%s (attempt %d)",
                    local_branch, remote, remote_branch, attempt
                )
                state.record_push_success()
                need_set_upstream = False  # upstream is now set
                return True

            # Classify the error
            if _is_permanent_push_error(result.stderr, result.stdout):
                log.error(
                    "Push failed with a permanent error (will not retry):\n%s",
                    (result.stderr or result.stdout).strip()
                )
                state.record_push_failure(permanent=True)
                return False

            # Transient error – back off and retry
            log.warning(
                "Push attempt %d failed (transient). Retrying in %.0fs.\n%s",
                attempt, delay,
                (result.stderr or result.stdout or "").strip()[:200]
            )
            state.record_push_failure()
            time.sleep(delay)
            delay = min(delay * 2, cap)

        except subprocess.CalledProcessError as exc:
            log.warning(
                "Push attempt %d raised an exception. Retrying in %.0fs.\n%s",
                attempt, delay, exc.stderr or str(exc)
            )
            state.record_push_failure()
            time.sleep(delay)
            delay = min(delay * 2, cap)
