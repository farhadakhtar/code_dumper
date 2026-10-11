# Technical Requirements Document (TRD): CodeDumper

**Document Version:** 2.1.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + `docs/PRD.md` (v2.0.0)
**File:** `docs/TRD.md`

---

## 1. Technology Stack

- **Runtime:** Python 3.10+ (executed here on 3.11 and 3.12; no 3.10
  interpreter was available in this environment, so 3.10 is supported per
  `requires-python` but not executed); CPython.
- **CLI:** Standard-library `argparse` with a `dump` subcommand + legacy
  positional form + interactive `input()` menu (options 1–5). *Rationale:*
  zero-dependency, testable, beginner-friendly with scriptable direct forms.
- **Filesystem:** `pathlib.Path` + `os.replace` (atomic write), `os.fsync`.
- **Matching:** `fnmatch` glob engine for `--exclude` patterns.
- **Binary/encoding:** 8,192-byte sample (null byte → binary; >30% non-text
  control bytes → binary); decode `utf-8` → `latin-1` → `utf-8/replace`;
  single read per file shared by classification and decoding.
- **Plain text (default):** `CODEBASE DUMP:` title, `PROJECT STRUCTURE`,
  verbatim `FILE:`/`END FILE:` sections, `EXCLUDED FILES` list.
- **Markdown (opt-in `--format markdown`):** dynamic fence
  `max(3, longest_backtick_run + 1)`; headings per PRD §1.3.
- **Browser:** stdlib `webbrowser` for the GitHub opener.
- **Self-update:** stdlib `urllib` (HTTPS GitHub Releases API) +
  `importlib.metadata` (version/method detection) + `subprocess` pip
  installs of allow-listed wheel files only. No new dependencies.
- **Packaging:** `pyproject.toml` (`setuptools.build_meta`, v1.1.0), console
  script `codedumper = codedumper.cli:main`, `readme = "README.md"`, MIT
  license with a real `LICENSE` file.
- **Tests:** `pytest>=8.0.0` on temporary projects only; network and package
  installation always mocked.

### 1.1 Dependency Footprint

- **Runtime:** **0** third-party packages (`pathlib`, `argparse`, `os`,
  `sys`, `dataclasses`, `fnmatch`, `re`, `hashlib`, `tempfile`, `time`,
  `shutil` for the watcher only).
- **Dev/test:** `pytest>=8.0.0`.
- **Companion-only:** `watchdog>=4.0.0`, `GitPython>=3.1.40` (for
  `autocommit`, never imported by `codedumper`).

### 1.2 Distribution

- **Build (offline-capable):** `python -m pip wheel . --no-deps
  --no-build-isolation -w dist/` produces a `py3-none-any` wheel using the
  local setuptools (verified 78.x). No network access required.
- **Install verification:** wheel installs in a clean virtualenv
  (`pip install <wheel>`); entry point `codedumper` plus the
  `python -m codedumper` fallback are both exercised from outside the repo.
- **Source of installs:** GitHub `https://github.com/farhadakhtar/code_dumper.git`
  only. PyPI installation must not be documented as working until a release
  is published **and** install-verified.
- **Never** install anything into, or write anything inside, a scanned
  project: dry-runs write nothing; real dumps default outside the target
  unless `--output` says otherwise.

---

## 2. Supported Platforms & Portability

