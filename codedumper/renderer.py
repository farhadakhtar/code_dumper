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


def format_size_plain(size_bytes: int) -> str:
    """Format bytes in plain words for `.txt` output (no abbreviations)."""
    if size_bytes == 1:
        return "1 byte"
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    return format_size(size_bytes)


# Human-friendly language names for `.txt` output. Any tag not listed here
# is shown as-is.
DISPLAY_LANGUAGES = {
    "python": "Python",
    "javascript": "JavaScript",
    "jsx": "JSX",
    "typescript": "TypeScript",
    "tsx": "TSX",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "sass": "Sass",
    "less": "Less",
    "json": "JSON",
    "yaml": "YAML",
    "toml": "TOML",
    "xml": "XML",
    "markdown": "Markdown",
    "rst": "reStructuredText",
    "c": "C",
    "cpp": "C++",
    "csharp": "C#",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "ruby": "Ruby",
    "php": "PHP",
    "bash": "Shell",
    "powershell": "PowerShell",
    "batch": "Batch",
    "sql": "SQL",
    "r": "R",
    "scala": "Scala",
    "lua": "Lua",
    "ini": "INI",
    "graphql": "GraphQL",
    "protobuf": "Protobuf",
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "cmake": "CMake",
    "groovy": "Groovy",
    "text": "Text",
}


def display_language(tag: str) -> str:
    """Map an internal language tag to a human-friendly display name."""
    return DISPLAY_LANGUAGES.get(tag, tag or "Text")


def iter_text_parts(config: ScanConfig, result: ScanResult):
    """Yield the plain-text document piece by piece (default `.txt` format).

    No Markdown headings, no code fences: source contents are embedded
    verbatim between ``FILE:`` / ``END FILE:`` markers. No timestamps are
    embedded so repeated runs stay byte-for-byte deterministic.
    """
    # Title
    yield f"CODEBASE DUMP: {result.project_name}\n"

    # Project Structure tree (reuses the deterministic tree builder)
    if result.tree_text and not config.no_tree:
        yield "PROJECT STRUCTURE\n"
        yield result.tree_text

    # File contents
    if result.included_files:
        for item in result.included_files:
            yield f"FILE: {item.rel_path}"
            yield f"Language: {display_language(item.language)}"
            yield f"Size: {format_size_plain(item.size)}"
            yield f"Lines: {item.line_count}"
            yield ""
            yield item.content
            yield ""
            yield f"END FILE: {item.rel_path}\n"

    # Excluded files
    if result.omitted_files:
        yield "EXCLUDED FILES\n"
        yield "The following files and paths were discovered during scanning but excluded from the dump:\n"
        for omitted in result.omitted_files:
            size_str = format_size_plain(omitted.size) if omitted.size > 0 else "-"
            yield f"{omitted.rel_path} | {omitted.reason} | {size_str}"
        yield ""


def render_text(config: ScanConfig, result: ScanResult) -> str:
    """Render the scan result as a single plain-text document (`.txt`)."""
    return "\n".join(iter_text_parts(config, result))


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
