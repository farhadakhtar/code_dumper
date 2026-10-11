"""Tests for the image-backed terminal logo (`codedumper/logo.py`).

- The bundled asset is the genuine `logo.png` artwork (provenance hash).
- The stdlib PNG decoder handles the real file and rejects bad input.
- Terminal capability detection gates true-color art with a safe fallback.
- Narrow windows scale down; tiny windows skip the art.
- Missing/invalid assets and unwritable streams never crash the menu.
- The packaged wheel carries the asset; resolution is CWD-independent.
"""

import io
import os
import struct
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

import codedumper
from codedumper import logo
from codedumper.logo import (
    LOGO_SOURCE_SHA256,
    LogoError,
    decode_png_rgba,
    fit_size,
    logo_asset_path,
    png_info,
    print_launch_logo,
    render_half_blocks,
    render_logo_for_width,
    terminal_supports_truecolor,
)


# ---------------------------------------------------------------------------
# Asset provenance and loading
# ---------------------------------------------------------------------------

def test_bundled_logo_matches_official_source():
    import hashlib
    path = logo_asset_path()
    assert path is not None and path.is_file()
    assert path.name == "logo.png"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == LOGO_SOURCE_SHA256


def test_bundled_logo_inspection():
    info = png_info(logo_asset_path().read_bytes())  # type: ignore[union-attr]
    assert info["width"] == 882
    assert info["height"] == 232
    assert info["bit_depth"] == 8
    assert info["color_type_name"] == "truecolor+alpha"
    assert info["interlace"] == 0


def test_logo_asset_resolves_outside_repository(tmp_path: Path, monkeypatch):
    """Asset lookup must not depend on the current working directory."""
    monkeypatch.chdir(tmp_path)
    path = logo_asset_path()
    assert path is not None
    assert path.parent.name == "codedumper"
    assert str(tmp_path) not in str(path)


