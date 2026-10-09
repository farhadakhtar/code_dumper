# Technical Requirements Document (TRD): CodeDumper

**Document Version:** 1.0.0  
**Status:** Approved  
**Author:** Engineering Team  
**File:** `docs/TRD.md`  

---

## 1. Technology Stack

### 1.1 Evaluated and Selected Technologies
- **Runtime Environment:** Python 3.10+ (tested on Python 3.10, 3.11, 3.12).
- **CLI Framework:** Python Standard Library `argparse`.  
  *Rationale:* Provides standard GNU/POSIX-compliant argument parsing, automatic `--help`, type validation, and zero external dependency footprint.
- **Packaging System:** Modern `pyproject.toml` based on standard `setuptools.build_meta`. Exposes console entry point `codedumper = codedumper.cli:main`.
- **Filesystem Access:** Python Standard Library `pathlib.Path` supplemented by `os` for POSIX path normalization and atomic replacement (`os.replace`).
- **Binary Detection & Encoding:** Custom pure-Python heuristic sampling the first 8,192 bytes for null byte `\x00` and high ratio of non-printable ASCII control characters. Text decoding attempts strict `utf-8`, falling back to `utf-8` with error replacement or `latin-1`.
- **Markdown Serialization:** Streaming writer using dynamic multi-backtick fencing algorithm (`max(3, max_consecutive_backticks + 1)`).
- **Test Framework:** `pytest` (version 8.0+).

### 1.2 Dependency Footprint
- **Production Runtime Dependencies:** **0** (Zero third-party packages required). Uses strictly standard library modules (`pathlib`, `argparse`, `os`, `sys`, `dataclasses`, `typing`, `fnmatch`, `hashlib`, `tempfile`, `time`).
- **Development Dependencies:** `pytest>=8.0.0`.

---

## 2. Supported Platforms & Portability

| Operating System | Path Separator | End-of-Line Default | Special Platform Concerns |
|---|---|---|---|
| **Windows 10 / 11** | `\` normalized to `/` | `\r\n` converted to `\n` in dump | Case-insensitive filesystems, reserved filenames (`CON`, `PRN`, `NUL`), path length restrictions. |
| **Linux (Ubuntu / Fedora / Debian)** | `/` | `\n` | Case-sensitive filesystems, symbolic link loops, non-UTF-8 locale encodings. |
| **macOS (Darwin)** | `/` | `\n` | Unicode normalization (NFC vs. NFD in HFS+/APFS), case-insensitive default. |

**Platform Invariants:**
1. All paths emitted into the generated Markdown document and tree view must use standard forward slashes (`/`).
2. All line endings in the generated Markdown file must be normalized to standard Unix `\n` for consistent checksumming and cross-platform tokenization.
3. Full Unicode support for filenames and directory paths (e.g., spaces, accented characters, CJK characters).

---

## 3. Runtime Requirements

- **Python Interpreter:** Standard CPython 3.10, 3.11, or 3.12.
- **Execution Modes:**
  - Standalone installed CLI: `codedumper [args]`
  - Python module execution: `python -m codedumper [args]`
  - Direct script execution: `python /path/to/codedumper/cli.py [args]`
- **Memory Overhead:** Streaming design ensures maximum memory footprint is bounded by the size of the largest single file being rendered (typically < 10 MB).

---

## 4. CLI Contract

### 4.1 Invocation Syntax
```bash
codedumper [TARGET_DIR] [-o OUTPUT] [-f] [-e PATTERN ...] [--include-hidden] [--max-size SIZE] [--no-tree] [--dry-run] [-v] [-h]
```

### 4.2 Options and Default Values
- `TARGET_DIR` (Positional, Optional): Target directory to scan. Default: `.`
- `-o, --output` (Option, Optional): Path to output file. Default: `./<target_basename>.md`
- `-f, --force` (Flag, Optional): Overwrite existing output file without prompt. Default: `False`
- `-e, --exclude` (Option, Repeatable): Glob pattern to exclude (e.g. `-e "*.log" -e "docs/*"`). Default: `[]`
- `--include-hidden` (Flag, Optional): Include hidden files and folders starting with `.`. Default: `False`
- `--max-size` (Option, Optional): Maximum file size limit with unit suffix (`B`, `KB`, `MB`). Default: `1MB` (1,048,576 bytes)
- `--no-tree` (Flag, Optional): Suppress directory tree generation in the Markdown output. Default: `False`
- `--dry-run` (Flag, Optional): Execute traversal and summary reporting without writing to disk. Default: `False`
- `-v, --version` (Flag, Optional): Print version and exit with code `0`.
- `-h, --help` (Flag, Optional): Print usage instructions and exit with code `0`.

### 4.3 Standard Exit Codes
- `0`: Operation completed successfully.
- `1`: Invalid arguments, configuration errors, or destination file exists without `--force`.
- `2`: Filesystem I/O error or permission denied on target directory.
- `130`: KeyboardInterrupt / SIGINT received from user.

---

## 5. Filesystem Requirements

### 5.1 Traversal & Ordering
- Traversal must be recursive starting from `TARGET_DIR`.
- Traversal ordering must be deterministic: at every directory level, subdirectories and files must be sorted alphabetically by name.
- Symlinks pointing to directories or files must **not** be followed recursively to eliminate infinite loop traps and privilege escalation leaks.

### 5.2 Exclusion Rules & Precedence
1. **Critical Sensitive Patterns:** Always excluded regardless of `--include-hidden`:
   - `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa`, `id_rsa.*`, `id_ed25519*`, `*.p12`, `*.pfx`, `credentials.json`, `token.json`, `secrets.yaml`.
2. **Default Build & VCS Noise:**
   - Directories: `.git`, `.hg`, `.svn`, `node_modules`, `__pycache__`, `.pytest_cache`, `.venv`, `venv`, `env`, `dist`, `build`, `.egg-info`, `.idea`, `.vscode`.
   - Files: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `*.pyc`, `*.pyo`, `*.pyd`, `.DS_Store`, `Thumbs.db`.
3. **Hidden Files:**
   - Any path segment starting with `.` is skipped unless `--include-hidden` is passed.
4. **User Glob Patterns:**
   - Matched against relative paths using case-sensitive (or platform-consistent) `fnmatch`.
5. **Size Threshold:**
   - Any file larger than `max_size_bytes` is recorded as omitted with reason `EXCEEDS_MAX_SIZE`.
6. **Binary Detection:**
   - Sample first 8,192 bytes. If a null byte `\x00` is encountered, or more than 30% of bytes are non-printable non-whitespace ASCII control characters, classify as `BINARY` and omit.

---

## 6. Security Requirements

### 6.1 Defense Against Secret Leakage
- High-priority regex/glob patterns detect credential containers before reading contents.
- The omission report lists detected sensitive files by name and records reason as `SENSITIVE_CREDENTIAL`, allowing the user to verify that secrets were excluded.

### 6.2 Safe Filesystem Operations
- **Atomic File Writing:** Write output to a sibling temporary file (`.<filename>.tmp.<pid>`) and atomically replace the target using `os.replace`. If writing fails or is interrupted by SIGINT, the temporary file is deleted and the existing destination file remains intact.
- **Path Traversal Protection:** Output path and target path are resolved using `Path.resolve()`. CodeDumper verifies that output path does not inadvertently overwrite critical system paths.
- **Source Integrity:** The source repository is treated as strictly read-only. No temporary files or caches are created inside the target repository unless the output file is explicitly directed there.

---

## 7. Performance and Reliability

### 7.1 Performance Targets
- **Target:** Scan, filter, and render 1,000 files (< 50 MB total text) in under 2.0 seconds.
- **Memory Consumption:** Stream file contents directly to output buffers; peak RAM under 50 MB.
- **Graceful Interruption:** Register signal handler for `SIGINT` to cleanly clean up any temporary files and exit immediately with status `130`.

---

## 8. Testing and Quality Gates

The test suite must validate:
1. **Directory Traversal:** Flat directories, deep nesting, empty folders.
2. **Sorting Determinism:** Repeated runs yield identical output.
3. **Filtering:** Hidden files omitted by default, included with flag; custom globs.
4. **Secret Protection:** `.env`, `.pem`, and `id_rsa` excluded under all circumstances.
5. **Binary Detection:** Images (`.png`), binaries (`.exe`), compiled Python (`.pyc`).
6. **Dynamic Fencing:** Files containing backticks (```` ``` ````, ```` ```` ````) fenced properly.
7. **Size Limits:** Files larger than threshold omitted and noted in report.
8. **Collision Protection:** Refusal to overwrite existing file without `--force`.
9. **CLI Exit Codes:** Validating `0`, `1`, `2`, `130`.
10. **Atomic Writing:** Ensuring interrupted or failing writes do not leave corrupted files.

