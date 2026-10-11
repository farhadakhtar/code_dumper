"""Tests for the fixed terminal wordmark (`codedumper/cli.py`).

- Exact block structure: 6 rows, aligned columns, style vocabulary,
  reference letterforms, no trailing whitespace, fits common widths.
- Green ANSI application + reset, plain fallback, narrow skip.
- Color policy matrix (NO_COLOR / dumb TERM / CLICOLOR_FORCE / tty).
- Unwritable/unencodable streams degrade without crashing.
- No competing image renderer remains in the package.
"""

import io

import pytest

from codedumper.cli import (
    WORDMARK_GREEN,
    WORDMARK_RESET,
    WORDMARK_TEXT,
    _WORDMARK_WIDTH,
    _build_wordmark,
    _color_enabled,
    _ensure_utf8_output,
    print_wordmark,
)


class _Tty(io.StringIO):
    def isatty(self):
        return True


class _Pipe(io.StringIO):
    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Block structure and reference letterforms
# ---------------------------------------------------------------------------

def test_wordmark_is_six_aligned_rows():
    rows = WORDMARK_TEXT.splitlines()
    assert len(rows) == 6
    assert all(row and row == row.rstrip() for row in rows)  # no trailing ws
    assert _WORDMARK_WIDTH == max(len(row) for row in rows)
    # Fits 100+ column terminals with room to spare.
    assert 80 <= _WORDMARK_WIDTH <= 100


def test_wordmark_uses_reference_style_vocabulary():
    for glyph in ("█", "═", "║", "╔", "╗", "╚", "╝"):
        assert glyph in WORDMARK_TEXT
    # Distinctive reference details (guard against transcription rot).
    assert "██╔████╔██" in WORDMARK_TEXT  # M segmented middle
    assert "╚═╝  ╚═╝" in WORDMARK_TEXT  # R leg
    assert "╚██████╗" in WORDMARK_TEXT  # C open lower-right
    assert "███████╗" in WORDMARK_TEXT  # E full bars


def test_wordmark_builder_is_deterministic():
    assert _build_wordmark() == WORDMARK_TEXT
    assert _build_wordmark("CODE DUMPER") == WORDMARK_TEXT
    with pytest.raises(KeyError):
        _build_wordmark("code dumper")  # uppercase design only


def test_green_and_reset_constants():
    assert WORDMARK_GREEN == "\x1b[1;32m"
    assert WORDMARK_RESET == "\x1b[0m"


# ---------------------------------------------------------------------------
# Color policy
# ---------------------------------------------------------------------------

def test_color_enabled_matrix():
    assert _color_enabled(_Tty(), {}) is True
    assert _color_enabled(_Pipe(), {}) is False
    assert _color_enabled(_Tty(), {"NO_COLOR": "1"}) is False
    assert _color_enabled(_Pipe(), {"CLICOLOR_FORCE": "1"}) is False  # NO_COLOR wins below
    assert _color_enabled(_Tty(), {"TERM": "dumb"}) is False
    assert _color_enabled(_Pipe(), {"CLICOLOR_FORCE": "1"}) is True
    assert _color_enabled(_Tty(), {"CLICOLOR_FORCE": "0"}) is True  # tty still counts
    assert _color_enabled(None, {}) is False


def test_print_wordmark_colored_and_plain_exact():
    out = _Tty()
    assert print_wordmark(stream=out, env={}, color=True, width=200) == "color"
    assert out.getvalue() == f"{WORDMARK_GREEN}{WORDMARK_TEXT}{WORDMARK_RESET}\n"

    out = _Pipe()
    assert print_wordmark(stream=out, env={}, width=200) == "plain"
    assert out.getvalue() == WORDMARK_TEXT + "\n"
    assert "\x1b[" not in out.getvalue()


def test_print_wordmark_param_overrides_policy():
    assert print_wordmark(stream=_Pipe(), env={}, color=True,
                          width=200) == "color"
    assert print_wordmark(stream=_Tty(), env={}, color=False,
                          width=200) == "plain"


def test_print_wordmark_skips_narrow_terminals():
    out = _Tty()
    assert print_wordmark(stream=out, env={"CLICOLOR_FORCE": "1"},
                          width=80) == "skipped"
    assert out.getvalue() == ""
    # Boundary: exact fit still renders.
    out = _Tty()
    assert print_wordmark(stream=out, env={}, color=True,
                          width=_WORDMARK_WIDTH) == "color"
    assert WORDMARK_TEXT in out.getvalue()


def test_print_wordmark_survives_broken_streams():
    calls = []

    class _Broken(_Tty):
        def write(self, text):
            calls.append(text)
            raise OSError("closed")

    assert print_wordmark(stream=_Broken(), env={}, color=True,
                          width=200) == "skipped"
    # Style reset was attempted even though rendering failed.
    assert any(text == WORDMARK_RESET for text in calls)

    class _Unencodable(_Tty):
        encoding = "cp1252"

        def write(self, text):
            raise UnicodeEncodeError("cp1252", text, 0, 1, "nope")

    assert print_wordmark(stream=_Unencodable(), env={}, color=True,
                          width=200) == "skipped"


def test_ensure_utf8_output_never_raises():
    _ensure_utf8_output(object())

    class _BadReconfig:
        def reconfigure(self, **kwargs):
            raise RuntimeError("denied")

    _ensure_utf8_output(_BadReconfig())  # swallowed


# ---------------------------------------------------------------------------
# No competing renderer
# ---------------------------------------------------------------------------

def test_no_image_renderer_remains():
    with pytest.raises(ImportError):
        import codedumper.logo  # noqa: F401