def test_logo_missing_asset_returns_none(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(logo, "logo_asset_path", lambda: None)
    assert render_logo_for_width(80) is None
    assert print_launch_logo(stream=io.StringIO()) is False


def test_logo_invalid_asset_falls_back(tmp_path: Path):
    bad = tmp_path / "logo.png"
    bad.write_bytes(b"definitely not a png file")
    assert render_logo_for_width(80, asset=bad) is None


# ---------------------------------------------------------------------------
# PNG decoder: real asset pixels + synthetic edge cases
# ---------------------------------------------------------------------------

def _make_png(width, height, color_type, rows, trns=b"", interlace=0):
    """Build a minimal in-memory PNG (filter-type-0 rows)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, interlace)
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    idat = zlib.compress(raw)
    out = [b"\x89PNG\r\n\x1a\n"]

    def chunk(typ, payload):
        return (struct.pack(">I", len(payload)) + typ + payload
                + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF))
    out.append(chunk(b"IHDR", ihdr))
    if trns:
        out.append(chunk(b"tRNS", trns))
    out.append(chunk(b"IDAT", idat))
    out.append(chunk(b"IEND", b""))
    return b"".join(out)


def test_decode_real_asset_pixel_content():
    width, height, rgba = decode_png_rgba(logo_asset_path().read_bytes())  # type: ignore[union-attr]
    assert (width, height) == (882, 232)
    assert len(rgba) == width * height * 4

    def px(x, y):
        o = (y * width + x) * 4
        return rgba[o], rgba[o + 1], rgba[o + 2], rgba[o + 3]

    # Dark background in a corner.
    assert sum(px(4, 4)[:3]) < 60
    # Bright metallic silver inside the CODE lettering (upper-left area).
    bright = [px(x, y) for y in range(30, 90, 6) for x in range(60, 260, 8)]
    assert sum(1 for r, g, b, _ in bright if r > 150 and g > 150 and b > 150) > 5
    # Purple-to-blue treatment inside DUMP (right-hand area).
    purples = [px(x, y) for y in range(30, 120, 6) for x in range(480, 800, 8)]
    assert sum(1 for r, g, b, _ in purples if b > 120 and b > r + 30) > 5


def test_decode_supported_color_types():
    # Grayscale: mid-gray pixel -> opaque RGB triple.
    w, h, px = decode_png_rgba(_make_png(2, 1, 0, [[128, 200]]))
    assert (w, h) == (2, 1)
    assert px == bytes((128, 128, 128, 255, 200, 200, 200, 255))
    # Truecolor.
    w, h, px = decode_png_rgba(_make_png(1, 1, 2, [[10, 20, 30]]))
    assert px == bytes((10, 20, 30, 255))
    # Grayscale + alpha.
    w, h, px = decode_png_rgba(_make_png(1, 1, 4, [[10, 77]]))
    assert px == bytes((10, 10, 10, 77))
    # Grayscale with tRNS key (0 transparent).
    w, h, px = decode_png_rgba(
        _make_png(2, 1, 0, [[0, 9]], trns=struct.pack(">H", 0)))
    assert px == bytes((0, 0, 0, 0, 9, 9, 9, 255))
    # Truecolor with tRNS key (pure red transparent; keys are 16-bit).
    w, h, px = decode_png_rgba(
        _make_png(2, 1, 2, [[255, 0, 0, 0, 1, 2]],
                  trns=struct.pack(">HHH", 65535, 0, 0)))
    assert px == bytes((255, 0, 0, 0, 0, 1, 2, 255))


def test_decode_rejects_bad_input():
    with pytest.raises(LogoError):
        decode_png_rgba(b"hello world")
    with pytest.raises(LogoError):
        decode_png_rgba(b"\x89PNG\r\n\x1a\nTRUNC")
    # Interlaced images are refused (would need Adam7 deinterlacing).
    blob = _make_png(1, 1, 2, [[1, 2, 3]], interlace=1)
    with pytest.raises(LogoError, match="interlaced"):
        decode_png_rgba(blob)
    # Unknown filter type.
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x09" + bytes((1, 2, 3))
    idat = zlib.compress(raw)

    def chunk(typ, payload):
        return (struct.pack(">I", len(payload)) + typ + payload
                + struct.pack(">I", zlib.crc32(typ + payload) & 0xFFFFFFFF))
    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    with pytest.raises(LogoError, match="filter"):
        decode_png_rgba(blob)
    with pytest.raises(LogoError):
        png_info(b"nope")


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

class _Tty(io.StringIO):
    def isatty(self):
        return True


class _Pipe(io.StringIO):
    def isatty(self):
        return False


class _BrokenStream(io.StringIO):
    def isatty(self):
        raise OSError("no tty info")


def test_capability_matrix():
    assert terminal_supports_truecolor(_Pipe(), {}) is False
    assert terminal_supports_truecolor(_BrokenStream(), {}) is False
    assert terminal_supports_truecolor(_Tty(), {"NO_COLOR": "1"}) is False
    assert terminal_supports_truecolor(_Tty(), {"TERM": "dumb"}) is False
    assert terminal_supports_truecolor(_Tty(), {"TERM": "xterm"}) is False
    assert terminal_supports_truecolor(_Tty(), {"WT_SESSION": "abc"}) is True
    assert terminal_supports_truecolor(
        _Tty(), {"COLORTERM": "truecolor"}) is True
    assert terminal_supports_truecolor(
        _Tty(), {"TERM_PROGRAM": "vscode"}) is True


# ---------------------------------------------------------------------------
# Sizing, rendering structure, narrow windows
# ---------------------------------------------------------------------------

def test_fit_preserves_aspect_and_caps():
    # fit_size returns (cols, downscaled image rows); the renderer pairs
    # image rows into half as many character rows (rounded up).
    assert fit_size(882, 232, 80) == (80, 11)
    assert fit_size(882, 232, 40) == (40, 6)
    cols, rows = fit_size(882, 232, 400)
    assert rows <= logo.MAX_ART_ROWS
    assert cols <= 400
    # Never upscale: tiny source stays tiny.
    assert fit_size(10, 10, 200) == (10, 5)


def test_render_structure_and_row_parity():
    art = render_logo_for_width(80)
    assert art is not None
    rows = art.split("\n")
    assert len(rows) == 6  # 11 downscaled rows paired into 6 character rows
    for row in rows:
        assert row.endswith(logo.RESET)
        assert row.count("\u2584") == 80
        assert "38;2;" in row and "48;2;" in row
    # Odd row counts pair the last row against black.
    small = bytes((255, 255, 255, 255)) * (4 * 3)
    odd = render_half_blocks(small, 4, 3)
    assert odd.count("\n") == 1  # two character rows
    assert "48;2;0;0;0m" in odd.split("\n")[1]


def test_narrow_window_skips_art():
    assert render_logo_for_width(39) is None
    assert render_logo_for_width(10) is None
    art = render_logo_for_width(40)
    assert art is not None
    assert len(art.split("\n")) == 3  # 6 downscaled rows, paired


def test_print_fallback_never_raises():
    assert print_launch_logo(stream=_Pipe()) is False
    assert print_launch_logo(stream=_BrokenStream()) is False

    class _Unwritable(_Tty):
        def write(self, _):
            raise UnicodeEncodeError("utf-8", "", 0, 1, "nope")

    assert print_launch_logo(stream=_Unwritable()) is False


# ---------------------------------------------------------------------------
# Launch integration: version line, no duplicated identity text
# ---------------------------------------------------------------------------

def test_menu_version_is_dynamic(monkeypatch, capsys):
    from codedumper.cli import run_interactive_menu
    monkeypatch.setattr(codedumper, "__version__", "9.9.9-test")
    with patch("builtins.input", side_effect=["7"]):
        assert run_interactive_menu() == 0
    assert "v9.9.9-test" in capsys.readouterr().out


def test_packaging_declares_logo_asset():
    repo_root = Path(__file__).resolve().parent.parent
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'codedumper = ["logo.png"]' in pyproject
    manifest = (repo_root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "codedumper/logo.png" in manifest


# ---------------------------------------------------------------------------
# Fallback reasons are identifiable (diagnose_launch_logo)
# ---------------------------------------------------------------------------

def test_diagnose_reasons_cover_every_fallback():
    from codedumper.logo import diagnose_launch_logo
    wt = {"WT_SESSION": "session-guid"}

    d = diagnose_launch_logo(stream=_Pipe(), env={})
    assert (d.shown, d.reason) == (False, "not-a-tty")

    d = diagnose_launch_logo(stream=_Tty(), env={"NO_COLOR": "1"})
    assert (d.shown, d.reason) == (False, "no-color")

    d = diagnose_launch_logo(stream=_Tty(), env={"TERM": "dumb"})
    assert (d.shown, d.reason) == (False, "dumb-terminal")

    d = diagnose_launch_logo(stream=_Tty(), env={"TERM": "xterm"})
    assert (d.shown, d.reason) == (False, "no-truecolor-indicators")
    assert "TERM" in d.detail  # tells the user what was inspected

    d = diagnose_launch_logo(stream=_Tty(), env=wt, width=10)
    assert (d.shown, d.reason) == (False, "narrow-window")

    d = diagnose_launch_logo(stream=_Tty(), env=wt, width=100)
    assert (d.shown, d.reason) == (True, "shown")


def test_diagnose_asset_and_decode_failures(monkeypatch, tmp_path: Path):
    from codedumper.logo import diagnose_launch_logo
    wt = {"WT_SESSION": "session-guid"}

    monkeypatch.setattr(logo, "logo_asset_bytes", lambda *a, **k: None)
    d = diagnose_launch_logo(stream=_Tty(), env=wt, width=100)
    assert (d.shown, d.reason) == (False, "asset-missing")

    bad = tmp_path / "logo.png"
    bad.write_bytes(b"not a png")
    monkeypatch.setattr(logo, "logo_asset_bytes",
                        lambda *a, **k: bad.read_bytes())
    d = diagnose_launch_logo(stream=_Tty(), env=wt, width=100)
    assert (d.shown, d.reason) == (False, "decode-failed")


def test_new_capability_indicators():
    assert terminal_supports_truecolor(_Tty(), {"WT_PROFILE": "{guid}"}) is True
    assert terminal_supports_truecolor(_Tty(), {"ConEmuANSI": "ON"}) is True
    assert terminal_supports_truecolor(_Tty(), {"TERM": "xterm-direct"}) is True
    assert terminal_supports_truecolor(_Tty(), {"TERM": "mintty"}) is True
    assert terminal_supports_truecolor(
        _Tty(), {"TERM_PROGRAM": "WindowsTerminal"}) is True
    assert terminal_supports_truecolor(
        _Tty(), {"TERM_PROGRAM": "Tabby"}) is True
    # Still conservative everywhere else.
    assert terminal_supports_truecolor(_Tty(), {"TERM": "xterm"}) is False
    assert terminal_supports_truecolor(_Tty(), {"TERM": "vt100"}) is False
    assert terminal_supports_truecolor(_Tty(), {}) is False


def test_encoding_fallback_and_reconfigure():
    from codedumper.logo import _ensure_block_encodable, diagnose_launch_logo
    wt = {"WT_SESSION": "session-guid"}

    class _Latin1Tty(_Tty):
        encoding = "cp1252"

        def write(self, _):
            raise UnicodeEncodeError("cp1252", "", 0, 1, "nope")

    # cp1252 cannot encode ▄ and this stream cannot reconfigure: honest refusal.
    ok, detail = _ensure_block_encodable(_Latin1Tty())
    assert ok is False and "cp1252" in detail
    d = diagnose_launch_logo(stream=_Latin1Tty(), env=wt, width=100)
    assert (d.shown, d.reason) == (False, "encoding")
    assert "chcp" in d.detail

    # Same codepage, but reconfigurable (e.g. a real console): art proceeds.
    written = []

    class _ReconfigurableTty(_Tty):
        encoding = "cp1252"

        def reconfigure(self, encoding=None, **kwargs):
            self.encoding = encoding or "utf-8"

        def write(self, text):
            text.encode(self.encoding, errors="strict")
            written.append(text)
            return len(text)

    ok, detail = _ensure_block_encodable(_ReconfigurableTty())
    assert ok is True and "reconfigured" in detail
    assert print_launch_logo(stream=_ReconfigurableTty(), width=100) is True
    assert any("\u2584" in chunk for chunk in written)


def test_asset_bytes_survives_non_file_installs(monkeypatch):
    """Zip-style installs expose no plain file; byte access still works."""
    import importlib.resources as real_resources
    real_png = logo_asset_path()
    assert real_png is not None

    class _FakeTrav:
        def is_file(self):
            return False

        def read_bytes(self):
            return real_png.read_bytes()

    class _FakeFiles:
        def joinpath(self, _):
            return _FakeTrav()

    monkeypatch.setattr(real_resources, "files", lambda *a, **k: _FakeFiles())
    data = logo.logo_asset_bytes()
    assert data is not None and data[:8] == b"\x89PNG\r\n\x1a\n"


def test_debug_env_prints_reason_without_spam(monkeypatch, capsys):
    monkeypatch.setenv(logo.LOGO_DEBUG_ENV_VAR, "1")
    assert print_launch_logo(stream=_Pipe()) is False
    assert "reason=not-a-tty" in capsys.readouterr().err

    monkeypatch.delenv(logo.LOGO_DEBUG_ENV_VAR)
    assert print_launch_logo(stream=_Pipe()) is False
    assert capsys.readouterr().err == ""