| OS | Separator | EOL | Notes |
|---|---|---|---|
| Windows 10/11 | `\` → normalized `/` | `\r\n` → `\n` | Case-insensitive FS; reserved names; PATH-length limits |
| Linux | `/` | `\n` | Case-sensitive; symlink loops; non-UTF-8 locales |
| macOS | `/` | `\n` | NFC/NFD normalization; case-insensitive default |

**Invariants:** POSIX `/` paths in output; `\n` endings; Unicode filenames
(spaces, CJK, accents) supported; no network calls on any platform.

---

## 3. Runtime Requirements

- `pip install -e .` then `codedumper [--help|--version]`,
  `codedumper dump ...`, or bare `codedumper` (menu);
  `python -m codedumper ...` equivalent.
- Memory bounded by the largest single file (default cap 1 MB); no whole-repo
  buffering beyond the rendered document.

---

## 4. CLI Contract (normative)

```text
codedumper                              # interactive menu (FR-001)
codedumper dump [PATH] [OPTIONS]        # primary non-interactive form
codedumper [PATH] [OPTIONS]             # legacy form (FR-020)
```

| Option | `dump` form | Legacy form | Default |
|---|---|---|---|
| Project path (positional) | `PATH` | `target_dir` | `.` |
| Output | `-o, --output PATH` | same | `<project-dir-name>.txt` outside the target (parent dir for CWD targets) |
| Format | `--format {text,markdown}` | same | `text` (`.md` output with `markdown`) |
| Overwrite guard | `-f, --force` | same | `False` (refuse) |
| Extra excludes | `-e, --exclude PATTERN` (repeatable) | same | `[]` |
| Hidden files | `--include-hidden` | same | `False` (FR-011 still enforced) |
| Size cap | `--max-file-size SIZE` (`--max-size` alias) | `--max-size` (+ alias) | `1MB` |
| Tree toggle | `--no-tree` | same | `False` |
| Preview | `--dry-run` | same | `False` |
| Help / version | `-h/--help`, `-v/--version` (+ `dump --help`) | same | — |

**Size grammar:** `^(\d+(\.\d+)?)\s*([KMG]?B?)$` (case-insensitive),
bytes-per-unit `B=1, KB=1024, MB=1024², GB=1024³`; anything else (or `<= 0`)
is a validation error → exit `1`.

**Exit codes:** `0` ok · `1` usage/validation (bad path, bad size, exists
w/o `--force`) · `2` I/O error · `130` `Ctrl+C`.

**Menu contract:** exact banner + options `1..5` (get dump, update dump,
open GitHub, update check, exit); option 1 prompts for an output path
(default accepted on Enter); option 2 confirms before regenerating and
never touches unrelated files; option 3 opens the browser or errors
helpfully; option 4 runs the updater flow; `5`/EOF exits `0`; invalid
choice re-prompts; `KeyboardInterrupt` exits `130`.

**Update contract (`codedumper/updater.py`):** source of truth is
`https://api.github.com/farhadakhtar/code_dumper/releases/latest`
(stable releases only; prereleases/drafts never offered). States:
up-to-date / available / unavailable-with-manual-route. Installs only
allow-listed `.../releases/download/` wheel assets via pip argument-list
invocation, only for PyPI-method installs, only after explicit
confirmation, and success counts only on version-match re-read. Editable
installs always take the manual route. No credentials, no executed
downloads, temp-only writes, 15–30 s timeouts, 50 MB asset cap.

---

## 5. Filesystem Requirements

### 5.1 Traversal & Ordering

Recursive from project root; lexicographic sort per directory
(`(is_file, name.lower(), name)`); symlinked dirs/files never followed
(recorded as omissions); `max_depth` guard (25) for the tree view.

### 5.2 Exclusion Rules & Precedence

1. **Sensitive (unbypassable):** `.env`, `.env.*`, `*.pem`, `*.key`,
   `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `*.p12`, `*.pfx`, `*.crt`, `*.cer`,
   `credentials.*`, `secrets.*`, `token.json`, `auth.json`, `*.gpg` →
   `SENSITIVE_CREDENTIAL`.
2. **Default noise:** dirs `.git .hg .svn node_modules __pycache__
   .pytest_cache .mypy_cache .ruff_cache .venv venv env dist build .eggs
   .idea .vscode` (`*.egg-info` too); files `package-lock.json yarn.lock
   pnpm-lock.yaml poetry.lock *.pyc *.pyo *.pyd .DS_Store Thumbs.db` →
   `DEFAULT_NOISE_*`.
3. **Hidden** (any leading-`.` segment, unless `--include-hidden`) →
   `HIDDEN_*`.
4. **User globs** (CLI `--exclude`) → `USER_EXCLUDE_PATTERN: <pat>`.
5. **Size** (`> max_size_bytes`) → `EXCEEDS_MAX_SIZE`.
6. **Binary/encoding** (extension list, null byte, >30% non-text, unreadable)
   → `BINARY_FILE` / `READ_ERROR`.
7. **Self-output** (the dump file itself inside its target) →
   `OUTPUT_FILE_SELF` (checked before all other tiers).

---

## 6. Output Document Requirements

### 6.1 Plain text (default, `.txt`)

1. `CODEBASE DUMP: <project>` title.
2. `PROJECT STRUCTURE` tree (omitted with `--no-tree`).
3. One `FILE: <posix/relative/path>` block per eligible file:
   `Language:` / `Size:` (plain words) / `Lines:` lines, verbatim content,
   `END FILE: <path>` marker. No `#`/`##` headings, no code fences.
4. `EXCLUDED FILES` list (`path | reason | size`) when omissions exist.
5. Deterministic bytes: no timestamps/durations inside the file.

### 6.2 Markdown (`--format markdown`, `.md`)

1. `# Codebase Dump: <project>` title.
2. `## Project Structure` fenced tree (omitted with `--no-tree`).
3. One `## File: <path>` section per eligible file with a language tag and
   dynamically sized fence.
