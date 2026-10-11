"""Contract tests for the CodeDumper CLI (README-defined behavior).

Covers: the ``dump`` subcommand, ``--max-file-size``, ``--format``,
the default plain-text (``.txt``) output contract, the interactive menu,
honest reporting, determinism, symlinks, unicode paths, and license
presence. All projects are temporary; no real credentials are used.
"""

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from codedumper.cli import MENU_BODY, MENU_PROMPT, _menu_open_github, execute_dump, main, run_interactive_menu
from codedumper.models import ScanConfig
from codedumper.renderer import render_markdown
from codedumper.scanner import scan_repository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mini_project(tmp_path: Path) -> Path:
    proj = tmp_path / "my_project"
    proj.mkdir()
    src = proj / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    print('hi')\n", encoding="utf-8")
    (proj / "README.md").write_text("# Demo\n", encoding="utf-8")
    (proj / ".env").write_text("SECRET=topsecret", encoding="utf-8")
    (proj / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    return proj


def _dump_config(proj: Path, out: Path, **kwargs) -> ScanConfig:
    defaults = dict(
        target_dir=proj, output_path=out, max_size_bytes=1_048_576,
        include_hidden=False, exclude_patterns=[],
    )
    defaults.update(kwargs)
    return ScanConfig(**defaults)


# ---------------------------------------------------------------------------
# dump subcommand
# ---------------------------------------------------------------------------

def test_dump_subcommand_basic(mini_project: Path, tmp_path: Path):
    out = tmp_path / "dump_basic.txt"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force"])
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "CODEBASE DUMP: my_project" in text
    assert "PROJECT STRUCTURE" in text
    assert "FILE: src/app.py" in text
    assert "END FILE: src/app.py" in text
    assert "EXCLUDED FILES" in text
    # Plain-text contract: no Markdown headings or fences.
    assert "## " not in text
    assert "```" not in text


def test_dump_subcommand_default_path(tmp_path: Path, monkeypatch):
    """`codedumper dump` with no path dumps the current directory.

    The default output lands OUTSIDE the scanned project (parent dir).
    """
    proj = tmp_path / "cur"
    proj.mkdir()
    (proj / "a.txt").write_text("hello", encoding="utf-8")
    monkeypatch.chdir(proj)
    rc = main(["dump", "--force"])
    assert rc == 0
    out = tmp_path / "cur.txt"
    assert out.exists()
    assert not (proj / "cur.txt").exists()
    assert "CODEBASE DUMP: cur" in out.read_text(encoding="utf-8")


def test_dump_subcommand_markdown_format_opt_in(mini_project: Path, tmp_path: Path):
    out = tmp_path / "dump_basic.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force",
               "--format", "markdown"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "# Codebase Dump: my_project" in text
    assert "## Project Structure" in text
    assert "## File: src/app.py" in text


def test_dump_output_self_exclusion(tmp_path: Path):
    """A previous dump living inside the target is never embedded."""
    proj = tmp_path / "selfref"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    (proj / "selfref.txt").write_text("STALE DUMP - must not be embedded\n", encoding="utf-8")
    out = proj / "selfref.txt"
    rc = main(["dump", str(proj), "-o", str(out), "--force"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "STALE DUMP" not in text
    assert "OUTPUT_FILE_SELF" in text
    assert "FILE: a.py" in text


def test_dump_subcommand_custom_output(mini_project: Path, tmp_path: Path):
    out = tmp_path / "exports" / "codebase.md"
    rc = main(["dump", str(mini_project), "--output", str(out)])
    assert rc == 0
    assert out.exists()


def test_dump_subcommand_dry_run_writes_nothing(mini_project: Path, tmp_path: Path):
    out = tmp_path / "dry.md"
    rc = main(["dump", str(mini_project), "--output", str(out), "--dry-run"])
    assert rc == 0
    assert not out.exists()


def test_dump_subcommand_exclude(mini_project: Path, tmp_path: Path):
    out = tmp_path / "excl.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force",
               "--exclude", "src/*"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "FILE: src/app.py" not in text
    assert "USER_EXCLUDE_PATTERN" in text


def test_dump_subcommand_include_hidden_keeps_secrets_out(mini_project: Path, tmp_path: Path):
    (mini_project / ".hidden.txt").write_text("visible-ish", encoding="utf-8")
    out = tmp_path / "hidden.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force", "--include-hidden"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "FILE: .hidden.txt" in text
    # Sensitive files stay excluded even with --include-hidden.
    assert "FILE: .env" not in text
    assert "SENSITIVE_CREDENTIAL" in text


def test_dump_subcommand_max_file_size(mini_project: Path, tmp_path: Path):
    big = mini_project / "big.txt"
    big.write_text("Z" * 5000, encoding="utf-8")
    out = tmp_path / "sized.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force",
               "--max-file-size", "1KB"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "FILE: big.txt" not in text
    assert "EXCEEDS_MAX_SIZE" in text


def test_dump_subcommand_max_size_alias(mini_project: Path, tmp_path: Path):
    out = tmp_path / "alias.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force",
               "--max-size", "1MB"])
    assert rc == 0
    assert out.exists()


def test_dump_subcommand_invalid_size(mini_project: Path, tmp_path: Path):
    out = tmp_path / "bad.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--max-file-size", "huge"])
    assert rc == 1
    assert not out.exists()


