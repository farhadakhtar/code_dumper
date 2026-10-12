"""Comprehensive test suite for CodeDumper covering all requirements and edge cases."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from codedumper import __version__
from codedumper.cli import build_parser, main, parse_size_str
from codedumper.classifier import detect_language, is_binary_file, read_text_safely
from codedumper.filter import ExclusionEngine
from codedumper.models import ScanConfig
from codedumper.renderer import calculate_code_fence, render_markdown
from codedumper.scanner import scan_repository
from codedumper.tree import generate_directory_tree
from codedumper.writer import write_dump_file


# ---------------------------------------------------------------------------
# Unit Tests: Size Parsing
# ---------------------------------------------------------------------------

def test_parse_size_str_valid():
    assert parse_size_str("100B") == 100
    assert parse_size_str("1KB") == 1024
    assert parse_size_str("500KB") == 500 * 1024
    assert parse_size_str("1MB") == 1024 * 1024
    assert parse_size_str("2.5MB") == int(2.5 * 1024 * 1024)
    assert parse_size_str("1GB") == 1024 * 1024 * 1024
    assert parse_size_str("2048") == 2048


def test_parse_size_str_invalid():
    with pytest.raises(ValueError):
        parse_size_str("invalid")
    with pytest.raises(ValueError):
        parse_size_str("-10MB")


# ---------------------------------------------------------------------------
# Unit Tests: Dynamic Code Fencing
# ---------------------------------------------------------------------------

def test_calculate_code_fence_no_backticks():
    content = "print('hello world')"
    assert calculate_code_fence(content) == "```"


def test_calculate_code_fence_with_three_backticks():
    content = "Here is some code:\n```python\nprint(1)\n```"
    fence = calculate_code_fence(content)
    assert fence == "````"


def test_calculate_code_fence_with_nested_quad_backticks():
    content = "````markdown\nNested code block\n````"
    fence = calculate_code_fence(content)
    assert fence == "`````"


# ---------------------------------------------------------------------------
# Unit Tests: Binary & Language Detection
# ---------------------------------------------------------------------------

def test_binary_detection_null_bytes(tmp_path: Path):
    bin_file = tmp_path / "sample.bin"
    bin_file.write_bytes(b"hello\x00world\x01\x02\x03")
    assert is_binary_file(bin_file) is True


def test_binary_detection_text_file(tmp_path: Path):
    text_file = tmp_path / "sample.py"
    text_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    assert is_binary_file(text_file) is False


def test_detect_language():
    assert detect_language(Path("app.py")) == "python"
    assert detect_language(Path("index.ts")) == "typescript"
    assert detect_language(Path("style.css")) == "css"
    assert detect_language(Path("Dockerfile")) == "dockerfile"
    assert detect_language(Path("unknown.xyz123")) == "text"


def test_read_text_safely_utf8_and_latin1(tmp_path: Path):
    utf8_file = tmp_path / "utf8.txt"
    utf8_file.write_text("Hello 世界", encoding="utf-8")
    content, enc = read_text_safely(utf8_file)
    assert "世界" in content
    assert enc == "utf-8"

    latin1_file = tmp_path / "latin1.txt"
    latin1_file.write_bytes("Café résumé".encode("latin-1"))
    content, enc = read_text_safely(latin1_file)
    assert "Café" in content


# ---------------------------------------------------------------------------
# Unit Tests: Exclusion Engine & Sensitive Files
# ---------------------------------------------------------------------------

def test_filter_sensitive_credentials():
    engine = ExclusionEngine()
    assert engine.should_skip_file(".env", ".env", 100, 1000000) == "SENSITIVE_CREDENTIAL"
    assert engine.should_skip_file(".env.production", ".env.production", 100, 1000000) == "SENSITIVE_CREDENTIAL"
    assert engine.should_skip_file("server.key", "certs/server.key", 100, 1000000) == "SENSITIVE_CREDENTIAL"
    assert engine.should_skip_file("id_rsa", ".ssh/id_rsa", 100, 1000000) == "SENSITIVE_CREDENTIAL"
    assert engine.should_skip_file("credentials.json", "credentials.json", 100, 1000000) == "SENSITIVE_CREDENTIAL"


def test_filter_default_noise():
    engine = ExclusionEngine()
    assert engine.should_skip_directory(".git", ".git") == "DEFAULT_NOISE_DIRECTORY"
    assert engine.should_skip_directory("node_modules", "node_modules") == "DEFAULT_NOISE_DIRECTORY"
    assert engine.should_skip_directory("__pycache__", "src/__pycache__") == "DEFAULT_NOISE_DIRECTORY"
    assert engine.should_skip_file("package-lock.json", "package-lock.json", 1000, 1000000) == "DEFAULT_NOISE_FILE"


def test_filter_hidden_files():
    engine_hide = ExclusionEngine(include_hidden=False)
    assert engine_hide.should_skip_file(".hidden.txt", ".hidden.txt", 10, 1000) == "HIDDEN_FILE"
    assert engine_hide.should_skip_directory(".config", ".config") == "HIDDEN_DIRECTORY"

    engine_show = ExclusionEngine(include_hidden=True)
    assert engine_show.should_skip_file(".hidden.txt", ".hidden.txt", 10, 1000) is None


def test_filter_custom_user_globs():
    engine = ExclusionEngine(user_patterns=["*.log", "legacy/*"])
    assert engine.should_skip_file("debug.log", "debug.log", 10, 1000) == "USER_EXCLUDE_PATTERN: *.log"
    assert engine.should_skip_file("old.py", "legacy/old.py", 10, 1000) == "USER_EXCLUDE_PATTERN: legacy/*"
    assert engine.should_skip_file("app.py", "src/app.py", 10, 1000) is None


def test_filter_max_size():
    engine = ExclusionEngine()
    assert engine.should_skip_file("big.txt", "big.txt", 2000, 1000) == "EXCEEDS_MAX_SIZE (2000 > 1000 bytes)"
    assert engine.should_skip_file("small.txt", "small.txt", 500, 1000) is None


def test_filter_temporary_write_files():
    """Atomic-write temp files (`.tmp.<pid>.<name>`) are never ingested,
    even when hidden files are explicitly included."""
    engine_hide = ExclusionEngine(include_hidden=False)
    assert engine_hide.should_skip_file(".tmp.1234.proj.txt", ".tmp.1234.proj.txt", 10, 1000) == "TEMPORARY_FILE"
    assert engine_hide.should_skip_directory(".tmp.staging", ".tmp.staging") == "TEMPORARY_FILE"

    engine_show = ExclusionEngine(include_hidden=True)
    assert engine_show.should_skip_file(".tmp.1234.proj.txt", ".tmp.1234.proj.txt", 10, 1000) == "TEMPORARY_FILE"

    # Ordinary names merely containing "tmp" are unaffected.
    assert engine_hide.should_skip_file("tmp.txt", "tmp.txt", 10, 1000) == "HIDDEN_FILE"
    assert engine_show.should_skip_file("tmp.txt", "tmp.txt", 10, 1000) is None
    assert engine_hide.should_skip_file("tmp_notes.txt", "tmp_notes.txt", 10, 1000) is None


# ---------------------------------------------------------------------------
# Unit Tests: Directory Tree Generation
# ---------------------------------------------------------------------------

def test_tree_generation(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')", encoding="utf-8")
    (tmp_path / "src" / "utils.py").write_text("print('utils')", encoding="utf-8")
    (tmp_path / "Readme.md").write_text("# Readme", encoding="utf-8")

    engine = ExclusionEngine()
    tree = generate_directory_tree(tmp_path, engine)
    assert "src/" in tree
    assert "app.py" in tree
    assert "utils.py" in tree
    assert "Readme.md" in tree


# ---------------------------------------------------------------------------
# Unit Tests: Atomic Writer & Overwrite Protection
# ---------------------------------------------------------------------------

def test_writer_atomic_and_overwrite(tmp_path: Path):
    target = tmp_path / "output.md"
    content = "# Test Dump\nHello world"

    # Initial write
    written = write_dump_file(target, content, force=False)
    assert written > 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Collision without force
    with pytest.raises(FileExistsError):
        write_dump_file(target, "New content", force=False)

    # Collision with force
    new_content = "# Overwritten"
    write_dump_file(target, new_content, force=True)
    assert target.read_text(encoding="utf-8") == new_content


# ---------------------------------------------------------------------------
# End-to-End & Integration Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    proj = tmp_path / "my_project"
    proj.mkdir()

    # Normal code files
    src = proj / "src"
    src.mkdir()
    (src / "main.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (src / "helper.js").write_text("console.log('hello');", encoding="utf-8")

    # Path with spaces
    spaced_dir = proj / "docs and guides"
    spaced_dir.mkdir()
    (spaced_dir / "quick start.md").write_text("# Quick Start\nGuide content here.", encoding="utf-8")

    # Nested empty directory
    (proj / "empty_folder").mkdir()

    # File with backticks in code
    (proj / "tutorial.md").write_text(
        "Example code:\n```python\nprint('fenced')\n```\nDone.",
        encoding="utf-8",
    )

    # Unicode characters in file
    (proj / "international.txt").write_text("こんにちは世界 - Hello World", encoding="utf-8")

    # Sensitive files (must be skipped)
    (proj / ".env").write_text("SECRET_KEY=12345", encoding="utf-8")
    (proj / "id_rsa").write_text("PRIVATE KEY DATA", encoding="utf-8")

    # Binary file (must be skipped)
    (proj / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00")

    # Large file (> 10 KB for test)
    (proj / "large.log").write_text("X" * 15000, encoding="utf-8")

    # Noise directory (must be pruned)
    git_dir = proj / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n", encoding="utf-8")

    return proj


def test_scan_repository_comprehensive(sample_project: Path):
    out_file = sample_project.parent / "dump.md"
    config = ScanConfig(
        target_dir=sample_project,
        output_path=out_file,
        max_size_bytes=10000,  # 10 KB limit
        include_hidden=False,
    )

    result = scan_repository(config)

    included_names = [f.rel_path for f in result.included_files]
    assert "src/main.py" in included_names
    assert "src/helper.js" in included_names
    assert "docs and guides/quick start.md" in included_names
    assert "tutorial.md" in included_names
    assert "international.txt" in included_names

    # Verify exclusions
    omitted_map = {o.rel_path: o.reason for o in result.omitted_files}
    assert ".env" in omitted_map
    assert omitted_map[".env"] == "SENSITIVE_CREDENTIAL"
    assert "id_rsa" in omitted_map
    assert omitted_map["id_rsa"] == "SENSITIVE_CREDENTIAL"
    assert "image.png" in omitted_map
    assert omitted_map["image.png"] == "BINARY_FILE"
    assert "large.log" in omitted_map
    assert "EXCEEDS_MAX_SIZE" in omitted_map["large.log"]

    # Verify .git is not included
    for name in included_names:
        assert not name.startswith(".git")

    # Render Markdown
    md = render_markdown(config, result)
    assert "# Codebase Dump: my_project" in md
    assert "## Project Structure" in md
    assert "## File: src/main.py" in md
    assert "## Excluded Files" in md

    # Check dynamic fencing for tutorial.md
    assert "````markdown" in md or "````" in md


def test_scan_determinism(sample_project: Path):
    """Verify that multiple scans on the identical project produce identical outputs."""
    config1 = ScanConfig(target_dir=sample_project, output_path=Path("out1.md"), max_size_bytes=50000)
    config2 = ScanConfig(target_dir=sample_project, output_path=Path("out2.md"), max_size_bytes=50000)

    res1 = scan_repository(config1)
    res2 = scan_repository(config2)

    assert [f.rel_path for f in res1.included_files] == [f.rel_path for f in res2.included_files]
    assert [o.rel_path for o in res1.omitted_files] == [o.rel_path for o in res2.omitted_files]


def test_empty_project(tmp_path: Path):
    empty_dir = tmp_path / "empty_repo"
    empty_dir.mkdir()

    config = ScanConfig(target_dir=empty_dir, output_path=tmp_path / "empty.md")
    result = scan_repository(config)
    assert len(result.included_files) == 0
    assert len(result.omitted_files) == 0
    md = render_markdown(config, result)
    assert "# Codebase Dump: empty_repo" in md


# ---------------------------------------------------------------------------
# CLI Integration Tests
# ---------------------------------------------------------------------------

def test_cli_version():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0


def test_cli_help():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


def test_cli_run_success(sample_project: Path, tmp_path: Path):
    out = tmp_path / "output_test.md"
    exit_code = main([str(sample_project), "-o", str(out), "--force"])
    assert exit_code == 0
    assert out.exists()
    assert "CODEBASE DUMP: my_project" in out.read_text(encoding="utf-8")


def test_cli_dry_run(sample_project: Path, tmp_path: Path):
    out = tmp_path / "dry_run.md"
    exit_code = main([str(sample_project), "-o", str(out), "--dry-run"])
    assert exit_code == 0
    assert not out.exists()


def test_cli_overwrite_refusal(sample_project: Path, tmp_path: Path):
    out = tmp_path / "existing.md"
    out.write_text("Already exists", encoding="utf-8")

    # Without force -> exit code 1
    exit_code = main([str(sample_project), "-o", str(out)])
    assert exit_code == 1
    assert out.read_text(encoding="utf-8") == "Already exists"

    # With force -> exit code 0
    exit_code_force = main([str(sample_project), "-o", str(out), "--force"])
    assert exit_code_force == 0
    assert "CODEBASE DUMP: my_project" in out.read_text(encoding="utf-8")


def test_cli_invalid_target():
    exit_code = main(["/non/existent/path/xyz123"])
    assert exit_code == 1


def test_cli_invalid_size():
    exit_code = main([".", "--max-size", "bad_size"])
    assert exit_code == 1


def test_cli_module_execution(sample_project: Path, tmp_path: Path):
    out = tmp_path / "module_exec.md"
    cmd = [sys.executable, "-m", "codedumper", str(sample_project), "-o", str(out), "--force"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert out.exists()
