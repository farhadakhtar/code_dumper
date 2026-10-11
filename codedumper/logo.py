"""Terminal logo renderer backed by the bundled ``logo.png`` artwork.

The official CodeDumper logo (``codedumper/logo.png``, byte-identical to the
repository-root ``logo.png`` source) is rendered with true-color ANSI
half-block cells (``▄`` carries two image rows: foreground = top pixel,
background = bottom pixel). This is a character-cell approximation, not
pixel-perfect reproduction:

- Downscaling to terminal columns necessarily softens fine detail such as
  the small tagline and ``v1.0.0`` label baked into the artwork.
- Output requires a true-color, UTF-8 capable terminal (e.g. Windows
  Terminal). Legacy consoles, pipes, and ``NO_COLOR``/``dumb`` terminals
  get a graceful plain fallback (menu only, no fake replacement logo).
- The aspect ratio is preserved (no stretching or clipping); narrow
  windows scale the art down, and very narrow windows skip it.
- Every fallback path reports a machine-readable reason through
  :func:`diagnose_launch_logo` (reasons also asserted in tests). Set
  ``CODEDUMPER_LOGO_DEBUG=1`` to print the reason to stderr on real
  launches; normal launches stay silent.

Standard library only: ``zlib`` for DEFLATE, hand-rolled PNG unfiltering
for 8-bit non-interlaced images (gray / gray+alpha / truecolor /
truecolor+alpha). No third-party imaging dependency.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Tuple

LOGO_FILENAME = "logo.png"
# Provenance: sha256 of the repository-root source image this asset was
# copied from (copy is byte-identical; the original is never modified).
LOGO_SOURCE_SHA256 = "2490db09391001e9472cd34812fa030a40e29d43f88293fcb0a42f6be394ac79"
# Opt-in stderr diagnostic for real launches (never printed otherwise).
LOGO_DEBUG_ENV_VAR = "CODEDUMPER_LOGO_DEBUG"

HALF_BLOCK = "\u2584"  # LOWER HALF BLOCK
ESC = "\x1b"
RESET = "\x1b[0m"

MAX_ART_ROWS = 24
MIN_TERM_COLS = 40


class LogoError(Exception):
    """Raised when the logo asset is missing, corrupt, or unsupported."""


# ---------------------------------------------------------------------------
# Asset location (works from source checkout and installed wheel)
# ---------------------------------------------------------------------------

def logo_asset_path() -> Optional[Path]:
    """Return the bundled logo path, or ``None`` if it is unavailable."""
    try:
        from importlib import resources as importlib_resources
        candidate = importlib_resources.files("codedumper").joinpath(LOGO_FILENAME)
        if candidate.is_file():
            return Path(str(candidate))
    except Exception:
        pass
    try:
        fallback = Path(__file__).with_name(LOGO_FILENAME)
        if fallback.is_file():
            return fallback
    except OSError:
        pass
    return None


def logo_asset_bytes(asset: Optional[Path] = None) -> Optional[bytes]:
    """Read the bundled logo bytes, or ``None`` when unavailable.

    Uses ``importlib.resources`` byte access first so zipped or otherwise
    non-filesystem installs work too — never assumes the asset is a plain
    file on disk, and never touches the current working directory.
    """
    if asset is not None:
        try:
            data = asset.read_bytes()
            return data or None
        except OSError:
            return None
    try:
        from importlib import resources as importlib_resources
        traversable = importlib_resources.files("codedumper").joinpath(LOGO_FILENAME)
        try:
            data = traversable.read_bytes()
            if data:
                return bytes(data)
        except (OSError, ValueError):
            pass
    except Exception:
        pass
    try:
        fallback = Path(__file__).with_name(LOGO_FILENAME)
        if fallback.is_file():
            data = fallback.read_bytes()
            return data or None
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Minimal PNG decoder (8-bit, non-interlaced; types 0/2/4/6)
# ---------------------------------------------------------------------------

def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw: bytes, width: int, height: int, bytes_per_pixel: int) -> bytes:
    stride = width * bytes_per_pixel
    out = bytearray(width * height * bytes_per_pixel)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        if pos >= len(raw):
            raise LogoError("truncated PNG image data")
        filtr = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if len(line) != stride:
            raise LogoError("truncated PNG scanline")
        if filtr == 1:  # Sub
            for i in range(bytes_per_pixel, stride):
                line[i] = (line[i] + line[i - bytes_per_pixel]) & 0xFF
        elif filtr == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filtr == 3:  # Average
            for i in range(stride):
                a = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filtr == 4:  # Paeth
            for i in range(stride):
                a = line[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                b = prev[i]
                c = prev[i - bytes_per_pixel] if i >= bytes_per_pixel else 0
                line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
        elif filtr != 0:
            raise LogoError(f"unknown PNG filter type {filtr}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return bytes(out)


def _apply_trns(pixel: bytearray, color_type: int, trns: Optional[bytes]) -> bytearray:
    """Apply tRNS transparency, always returning RGBA (types 0 and 2)."""
    if color_type == 0:
        key = None
        if trns is not None and len(trns) >= 2:
            key = struct.unpack(">H", trns[:2])[0] >> 8
        res = bytearray()
        for gray in pixel:
            res += bytes((gray, gray, gray,
                          0 if (key is not None and gray == key) else 255))
        return res
    if color_type == 2:
        key = None
        if trns is not None and len(trns) >= 6:
            raw_key = struct.unpack(">HHH", trns[:6])
            key = (raw_key[0] >> 8, raw_key[1] >> 8, raw_key[2] >> 8)
        res = bytearray()
        for i in range(0, len(pixel), 3):
            triple = (pixel[i], pixel[i + 1], pixel[i + 2])
            res += bytes(triple)
            res.append(0 if (key is not None and triple == key) else 255)
        return res
    return pixel


def decode_png_rgba(data: bytes) -> Tuple[int, int, bytes]:
    """Decode PNG bytes to ``(width, height, RGBA bytes)``.

    Supports 8-bit non-interlaced grayscale / gray+alpha / truecolor /
    truecolor+alpha, including tRNS transparency. Raises :class:`LogoError`
    for anything else (including interlaced images).
    """
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LogoError("not a PNG image")
    pos = 8
    width = height = 0
    bit_depth = color_type = 0
    seen_ihdr = False
    idat_parts: List[bytes] = []
    trns: Optional[bytes] = None
    plte: Optional[bytes] = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        chunk_type = data[pos + 4:pos + 8].decode("latin1")
        chunk_data = data[pos + 8:pos + 8 + length]
        if len(chunk_data) != length:
            raise LogoError("truncated PNG chunk")
        if chunk_type == "IHDR":
            if len(chunk_data) != 13:
                raise LogoError("bad IHDR chunk")
            width, height, bit_depth, color_type, comp, filt, interlace = \
                struct.unpack(">IIBBBBB", chunk_data)
            if comp != 0 or filt != 0:
                raise LogoError("unsupported PNG compression/filter method")
            if interlace != 0:
                raise LogoError("interlaced PNG is not supported")
            if bit_depth != 8:
                raise LogoError(f"unsupported bit depth {bit_depth}")
            if color_type not in (0, 2, 4, 6):
                raise LogoError(f"unsupported color type {color_type}")
            seen_ihdr = True
        elif chunk_type == "PLTE":
            plte = bytes(chunk_data)
        elif chunk_type == "tRNS":
            trns = bytes(chunk_data)
        elif chunk_type == "IDAT":
            idat_parts.append(bytes(chunk_data))
        elif chunk_type == "IEND":
            break
        pos += 12 + length
    if not seen_ihdr or width <= 0 or height <= 0:
        raise LogoError("missing or invalid IHDR")
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error as exc:
        raise LogoError(f"DEFLATE error: {exc}")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    pixels = bytearray(_unfilter(raw, width, height, channels))

    if color_type == 3:
        # Palette expansion (defensive; our asset is truecolor+alpha).
        if plte is None or len(plte) % 3 != 0:
            raise LogoError("bad PLTE chunk")
        entries = len(plte) // 3
        alpha_table = None
        if trns is not None:
            alpha_table = bytes(trns) + bytes([255] * (entries - len(trns)))
        expanded = bytearray()
        for index in pixels:
            if index >= entries:
                raise LogoError("palette index out of range")
            expanded += plte[index * 3:index * 3 + 3]
            expanded.append(alpha_table[index] if alpha_table else 255)
        pixels = expanded
    elif color_type in (0, 2):
        pixels = _apply_trns(pixels, color_type, trns)
    elif color_type == 4:
        # gray+alpha -> RGBA
        expanded = bytearray()
        for i in range(0, len(pixels), 2):
            gray, alpha = pixels[i], pixels[i + 1]
            expanded += bytes((gray, gray, gray, alpha))
        pixels = expanded
    # color_type 6 (and everything converted above) is RGBA here.

    expected = width * height * 4
    if len(pixels) != expected:
        raise LogoError("decoded pixel size mismatch")
    return width, height, bytes(pixels)


def png_info(data: bytes) -> Dict[str, object]:
    """Return ``width``/``height``/``bit_depth``/``color_type``/``interlace``."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LogoError("not a PNG image")
    (length,) = struct.unpack(">I", data[8:12])
    if data[12:16] != b"IHDR" or length != 13:
        raise LogoError("missing IHDR")
    width, height, bit_depth, color_type, _, _, interlace = \
        struct.unpack(">IIBBBBB", data[16:29])
    names = {0: "grayscale", 2: "truecolor", 3: "palette",
             4: "grayscale+alpha", 6: "truecolor+alpha"}
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "color_type_name": names.get(color_type, f"unknown-{color_type}"),
        "interlace": interlace,
        "bytes": len(data),
    }


