"""Atomic filesystem writer with overwrite protection for CodeDumper."""

import os
from pathlib import Path


def write_dump_file(output_path: Path, content: str, force: bool = False) -> int:
    """Atomically write Markdown content to output_path.

    Raises:
        FileExistsError: If output_path already exists and force is False.
        OSError: If filesystem operations fail.
    Returns:
        Total bytes written.
    """
    resolved_path = output_path.resolve()

    if resolved_path.exists() and not force:
        raise FileExistsError(
            f"Destination file already exists: '{resolved_path}'. Use --force (-f) to overwrite."
        )

    # Ensure parent directory exists
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temporary file in the same directory for atomic rename
    temp_file = resolved_path.with_name(f".tmp.{os.getpid()}.{resolved_path.name}")
    try:
        content_bytes = content.encode("utf-8")
        with open(temp_file, "wb") as f:
            f.write(content_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replacement
        os.replace(temp_file, resolved_path)
        return len(content_bytes)
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise
