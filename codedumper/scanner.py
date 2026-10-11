"""Recursive directory scanner and collection coordinator for CodeDumper."""

import time
from pathlib import Path
from typing import List, Tuple
from codedumper.classifier import decode_bytes_safely, detect_language, is_binary_bytes
from codedumper.filter import ExclusionEngine
from codedumper.models import FileItem, OmissionRecord, ScanConfig, ScanResult
from codedumper.tree import generate_directory_tree


def scan_repository(config: ScanConfig) -> ScanResult:
    """Perform recursive deterministic scanning, filtering, and content ingestion."""
    start_time = time.perf_counter()
    target_dir = config.target_dir.resolve()
    project_name = target_dir.name or "repository"
    # Resolved once: the dump output itself must never be embedded, even
    # when it lives inside the scanned project (e.g. --output pointing
    # there, or a previous dump from an earlier run).
    output_resolved = config.output_path.resolve()
    output_name = output_resolved.name

    filter_engine = ExclusionEngine(
        user_patterns=config.exclude_patterns,
        include_hidden=config.include_hidden,
    )

    included_files: List[FileItem] = []
    omitted_files: List[OmissionRecord] = []
    total_discovered = 0

    # Recursive traversal helper
    def _scan_dir(current_dir: Path) -> None:
        nonlocal total_discovered
        try:
            # Deterministic sorting: directories first, then alphabetical by name
            entries = sorted(current_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower(), p.name))
        except PermissionError:
            try:
                rel = current_dir.relative_to(target_dir).as_posix()
            except ValueError:
                rel = current_dir.name
            omitted_files.append(OmissionRecord(rel_path=rel, reason="PERMISSION_DENIED", size=0))
            return
        except OSError as e:
            try:
                rel = current_dir.relative_to(target_dir).as_posix()
            except ValueError:
                rel = current_dir.name
            omitted_files.append(OmissionRecord(rel_path=rel, reason=f"OS_ERROR: {e}", size=0))
            return

        subdirectories: List[Path] = []
        files: List[Path] = []

        for entry in entries:
            total_discovered += 1
            try:
                rel_path = entry.relative_to(target_dir).as_posix()
            except ValueError:
                rel_path = entry.name

            if entry.is_dir():
                # Check directory exclusion
                skip_dir_reason = filter_engine.should_skip_directory(entry.name, rel_path)
                if skip_dir_reason is not None:
                    # Only record user-specified or sensitive exclusions in omission report
                    if not skip_dir_reason.startswith("DEFAULT_NOISE"):
                        omitted_files.append(OmissionRecord(rel_path=f"{rel_path}/", reason=skip_dir_reason, size=0))
                    continue

                if entry.is_symlink():
                    omitted_files.append(OmissionRecord(rel_path=f"{rel_path}/", reason="SYMLINK_DIRECTORY_NOT_FOLLOWED", size=0))
                    continue

                subdirectories.append(entry)
            elif entry.is_file():
                files.append(entry)

        # Process files in current directory
        for file_path in files:
            try:
                rel_path = file_path.relative_to(target_dir).as_posix()
            except ValueError:
                rel_path = file_path.name

            try:
                st = file_path.stat()
                file_size = st.st_size
            except OSError as e:
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason=f"STAT_ERROR: {e}", size=0))
                continue

            # Step 0: Never embed the dump output file itself.
            if file_path.name == output_name and file_path.resolve() == output_resolved:
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason="OUTPUT_FILE_SELF", size=file_size))
                continue

            # Step 1: Rule filtering (sensitive, noise, hidden, user glob, max size)
            skip_reason = filter_engine.should_skip_file(
                file_name=file_path.name,
                rel_path=rel_path,
                file_size=file_size,
                max_size_bytes=config.max_size_bytes,
            )
            if skip_reason is not None:
                # Omit default noise like .DS_Store from cluttering omission report if not needed,
                # but always report sensitive or user or size exclusions
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason=skip_reason, size=file_size))
                continue

            # Steps 2+3: Single read per file; classify the bytes, then decode.
            # (One open instead of two: binary sampling and text ingestion
            # share the same read.)
            try:
                with open(file_path, "rb") as f:
                    raw_bytes = f.read()
            except OSError as e:
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason=f"READ_ERROR: {e}", size=file_size))
                continue

            if is_binary_bytes(raw_bytes, suffix=file_path.suffix):
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason="BINARY_FILE", size=file_size))
                continue

            try:
                content, _ = decode_bytes_safely(raw_bytes)
                # Normalize line endings to \n
                content = content.replace("\r\n", "\n").replace("\r", "\n")
                lang = detect_language(file_path)
                line_count = len(content.splitlines())

                included_files.append(
                    FileItem(
                        path=file_path,
                        rel_path=rel_path,
                        size=file_size,
                        content=content,
                        language=lang,
                        line_count=line_count,
                    )
                )
            except OSError as e:
                omitted_files.append(OmissionRecord(rel_path=rel_path, reason=f"READ_ERROR: {e}", size=file_size))

        # Recurse into subdirectories
        for sub_dir in subdirectories:
            _scan_dir(sub_dir)

    _scan_dir(target_dir)

    # Generate tree
    tree_text = ""
    if not config.no_tree:
        tree_text = generate_directory_tree(target_dir, filter_engine)

    elapsed = time.perf_counter() - start_time

    # Sort included files deterministically by relative path
    included_files.sort(key=lambda f: f.rel_path.lower())
    omitted_files.sort(key=lambda o: o.rel_path.lower())

    return ScanResult(
        project_name=project_name,
        target_dir=target_dir,
        included_files=included_files,
        omitted_files=omitted_files,
        tree_text=tree_text,
        elapsed_seconds=elapsed,
        total_files_discovered=total_discovered,
    )
