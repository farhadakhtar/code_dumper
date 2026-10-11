"""Command Line Interface (CLI) entry point for CodeDumper.

Implements the README contract:

- Bare ``codedumper`` launches the interactive menu (dump, update dump,
  GitHub, self-update check, exit).
- ``codedumper dump [PATH] [OPTIONS]`` is the primary non-interactive form.
- ``codedumper [PATH] [OPTIONS]`` (legacy direct form) keeps working.
- Default output is plain text (``.txt``); ``--format markdown`` opts in
  to the Markdown rendering.
"""

import argparse
import re
import signal
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

import codedumper
from codedumper.models import ScanConfig
from codedumper.renderer import iter_markdown_parts, iter_text_parts
from codedumper.reporter import format_cli_summary
from codedumper.scanner import scan_repository
from codedumper.updater import GITHUB_REPO_URL, run_update_interactive
from codedumper.writer import write_dump_stream


BANNER = """\
====================================
          CODEDUMPER
====================================

What would you like to do?

  1. Get a code dump
  2. Update the code dump
  3. See GitHub
  4. Check for updates and install
  5. Exit
"""

MENU_PROMPT = "Select an option [1-5]: "

FORMAT_TEXT = "text"
FORMAT_MARKDOWN = "markdown"
FORMAT_CHOICES = (FORMAT_TEXT, FORMAT_MARKDOWN)
FORMAT_EXTENSIONS = {FORMAT_TEXT: "txt", FORMAT_MARKDOWN: "md"}


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