# ---------------------------------------------------------------------------
# Terminal capability detection
# ---------------------------------------------------------------------------

_TRUECOLOR_TERMS = {
    "xterm-kitty", "alacritty", "foot", "wezterm", "kitty",
    "xterm-direct", "mintty", "cygwin", "contour", "rio",
}
_TRUECOLOR_TERM_PROGRAMS = {
    "vscode", "WezTerm", "ghostty", "iTerm.app", "Warp", "Hyper",
    "WindowsTerminal", "Tabby",
}


def _stream_is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _check_indicators(env) -> Tuple[bool, str, str]:
    """Evaluate environment indicators.

    Returns ``(ok, reason, detail)`` where ``reason`` is ``""`` when true-color
    output is indicated, otherwise a stable fallback-reason code.
    """
    if env.get("NO_COLOR"):
        return False, "no-color", "NO_COLOR is set"
    term = (env.get("TERM") or "").lower()
    if term in ("dumb", "unknown"):
        return False, "dumb-terminal", f"TERM={env.get('TERM')!r}"
    if env.get("WT_SESSION"):
        return True, "", "WT_SESSION (Windows Terminal)"
    if env.get("WT_PROFILE"):
        return True, "", "WT_PROFILE (Windows Terminal)"
    if (env.get("ConEmuANSI") or "").upper() == "ON":
        return True, "", "ConEmuANSI=ON (ConEmu/Cmder)"
    if (env.get("COLORTERM") or "").lower() in ("truecolor", "24bit"):
        return True, "", f"COLORTERM={env.get('COLORTERM')!r}"
    program = env.get("TERM_PROGRAM") or ""
    if program in _TRUECOLOR_TERM_PROGRAMS:
        return True, "", f"TERM_PROGRAM={program!r}"
    if term in _TRUECOLOR_TERMS:
        return True, "", f"TERM={env.get('TERM')!r}"
    inspected = ("WT_SESSION/WT_PROFILE/COLORTERM/TERM_PROGRAM unset; "
                 f"TERM={env.get('TERM')!r}")
    return False, "no-truecolor-indicators", inspected


