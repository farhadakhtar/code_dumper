# Product Requirements Document (PRD): CodeDumper

**Document Version:** 2.1.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + working implementation (v1.1.0)
**File:** `docs/PRD.md`

*v2.1.0 changes: specified menu (options 1–7) with image-backed launch
art, plain-text (`.txt`) default output contract, `--format markdown`
opt-in, outside-project default location with output self-exclusion,
update-dump flow, and updater module with honest unavailable state.*

---

## 1. Product Overview

### 1.1 Product Name and Purpose

**CodeDumper** is a cross-platform command-line tool that scans a project
directory, builds a readable directory tree, collects eligible source and
text files, and exports everything into a single, structured plain-text
file (`<project-name>.txt`). A Markdown rendering remains available via
`--format markdown`.

### 1.2 Problem Statement

Sharing a multi-file codebase with an AI assistant, researcher, teammate, or
reviewer is friction-heavy:

- Manually opening dozens of files to copy context is slow and error-prone.
- Directory structure and file relationships are lost in chat transcripts.
- Credential files (`.env`, private keys) are easily pasted by accident.
- Binary assets and huge files bloat prompts and break token budgets.
- Beginners face a wall of flags; existing dumps go stale; staying updated
  requires manual reinstall steps.

### 1.3 Proposed Solution

Typing `codedumper` opens a guided menu (get a dump, update a dump, open
GitHub, check for updates, exit). Dumps default to plain `.txt` outside the
scanned project, with secrets excluded, binaries skipped, atomic writes,
and honest update checks against official GitHub releases. Direct commands
(`codedumper dump ...`) serve scripts and automation. All statistics shown
are real scan results; nothing is fabricated.

### 1.4 Product Vision

**One command. One organized document. Your codebase, clearly presented.**

### 1.5 Scope and Boundaries

- **In Scope:** Local directory scanning, directory-tree rendering,
  plain-text and Markdown export, interactive menu, `dump` subcommand,
  exclusion and safety rules, preview mode, dump refresh with overwrite
  confirmation, browser opener for the official repository, self-update
  check + verified install, progress reporting, exit codes, automated
  tests (network/install always mocked).
- **Out of Scope:** Uploading or transmitting code to any external service
  or LLM API; git network operations for CodeDumper itself (except reading
  release metadata over HTTPS); code execution, minification, or
  transformation; multiple export formats beyond text/Markdown;
  token-count estimates; incremental export; configuration profiles;
  standalone executables; `.codedumperignore` support.
- **Companion (preserved, not in scope):** The existing `autocommit`
  Git-watcher package is retained as-is.

---

## 2. Users and Use Cases

### 2.1 Target Users

1. **AI-assisted developers:** Export a project to feed complete context to an
   AI assistant without manual copy-paste.
2. **Beginners:** Get a first dump through a guided menu with no flags to
   learn.
3. **Teammates, researchers, and reviewers:** Read or review a whole codebase
   from a single document; refresh stale dumps safely.
4. **Contributors:** Extend or fix CodeDumper following its docs and tests.

### 2.2 Key Workflows

- **W-1 Get a dump (menu `1`):** User runs `codedumper` in a project
  (wordmark launch), picks `1`, accepts (or overrides) the default
  `<name>.txt` path outside the project, receives the file plus a
  real-counts summary.
- **W-2 Dump another (menu `2`):** User picks `2`, enters a project path,
  and gets its dump the same way.
- **W-3 Preview (menu `3`):** Dry-run scan of the current directory with
  real counts; nothing is written.
- **W-4 Update a dump (menu `4`):** The tool finds the project's `.txt`
  dump, confirms, and regenerates it atomically. Missing dump → offer to
  create; legacy `.md` → left untouched with an explanatory note.
- **W-5 Session exclusions (menu `5`):** Extra glob patterns apply to dumps
  in the same session.
- **W-5 Direct dump:** `codedumper dump ./my-project` writes
  `my-project.txt` outside the target.
- **W-6 Custom output:** `codedumper dump ./my-project --output ./exports/codebase.txt`.
- **W-7 Preview:** `codedumper dump ./my-project --dry-run` reports without
  writing.
