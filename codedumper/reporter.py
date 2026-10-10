"""Terminal reporting and execution summaries for CodeDumper."""

from pathlib import Path
from typing import Optional
from codedumper.models import ScanResult
from codedumper.renderer import format_size


def format_cli_summary(result: ScanResult, output_path: Optional[Path], dry_run: bool = False) -> str:
    """Format human-readable execution summary for stdout.

    Follows the README contract (real measured counts only):
    ``[INFO] Project`` header, ``Files discovered/included/excluded``,
    ``Sensitive files skipped``, output path, and an ``[OK]`` line.
    """
    sensitive_skipped = sum(
        1 for o in result.omitted_files if "SENSITIVE" in o.reason
    )
    lines = [
        f"[INFO] Project: {result.project_name}",
        f"[INFO] Target directory: {result.target_dir}",
        "",
        f"Files discovered:       {result.total_files_discovered}",
        f"Files included:         {len(result.included_files)}",
        f"Files excluded:         {len(result.omitted_files)}",
        f"Sensitive files skipped: {sensitive_skipped}",
        f"Source content:         {format_size(result.total_included_bytes)} ({result.total_lines:,} lines)",
        f"Duration:               {result.elapsed_seconds:.2f}s",
        "",
    ]

    if dry_run:
        lines.append("Status: DRY-RUN (no file written)")
    elif output_path:
        lines.append(f"Output: {output_path.resolve()}")
        lines.append("")
        lines.append("[OK] Markdown export completed successfully.")

    if result.omitted_files:
        lines.append("")
        lines.append("Excluded files (top 10):")
        for omitted in result.omitted_files[:10]:
            size_tag = f" ({format_size(omitted.size)})" if omitted.size > 0 else ""
            lines.append(f"  - {omitted.rel_path} -> {omitted.reason}{size_tag}")
        if len(result.omitted_files) > 10:
            lines.append(f"  ... and {len(result.omitted_files) - 10} more excluded files.")

    return "\n".join(lines)
