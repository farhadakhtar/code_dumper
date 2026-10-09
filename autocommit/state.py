"""
autocommit/state.py
===================
Persistent state management for the auto-commit watcher.

The state file (autocommit_state.json) lives at the repository root but is
excluded from commits via .gitignore.  It records:

- Whether there are unpushed commits that should be retried on restart.
- Push failure counters for observability.
- The last successful push timestamp.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("autocommit.state")

STATE_FILE = "autocommit_state.json"


class PushState:
    """Thread-safe manager for push retry state, persisted to disk."""

    def __init__(self, repo_root: Path) -> None:
        self._path = repo_root / STATE_FILE
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with self._path.open() as fh:
                    data = json.load(fh)
                log.debug("Loaded push state from %s", self._path)
                return data
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not load state file: %s – starting fresh.", exc)
        return {
            "has_pending_push": False,
            "total_push_failures": 0,
            "last_push_success": None,
            "permanent_failure": False,
        }

    def _save(self) -> None:
        try:
            with self._path.open("w") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError as exc:
            log.warning("Could not save state file: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_pending_push(self) -> bool:
        with self._lock:
            return bool(self._data.get("has_pending_push", False))

    @property
    def permanent_failure(self) -> bool:
        with self._lock:
            return bool(self._data.get("permanent_failure", False))

    def mark_pending_push(self) -> None:
        """Call after a successful commit to record that a push is needed."""
        with self._lock:
            self._data["has_pending_push"] = True
            self._data["permanent_failure"] = False
            self._save()

    def record_push_success(self) -> None:
        from datetime import datetime
        with self._lock:
            self._data["has_pending_push"] = False
            self._data["permanent_failure"] = False
            self._data["last_push_success"] = datetime.now().isoformat()
            self._save()

    def record_push_failure(self, permanent: bool = False) -> None:
        with self._lock:
            self._data["total_push_failures"] = (
                self._data.get("total_push_failures", 0) + 1
            )
            if permanent:
                self._data["permanent_failure"] = True
                self._data["has_pending_push"] = True  # keep for manual fix
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {
                "has_pending_push": False,
                "total_push_failures": 0,
                "last_push_success": None,
                "permanent_failure": False,
            }
            self._save()

    def summary(self) -> dict:
        with self._lock:
            return dict(self._data)