def _add_dump_options(parser: argparse.ArgumentParser) -> None:
    """Attach the shared dump options to a parser (dump subcommand or legacy)."""
    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        default=None,
        help="Destination filepath for the generated dump. (Default: <project_directory_name>.txt outside the scanned project)",
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
        help="Include hidden files and directories (names starting with '.'). Sensitive files stay excluded.",
    )
    parser.add_argument(
        "--max-file-size",
        "--max-size",
        dest="max_size",
        default="1MB",
        help="Maximum individual file size to include in the dump (e.g. '500KB', '2MB'). (Default: 1MB)",
    )
    parser.add_argument(
        "--no-tree",
        action="store_true",
        help="Suppress the project structure section in the generated dump.",
    )
    parser.add_argument(
        "--format",
        choices=FORMAT_CHOICES,
        default=FORMAT_TEXT,
        help="Output format: plain text '.txt' (default) or Markdown '.md'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report without writing any file to disk.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the legacy direct-form parser (also used for top-level help).

    The ``dump`` subcommand has its own parser (see :func:`build_dump_parser`);
    :func:`main` dispatches on the first token so a project directory never
    collides with the subcommand name.
    """
    parser = argparse.ArgumentParser(
        prog="codedumper",
        description="Turn any codebase into one organized plain-text document.\n\n"
        "Run with no arguments to launch the interactive menu, or use "
        "'codedumper dump [PATH] [OPTIONS]' for non-interactive export.",
        epilog="Examples:\n"
        "  codedumper\n"
        "  codedumper dump ./my-project\n"
        '  codedumper dump ./my-project --output ./exports/codebase.txt\n'
        "  codedumper dump ./my-project --dry-run\n"
        "  codedumper dump ./my-project --format markdown\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {codedumper.__version__}",
    )

    # Legacy direct form: `codedumper [TARGET_DIR] [OPTIONS]`
    parser.add_argument(
        "target_dir",
        nargs="?",
        default=None,
        help="Path to the repository or directory to export. (Default: current working directory)",
    )
    _add_dump_options(parser)

    return parser


def build_dump_parser() -> argparse.ArgumentParser:
    """Construct the ``codedumper dump`` subcommand parser."""
    dump_parser = argparse.ArgumentParser(
        prog="codedumper dump",
        description="Export a project directory to a single, organized plain-text document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    dump_parser.add_argument(
        "dump_path",
        nargs="?",
        default=".",
        help="Path to the project directory to export. (Default: current working directory)",
    )
    dump_parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {codedumper.__version__}",
    )
    _add_dump_options(dump_parser)
    return dump_parser


def execute_dump(
    target_dir: str,
    output_path: Optional[str] = None,
    force: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    include_hidden: bool = False,
    max_size: str = "1MB",
    no_tree: bool = False,
    dry_run: bool = False,
) -> int:
    """Run one full scan-and-export cycle. Returns the process exit code."""
    target_path = Path(target_dir).resolve()
    if not target_path.exists():
        print(f"Error: Target directory does not exist: '{target_path}'", file=sys.stderr)
        return 1

    if not target_path.is_dir():
        print(f"Error: Target path is not a directory: '{target_path}'", file=sys.stderr)
        return 1

    try:
        max_size_bytes = parse_size_str(max_size)
        if max_size_bytes <= 0:
            raise ValueError("Max file size must be greater than zero.")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Determine default output path if not explicitly provided
    if output_path:
        output_file = Path(output_path).resolve()
    else:
        dir_name = target_path.name or "repository"
        output_file = Path(f"{dir_name}.md").resolve()

    # Pre-flight check: destination existence
    if not dry_run and output_file.exists() and not force:
        print(
            f"Error: Destination file already exists: '{output_file}'. Use --force (-f) to overwrite.",
            file=sys.stderr,
        )
        return 1

    config = ScanConfig(
        target_dir=target_path,
        output_path=output_file,
        max_size_bytes=max_size_bytes,
        include_hidden=include_hidden,
        exclude_patterns=exclude_patterns or [],
        force=force,
        dry_run=dry_run,
        no_tree=no_tree,
    )

    print(f"[INFO] Project: {config.target_dir.name}")
    print("[INFO] Scanning directory...")
    try:
        result = scan_repository(config)
    except PermissionError as e:
        print(f"Filesystem Permission Error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Filesystem Error: {e}", file=sys.stderr)
        return 2
    print("[INFO] Applying exclusion rules...")
    print("[INFO] Collecting eligible files...")

    # Persist (streaming: the document is encoded and written piece by piece
    # so the joined Markdown string is never materialized) or dry-run
    if not config.dry_run:
        try:
            write_dump_stream(
                config.output_path,
                iter_markdown_parts(config, result),
                force=config.force,
            )
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


def run_interactive_menu() -> int:
    """Launch the interactive CODEDUMPER CLI menu. Returns the exit code."""
    print(BANNER)
    session_excludes: List[str] = []

    while True:
        try:
            choice = input(MENU_PROMPT).strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nOperation canceled by user.", file=sys.stderr)
            return 130

        if choice == "1":
            rc = _menu_dump(".", session_excludes)
            if rc != 0:
                print(f"[INFO] Dump finished with exit code {rc}.")
        elif choice == "2":
            try:
                path = input("Enter the project path: ").strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\nOperation canceled by user.", file=sys.stderr)
                return 130
            if not path:
                print("No path entered. Returning to the menu.")
                continue
            rc = _menu_dump(path, session_excludes)
            if rc != 0:
                print(f"[INFO] Dump finished with exit code {rc}.")
        elif choice == "3":
            execute_dump(".", dry_run=True, exclude_patterns=list(session_excludes))
        elif choice == "4":
            try:
                raw = input("Enter extra glob patterns, comma-separated (e.g. *.log, docs/*): ").strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\nOperation canceled by user.", file=sys.stderr)
                return 130
            new_patterns = [p.strip() for p in raw.split(",") if p.strip()]
            if new_patterns:
                session_excludes.extend(new_patterns)
                print(f"[INFO] Added {len(new_patterns)} exclusion pattern(s) for this session.")
            else:
                print("[INFO] No patterns entered; session exclusions unchanged.")
        elif choice == "5":
            print(build_parser().format_help())
        elif choice == "6":
            print("Goodbye!")
            return 0
        else:
            print(f"Invalid choice: '{choice}'. Please select an option [1-6].")


def _menu_dump(path: str, session_excludes: List[str]) -> int:
    """Dump helper for menu options 1/2 with overwrite confirmation."""
    target_path = Path(path).resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory is not valid: '{target_path}'", file=sys.stderr)
        return 1
    dir_name = target_path.name or "repository"
    default_output = Path(f"{dir_name}.md").resolve()
    if default_output.exists():
        try:
            answer = input(f"Output file '{default_output}' already exists. Overwrite? [y/N]: ").strip().lower()
        except EOFError:
            print()
            return 1
        except KeyboardInterrupt:
            print("\nOperation canceled by user.", file=sys.stderr)
            return 130
        if answer not in ("y", "yes"):
            print("[INFO] Dump canceled; existing file preserved.")
            return 0
        return execute_dump(path, force=True, exclude_patterns=list(session_excludes))
    return execute_dump(path, exclude_patterns=list(session_excludes))


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

    if args is None:
        args = sys.argv[1:]

    # Bare invocation launches the interactive menu.
    if len(args) == 0:
        try:
            return run_interactive_menu()
        except KeyboardInterrupt:
            print("\nOperation canceled by user.", file=sys.stderr)
            return 130

    # Subcommand dispatch: `codedumper dump ...` vs. legacy direct form.
    # (A project directory is never confused with the subcommand name.)
    if args[0] == "dump":
        parsed_args = build_dump_parser().parse_args(args[1:])
        return execute_dump(
            target_dir=parsed_args.dump_path,
            output_path=parsed_args.output_path,
            force=parsed_args.force,
            exclude_patterns=parsed_args.exclude_patterns or [],
            include_hidden=parsed_args.include_hidden,
            max_size=parsed_args.max_size,
            no_tree=parsed_args.no_tree,
            dry_run=parsed_args.dry_run,
        )

    parser = build_parser()
    parsed_args = parser.parse_args(args)

    # Legacy direct form.
    target = parsed_args.target_dir or "."
    return execute_dump(
        target_dir=target,
        output_path=parsed_args.output_path,
        force=parsed_args.force,
        exclude_patterns=parsed_args.exclude_patterns or [],
        include_hidden=parsed_args.include_hidden,
        max_size=parsed_args.max_size,
        no_tree=parsed_args.no_tree,
        dry_run=parsed_args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