---

## 9. Dependency and Compatibility Policy

- Zero runtime external dependencies.
- Standard library modules only.
- Strict backwards compatibility across Python 3.10, 3.11, and 3.12.

---

## 10. Requirement Traceability Matrix (TRD to PRD)

| Technical Requirement | Originating PRD Requirement | Description |
|---|---|---|
| **TR-001** | FR-001 | Accept optional positional target directory argument |
| **TR-002** | FR-002, FR-003 | Recursive deterministic traversal using sorted pathlib generators |
| **TR-003** | FR-004 | ASCII tree generator formatting hierarchical nodes |
| **TR-004** | FR-005, FR-014 | Text ingestion with dynamic backtick fencing |
| **TR-005** | FR-006 | 8 KB header sampling for null-byte binary detection |
| **TR-006** | FR-007, FR-008 | Default exclusions for build artifacts and credential patterns |
| **TR-007** | FR-009, FR-010 | Hidden file toggle and repeatable custom `--exclude` globs |
| **TR-008** | FR-011 | Configurable `--max-size` with unit parser (`B`, `KB`, `MB`) |
| **TR-009** | FR-012, FR-013 | Configurable output path with overwrite check and `--force` |
| **TR-010** | FR-015 | Dry-run mode skipping file persistence |
| **TR-011** | FR-016 | Markdown and terminal omission telemetry reporting |
| **TR-012** | FR-017, FR-018 | CLI `--help`, `--version`, and compliant exit codes (`0, 1, 2, 130`) |
| **TR-013** | NFR-001, NFR-002 | Streaming file rendering and low memory footprint |
| **TR-014** | NFR-003, NFR-010 | Cross-platform POSIX path normalization and robust encoding fallback |
| **TR-015** | NFR-004, NFR-005 | Read-only source repository access and atomic temporary file writes |
| **TR-016** | NFR-006 | Deterministic byte-for-byte reproducibility |
| **TR-017** | NFR-007 | Zero third-party runtime dependencies |
| **TR-018** | NFR-009 | Automated test suite in `pytest` with >90% coverage |
