#!/usr/bin/env python
"""
run_watcher.py
==============
Entry-point script.  Run from the repository root:

    python run_watcher.py

Optional flags:
  --repo PATH     Path to the repository root (defaults to current directory)
  --verbose       Enable DEBUG-level logging
  --config PATH   Path to a JSON config file (copied to <repo>/autocommit_config.json)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, stream=sys.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git Auto-Commit Watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to the repository root (default: current directory)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a JSON config file (copied to <repo>/autocommit_config.json)",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)
    log = logging.getLogger("autocommit.main")

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        log.error("Repository path does not exist: %s", repo_root)
        sys.exit(1)

    if not (repo_root / ".git").is_dir():
        log.error(
            "%s is not a Git repository (no .git directory found).", repo_root
        )
        sys.exit(1)

    if args.config:
        config_src = Path(args.config).resolve()
        if not config_src.is_file():
            log.error("Config file does not exist: %s", config_src)
            sys.exit(1)
        try:
            shutil.copyfile(config_src, repo_root / "autocommit_config.json")
            log.info("Copied config %s -> %s", config_src, repo_root / "autocommit_config.json")
        except OSError as exc:
            log.error("Could not copy config file: %s", exc)
            sys.exit(1)

    # Late import so logging is configured first
    from autocommit.watcher import AutoCommitWatcher

    watcher = AutoCommitWatcher(repo_root=repo_root)
    watcher.run_until_interrupted()


if __name__ == "__main__":
    main()
