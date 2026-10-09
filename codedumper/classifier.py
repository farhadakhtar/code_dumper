"""Content inspection, binary detection, and syntax language identification."""

from pathlib import Path
from typing import Tuple, Set

# Known binary extensions that can be classified without disk reads
KNOWN_BINARY_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svgz", ".bmp", ".tiff",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".iso",
    ".pyc", ".pyo", ".pyd", ".class", ".wasm", ".o", ".obj",
    ".db", ".sqlite", ".sqlite3", ".parquet", ".arrow",
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".mov", ".avi", ".mkv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
}

# Filename to syntax highlighting tag mapping
SPECIAL_FILENAMES = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    "cmakelists.txt": "cmake",
    "jenkinsfile": "groovy",
    "vagrantfile": "ruby",
    "gemfile": "ruby",
    "procfile": "yaml",
}

# Extension to language mapping
EXTENSION_LANGUAGE_MAP = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".r": "r",
    ".scala": "scala",
    ".lua": "lua",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".txt": "text",
}


def is_binary_file(file_path: Path, sample_size: int = 8192) -> bool:
    """Determine whether a file is binary using extension heuristics and null-byte sampling."""
    suffix = file_path.suffix.lower()
    if suffix in KNOWN_BINARY_EXTENSIONS:
        return True

    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
            if not chunk:
                # Empty file is treated as safe text
                return False

            # Check for null byte
            if b"\x00" in chunk:
                return True

            # Check ratio of non-text bytes
            # Text bytes: standard ASCII printable (0x20..0x7E), whitespace (\t, \n, \r, \b, \f),
            # or high bytes (>= 0x80) indicative of UTF-8 sequences.
            text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})
            non_text_count = sum(1 for byte in chunk if byte not in text_chars)
            if non_text_count / len(chunk) > 0.30:
                return True

            return False
    except OSError:
        # If file cannot be read, report as binary to be safe
        return True


def detect_language(file_path: Path) -> str:
    """Determine the Markdown language tag for a given file."""
    name_lower = file_path.name.lower()
    if name_lower in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name_lower]

    suffix = file_path.suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(suffix, "text")


def read_text_safely(file_path: Path) -> Tuple[str, str]:
    """Read a text file with multi-tier encoding fallback (utf-8 -> utf-8 replace -> latin-1)."""
    with open(file_path, "rb") as f:
        raw_bytes = f.read()

    try:
        content = raw_bytes.decode("utf-8")
        return content, "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        content = raw_bytes.decode("latin-1")
        return content, "latin-1"
    except UnicodeDecodeError:
        pass

    content = raw_bytes.decode("utf-8", errors="replace")
    return content, "utf-8-replaced"
