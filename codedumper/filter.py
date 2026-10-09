"""Exclusion and filtering engine for CodeDumper."""

import fnmatch
from pathlib import Path
from typing import List, Optional, Set


# Built-in noise directories to always prune
DEFAULT_NOISE_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".idea",
    ".vscode",
}

# Built-in noise files
DEFAULT_NOISE_FILES: Set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    ".DS_Store",
    "Thumbs.db",
}

# High-priority sensitive credential file patterns
SENSITIVE_PATTERNS: List[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "token.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
]


class ExclusionEngine:
    """Evaluates files and directories against security and noise exclusion rules."""

    def __init__(self, user_patterns: Optional[List[str]] = None, include_hidden: bool = False):
        self.user_patterns = user_patterns or []
        self.include_hidden = include_hidden

    def is_sensitive(self, name: str) -> bool:
        """Check if filename matches sensitive credential patterns."""
        name_lower = name.lower()
        for pat in SENSITIVE_PATTERNS:
            if fnmatch.fnmatch(name_lower, pat.lower()):
                return True
        return False

    def should_skip_directory(self, dir_name: str, rel_path: str) -> Optional[str]:
        """Determine if a directory should be pruned during traversal.

        Returns reason string if it should be skipped, else None.
        """
        # 1. Built-in VCS and noise directories
        if dir_name in DEFAULT_NOISE_DIRS or dir_name.endswith(".egg-info"):
            return "DEFAULT_NOISE_DIRECTORY"

        # 2. Hidden directories
        if not self.include_hidden and dir_name.startswith("."):
            return "HIDDEN_DIRECTORY"

        # 3. User exclusion patterns
        posix_rel = rel_path.replace("\\", "/")
        for pattern in self.user_patterns:
            pat_clean = pattern.rstrip("/")
            if fnmatch.fnmatch(dir_name, pat_clean) or fnmatch.fnmatch(posix_rel, pat_clean) or fnmatch.fnmatch(f"{posix_rel}/", pattern):
                return f"USER_EXCLUDE_PATTERN: {pattern}"

        return None

    def should_skip_file(
        self,
        file_name: str,
        rel_path: str,
        file_size: int,
        max_size_bytes: int,
    ) -> Optional[str]:
        """Determine if a file should be excluded from the dump.

        Returns reason string if excluded, else None.
        """
        # 1. Highest priority: Sensitive files
        if self.is_sensitive(file_name):
            return "SENSITIVE_CREDENTIAL"

        # 2. Default noise files
        if file_name in DEFAULT_NOISE_FILES:
            return "DEFAULT_NOISE_FILE"

        # 3. Hidden files
        if not self.include_hidden and file_name.startswith("."):
            return "HIDDEN_FILE"

        # 4. User exclusion patterns
        posix_rel = rel_path.replace("\\", "/")
        for pattern in self.user_patterns:
            if fnmatch.fnmatch(file_name, pattern) or fnmatch.fnmatch(posix_rel, pattern):
                return f"USER_EXCLUDE_PATTERN: {pattern}"

        # 5. File size threshold
        if file_size > max_size_bytes:
            return f"EXCEEDS_MAX_SIZE ({file_size} > {max_size_bytes} bytes)"

        return None