def terminal_supports_truecolor(stream=None, env=None) -> bool:
    """Decide whether true-color half-block art can be shown.

    Conservative on purpose: legacy conhost (classic PowerShell/CMD),
    pipes, ``NO_COLOR``, and ``dumb`` terminals all report ``False`` and
    get the plain menu fallback. ``stream``/``env`` are injectable for
    tests. Use :func:`diagnose_launch_logo` to learn *why* a session
    falls back.
    """
    if env is None:
        env = os.environ
    if stream is None:
        stream = sys.stdout
    if not _stream_is_tty(stream):
        return False
    ok, _, _ = _check_indicators(env)
    return ok


def terminal_width(default: int = 80, env=None) -> int:
    """Best-effort terminal column count (respects ``COLUMNS``)."""
    try:
        import shutil
        return shutil.get_terminal_size((default, 24)).columns or default
    except (AttributeError, ValueError, OSError):
        return default


# ---------------------------------------------------------------------------
# Downscale + true-color half-block rendering
# ---------------------------------------------------------------------------

def fit_size(image_width: int, image_height: int, term_cols: int,
             max_rows: int = MAX_ART_ROWS) -> Tuple[int, int]:
    """Fit the image into ``term_cols`` columns preserving aspect ratio.

    Returns ``(cols, char_rows)`` where each character row covers two image
    rows. Never upscales beyond the source pixels.
    """
    cols = max(1, min(image_width, term_cols))
    rows = max(1, -(-cols * image_height // (image_width * 2)))
    if rows > max_rows:
        rows = max_rows
        cols = max(1, (rows * 2 * image_width) // image_height)
    return cols, rows


def downscale_rgba(pixels: bytes, width: int, height: int,
                   cols: int, rows: int) -> bytes:
    """Box-average ``pixels`` to ``cols`` x ``rows`` RGBA.

    Semi-transparent samples are composited onto black (the artwork's own
    dark background), so edges never glow against the terminal.
    """
    out = bytearray(cols * rows * 4)
    for ty in range(rows):
        y0 = ty * height // rows
        y1 = max(y0 + 1, (ty + 1) * height // rows)
        for tx in range(cols):
            x0 = tx * width // cols
            x1 = max(x0 + 1, (tx + 1) * width // cols)
            red = green = blue = alpha = count = 0
            for y in range(y0, y1):
                base = y * width * 4
                for x in range(x0, x1):
                    o = base + x * 4
                    red += pixels[o]
                    green += pixels[o + 1]
                    blue += pixels[o + 2]
                    alpha += pixels[o + 3]
                    count += 1
            cover = (alpha / count) / 255.0
            o = (ty * cols + tx) * 4
            out[o] = int(red / count * cover)
            out[o + 1] = int(green / count * cover)
            out[o + 2] = int(blue / count * cover)
            out[o + 3] = 255
    return bytes(out)


def render_half_blocks(small: bytes, cols: int, rows: int) -> str:
    """Render downscaled RGBA as true-color ``▄`` half-block rows."""
    lines: List[str] = []
    for y in range(0, rows, 2):
        top = y * cols * 4
        bottom = top + cols * 4 if y + 1 < rows else None
        cells: List[str] = []
        for x in range(cols):
            o = top + x * 4
            r1, g1, b1 = small[o], small[o + 1], small[o + 2]
            if bottom is None:
                r2 = g2 = b2 = 0
            else:
                q = bottom + x * 4
                r2, g2, b2 = small[q], small[q + 1], small[q + 2]
            cells.append(
                f"{ESC}[38;2;{r1};{g1};{b1};48;2;{r2};{g2};{b2}m{HALF_BLOCK}"
            )
        lines.append("".join(cells) + RESET)
    return "\n".join(lines)


def render_logo_for_width(term_cols: int, max_rows: int = MAX_ART_ROWS,
                          asset: Optional[Path] = None) -> Optional[str]:
    """Render the bundled logo for ``term_cols`` columns, or ``None``.

    Returns ``None`` when the asset is missing/unreadable/unsupported or
    the window is too narrow — callers then use the plain menu fallback.
    """
    if term_cols < MIN_TERM_COLS:
        return None
    try:
        data = logo_asset_bytes(asset)
        if not data:
            return None
        width, height, rgba = decode_png_rgba(data)
        cols, rows = fit_size(width, height, term_cols, max_rows)
        small = downscale_rgba(rgba, width, height, cols, rows)
        return render_half_blocks(small, cols, rows)
    except (OSError, LogoError, ValueError, struct.error, zlib.error,
            MemoryError, RecursionError):
        return None


@dataclass
class LaunchDiagnosis:
    """Machine-readable outcome of a launch-logo attempt (for tests)."""

    shown: bool
    reason: str = "shown"
    detail: str = ""


def _stream_encoding(stream) -> Optional[str]:
    try:
        return stream.encoding or None
    except Exception:
        return None


def _ensure_block_encodable(stream) -> Tuple[bool, str]:
    """Make sure ``▄`` can be written to ``stream``.

    Tries (in order): the stream's own encoding, reconfiguring it to
    UTF-8, and — when the encoding is unknown — an optimistic proceed
    (the guarded write below still converts failures into a fallback).
    Returns ``(ok, detail)``.
    """
    encoding = _stream_encoding(stream)
    if encoding is not None:
        try:
            HALF_BLOCK.encode(encoding, errors="strict")
            return True, ""
        except (LookupError, UnicodeEncodeError, TypeError):
            pass
    reconfig = getattr(stream, "reconfigure", None)
    if callable(reconfig):
        try:
            reconfig(encoding="utf-8")
            return True, "reconfigured-output-to-utf-8"
        except Exception as exc:
            return False, f"reconfigure-failed: {exc}"
    if encoding is None:
        return True, "encoding-unknown-assumed-utf-8"
    return False, f"encoding-cannot-represent-block:{encoding}"


def diagnose_launch_logo(stream=None, env=None,
                         width: Optional[int] = None) -> LaunchDiagnosis:
    """Attempt the launch logo and report exactly what happened.

    Never raises and never prints: returns :class:`LaunchDiagnosis` with
    ``shown`` plus a stable ``reason`` (``shown`` / ``not-a-tty`` /
    ``no-color`` / ``dumb-terminal`` / ``no-truecolor-indicators`` /
    ``narrow-window`` / ``asset-missing`` / ``decode-failed`` /
    ``render-failed`` / ``encoding`` / ``write-failed``) and a human
    ``detail`` string. Powers both the silent normal path and the
    opt-in ``CODEDUMPER_LOGO_DEBUG`` diagnostic.
    """
    import sys as _sys
    out = stream if stream is not None else _sys.stdout
    environment = os.environ if env is None else env

    if not _stream_is_tty(out):
        return LaunchDiagnosis(False, "not-a-tty",
                               "stdout is piped, redirected, or closed")
    ok, reason, detail = _check_indicators(environment)
    if not ok:
        return LaunchDiagnosis(False, reason, detail)

    cols = width if width is not None else terminal_width()
    if cols < MIN_TERM_COLS:
        return LaunchDiagnosis(False, "narrow-window",
                               f"terminal width {cols} < {MIN_TERM_COLS}")

    data = logo_asset_bytes()
    if not data:
        return LaunchDiagnosis(False, "asset-missing",
                               "bundled logo.png not found via "
                               "importlib.resources nor source tree")
    try:
        width_px, height_px, rgba = decode_png_rgba(data)
    except (LogoError, ValueError, struct.error, zlib.error,
            MemoryError, RecursionError) as exc:
        return LaunchDiagnosis(False, "decode-failed", f"{exc}")
    except OSError as exc:
        return LaunchDiagnosis(False, "asset-unreadable", f"{exc}")

    try:
        cols, rows = fit_size(width_px, height_px, cols)
        small = downscale_rgba(rgba, width_px, height_px, cols, rows)
        art = render_half_blocks(small, cols, rows)
    except (ValueError, MemoryError, RecursionError) as exc:
        return LaunchDiagnosis(False, "render-failed", f"{exc}")

    enc_ok, enc_detail = _ensure_block_encodable(out)
    if not enc_ok:
        hint = ("set the console code page to UTF-8 "
                "(e.g. `chcp 65001`) and retry" if "encoding-cannot" in enc_detail
                else enc_detail)
        return LaunchDiagnosis(False, "encoding", hint)

    try:
        out.write(art + "\n")
        out.flush()
    except (OSError, UnicodeEncodeError, ValueError) as exc:
        return LaunchDiagnosis(False, "write-failed", f"{exc}")

    if enc_detail:
        return LaunchDiagnosis(True, "shown", enc_detail)
    return LaunchDiagnosis(True, "shown", f"{cols}x{rows // 2 + rows % 2} cells")


def print_launch_logo(stream=None, width: Optional[int] = None) -> bool:
    """Print the logo art when the terminal supports it.

    Returns ``True`` when art was written, ``False`` for the plain
    fallback. Never raises for I/O or encoding problems. Set
    ``CODEDUMPER_LOGO_DEBUG=1`` to also print the fallback reason to
    stderr (normal launches stay silent).
    """
    import sys as _sys
    diagnosis = diagnose_launch_logo(stream=stream, width=width)
    if os.environ.get(LOGO_DEBUG_ENV_VAR):
        try:
            print(f"[codedumper-logo] shown={diagnosis.shown} "
                  f"reason={diagnosis.reason} {diagnosis.detail}".rstrip(),
                  file=_sys.stderr)
        except OSError:
            pass
    return diagnosis.shown
