"""
autocommit/config.py
====================
Configuration for the Git auto-commit watcher.

All settings can be overridden via environment variables or a local
``autocommit_config.json`` file placed at the repository root.

Priority (highest → lowest):
  1. Environment variables
  2. autocommit_config.json
  3. Defaults defined here
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict = {
    # Seconds to wait after the last filesystem event before committing.
    # Keep at 1-2 s to consolidate rapid editor saves (atomic-write pattern).
    "debounce_seconds": 1.5,

    # Maximum seconds between push retries (exponential backoff cap).
    "push_retry_max_seconds": 300,

    # Base seconds for push retry backoff.
    "push_retry_base_seconds": 5,

    # Maximum consecutive push retry attempts before giving up on a push
    # (0 = unlimited).  Permanent errors stop immediately regardless.
    "push_retry_max_attempts": 10,

    # Branch to push to.  Empty string means "use the current branch".
    "target_branch": "",

    # Remote name.
    "remote": "origin",

    # Commit message template.  Supports strftime codes.
    "commit_message_template": "Auto-save: %Y-%m-%d %H:%M:%S",

    # Extra directories / patterns to exclude (on top of .gitignore).
    "extra_excludes": [],

    # Whether to enable verbose console output.
    "verbose": False,
}

# ---------------------------------------------------------------------------
# Sensitive-content patterns (scan staged diffs before committing)
# ---------------------------------------------------------------------------

# Patterns that indicate a line contains a secret.
SENSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+'),
    re.compile(r'(?i)(secret|token|api[_-]?key|access[_-]?key)\s*[=:]\s*\S+'),
    re.compile(r'(?i)auth[_-]?token\s*[=:]\s*\S+'),
    re.compile(r'(?i)private[_-]?key'),
    # AWS-style keys
    re.compile(r'AKIA[0-9A-Z]{16}'),
    # Generic high-entropy Base64-like blobs ≥ 40 chars on an assignment line
    re.compile(r'(?i)(key|secret|token)\s*[=:]\s*[A-Za-z0-9+/]{40,}'),
    # BEGIN PRIVATE KEY / CERTIFICATE etc.
    re.compile(r'-----BEGIN [A-Z ]+-----'),
]

# Files that should never be staged regardless of .gitignore
BLOCKED_FILENAME_PATTERNS: list[re.Pattern] = [
    re.compile(r'(?i)^\.env(\..+)?$'),
    re.compile(r'(?i)\.(pem|key|p12|pfx|crt|cer|der)$'),
    re.compile(r'(?i)^(id_rsa|id_ed25519|id_ecdsa)$'),
    re.compile(r'(?i)secrets?\.(json|yaml|yml)$'),
    re.compile(r'(?i)credentials?\.(json|yaml|yml)$'),
    re.compile(r'(?i)^auth\.json$'),
    re.compile(r'(?i)\.gpg$'),
]

# ---------------------------------------------------------------------------
# Paths / patterns that are always ignored by the watcher
# (even if not in .gitignore)
# ---------------------------------------------------------------------------

ALWAYS_IGNORE_DIRS: set[str] = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "ENV",
    "node_modules",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    ".cache",
    "logs",
}

ALWAYS_IGNORE_SUFFIXES: set[str] = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".temp",
    ".bak",
    ".orig",
    ".swp",
    ".swo",
    "~",
}

# Files that the watcher itself generates and must never commit
SELF_GENERATED_FILES: set[str] = {
    "autocommit_state.json",
}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(repo_root: Path) -> dict:
    """Load configuration, merging defaults → JSON file → env vars."""
    cfg = dict(DEFAULTS)

    # 1. JSON override file
    config_file = repo_root / "autocommit_config.json"
    if config_file.exists():
        try:
            with config_file.open() as fh:
                overrides = json.load(fh)
            for key in DEFAULTS:
                if key in overrides:
                    cfg[key] = overrides[key]
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[autocommit] Warning: could not read {config_file}: {exc}")

    # 2. Environment variable overrides (AC_<UPPER_KEY>)
    for key in DEFAULTS:
        env_name = f"AC_{key.upper()}"
        env_val = os.environ.get(env_name)
        if env_val is not None:
            default = DEFAULTS[key]
            if isinstance(default, bool):
                cfg[key] = env_val.lower() in ("1", "true", "yes")
            elif isinstance(default, (int, float)):
                try:
                    cfg[key] = type(default)(env_val)
                except ValueError:
                    pass
            else:
                cfg[key] = env_val

    return cfg
