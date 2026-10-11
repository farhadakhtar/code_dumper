"""Atomic filesystem writer with overwrite protection for CodeDumper."""

import os
from pathlib import Path
from typing import Iterable


def _prepare_destination(output_path: Path, force: bool) -> Path:
    """Resolve, overwrite-check, and ensure parents. Returns resolved path."""
    resolved_path = output_path.resolve()

    if resolved_path.exists() and not force:
        raise FileExistsError(
            f"Destination file already exists: '{resolved_path}'. Use --force (-f) to overwrite."
        )

    # Ensure parent directory exists
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def _commit_temp_file(temp_file: Path, resolved_path: Path) -> None:
    """Atomically replace the destination with the temp file."""
    os.replace(temp_file, resolved_path)


def _discard_temp_file(temp_file: Path) -> None:
    if temp_file.exists():
        try:
            temp_file.unlink()
        except OSError:
            pass


def write_dump_file(output_path: Path, content: str, force: bool = False) -> int:
    """Atomically write Markdown content to output_path.

    Raises:
        FileExistsError: If output_path already exists and force is False.
        OSError: If filesystem operations fail.
    Returns:
        Total bytes written.
    """
    resolved_path = _prepare_destination(output_path, force)

    # Write to temporary file in the same directory for atomic rename
    temp_file = resolved_path.with_name(f".tmp.{os.getpid()}.{resolved_path.name}")
    try:
        content_bytes = content.encode("utf-8")
        with open(temp_file, "wb") as f:
            f.write(content_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replacement
        _commit_temp_file(temp_file, resolved_path)
        return len(content_bytes)
    except Exception:
        _discard_temp_file(temp_file)
        raise


def write_dump_stream(output_path: Path, parts: Iterable[str], force: bool = False) -> int:
    """Atomically write Markdown document pieces to output_path.

    Joins ``parts`` with ``"\\n"`` exactly like ``"\\n".join(parts)`` but
    encodes and writes incrementally, so the full document string is never
    materialized in memory. Output is byte-identical to joining first.
    Uses the same overwrite guard, temp file, fsync, and atomic replace
    as :func:`write_dump_file`.

    Raises:
        FileExistsError: If output_path already exists and force is False.
        OSError: If filesystem operations fail.
    Returns:
        Total bytes written.
    """
    resolved_path = _prepare_destination(output_path, force)

    temp_file = resolved_path.with_name(f".tmp.{os.getpid()}.{resolved_path.name}")
    try:
        total_bytes = 0
        with open(temp_file, "wb") as f:
            first = True
            for part in parts:
                if not first:
                    f.write(b"\n")
                    total_bytes += 1
                first = False
                data = part.encode("utf-8")
                f.write(data)
                total_bytes += len(data)
            f.flush()
            os.fsync(f.fileno())

        _commit_temp_file(temp_file, resolved_path)
        return total_bytes
    except Exception:
        _discard_temp_file(temp_file)
        raise
