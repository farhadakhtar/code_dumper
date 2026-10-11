"""Command Line Interface (CLI) entry point for CodeDumper.

Implements the README contract:

- Bare ``codedumper`` launches the interactive menu exactly as specified
  (dump current / dump another / preview / update / configure-exclusions
  display / help / exit); input ``4`` runs the update-dump flow.
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
from codedumper.updater import GITHUB_REPO_URL
from codedumper.writer import write_dump_stream


BANNER = """\
                 CODEDUMPER CLI

         Turn your codebase into Markdown.


 1. Dump the current project

 2. Dump another project

 3. Preview project contents
 4. Update

 5. Configure exclusions

 6. Help and documentation

 7. Exit

"""

MENU_PROMPT = " Select an option [1-7]: "

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
        dest="dump_format",
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


def default_output_path(target_path: Path, dump_format: str) -> Path:
    """Predictable default dump location: outside the scanned project.

    - Dumping another project from elsewhere: ``<name>.txt`` in the current
      working directory (already outside the target).
    - Dumping the current directory: ``<name>.txt`` in the *parent*
      directory, so later scans of the project do not re-ingest the dump.
    - Fallback (e.g. filesystem root, where parent == target): current
      directory. The scanner additionally always excludes the output file
      itself (``OUTPUT_FILE_SELF``), so a dump inside its own project can
      never be embedded.
    """
    extension = FORMAT_EXTENSIONS.get(dump_format, "txt")
    base_name = f"{target_path.name or 'repository'}.{extension}"
    current_dir = Path.cwd().resolve()
    if target_path == current_dir and target_path.parent != target_path:
        return target_path.parent / base_name
    return current_dir / base_name


def execute_dump(
    target_dir: str,
    output_path: Optional[str] = None,
    force: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    include_hidden: bool = False,
    max_size: str = "1MB",
    no_tree: bool = False,
    dry_run: bool = False,
    dump_format: str = FORMAT_TEXT,
) -> int:
    """Run one full scan-and-export cycle. Returns the process exit code."""
    if dump_format not in FORMAT_CHOICES:
        print(f"Error: Unknown format: '{dump_format}'. Choose from: {', '.join(FORMAT_CHOICES)}.", file=sys.stderr)
        return 1

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
        output_file = default_output_path(target_path, dump_format)

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
    # so the joined document string is never materialized) or dry-run
    if not config.dry_run:
        try:
            if dump_format == FORMAT_MARKDOWN:
                parts = iter_markdown_parts(config, result)
            else:
                parts = iter_text_parts(config, result)
            write_dump_stream(
                config.output_path,
                parts,
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


class _MenuExit(Exception):
    """Internal control flow: leave the menu with the given exit code."""

    def __init__(self, code: int):
        super().__init__(f"menu exit {code}")
        self.code = code


def _ask(prompt: str) -> str:
    """Prompt for one line, translating EOF/Ctrl+C into menu exits."""
    try:
        return input(prompt)
    except EOFError:
        print()
        raise _MenuExit(0)
    except KeyboardInterrupt:
        print("\nOperation canceled by user.", file=sys.stderr)
        raise _MenuExit(130)


def _confirm(prompt: str) -> bool:
    """Ask an explicit yes/no question. True only on y/yes."""
    return _ask(prompt).strip().lower() in ("y", "yes")


def _find_existing_dump(target_path: Path) -> tuple[Optional[Path], Optional[Path]]:
    """Locate this project's dump files.

    Returns ``(txt_dump, legacy_markdown_dump)`` where each is an existing
    path or ``None``. The ``.txt`` search covers the parent directory (the
    current default location) and the project directory itself.
    """
    project_name = target_path.name or "repository"
    txt_name = f"{project_name}.txt"
    parent_txt = target_path.parent / txt_name
    local_txt = target_path / txt_name
    legacy_md = target_path / f"{project_name}.md"

    txt_dump: Optional[Path] = None
    if parent_txt.exists() and parent_txt.is_file():
        txt_dump = parent_txt.resolve()
    elif local_txt.exists() and local_txt.is_file():
        txt_dump = local_txt.resolve()

    legacy_dump: Optional[Path] = None
    if txt_dump is None and legacy_md.exists() and legacy_md.is_file():
        legacy_dump = legacy_md.resolve()
    return txt_dump, legacy_dump


def _menu_get_dump(target_dir: str = ".", session_excludes: Optional[List[str]] = None) -> None:
    """Menu dump flow: dump a project directory to `.txt` (default: CWD)."""
    target_path = Path(target_dir).resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory is not valid: '{target_path}'", file=sys.stderr)
        return
    target = str(target_path)
    excludes = list(session_excludes or [])
    default_file = default_output_path(target_path, FORMAT_TEXT)
    print(f"Project: {target_path.name}")
    print(f"Default output: {default_file}")
    try:
        raw = _ask(f"Output path [{default_file}] (Enter to accept): ").strip()
    except _MenuExit as e:
        if e.code != 0:
            raise
        print("[INFO] Dump canceled; no file written.")
        return
    output = raw or str(default_file)
    output_path = Path(output).resolve()
    if output_path.exists() and output_path.is_file():
        print(f"Output file '{output_path}' already exists.")
        if not _confirm("Overwrite it? [y/N]: "):
            print("[INFO] Dump canceled; existing file preserved.")
            return
        rc = execute_dump(target, output_path=str(output_path), force=True,
                           exclude_patterns=excludes)
    else:
        rc = execute_dump(target, output_path=str(output_path),
                           exclude_patterns=excludes)
    if rc != 0:
        print(f"[INFO] Dump finished with exit code {rc}.")


def _menu_dump_other(session_excludes: Optional[List[str]] = None) -> None:
    """Menu option 2: prompt for a project path, then dump it."""
    try:
        path = _ask("Enter the project path: ").strip()
    except _MenuExit as e:
        if e.code != 0:
            raise
        return
    if not path:
        print("No path entered. Returning to the menu.")
        return
    _menu_get_dump(path, session_excludes)


def _menu_configure_exclusions(session_excludes: List[str]) -> None:
    """Menu option 5: collect extra glob patterns for this session."""
    raw = _ask("Enter extra glob patterns, comma-separated (e.g. *.log, docs/*): ").strip()
    new_patterns = [p.strip() for p in raw.split(",") if p.strip()]
    if new_patterns:
        session_excludes.extend(new_patterns)
        print(f"[INFO] Added {len(new_patterns)} exclusion pattern(s) for this session.")
    else:
        print("[INFO] No patterns entered; session exclusions unchanged.")


def _menu_update_dump(session_excludes: Optional[List[str]] = None) -> None:
    """Menu option 4: regenerate the current project's `.txt` dump."""
    target_path = Path.cwd().resolve()
    project_name = target_path.name or "repository"
    txt_dump, legacy_dump = _find_existing_dump(target_path)

    if txt_dump is not None:
        print(f"Found existing dump: {txt_dump}")
        if not _confirm(f"Regenerate '{txt_dump.name}' with the latest source? [y/N]: "):
            print("[INFO] Update canceled; existing file preserved.")
            return
        # Atomic writer swaps in the new file; an interrupted update cannot
        # corrupt the previous dump.
        rc = execute_dump(str(target_path), output_path=str(txt_dump), force=True)
        if rc != 0:
            print(f"[INFO] Update finished with exit code {rc}.")
        return

    if legacy_dump is not None:
        print(f"Found a legacy Markdown dump: {legacy_dump}")
        print("It will be left untouched. A fresh plain-text dump can be created.")
    else:
        print(f"No existing dump found for '{project_name}'.")
    if _confirm("Create a new code dump now? [y/N]: "):
        _menu_get_dump()
    else:
        print("[INFO] No dump created.")