- **W-8 Tailored dump:** `codedumper dump ./my-project --include-hidden
  --exclude node_modules --max-file-size 1MB --format markdown`.

---

## 3. Functional Requirements

| Requirement ID | Title | Description | Priority |
|---|---|---|---|
| **FR-001** | Interactive menu (1–7) + wordmark | Bare `codedumper` prints the fixed green wordmark (or the plain block when color is unsupported, or nothing when the terminal is narrower than the block) with centered version/tagline lines, then the specified menu (dump current / dump another / preview / update / exclusions / help / exit); invalid input re-prompts; EOF exits 0; Ctrl+C exits 130; piped stdin works. | High |
| **FR-002** | `dump` subcommand | `codedumper dump [PATH]` dumps the given project; `PATH` defaults to `.`. | High |
| **FR-003** | Recursive scanning | Recursively discover directories/files under the project root. | High |
| **FR-004** | Deterministic ordering | Stable sorted processing; identical inputs → byte-identical files (timing is console-only). | High |
| **FR-005** | Project structure tree | Plain-text `PROJECT STRUCTURE` section with the sorted directory tree. | High |
| **FR-006** | Plain-text file sections (default) | Each eligible file gets `FILE: <path>`, `Language:`, `Size:`, `Lines:` lines, verbatim content, and an `END FILE:` marker. No `#`/`##` headings, no code fences. | High |
| **FR-007** | Markdown opt-in | `--format markdown` renders `# Codebase Dump`, `## Project Structure`, fenced `## File:` sections with dynamic `max(3, run+1)` fences. | Medium |
| **FR-008** | Binary detection | Extension list, null bytes, or >30% non-text bytes in an 8 KB sample → skip + report. | High |
| **FR-009** | Size limit (`--max-file-size`) | Default `1MB`; units `B/KB/MB/GB`; invalid rejected (exit 1). `--max-size` alias retained. Oversized files skipped + reported. | High |
| **FR-010** | Default noise exclusions | VCS internals, dependency/caches, build outputs, lockfiles pruned by default. | High |
| **FR-011** | Sensitive-file protection | Credential patterns **always** excluded — even with `--include-hidden`. Only filenames/reasons reported, never secret values. | Critical |
| **FR-012** | Hidden-file handling | Dotfiles excluded by default; `--include-hidden` includes them (FR-011 still applies). | High |
| **FR-013** | Custom exclusions | Repeatable `--exclude PATTERN` (glob on filename + relative path). | Medium |
| **FR-014** | Output selection + outside rule | `--output` (`-o`) selects destination; default `<name>.txt` (or `.md` with `--format markdown`) placed **outside** the scanned project when practical (CWD for foreign targets; parent dir for CWD targets; CWD fallback at filesystem root). The output file itself is always excluded from its own scan (`OUTPUT_FILE_SELF`). | High |
| **FR-015** | Overwrite protection | Existing output never silently overwritten: non-interactive refuses (exit 1) without `--force`; menu asks explicit confirmation. Atomic temp-file + `os.replace` writes. | High |
| **FR-016** | Dry-run preview | `--dry-run` scans and reports real statistics without writing. | Medium |
| **FR-017** | Honest reporting | `EXCLUDED FILES` section + console counts (discovered/included/excluded/sensitive/duration/output) show measured values only. | High |
| **FR-018** | Help and version | `codedumper --help`, `codedumper dump --help`, `codedumper --version` work, exit 0. | High |
| **FR-019** | Exit codes | `0` ok · `1` usage/validation · `2` I/O error · `130` interrupt. | High |
| **FR-020** | Backward compatibility | Legacy `codedumper [TARGET_DIR] [options]` keeps working. | Medium |
| **FR-021** | Update-dump flow | Option 2 locates the project's `.txt` dump, confirms, regenerates; missing → offer create; legacy `.md` → untouched + note; unrelated files never overwritten without confirmation. | High |
| **FR-022** | GitHub opener | Option 3 opens the official repository URL; browser failure → helpful error. | Low |
| **FR-023** | Update check | Option 4 reads the installed version, queries the official GitHub Releases `.../releases/latest` source (stable only), and reports up-to-date / available / unavailable (with manual route when no release is published). No release is ever fabricated. | High |
| **FR-024** | Verified install | On confirmation, install only an allow-listed wheel asset from the official release via pip (no shell, no executed downloads); report success only when the re-read installed version matches; editable installs keep the manual route; all failures report + manual route. | High |
| **FR-025** | Updater isolation | The updater is a separate module; offline dumping never needs network; tests mock all network/install behavior. | High |

