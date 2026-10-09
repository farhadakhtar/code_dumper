"""Terminal reporting and execution summaries for CodeDumper."""

from pathlib import Path
from typing import Optional
from codedumper.models import ScanResult
from codedumper.renderer import format_size


def format_cli_summary(result: ScanResult, output_path: Optional[Path], dry_run: bool = False) -> str:
    """Format human-readable execution summary for stdout."""
    lines = [
        "=" * 60,
        f" CodeDumper Summary: {result.project_name}",
        "=" * 60,
        f" Target Directory : {result.target_dir}",
        f" Files Discovered : {result.total_files_discovered}",
        f" Files Dumped     : {len(result.included_files)}",
        f" Files Omitted    : {len(result.omitted_files)}",
        f" Source Content   : {format_size(result.total_included_bytes)} ({result.total_lines:,} lines)",
        f" Duration         : {result.elapsed_seconds:.2f}s",
    ]

    if dry_run:
        lines.append(" Status           : DRY-RUN (no file written)")
    elif output_path:
        lines.append(f" Output File      : {output_path.resolve()}")
        lines.append(" Status           : SUCCESS")

    if result.omitted_files:
        lines.append("-" * 60)
        lines.append(" Top Omissions:")
        for omitted in result.omitted_files[:10]:
            size_tag = f" ({format_size(omitted.size)})" if omitted.size > 0 else ""
            lines.append(f"  - {omitted.rel_path} -> {omitted.reason}{size_tag}")
        if len(result.omitted_files) > 10:
            lines.append(f"  ... and {len(result.omitted_files) - 10} more omitted files.")

    lines.append("=" * 60)
    return "\n".join(lines)
