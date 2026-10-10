# Product Requirements Document (PRD): CodeDumper

**Document Version:** 2.0.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` (working copy: interactive CLI + `dump` subcommand contract)
**File:** `docs/PRD.md`

---

## 1. Product Overview

### 1.1 Product Name and Purpose

**CodeDumper** is a cross-platform command-line tool that scans a project
directory, builds a readable directory tree, collects eligible source and
text files, and exports everything into a single, structured Markdown file
(`<project-name>.md`).

### 1.2 Problem Statement

Sharing a multi-file codebase with an AI assistant, researcher, teammate, or
reviewer is friction-heavy:

- Manually opening dozens of files to copy context is slow and error-prone.
- Directory structure and file relationships are lost in chat transcripts.
- Credential files (`.env`, private keys) are easily pasted by accident.
- Binary assets and huge files bloat prompts and break token budgets.
- Source files containing triple backticks corrupt naive Markdown exports.

### 1.3 Proposed Solution

One command produces one organized document: a `# Codebase Dump` title, a
`## Project Structure` tree, one `## File: <path>` section per eligible file
with a language-tagged, fence-escaped code block, and a `## Excluded Files`
report. An interactive menu (`codedumper` with no arguments) and a
non-interactive subcommand (`codedumper dump ...`) serve beginners and
automation equally. All statistics shown are real scan results; nothing is
fabricated.

### 1.4 Product Vision

**One command. One organized document. Your codebase, clearly presented.**

### 1.5 Scope and Boundaries

- **In Scope:** Local directory scanning, directory-tree rendering, text
  collection, Markdown export, interactive menu, `dump` subcommand, exclusion
  and safety rules, preview mode, progress reporting, exit codes, automated
  tests.
- **Out of Scope:** Uploading or transmitting code to any external service or
  LLM API; git network operations; code execution, minification, or
  transformation; multiple export formats; token-count estimates; incremental
  export; configuration profiles; standalone executables; `.codedumperignore`
  support (all deferred to future releases per `README.md` roadmap).
- **Companion (preserved, not in scope):** The existing `autocommit`
  Git-watcher package is retained as-is. It is not part of the CodeDumper
  requirements and is not modified by this PRD.

---

## 2. Users and Use Cases

### 2.1 Target Users

1. **AI-assisted developers:** Export a project to feed complete context to an
   AI assistant without manual copy-paste.
2. **Teammates, researchers, and reviewers:** Read or review a whole codebase
   from a single document.
3. **Contributors:** Extend or fix CodeDumper following its docs and tests.

### 2.2 Key Workflows

- **W-1 Interactive dump (current project):** User runs `codedumper`, sees the
  `CODEDUMPER CLI` menu, selects `1`. The tool scans, applies exclusions,
  collects files, writes `my-application.md`, and prints real counts plus
  `[OK] Markdown export completed successfully.`
- **W-2 Interactive dump (another project):** Menu option `2` prompts for a
  project path, then dumps it.
- **W-3 Interactive preview:** Menu option `3` runs a dry-run on the current
  directory and shows counts without writing a file.
- **W-4 Configure exclusions:** Menu option `4` prompts for extra
  comma-separated glob patterns used for subsequent menu-driven dumps in the
  same session.
- **W-5 Direct dump:** `codedumper dump ./my-project` writes `my-project.md`.
- **W-6 Custom output:** `codedumper dump ./my-project --output ./exports/codebase.md`.
- **W-7 Preview:** `codedumper dump ./my-project --dry-run` prints findings
  without writing a file.
- **W-8 Tailored dump:** `codedumper dump ./my-project --include-hidden
  --exclude node_modules --exclude .venv --max-file-size 1MB`.

---

## 3. Functional Requirements