def _menu_open_github() -> None:
    """Open the official repository in the default browser (tested directly)."""
    print(f"Opening: {GITHUB_REPO_URL}")
    try:
        opened = webbrowser.open(GITHUB_REPO_URL)
    except Exception as exc:
        opened = False
        print(f"Could not open the browser: {exc}", file=sys.stderr)
    if opened:
        print("Opened in your default browser. If nothing appeared, visit:")
        print(f"  {GITHUB_REPO_URL}")
    else:
        print("The browser could not be opened. Please visit manually:", file=sys.stderr)
        print(f"  {GITHUB_REPO_URL}", file=sys.stderr)


def run_interactive_menu() -> int:
    """Launch the interactive CodeDumper menu. Returns the exit code.

    Display matches the approved launch-screen specification verbatim
    (including its unusual numbering). Input ``4`` runs the update-dump
    flow: it is the first of the two ``4`` lines, which keeps every
    dump capability reachable from the menu.
    """
    print(BANNER)
    try:
        while True:
            choice = (_ask(MENU_PROMPT) or "").strip()
            if choice == "1":
                _menu_get_dump()
            elif choice == "2":
                _menu_dump_other()
            elif choice == "3":
                execute_dump(".", dry_run=True)
            elif choice == "4":
                _menu_update_dump()
            elif choice == "5":
                print(build_parser().format_help())
            elif choice == "6":
                print("Goodbye!")
                return 0
            else:
                print(f"Invalid choice: '{choice}'. Please select an option [1-6].")
    except _MenuExit as e:
        return e.code


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
            dump_format=parsed_args.dump_format,
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
        dump_format=parsed_args.dump_format,
    )


if __name__ == "__main__":
    sys.exit(main())
