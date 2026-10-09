"""Command Line Interface (CLI) entry point for CodeDumper."""

import argparse
import re
import signal
import sys
from pathlib import Path
from typing import List, Optional

import codedumper
from codedumper.models import ScanConfig
from codedumper.renderer import render_markdown
from codedumper.reporter import format_cli_summary
from codedumper.scanner import scan_repository
from codedumper.writer import write_dump_file


def parse_size_str(val: str) -> int:
    """Parse human size strings like '500KB', '2MB', or raw integers into bytes."""
    val = val.strip().upper()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([KMG]?B?)$", val)
    if not match:
        raise ValueError(f"Invalid size specification: '{val}'. Expected e.g. '500KB', '2MB', '1048576'.")

    number, unit = match.groups()
    num = float(number)

    if unit in ("MB", "M"):
        return int(num * 1024 * 1024)
    elif unit in ("KB", "K"):
        return int(num * 1024)
    elif unit in ("GB", "G"):
        return int(num * 1024 * 1024 * 1024)
    elif unit in ("B", ""):
        return int(num)
    else:
        raise ValueError(f"Unsupported size unit in: '{val}'")


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for codedumper CLI."""
    parser = argparse.ArgumentParser(
        prog="codedumper",
        description="Export a codebase into a single, clean Markdown document for AI coding assistants.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "target_dir",
        nargs="?",
        default=".",
        help="Path to the repository or directory to export. (Default: current working directory)",
    )

    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        default=None,
        help="Destination filepath for the generated Markdown dump. (Default: <target_directory_name>.md)",
    )

    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Overwrite destination file if it already exists without prompt.",
    )

    parser.add_argument(
        "-e",
        "--exclude",
        action="append",
        dest="exclude_patterns",
        default=[],
        help="Glob pattern to exclude (can be specified multiple times, e.g. -e '*.log' -e 'docs/*').",
    )

    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and directories (names starting with '.').",
    )

    parser.add_argument(
        "--max-size",
        default="1MB",
        help="Maximum individual file size to include in the dump. (Default: 1MB)",
    )

    parser.add_argument(
        "--no-tree",
        action="store_true",
        help="Suppress the directory tree section in the generated Markdown output.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without writing any file to disk.",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {codedumper.__version__}",
    )

    return parser


def main(args: Optional[List[str]] = None) -> int:
    """Main CLI execution routine."""
    # Register SIGINT handler
    def _sigint_handler(signum, frame):
        print("\nOperation canceled by user.", file=sys.stderr)
        sys.exit(130)

    try:
        signal.signal(signal.SIGINT, _sigint_handler)
    except (ValueError, AttributeError):
        pass  # In certain non-main threads or environments signal cannot be registered

    parser = build_parser()
    parsed_args = parser.parse_args(args)

    target_path = Path(parsed_args.target_dir).resolve()
    if not target_path.exists():
        print(f"Error: Target directory does not exist: '{target_path}'", file=sys.stderr)
        return 1

    if not target_path.is_dir():
        print(f"Error: Target path is not a directory: '{target_path}'", file=sys.stderr)
        return 1

    try:
        max_size_bytes = parse_size_str(parsed_args.max_size)
        if max_size_bytes <= 0:
            raise ValueError("Max size must be greater than zero.")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Determine default output path if not explicitly provided
    if parsed_args.output_path:
        output_file = Path(parsed_args.output_path).resolve()
    else:
        dir_name = target_path.name or "repository"
        output_file = Path(f"{dir_name}.md").resolve()

    # Pre-flight check: destination existence
    if not parsed_args.dry_run and output_file.exists() and not parsed_args.force:
        print(
            f"Error: Destination file already exists: '{output_file}'. Use --force (-f) to overwrite.",
            file=sys.stderr,
        )
        return 1

    config = ScanConfig(
        target_dir=target_path,
        output_path=output_file,
        max_size_bytes=max_size_bytes,
        include_hidden=parsed_args.include_hidden,
        exclude_patterns=parsed_args.exclude_patterns or [],
        force=parsed_args.force,
        dry_run=parsed_args.dry_run,
        no_tree=parsed_args.no_tree,
    )

    try:
        result = scan_repository(config)
    except PermissionError as e:
        print(f"Filesystem Permission Error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Filesystem Error: {e}", file=sys.stderr)
        return 2

    # Render Markdown
    markdown_content = render_markdown(config, result)

    # Persist or dry-run
    if not config.dry_run:
        try:
            write_dump_file(config.output_path, markdown_content, force=config.force)
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
            return 2

    # Display report
    summary_output = format_cli_summary(result, config.output_path if not config.dry_run else None, dry_run=config.dry_run)
    print(summary_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