def test_dump_subcommand_no_tree(mini_project: Path, tmp_path: Path):
    out = tmp_path / "notree.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force", "--no-tree"])
    assert rc == 0
    assert "PROJECT STRUCTURE" not in out.read_text(encoding="utf-8")


def test_dump_subcommand_help():
    with pytest.raises(SystemExit) as exc:
        main(["dump", "--help"])
    assert exc.value.code == 0


def test_legacy_form_still_works(mini_project: Path, tmp_path: Path):
    out = tmp_path / "legacy.md"
    rc = main([str(mini_project), "-o", str(out), "--force", "--max-size", "2MB"])
    assert rc == 0
    assert "PROJECT STRUCTURE" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Output format & honesty
# ---------------------------------------------------------------------------

def test_output_layout_matches_readme(mini_project: Path, tmp_path: Path):
    out = tmp_path / "layout.md"
    config = _dump_config(mini_project, out)
    result = scan_repository(config)
    md = render_markdown(config, result)
    assert md.startswith("# Codebase Dump: my_project")
    assert "## Project Structure" in md
    assert "```python" in md  # language-tagged fence
    assert "## Excluded Files" in md
    assert "| Relative Path | Reason | File Size |" in md
    # Determinism metadata: no wall-clock timing inside the file.
    assert "Scan Duration" not in md
    # Secret values never leak; only names + reasons.
    assert "topsecret" not in md


def test_output_deterministic_bytes(mini_project: Path, tmp_path: Path):
    c1 = _dump_config(mini_project, tmp_path / "a.md")
    c2 = _dump_config(mini_project, tmp_path / "b.md")
    h1 = hashlib.sha256(render_markdown(c1, scan_repository(c1)).encode()).hexdigest()
    h2 = hashlib.sha256(render_markdown(c2, scan_repository(c2)).encode()).hexdigest()
    assert h1 == h2