| Requirement ID | Title | Description | Priority |
|---|---|---|---|
| **FR-001** | Interactive menu on bare invocation | Running `codedumper` with no arguments launches the `CODEDUMPER CLI` menu with options `1..6` (dump current, dump another, preview, configure exclusions, help, exit). | High |
| **FR-002** | `dump` subcommand | `codedumper dump [PATH]` dumps the given project; `PATH` defaults to `.` (current directory). | High |
| **FR-003** | Recursive scanning | The system recursively discovers directories and files under the project root. | High |
| **FR-004** | Deterministic ordering | Entries are processed in a stable sorted order so repeated runs on unchanged projects produce identical Markdown files (byte-for-byte, excluding console-only timing). | High |
| **FR-005** | Project Structure tree | The Markdown contains a `## Project Structure` section with an indented, sorted directory tree. | High |
| **FR-006** | Per-file sections | Each eligible file gets a `## File: <relative/path>` heading and its content in a language-tagged code block (` ```python ` etc., derived from file extension). | High |
| **FR-007** | Fence escaping | Content containing backtick runs is wrapped in a longer fence (`max(3, longest_run + 1)` backticks) so exports never break. | High |
| **FR-008** | Binary detection | Files detected as binary (known binary extensions, null bytes, or >30% non-text bytes in an 8 KB sample) are skipped and reported. | High |
| **FR-009** | Size limit (`--max-file-size`) | `--max-file-size` sets the per-file limit (default `1MB`; units `B`, `KB`, `MB`, `GB`; invalid values are rejected with exit code `1`). Oversized files are skipped and reported. `--max-size` remains as a backward-compatible alias. | High |
| **FR-010** | Default noise exclusions | VCS internals (`.git`, `.hg`, `.svn`), dependency/caches (`node_modules`, `__pycache__`, `.pytest_cache`, `.venv`, `venv`, `env`, `dist`, `build`, `.idea`, `.vscode`), and lockfiles/noise files are pruned by default. | High |
| **FR-011** | Sensitive-file protection | Credential patterns (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `*.p12`, `*.pfx`, `credentials.*`, `secrets.*`, `token.json`) are **always** excluded — even with `--include-hidden`. Only filenames/reasons are reported, never secret values. | Critical |
| **FR-012** | Hidden-file handling | Dotfiles/dot-directories are excluded by default; `--include-hidden` includes them (FR-011 still applies). | High |
| **FR-013** | Custom exclusions | Repeatable `--exclude PATTERN` (glob matched against filename and relative path) plus menu option `4` session patterns. | Medium |
| **FR-014** | Output selection | `--output` (`-o`) selects the Markdown destination; default is `<project-dir-name>.md`. Missing parent directories are created. | High |
| **FR-015** | Overwrite protection | An existing output file is never silently overwritten: non-interactive mode fails with exit code `1` unless `--force` (`-f`) is given (atomic write via temp file + `os.replace`); menu mode asks for explicit confirmation. | High |
| **FR-016** | Dry-run preview | `--dry-run` (and menu option `3`) scans and reports real statistics without writing any file. | Medium |
| **FR-017** | Honest reporting | Both the Markdown (`## Excluded Files` table with path + reason) and the console (`Files discovered/included/excluded`, `Sensitive files skipped`, `[INFO]`/`[OK]` lines) show real measured values. Statistics are never fabricated; secret contents are never printed. | High |
| **FR-018** | Help and version | `codedumper --help`, `codedumper dump --help`, and `codedumper --version` work and exit `0`. | High |
| **FR-019** | Exit codes | `0` success · `1` usage/validation error (bad path, bad size, output exists without `--force`) · `2` filesystem I/O error · `130` user interrupt (`Ctrl+C`). | High |
| **FR-020** | Backward compatibility | The legacy direct form `codedumper [TARGET_DIR] [options]` (with `-o`, `-f`, `-e`, `--include-hidden`, `--max-size`, `--no-tree`, `--dry-run`) keeps working; `dump` is the documented primary form. | Medium |

---

## 4. Non-Functional Requirements

| Requirement ID | Category | Requirement | Acceptance Criteria |
|---|---|---|---|
| **NFR-001** | Performance | Fast scanning/export. | 1,000-file project (<50 MB text) completes in under 2.0 s on standard SSD hardware. |
| **NFR-002** | Memory efficiency | Bounded memory footprint. | Peak RAM under 100 MB for up to 500 MB of total text; per-file cap enforced by FR-009. |
| **NFR-003** | Portability | Windows, Linux, macOS on Python 3.10+. | POSIX-normalized (`/`) relative paths in output; `\n` line endings; verified on 3.10/3.11/3.12. |
| **NFR-004** | Security & privacy | Safe defaults, offline only. | No network transmission; symlinks never followed; source tree read-only; filename-only exclusion reporting; secret-content disclaimer in docs. |
| **NFR-005** | Reliability | No partial/corrupt outputs; no source mutation. | Atomic temp-file write + `os.replace`; source checksums identical before/after. |
| **NFR-006** | Determinism | Identical file output across runs. | Two runs with identical inputs produce identical SHA-256 of the Markdown file (wall-clock timing is console-only). |
| **NFR-007** | Dependency minimization | Standard library only at runtime. | Zero third-party runtime dependencies for `codedumper` (`watchdog`/`GitPython` remain companion-only for `autocommit`). |
| **NFR-008** | Usability | Clean professional CLI. | Menu banner + numbered options; `[INFO]` progress and `[OK]` completion lines; errors on stderr. |
| **NFR-009** | Testability | Automated pytest suite on temp projects. | Covers §7 list (empty dirs, paths, unicode, binary/size, secrets, globs, permissions, symlinks, fences, overwrite/args, interactive + non-interactive); no real credentials; no dumping of the repo's own secrets. |
| **NFR-010** | Robust encoding | Mixed-encoding projects never crash the run. | UTF-8 first, `latin-1`/`replace` fallback; unreadable files recorded as omissions. |
| **NFR-011** | Licensing honesty | No false license claims. | A real `LICENSE` file exists matching the `pyproject.toml` license field. |

---

## 5. User Stories and Acceptance Criteria

### US-1: Dump the current project from the menu

**Story:** As a developer, I run `codedumper`, pick `1`, and get `my-application.md` to share with an AI assistant.
**Acceptance:**
1. Menu matches the `README.md` banner/options (`1..6`).
2. Output starts with `# Codebase Dump: my-application` and contains `## Project Structure` plus one `## File:` section per eligible file.
3. Console shows real `Files discovered/included/excluded`, `Sensitive files skipped`, output path, and `[OK] Markdown export completed successfully.`

### US-2: Dump a specific project non-interactively

**Story:** As a developer, I run `codedumper dump ./my-project --output ./exports/codebase.md` in a script.
**Acceptance:**
1. The command exits `0` and writes the requested file with actual project contents.
2. `codedumper dump ./my-project --dry-run` writes nothing and still reports findings.

### US-3: Secrets and noise never leak into exports

**Story:** As a developer, I trust that `.env`, keys, certificates, `.git/`, `node_modules/`, binaries, and oversized files stay out of the dump.
**Acceptance:**
1. Such files never appear in a `## File:` section — even with `--include-hidden`.
2. Each appears in `## Excluded Files` with a reason; no secret value is printed anywhere.

### US-4: Fences and overwrite safety

**Story:** As a reviewer, pasted Markdown always renders; my existing files are never clobbered silently.
**Acceptance:**
1. A source file containing ```` ``` ```` is wrapped in a longer fence.
2. Existing output without `--force` (or without menu confirmation) aborts with exit `1` and preserves the old file.

---

## 6. CLI Contract (normative)

```text
codedumper                          # launch interactive menu
codedumper dump [PATH] [OPTIONS]    # non-interactive dump
codedumper [PATH] [OPTIONS]         # legacy direct form (FR-020)
```

`dump` options: `PATH` (default `.`) · `-o, --output PATH` ·
`-f, --force` · `-e, --exclude PATTERN` (repeatable) ·
`--include-hidden` · `--max-file-size SIZE` (`--max-size` alias, default `1MB`) ·
`--no-tree` (legacy-compat: omit `## Project Structure`) · `--dry-run` ·
`-h, --help` · `-v, --version`. Exit codes per FR-019.

---

## 7. Scope Management

### 7.1 MVP (v1.0 per README roadmap)

Menu + `dump` subcommand, scanning/tree/export, exclusion & safety rules,
preview mode, honest reporting, pytest suite, install docs, `LICENSE`.

### 7.2 Post-MVP (README roadmap, explicitly deferred)

`.codedumperignore`, multiple export formats, token-count estimates,
incremental export/diff, configuration profiles, standalone executables.

### 7.3 Explicitly Out of Scope

Network upload/API transmission, git operations for CodeDumper itself,
code transformation, relational-database persistence.

---

## 8. Risks, Assumptions, and Phase-1 Decisions

- **R-1 Secret leakage:** Filename rules cannot catch every secret
  (high-entropy strings inside normal files). *Mitigation:* conservative
  blacklist + docs disclaimer that users must review dumps before sharing.
- **R-2 New-vs-old contract drift:** `README.md` (working copy) redefines the
  CLI versus the v1.x implementation/docs. *Decision:* this PRD v2.0.0 follows
  the working-copy `README.md`; legacy flags stay as aliases (FR-020).
- **R-3 Menu option 4 underspecified:** *Decision:* session-scoped extra
  exclude patterns prompted at runtime (W-4).
- **R-4 Overwrite flag unspecified in README:** *Decision:* retain
  `--force`/`-f` + menu confirmation (FR-015); covered by "overwrite behavior"
  tests.
- **R-5 Exit codes unspecified in README:** *Decision:* retain `0/1/2/130`
  (FR-019).
- **R-6 Module layout:** README's suggested files are explicitly optional
  ("do not create unnecessary modules"). *Decision:* keep existing modules;
  menu lives in `cli.py` (see DRD mapping).
- **A-1** Default output `<project-dir-name>.md` in the caller's working
  directory. **A-2** Symlinks never followed. **A-3** Offline-only operation.

---

## 9. Acceptance Criteria (release gate)

1. Every `README.md` command (`--help`, `--version`, `dump . --dry-run`,
   `dump . --output ...`, menu options `1..6`) works as documented.
2. Export matches §1.3 structure with real contents; fences escape correctly.
3. Secrets/noise/binaries/oversize files excluded under all flag combinations
   (except user globs never override FR-011).
4. Full pytest suite passes; E2E dry-run + write + overwrite + invalid-arg
   paths verified for both `dump` and legacy forms.
5. `LICENSE` present; `pip install -e .` works on Python 3.10+.