4. `## Excluded Files` table when omissions exist.
5. Deterministic bytes: no timestamps/durations inside the file.

---

## 7. Security Requirements

- Offline dumping: no sockets, no uploads, no telemetry in dump flows.
  The updater reads release metadata over HTTPS only.
- Secret filenames/reasons only in reports; secret contents never printed,
  logged, or embedded.
- Atomic writes (`os.replace`); read-only source handling; output-outside-root
  allowed but never silently overwrites (FR-015); the dump file itself is
  always excluded from its own scan.
- Update safety: single documented release source; strict asset-URL
  allow-list; wheel-only pip installs without shell; no executed downloads;
  no credentials in code; editable installs keep the manual route; success
  only on verified version match; temp-only writes with cleanup.
- Docs carry the "review dumps before sharing" disclaimer (README + PRD R-1).

---

## 8. Performance and Reliability

- Warm steady-state scan + stream-write of 1,000 files (~15 MB text) in
  <2 s (measured ~1.0 s); ~50 MB text under 100 MB peak RAM (measured
  48.8 MB → 50.3 MB). Cold first-touch timing is environmental, not gated.
- `SIGINT` → temp-file cleanup, exit `130`.
- Disk-full / permission failures → exit `2`, destination untouched.

---

## 9. Testing and Quality Gates

Must cover (README §"Development and testing" + PRD NFR-009): empty/nested
projects; Win/Unix paths (incl. spaces); unicode names; binary/oversize;
secret exclusion (with `--include-hidden`); custom globs; permission/
unreadable files; symlinks/traversal; plain-text contract (no `#`/fences,
verbatim source, markers); Markdown opt-in + fence escaping; output
creation/overwrite/invalid args/invalid `--format`; default outside-project
location; output self-exclusion; **both** `dump` and legacy invocations;
**interactive menu** paths (`1..5`, invalid choice, EOF, Ctrl+C); update
flows (confirm/decline/missing/legacy); GitHub opener success/failure;
updater states (up-to-date/available/unavailable/prerelease/malformed/
network/untrusted) and install success/failure — all mocked, never real
network or installs; determinism via SHA-256 equality; `--max-file-size`
units + rejection; no project modification by any flow. Temp projects only;
no real secrets.

Performance/memory gates (NFR-001/002) are enforced by
`tests/test_performance.py` on the production streaming path
(scan → `iter_markdown_parts` → `write_dump_stream`):
warm 1,000-file run (~15 MB) under 2.0 s (measured ~1.0 s) after one
untimed warm-up pass; cold first-touch run asserted correct with a loose
<60 s regression guardrail (measured ~12 s on a Defender-guarded Windows
box; environmental, not gated); ~50 MB text under 100 MB tracemalloc peak
(measured 48.8 MB → 50.3 MB). Streamed bytes are asserted identical to
`render_markdown` output.

---

## 10. Traceability (TRD → PRD)

| TR | PRD | Design home |
|---|---|---|
| TR-001 | FR-001 | `cli.py` menu loop (1–5) |
| TR-002 | FR-002/FR-020 | `cli.py` `dump` subparser + legacy path |
| TR-003 | FR-003/FR-004 | `scanner.py` sorted recursion |
| TR-004 | FR-005 | `tree.py` |
| TR-005 | FR-006/FR-007 | `renderer.py` text parts + markdown fences |
| TR-006 | FR-008 | `classifier.py` 8 KB heuristic |
| TR-007 | FR-009 | `cli.py` size grammar + `filter.py` gate |
| TR-008 | FR-010/FR-011/FR-012/FR-013 | `filter.py` precedence chain |
| TR-009 | FR-014/FR-015 | `cli.py` defaults + `writer.py` atomic guard + self-exclusion |
| TR-010 | FR-016 | `cli.py` dry-run short-circuit |
| TR-011 | FR-017 | `renderer.py` + `reporter.py` |
| TR-012 | FR-018/FR-019 | `cli.py` flags + exit codes |
| TR-013 | NFR-001/002 | streaming renderer/writer |
| TR-014 | NFR-003/010 | POSIX/`\n` normalization + decode fallback |
| TR-015 | NFR-004/005 | read-only scan + atomic write + no-follow symlinks |
| TR-016 | NFR-006 | timing kept out of the file |
| TR-017 | NFR-007 | `pyproject.toml` zero-dep check |
| TR-018 | NFR-009 | `tests/` suite |
| TR-019 | NFR-011 | `LICENSE` + license metadata |
| TR-020 | FR-021/FR-022 | `cli.py` update flow + browser opener |
| TR-021 | FR-023/FR-024/FR-025 | `updater.py` check/install isolation |
