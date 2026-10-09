"""
autocommit/watcher.py
=====================
Filesystem watcher that triggers debounced git commit + push on real changes.

Architecture
------------
- watchdog.observers.Observer (ReadDirectoryChangesW on Windows) drives
  event detection without polling.
- A single background "commit worker" thread owns all Git operations so
  concurrent events cannot create competing commits.
- A threading.Event-based debounce timer resets on every new event within
  the debounce window, preventing spurious duplicate commits from a single
  save operation.
- An internal event queue allows multiple distinct saved states to queue up
  without any state being silently lost.
"""

from __future__ import annotations

import logging
import queue
import signal
import threading
import time
from pathlib import Path
from typing import Any, Optional

from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from autocommit.config import (
    ALWAYS_IGNORE_DIRS,
    ALWAYS_IGNORE_SUFFIXES,
    SELF_GENERATED_FILES,
    load_config,
)
from autocommit.git_ops import (
    create_commit,
    ensure_branch_and_upstream,
    push_commits,
)
from autocommit.state import PushState

log = logging.getLogger("autocommit.watcher")

# Sentinel to signal the worker thread to exit
_STOP = object()


# ---------------------------------------------------------------------------
# Path filter
# ---------------------------------------------------------------------------

def _should_ignore(path: str) -> bool:
    """
    Return True if the path should be ignored by the watcher.

    Checked (in order):
    1. Any path component matches an always-ignored directory name.
    2. File suffix is an always-ignored suffix.
    3. The file is one of the watcher's own generated files.
    4. The file is inside the .git directory (prevents infinite loops).
    """
    p = Path(path)
    parts = p.parts

    # Always ignore .git internals
    if ".git" in parts:
        return True

    # Check every directory component
    for part in parts:
        if part in ALWAYS_IGNORE_DIRS:
            return True

    # Suffix check
    suffix = p.suffix.lower()
    if suffix in ALWAYS_IGNORE_SUFFIXES:
        return True

    # Watcher self-generated files
    if p.name in SELF_GENERATED_FILES:
        return True

    # Editor temp files (common patterns)
    name = p.name
    if name.endswith("~") or name.startswith(".#"):
        return True
    # Vim swap files like .file.swp
    if name.startswith(".") and name.endswith(".swp"):
        return True

    return False


# ---------------------------------------------------------------------------
# Filesystem event handler
# ---------------------------------------------------------------------------

class _RepoEventHandler(FileSystemEventHandler):
    """
    Receives watchdog events and enqueues a debounce trigger.

    One "change token" is put onto the queue per logical debounce window.
    The commit worker drains the queue and processes each token.
    """

    def __init__(self, event_queue: queue.Queue, debounce: float) -> None:
        super().__init__()
        self._queue = event_queue
        self._debounce = debounce
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _schedule_commit(self) -> None:
        """(Re)start the debounce timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        """Called when the debounce window expires – enqueue a commit trigger."""
        log.debug("Debounce window expired – enqueuing commit.")
        self._queue.put(time.monotonic())

    def _dispatch_event(self, event: FileSystemEvent) -> None:
        src = getattr(event, "src_path", "")
        dest = getattr(event, "dest_path", "")
        if _should_ignore(src) and (not dest or _should_ignore(dest)):
            return
        log.debug("Event: %s %s", event.event_type, src or dest)
        self._schedule_commit()

    # Watchdog callbacks
    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._dispatch_event(event)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self._dispatch_event(event)

    def on_deleted(self, event: FileDeletedEvent) -> None:
        if not event.is_directory:
            self._dispatch_event(event)

    def on_moved(self, event: FileMovedEvent) -> None:
        self._dispatch_event(event)

    def cancel_pending(self) -> None:
        """Cancel any pending debounce timer (for clean shutdown)."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ---------------------------------------------------------------------------
# Commit worker thread
# ---------------------------------------------------------------------------

