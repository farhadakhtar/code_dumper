"""Hierarchical directory tree generation for CodeDumper."""

from pathlib import Path
from typing import List, Tuple
from codedumper.filter import ExclusionEngine


def generate_directory_tree(root_dir: Path, filter_engine: ExclusionEngine, max_depth: int = 25) -> str:
    """Generate a deterministic, sorted ASCII tree representation of the project hierarchy."""
    lines: List[str] = [f"{root_dir.resolve().name}/"]

    def _build_tree(current_dir: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}└── ... (max depth reached)")
            return

        try:
            entries = sorted(current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower(), p.name))
        except OSError:
            lines.append(f"{prefix}└── [Permission Denied]")
            return

        # Separate into filtered valid entries
        visible_entries: List[Tuple[Path, bool]] = []
        for entry in entries:
            try:
                rel = entry.relative_to(root_dir).as_posix()
            except ValueError:
                rel = entry.name

            if entry.is_dir():
                if filter_engine.should_skip_directory(entry.name, rel) is None:
                    visible_entries.append((entry, True))
            else:
                # File: show in tree unless it's default VCS noise or hidden
                if not filter_engine.include_hidden and entry.name.startswith("."):
                    continue
                if entry.name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", ".DS_Store"}:
                    continue
                visible_entries.append((entry, False))

        count = len(visible_entries)
        for i, (entry, is_dir) in enumerate(visible_entries):
            is_last = (i == count - 1)
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "

            display_name = f"{entry.name}/" if is_dir else entry.name
            lines.append(f"{prefix}{connector}{display_name}")

            if is_dir and not entry.is_symlink():
                _build_tree(entry, prefix + child_prefix, depth + 1)

    _build_tree(root_dir, "", 1)
    return "\n".join(lines)
