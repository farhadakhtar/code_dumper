"""Domain models and data structures for CodeDumper."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class ScanConfig:
    """Immutable scan configuration options provided by CLI or library callers."""
    target_dir: Path
    output_path: Path
    max_size_bytes: int = 1_048_576  # Default: 1 MB
    include_hidden: bool = False
    exclude_patterns: List[str] = field(default_factory=list)
    force: bool = False
    dry_run: bool = False
    no_tree: bool = False


@dataclass(frozen=True)
class FileItem:
    """Represents an accepted source file included in the Markdown dump."""
    path: Path
    rel_path: str
    size: int
    content: str
    language: str
    line_count: int


@dataclass(frozen=True)
class OmissionRecord:
    """Represents a skipped or excluded file and the formal reason why."""
    rel_path: str
    reason: str
    size: int = 0


@dataclass
class ScanResult:
    """Comprehensive result of a directory scan and classification cycle."""
    project_name: str
    target_dir: Path
    included_files: List[FileItem] = field(default_factory=list)
    omitted_files: List[OmissionRecord] = field(default_factory=list)
    tree_text: str = ""
    elapsed_seconds: float = 0.0
    total_files_discovered: int = 0

    @property
    def total_included_bytes(self) -> int:
        return sum(f.size for f in self.included_files)

    @property
    def total_lines(self) -> int:
        return sum(f.line_count for f in self.included_files)