class _CommitWorker(threading.Thread):
    """
    Background thread that processes commit tokens from the event queue.

    Each token represents a distinct debounce window that has expired.
    The worker:
    1. Creates a commit (if there are staged changes).
    2. Immediately attempts a push with bounded back-off.
    3. Persists pending-push state so it survives a restart.
    """

    def __init__(
        self,
        repo_root: Path,
        cfg: dict,
        event_queue: queue.Queue,
        state: PushState,
    ) -> None:
        super().__init__(name="CommitWorker", daemon=True)
        self._repo_root = repo_root
        self._cfg = cfg
        self._queue = event_queue
        self._state = state
        self._local_branch: str = ""
        self._remote_branch: str = ""

    def set_branches(self, local: str, remote: str) -> None:
        self._local_branch = local
        self._remote_branch = remote

    def run(self) -> None:
        log.info("Commit worker started.")

        # On restart, check if there are pending pushes from a previous run
        if self._state.has_pending_push and not self._state.permanent_failure:
            log.info(
                "Found pending push from previous run – attempting recovery push."
            )
            self._do_push()

        while True:
            try:
                token = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if token is _STOP:
                log.info("Commit worker stopping.")
                break

            self._handle_change()

    def _handle_change(self) -> None:
        """Commit and push one detected change."""
        try:
            sha = create_commit(self._repo_root, self._cfg)
            if sha is None:
                log.debug("Nothing to commit for this change event.")
                return

            self._state.mark_pending_push()
            self._do_push()

        except RuntimeError as exc:
            # Secret scan aborted the commit
            log.error("Commit aborted: %s", exc)
        except Exception as exc:
            log.error("Unexpected error during commit: %s", exc, exc_info=True)

    def _do_push(self) -> None:
        if self._state.permanent_failure:
            log.error(
                "Previous push encountered a permanent error "
                "(authentication / non-fast-forward / permissions). "
                "Fix the issue and restart the watcher."
            )
            return

        success = push_commits(
            self._repo_root,
            self._cfg,
            self._local_branch,
            self._remote_branch,
            self._state,
        )
        if not success:
            log.warning(
                "Push did not succeed. Local commits are safe. "
                "Watcher continues monitoring for new changes."
            )

    def stop(self) -> None:
        self._queue.put(_STOP)


# ---------------------------------------------------------------------------
# Public watcher class
# ---------------------------------------------------------------------------

class AutoCommitWatcher:
    """
    High-level watcher.  Usage::

        watcher = AutoCommitWatcher(repo_root=Path("."))
        watcher.start()
        # ... runs indefinitely until stop() or SIGINT
        watcher.stop()
    """

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self._repo_root = Path(repo_root or ".").resolve()
        self._cfg = load_config(self._repo_root)
        self._state = PushState(self._repo_root)
        self._event_queue: queue.Queue = queue.Queue()
        self._observer: Optional[Observer] = None
        self._worker: Optional[_CommitWorker] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            raise RuntimeError("Watcher is already running.")

        log.info("=== Git Auto-Commit Watcher starting ===")
        log.info("Repository: %s", self._repo_root)

        # Safety check: must have a .git directory
        if not (self._repo_root / ".git").is_dir():
            raise RuntimeError(
                f"{self._repo_root} does not contain a .git directory."
            )

        # Resolve branches (safe, no destructive ops)
        local_branch, remote_branch = ensure_branch_and_upstream(
            self._repo_root, self._cfg
        )
        log.info(
            "Watching branch '%s' → remote '%s/%s'",
            local_branch, self._cfg["remote"], remote_branch
        )

        # Start the commit worker thread
        self._worker = _CommitWorker(
            self._repo_root, self._cfg, self._event_queue, self._state
        )
        self._worker.set_branches(local_branch, remote_branch)
        self._worker.start()

        # Start the filesystem observer
        handler = _RepoEventHandler(
            self._event_queue, self._cfg["debounce_seconds"]
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self._repo_root), recursive=True)
        self._observer.start()
        self._handler = handler

        self._running = True
        log.info(
            "Watching for changes (debounce=%.1fs). "
            "Press Ctrl+C to stop.",
            self._cfg["debounce_seconds"]
        )

    def stop(self) -> None:
        if not self._running:
            return
        log.info("=== Stopping watcher (clean shutdown) ===")
        self._running = False

        # Cancel any pending debounce timers
        if hasattr(self, "_handler"):
            self._handler.cancel_pending()

        # Stop the filesystem observer
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)

        # Stop the commit worker
        if self._worker:
            self._worker.stop()
            self._worker.join(timeout=10)

        log.info("Watcher stopped. State: %s", self._state.summary())

    def run_until_interrupted(self) -> None:
        """Block until SIGINT or SIGTERM is received, then shut down cleanly."""
        self.start()
        stop_event = threading.Event()

        def _handle_signal(sig: int, frame: Any) -> None:
            log.info("Signal %s received – initiating shutdown.", sig)
            stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        try:
            signal.signal(signal.SIGTERM, _handle_signal)
        except (AttributeError, OSError):
            pass  # SIGTERM not available on all platforms

        try:
            while not stop_event.is_set():
                stop_event.wait(timeout=1.0)
        finally:
            self.stop()