---

## 4. Non-Functional Requirements

| Requirement ID | Category | Requirement | Acceptance Criteria |
|---|---|---|---|
| **NFR-001** | Performance | Fast scanning/export on steady-state trees. | Warm scan + stream-write of a 1,000-file project (~15 MB text) completes in under 4.0 s (measured ~1.0 s on quiet reference hardware, ~2.5 s on a heavily contended box with byte-identical code; best-of-3 filters scheduling noise). Cold first-touch scans are environmental (OS/antivirus) and carry no hard gate; correctness is still tested. Verified by `tests/test_performance.py`. |
| **NFR-002** | Memory efficiency | Bounded memory footprint via streaming writes. | Peak allocation under 100 MB for total text up to ~50 MB (tested at 48.8 MB → 50.3 MB tracemalloc peak). Larger scales are explicitly out of scope for v1 (see §7.2). Verified by `tests/test_performance.py`. |
| **NFR-003** | Portability | Windows, Linux, macOS on Python 3.10+. | POSIX-normalized (`/`) relative paths in output; `\n` line endings; executed here on 3.11/3.12 (no 3.10 interpreter available). Install verified in a clean virtualenv from a wheel; CLI runs from any working directory; `python -m codedumper` is the documented PATH workaround. |
| **NFR-004** | Security & privacy | Safe defaults, offline dumping. | No network transmission by dump flows (updater HTTPS reads release metadata only); symlinks never followed; source tree read-only; filename-only exclusion reporting; secret-content disclaimer in docs; no credentials in code; untrusted update sources refused. |
| **NFR-005** | Reliability | No partial/corrupt outputs; no source mutation. | Atomic temp-file write + `os.replace`; source checksums identical before/after; interrupted updates cannot corrupt the previous dump. |
| **NFR-006** | Determinism | Identical file output across runs. | Two runs with identical inputs produce identical SHA-256 of the dump file (wall-clock timing is console-only); streamed bytes equal in-memory render. |
| **NFR-007** | Dependency minimization | Standard library only at runtime. | Zero third-party runtime dependencies for `codedumper` including the updater (`urllib`, `webbrowser`, `importlib.metadata` are stdlib). |
| **NFR-008** | Usability | Clean beginner-friendly CLI. | Exact specified menu; `[INFO]` progress and `[OK]` completion lines; errors on stderr; confirmations before destructive actions. |
| **NFR-009** | Testability | Automated pytest suite on temp projects. | Covers menus, txt/markdown contracts, update flows, updater states (mocked), paths with spaces, CWD independence, permissions, symlinks, fences, overwrite/args; no real credentials or network/installs. |
| **NFR-010** | Robust encoding | Mixed-encoding projects never crash the run. | UTF-8 first, `latin-1`/`replace` fallback; unreadable files recorded as omissions. |
| **NFR-011** | Licensing honesty | No false license claims. | A real `LICENSE` file exists matching the `pyproject.toml` license field. |

---

## 5. User Stories and Acceptance Criteria

### US-1: First dump from the menu

**Story:** As a beginner, I run `codedumper`, pick `1`, accept the default
path, and get `<project>.txt` next to my project.
**Acceptance:**
1. Menu matches the specified launch screen (logo or plain fallback, options `1..7`).
2. Output starts with `CODEBASE DUMP: <name>` and contains
   `PROJECT STRUCTURE`, one `FILE:`/`END FILE:` pair per eligible file,
   and no `#`/`##` headings or fences.
3. Console shows real counts, duration, output path, and `[OK]`.

### US-2: Refresh a stale dump