def test_console_report_shows_real_counts(mini_project: Path, tmp_path: Path, capsys):
    out = tmp_path / "rep.md"
    rc = main(["dump", str(mini_project), "-o", str(out), "--force"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "[INFO] Project: my_project" in captured
    assert "Files discovered:" in captured
    assert "Files included:" in captured
    assert "Files excluded:" in captured
    assert "Sensitive files skipped:" in captured
    assert "[OK] Export completed successfully." in captured


def test_unicode_and_spaces(tmp_path: Path):
    proj = tmp_path / "uni"
    proj.mkdir()
    (proj / "docs and guides").mkdir()
    (proj / "docs and guides" / "快速指南.md").write_text("# 你好世界\n", encoding="utf-8")
    (proj / "café.txt").write_text("naïve résumé", encoding="utf-8")
    out = tmp_path / "uni.md"
    rc = main(["dump", str(proj), "-o", str(out), "--force"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "你好世界" in text
    assert "café.txt" in text


def test_symlink_not_followed(tmp_path: Path):
    proj = tmp_path / "links"
    proj.mkdir()
    (proj / "real.py").write_text("x = 1\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("should not be embedded", encoding="utf-8")
    link = proj / "evil_link.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Cannot create symlinks on this platform/context.")
    out = tmp_path / "links.md"
    rc = main(["dump", str(proj), "-o", str(out), "--force"])
    assert rc == 0
    assert "should not be embedded" not in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Interactive menu (spec launch screen)
# ---------------------------------------------------------------------------

def test_menu_exit_option():
    with patch("builtins.input", side_effect=["7"]):
        assert run_interactive_menu() == 0


def test_menu_matches_exact_spec(capsys):
    """The fallback launch screen matches the specification verbatim.

    Under pytest stdout is not a tty, so the image logo is skipped and the
    plain menu (dynamic version + options block) is shown.
    """
    with patch("builtins.input", side_effect=["7"]):
        assert run_interactive_menu() == 0
    import codedumper
    out = capsys.readouterr().out
    assert out == f"v{codedumper.__version__}\n\n" + MENU_BODY + "\nGoodbye!\n"
    # Options on consecutive lines with no blanks between them.
    assert (" 1. Dump the current project\n"
            " 2. Dump another project\n"
            " 3. Preview project contents\n"
            " 4. Update\n"
            " 5. Configure exclusions\n"
            " 6. Help and documentation\n"
            " 7. Exit\n") in out
    # No plain-text replacement heading and no duplicated tagline text.
    assert "CODEDUMPER CLI" not in out
    assert "AI-ready" not in out
    # PowerShell/CMD-safe: fallback menu output must be pure ASCII.
    out.encode("ascii")
    # The prompt itself is passed to input(), not printed (mocked input
    # never echoes it), so verify the constant directly.
    assert MENU_PROMPT == "Select an option [1-7]: "


def test_menu_banner(capsys):
    with patch("builtins.input", side_effect=["7"]):
        assert run_interactive_menu() == 0
    out = capsys.readouterr().out
    assert "1. Dump the current project" in out
    assert "2. Dump another project" in out
    assert "3. Preview project contents" in out
    assert "4. Update" in out
    assert "5. Configure exclusions" in out
    assert "6. Help and documentation" in out
    assert "7. Exit" in out


def test_menu_shows_image_logo_when_capable(monkeypatch, capsys):
    """Forced-capability integration: real asset pixels become ANSI art."""
    import codedumper
    monkeypatch.setattr("codedumper.logo.terminal_supports_truecolor",
                        lambda stream=None, env=None: True)
    monkeypatch.setenv("COLUMNS", "100")
    with patch("builtins.input", side_effect=["7"]):
        assert run_interactive_menu() == 0
    out = capsys.readouterr().out
    assert "\x1b[38;2;" in out  # true-color escapes from real pixels
    assert "\u2584" in out
    assert f"v{codedumper.__version__}" in out
    assert " 1. Dump the current project" in out
    # Identity preserved without text duplication.
    assert "CODEDUMPER CLI" not in out
    assert "AI-ready" not in out
    assert "Turn your codebase" not in out


def test_menu_invalid_choice_reprompts(capsys):
    with patch("builtins.input", side_effect=["banana", "7"]):
        assert run_interactive_menu() == 0
    assert "Invalid choice" in capsys.readouterr().out


def test_menu_eof_exits_zero():
    with patch("builtins.input", side_effect=EOFError):
        assert run_interactive_menu() == 0


def test_menu_keyboard_interrupt_returns_130():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        assert run_interactive_menu() == 130


def test_menu_get_dump_creates_txt_outside_project(tmp_path: Path, monkeypatch):
    proj = tmp_path / "menudump"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["1", "", "7"]):
        assert run_interactive_menu() == 0
    out = tmp_path / "menudump.txt"
    assert out.exists()
    assert not (proj / "menudump.txt").exists()
    text = out.read_text(encoding="utf-8")
    assert "CODEBASE DUMP: menudump" in text
    assert "FILE: a.py" in text
    assert "END FILE: a.py" in text
    assert "```" not in text
    assert "## " not in text


def test_menu_get_dump_custom_path_with_spaces(tmp_path: Path, monkeypatch):
    proj = tmp_path / "my project"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    custom = tmp_path / "custom out" / "dump result.txt"
    with patch("builtins.input", side_effect=["1", str(custom), "7"]):
        assert run_interactive_menu() == 0
    assert custom.exists()
    assert "FILE: a.py" in custom.read_text(encoding="utf-8")


def test_menu_dump_another_project(tmp_path: Path, monkeypatch, capsys):
    other = tmp_path / "other proj"
    (other / "src").mkdir(parents=True)
    (other / "src" / "app.py").write_text("print('other')\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)
    with patch("builtins.input", side_effect=["2", str(other), "", "7"]):
        assert run_interactive_menu() == 0
    out = home / "other proj.txt"
    assert out.exists()
    assert "CODEBASE DUMP: other proj" in out.read_text(encoding="utf-8")
    assert "FILE: src/app.py" in out.read_text(encoding="utf-8")


def test_menu_dump_another_empty_path_returns(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / "home2"
    home.mkdir()
    monkeypatch.chdir(home)
    with patch("builtins.input", side_effect=["2", "", "7"]):
        assert run_interactive_menu() == 0
    assert "No path entered" in capsys.readouterr().out


def test_menu_preview_writes_nothing(tmp_path: Path, monkeypatch, capsys):
    proj = tmp_path / "previewproj"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["3", "7"]):
        assert run_interactive_menu() == 0
    assert not (proj / "previewproj.txt").exists()
    assert not (tmp_path / "previewproj.txt").exists()
    assert "Files discovered:" in capsys.readouterr().out


def test_menu_help_prints_usage(capsys):
    with patch("builtins.input", side_effect=["6", "7"]):
        assert run_interactive_menu() == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_menu_configure_exclusions_applies_to_dump(tmp_path: Path, monkeypatch, capsys):
    proj = tmp_path / "exclproj"
    proj.mkdir()
    (proj / "keep.py").write_text("print(1)\n", encoding="utf-8")
    (proj / "skip.log").write_text("noise\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["5", "*.log", "1", "", "7"]):
        assert run_interactive_menu() == 0
    out = tmp_path / "exclproj.txt"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "FILE: keep.py" in text
    assert "FILE: skip.log" not in text
    assert "USER_EXCLUDE_PATTERN" in text
    assert "1 exclusion pattern" in capsys.readouterr().out


def test_menu_configure_exclusions_empty_keeps_session(tmp_path: Path, monkeypatch, capsys):
    proj = tmp_path / "noexcl"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["5", "", "7"]):
        assert run_interactive_menu() == 0
    assert "unchanged" in capsys.readouterr().out


def test_menu_update_existing_dump_with_confirmation(tmp_path: Path, monkeypatch):
    proj = tmp_path / "updproj"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    existing = tmp_path / "updproj.txt"
    existing.write_text("STALE CONTENT", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["4", "y", "7"]):
        assert run_interactive_menu() == 0
    text = existing.read_text(encoding="utf-8")
    assert "STALE CONTENT" not in text
    assert "CODEBASE DUMP: updproj" in text


def test_menu_update_decline_preserves_dump(tmp_path: Path, monkeypatch):
    proj = tmp_path / "updkeep"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    existing = tmp_path / "updkeep.txt"
    existing.write_text("KEEP ME", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["4", "n", "7"]):
        assert run_interactive_menu() == 0
    assert existing.read_text(encoding="utf-8") == "KEEP ME"


def test_menu_update_missing_dump_offers_create(tmp_path: Path, monkeypatch, capsys):
    proj = tmp_path / "freshproj"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["4", "y", "", "7"]):
        assert run_interactive_menu() == 0
    out = tmp_path / "freshproj.txt"
    assert out.exists()
    assert "No existing dump found" in capsys.readouterr().out


def test_menu_update_missing_dump_decline(tmp_path: Path, monkeypatch):
    proj = tmp_path / "nodump"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["4", "n", "7"]):
        assert run_interactive_menu() == 0
    assert not (tmp_path / "nodump.txt").exists()


def test_menu_update_leaves_legacy_markdown_alone(tmp_path: Path, monkeypatch, capsys):
    proj = tmp_path / "legacyproj"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    legacy = proj / "legacyproj.md"
    legacy.write_text("LEGACY MARKDOWN", encoding="utf-8")
    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["4", "n", "7"]):
        assert run_interactive_menu() == 0
    assert legacy.read_text(encoding="utf-8") == "LEGACY MARKDOWN"
    assert "legacy" in capsys.readouterr().out.lower()


def test_menu_open_github_success(monkeypatch, capsys):
    opened = []

    def fake_open(url):
        opened.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", fake_open)
    _menu_open_github()
    assert opened == ["https://github.com/farhadakhtar/code_dumper"]
    assert "github.com/farhadakhtar/code_dumper" in capsys.readouterr().out


def test_menu_open_github_failure(monkeypatch, capsys):
    def fake_open(url):
        raise RuntimeError("no browser")

    monkeypatch.setattr("webbrowser.open", fake_open)
    _menu_open_github()
    captured = capsys.readouterr()
    assert "could not be opened" in (captured.out + captured.err).lower()


def test_bare_main_launches_menu(monkeypatch):
    with patch("builtins.input", side_effect=["7"]) as mock_input:
        assert main([]) == 0
    mock_input.assert_called_once()


# ---------------------------------------------------------------------------
# Packaging honesty
# ---------------------------------------------------------------------------

def test_license_file_exists():
    repo_root = Path(__file__).resolve().parent.parent
    license_file = repo_root / "LICENSE"
    assert license_file.exists()
    assert "MIT" in license_file.read_text(encoding="utf-8")
