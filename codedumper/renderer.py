"""Markdown serialization and dynamic code block fencing for CodeDumper."""

import re
from codedumper.models import ScanConfig, ScanResult


def calculate_code_fence(content: str) -> str:
    """Calculate the minimum code fence length required to safely wrap content.

    Finds the maximum sequence of consecutive backticks in content and returns
    a fence string with at least max(3, max_backticks + 1) backticks.
    """
    matches = re.findall(r"`+", content)
    if not matches:
        return "```"
    max_backticks = max(len(m) for m in matches)
    return "`" * max(3, max_backticks + 1)


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def iter_markdown_parts(config: ScanConfig, result: ScanResult):
    """Yield the Markdown document piece by piece (single source of truth).

    Both :func:`render_markdown` and the streaming writer consume this
    generator, so in-memory and streamed outputs are byte-identical by
    construction. Streaming avoids ever holding the joined document plus
    the parts list in memory at once.
    """
    # Title
    yield f"# Codebase Dump: {result.project_name}\n"

    # Project Structure tree
    if result.tree_text and not config.no_tree:
        yield "## Project Structure\n"
        yield "```text"
        yield result.tree_text
        yield "```\n"

    # File Contents
    if result.included_files:
        for item in result.included_files:
            yield f"## File: {item.rel_path}\n"
            yield f"- Language: `{item.language}` | Size: {format_size(item.size)} | Lines: {item.line_count}\n"

            fence = calculate_code_fence(item.content)
            yield f"{fence}{item.language}"
            yield item.content
            yield f"{fence}\n"

    # Excluded Files
    if result.omitted_files:
        yield "## Excluded Files\n"
        yield "The following files and paths were discovered during scanning but excluded from the dump:\n"
        yield "| Relative Path | Reason | File Size |"
        yield "|---|---|---|"
        for omitted in result.omitted_files:
            size_str = format_size(omitted.size) if omitted.size > 0 else "-"
            yield f"| `{omitted.rel_path}` | {omitted.reason} | {size_str} |"
        yield ""


def render_markdown(config: ScanConfig, result: ScanResult) -> str:
    """Render the complete repository scan result into a single Markdown document.

    Layout follows the README contract: title, ``## Project Structure`` tree,
    one ``## File: <path>`` section per eligible file with a dynamically sized
    fence, and a ``## Excluded Files`` table. No timestamps are embedded so
    repeated runs stay byte-for-byte deterministic.
    """
    return "\n".join(iter_markdown_parts(config, result))