**Story:** As a developer, I pick `2`, confirm, and my `.txt` is regenerated
without risking other files.
**Acceptance:**
1. Existing dump confirmed before overwrite; decline preserves it byte-for-byte.
2. Missing dump offers creation; legacy `.md` is never modified.

### US-3: Secrets stay out

**Story:** As a developer, `.env`, keys, binaries, and oversized files never
reach the dump under any flag combination.
**Acceptance:**
1. Such files never appear in a `FILE:` section — even with `--include-hidden`.
2. Each appears in `EXCLUDED FILES` with a reason; no secret value is printed.

### US-4: Honest updates

**Story:** As a user, option `4` tells me the truth about releases.
**Acceptance:**
1. With no published releases: unavailable state + manual route, zero changes.
2. Up-to-date: clear report, zero changes. Available (mocked): version
   shown, confirmation required, success only on verified version match.

---

## 6. CLI Contract (normative)

```text
codedumper                              # interactive menu (options 1-7 + logo)
codedumper dump [PATH] [OPTIONS]        # primary non-interactive form
codedumper [PATH] [OPTIONS]             # legacy form
```

`dump` options: `PATH` (default `.`) · `-o, --output PATH` ·
`--format {text,markdown}` (default `text`) · `-f, --force` ·
`-e, --exclude PATTERN` (repeatable) · `--include-hidden` ·
`--max-file-size SIZE` (`--max-size` alias, default `1MB`) · `--no-tree` ·
`--dry-run` · `-h/--help` · `-v/--version`. Default output per FR-014.
Exit codes per FR-019.

---

## 7. Scope Management

### 7.1 MVP (v1.1)

Menu 1–7 with image-backed launch art, `.txt` default + Markdown opt-in, outside-project defaults with
self-exclusion, update-dump flow, GitHub opener, release check with honest
unavailable state, pytest suite, install docs, `LICENSE`.

### 7.2 Post-MVP (deferred)

`.codedumperignore`, token-count estimates, incremental export/diff,
configuration profiles, standalone executables, two-pass render for >50 MB
text workloads, published-release install path (activates automatically
once a stable GitHub release with a wheel asset exists).

### 7.3 Explicitly Out of Scope

Network upload/API transmission, git operations for CodeDumper itself,
code transformation, relational-database persistence, PyPI publication
(undescribed as working until published + verified), prerelease auto-install.

---

## 8. Risks, Assumptions, and Decisions

- **R-1 Secret leakage:** Filename rules cannot catch every secret.
  *Mitigation:* conservative blacklist + review-before-sharing disclaimer.
- **R-2 No releases published:** The updater's install path cannot trigger
  live. *Decision:* honest unavailable state + manual route; full install
  machinery proven by mocked tests (FR-023/FR-024).
- **R-3 Untrusted updates:** Forged metadata could point elsewhere.
  *Mitigation:* HTTPS GitHub API source, strict asset-URL allow-list,
  wheel-only pip installs, version-match verification.
- **R-4 Editable installs:** Pip-overwriting a checkout corrupts workflows.
  *Decision:* non-PyPI methods always take the manual route.
- **R-5 Menu vs scripting:** Interactive prompts block automation.
  *Decision:* all menu capabilities have non-interactive direct-command
  equivalents.
- **A-1** Default output per FR-014. **A-2** Symlinks never followed.
  **A-3** Dumping is offline-only. **A-4** Single-write default format is
  plain text.

---

## 9. Acceptance Criteria (release gate)

1. Menu matches the specified banner/options; invalid/EOF/Ctrl+C behave.
2. `.txt` default verified: no `#`/`##`/fences, verbatim source, markers,
   metadata, exclusion section; `--format markdown` still correct.
3. Secrets/noise/binaries/oversize excluded under all flag combinations.
4. Update flows: confirm/decline/missing/legacy all correct; updater states
   (up-to-date/newer/unavailable/prerelease/malformed/network/untrusted)
   covered by mocked tests; no project modification by any flow.
5. Full pytest suite passes; E2E verified for menu + direct forms.
6. `LICENSE` present; clean-venv wheel install works; CLI runs from any
   working directory; no PyPI/release claims beyond reality.
