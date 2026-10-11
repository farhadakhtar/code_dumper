# Detailed Design Document (DRD): CodeDumper

**Document Version:** 2.1.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + `docs/PRD.md` + `docs/TRD.md` (v2.1.0)
**File:** `docs/DRD.md`

---

## 1. Architecture Overview

```text
 bare `codedumper` ──▶ interactive menu ──▶ ScanConfig ──┐
 `codedumper dump …` ──▶ subcommand parser ──▶ ScanConfig ─┤
 legacy `codedumper …` ──▶ legacy parser ──▶ ScanConfig ───┘
                                                        ▼
 Scanner ──▶ Filter Engine ──▶ Classifier ──▶ Tree Builder ──▶ Text/Markdown Renderer ──▶ Atomic Writer ──▶ Reporter
                                                  └─ menu options 2/3/4 ──▶ dump-locator / browser opener / updater (isolated)
```

Single-responsibility modules, one-way data flow through immutable
dataclasses, zero global state, zero runtime third-party imports. Per README
("do not create unnecessary modules"), the suggested `exporter/exclusions/
safety/config.py` files are **not** created; their responsibilities map onto
existing modules (§3.8).

---

## 2. Directory Structure

```text
code_dumper/
├── LICENSE                       # MIT license text (NFR-011)
├── README.md                       # normative user contract
├── pyproject.toml                  # build + `codedumper` entry point
├── requirements.txt                # dev/companion pins
├── run_watcher.py                  # companion launcher (untouched contract + --config)
├── codedumper/
│   ├── __init__.py                 # version + public exports
│   ├── __main__.py                 # `python -m codedumper`
│   ├── cli.py                      # spec menu (1-7) + dump/legacy parsers + orchestration
│   ├── models.py                   # ScanConfig / FileItem / OmissionRecord / ScanResult
│   ├── scanner.py                  # sorted recursion + ingestion + output self-exclusion (TR-003)
│   ├── filter.py                   # precedence chain (TR-008)
│   ├── classifier.py               # binary/language/encoding (TR-006)
│   ├── tree.py                     # structure tree (TR-004)
│   ├── renderer.py                 # text + Markdown parts/renderers (TR-005/011)
│   ├── writer.py                   # atomic write/stream + overwrite guard (TR-009)
│   ├── updater.py                  # release check + verified install, isolated (TR-021)
│   └── reporter.py                 # console summary (TR-011)
├── autocommit/                     # preserved companion (out of CodeDumper scope)
├── docs/                           # PRD/ERD/TRD/DRD/EDR/TRACEABILITY/ASSESSMENT
└── tests/
    ├── test_codedumper.py          # engine + legacy CLI tests
    ├── test_codedumper_contract.py # contract: dump/menu/format/launch tests
    ├── test_ux_update.py           # menu flows, .txt contract, updater (mocked)
    ├── test_wordmark.py            # wordmark structure, color policy, fallback tests
    └── test_performance.py         # NFR-001/002 benchmarks + determinism
```

---

## 3. Module Design & Contracts

### 3.1 `models` — domain entities

```python
@dataclass(frozen=True)
class ScanConfig:
    target_dir: Path
    output_path: Path
    max_size_bytes: int = 1_048_576
    include_hidden: bool = False
    exclude_patterns: list[str] = field(default_factory=list)
    force: bool = False
    dry_run: bool = False
    no_tree: bool = False

@dataclass(frozen=True)
class FileItem:
    path: Path; rel_path: str; size: int
    content: str; language: str; line_count: int

@dataclass(frozen=True)
class OmissionRecord:
    rel_path: str; reason: str; size: int = 0

@dataclass
class ScanResult:
    project_name: str; target_dir: Path
    included_files: list[FileItem] = field(default_factory=list)
    omitted_files: list[OmissionRecord] = field(default_factory=list)
    tree_text: str = ""
    elapsed_seconds: float = 0.0      # console-only; never rendered to file
    total_files_discovered: int = 0
```

### 3.2 `filter` — precedence engine (TR-008)

```python
class ExclusionEngine:
    def __init__(self, user_patterns: list[str] | None = None,
                 include_hidden: bool = False): ...
    def should_skip_directory(self, dir_name: str, rel_path: str) -> str | None: ...
    def should_skip_file(self, file_name: str, rel_path: str,
                         file_size: int, max_size_bytes: int) -> str | None: ...
```

Order: sensitive → default noise → hidden → user globs → size.
(Binary/encoding is the classifier's gate, applied after.)

### 3.3 `classifier` — safety checks (TR-006)

```python
def is_binary_bytes(data: bytes, suffix: str = "", sample_size: int = 8192) -> bool: ...
def is_binary_file(file_path: Path, sample_size: int = 8192) -> bool: ...  # delegates to is_binary_bytes
def detect_language(file_path: Path) -> str: ...   # ext map, fallback "text"
def decode_bytes_safely(raw_bytes: bytes) -> tuple[str, str]: ...  # utf-8 → latin-1 → utf-8/replace
def read_text_safely(file_path: Path) -> tuple[str, str]: ...      # reads, then delegates
```

The scanner reads each file once and classifies/decodes the bytes in memory
(one open per file instead of two). Verdicts are identical to the
path-based functions, which remain as the public/tested API.

### 3.4 `tree` — structure view (TR-004)

```python
def generate_directory_tree(root_dir: Path, filter_engine: ExclusionEngine,
                            max_depth: int = 25) -> str: ...
```

Glyphs `├── └── │   `, dirs suffixed `/`, sorted identically to the scanner.
Shows eligible layout including omitted paths (noise pruned); sensitive
**names** may appear in the tree but their **contents** are never embedded.

### 3.5 `renderer` — text + Markdown serialization (TR-005/011)

```python
def calculate_code_fence(content: str) -> str: ...  # "`" * max(3, longest_run + 1)
def format_size(size_bytes: int) -> str: ...
def format_size_plain(size_bytes: int) -> str: ...  # "N bytes" wording
def display_language(tag: str) -> str: ...          # human-friendly names
def iter_text_parts(config: ScanConfig, result: ScanResult): ...       # default .txt
def render_text(config: ScanConfig, result: ScanResult) -> str: ...
def iter_markdown_parts(config: ScanConfig, result: ScanResult): ...   # --format markdown
def render_markdown(config: ScanConfig, result: ScanResult) -> str: ...  # "\n".join(parts)
```

Text layout: `CODEBASE DUMP: <project>` → `PROJECT STRUCTURE` →
`FILE: <rel>` + `Language:`/`Size:`/`Lines:` + verbatim content +
`END FILE:` (repeated, sorted) → `EXCLUDED FILES` list when omissions
exist. No `#`/`##` headings, no fences. Markdown layout: `# Codebase
Dump:` → `## Project Structure` → fenced `## File:` sections →
`## Excluded Files` table. No timestamps in either (determinism).

### 3.6 `writer` — atomic persistence (TR-009)

```python
def write_dump_file(output_path: Path, content: str, force: bool = False) -> int: ...
def write_dump_stream(output_path: Path, parts: Iterable[str], force: bool = False) -> int: ...
```

Refuse-if-exists without `force` (`FileExistsError` → exit `1`); `mkdir -p`
parents; temp sibling `.tmp.<pid>.<name>` + `flush/fsync` + `os.replace`;
temp cleanup on failure. `write_dump_stream` joins `parts` with `"\n"`
incrementally (byte-identical to `"\n".join(parts)`) so the production path
never materializes the whole document string; `write_dump_file` remains for
API/test compatibility.

### 3.7 `cli` — menu + parsers + orchestration (TR-001/002/007/009/010/012/020)

```python
MENU_BODY: str                       # spec options block (1-7), byte-stable
MENU_PROMPT: str                     # "Select an option [1-7]: "
def build_parser() -> argparse.ArgumentParser: ...   # dump subcommand + legacy
def parse_size_str(val: str) -> int: ...             # B/KB/MB/GB grammar
def default_output_path(target: Path, format: str) -> Path: ...  # outside-project rule
def run_interactive_menu() -> int: ...               # logo + version + options 1-7
def execute_dump(target_dir, output_path, force, exclude_patterns,  # shared dump pipeline
                 include_hidden, max_size, no_tree, dry_run, dump_format) -> int: ...
def main(argv: list[str] | None = None) -> int: ...
```

Launch: `logo.print_launch_logo()` (art or silent fallback) →
`v<installed>` version line → `MENU_BODY` → prompt loop.
Dispatch: `1` dump CWD (output-path prompt); `2` prompt path then dump;
`3` dry-run preview; `4` update-dump flow with confirmation; `5` session
exclusion globs; `6` print help; `7`/EOF exits `0`;
`KeyboardInterrupt` → `130`. `--format {text,markdown}` (default `text`),
`--max-file-size` primary, `--max-size` alias.

### 3.9 `updater` — release check + verified install (TR-021)

```python
RELEASES_LATEST_URL: str           # api.github.com .../releases/latest (stable only)
def check_for_updates(fetcher=fetch_latest_release) -> UpdateCheck: ...  # never raises
def fetch_latest_release(timeout=...) -> ReleaseInfo: ...  # prerelease/draft refused
def is_newer(latest: str, installed: str) -> bool | None: ...
def detect_install_method() -> str: ...  # editable:/git:/pypi/other:/unknown
def select_install_asset(release) -> dict | None: ...  # strict URL allow-list
def download_asset(url, dest_dir, ...) -> Path: ...    # size-capped, temp-only
def install_wheel_file(path, ...) -> tuple[bool, str]: ...  # pip argv, no shell
def installed_dist_version() -> str | None: ...        # post-install verification
def run_update_interactive() -> int: ...               # full menu flow, always returns to menu
```

### 3.10 Wordmark — fixed terminal branding (TR-022)

```python
WORDMARK_GREEN = "\x1b[1;32m"        # bold green foreground
WORDMARK_RESET = "\x1b[0m"           # styles always reset, even on error
_GLYPHS: dict                       # "CODE DUMPER" letterforms, 6 rows each
WORDMARK_TEXT: str                   # builder-aligned fixed block (no trailing ws)
TAGLINE: str = "Turn your codebase into a clean, AI-ready dump."
def print_wordmark(stream, env, color, width) -> str: ...  # "color"|"plain"|"skipped"
def _color_enabled(stream, env) -> bool: ...  # NO_COLOR/dumb off; force/tty on
```

Launch prints the green wordmark (or the identical block without color
when unsupported, or nothing when the terminal is narrower than the
block), then centered version/tagline lines, then the options block.
No image decoding, no network, no extra dependencies.

### 3.8 Suggested-module mapping (README §"Technical design")

| Suggested | Actual home | Note |
|---|---|---|
| `cli.py` | `cli.py` | menu + parsers + output |
| `scanner.py` | `scanner.py` | discovery |
| `tree.py` | `tree.py` | structure |
| `exporter.py` | `renderer.py` + `writer.py` | generation + persistence |
| `exclusions.py` | `filter.py` | rules |
| `safety.py` | `classifier.py` + `filter.py` (sensitive tier) | type/size/secrets |
| `config.py` | `models.ScanConfig` + `cli.parse_size_str` | validated settings |

No new modules: creating them would split cohesive units for no behavioral
gain.

---

## 4. Workflows

### 4.1 Dispatch

```mermaid
flowchart TD
    Invoke([codedumper invocation]) --> HasArgs{Arguments?}
    HasArgs -->|None| Logo[Print green wordmark or plain fallback]
    Logo --> Menu[Interactive menu 1..7]
    HasArgs -->|First token is dump| Sub[Parse dump subcommand]
    HasArgs -->|Otherwise| Leg[Parse legacy form]
    Menu -->|1| Get[Dump CWD to .txt, path prompt]
    Menu -->|2| Other[Prompt path → dump it]
    Menu -->|3| Dry[Dry-run preview]
    Menu -->|4| Update[Find .txt → confirm → regenerate / offer create]
    Menu -->|5| Excl[Session exclusion globs]
    Menu -->|6| Help[Print help]
    Menu -->|7/EOF| Exit0([Exit 0])
    Sub --> Val{Valid?}
    Leg --> Val
    Val -->|No| Exit1[Exit 1]
    Val -->|Yes| Scan[scan_repository]
    Scan --> Stream[iter_*_parts → write_dump_stream]
    Stream --> IsDry{--dry-run?}
    IsDry -->|Yes| Report[Console report]
    IsDry -->|No| Guard{Exists && !--force?}
    Guard -->|Yes + non-interactive| Exit1
    Guard -->|Yes + menu| Confirm{Confirm overwrite?}
    Confirm -->|No| Menu
    Confirm -->|Yes| Write[Atomic write]
    Guard -->|No| Write
    Write -->|OSError| Exit2[Exit 2]
    Write --> Report --> Exit0
```

### 4.2 Filtering (precedence)

```mermaid
flowchart TD
    F[Discovered node] --> S{Sensitive?}
    S -->|Yes| O1[Omit SENSITIVE_CREDENTIAL]
    S -->|No| N{Default noise?}
    N -->|Yes| O2[Omit DEFAULT_NOISE]
    N -->|No| H{Hidden && !include_hidden?}
    H -->|Yes| O3[Omit HIDDEN]
    H -->|No| G{User glob?}
    G -->|Yes| O4[Omit USER_EXCLUDE_PATTERN]
    G -->|No| Z{Size > cap?}
    Z -->|Yes| O5[Omit EXCEEDS_MAX_SIZE]
    Z -->|No| B{Binary / unreadable?}
    B -->|Yes| O6[Omit BINARY_FILE / READ_ERROR]
    B -->|No| I[Include]
```

---

## 5. Security & Safety Design

1. Dump flows are offline-only (no sockets, uploads, or telemetry); only
   the updater reads release metadata over HTTPS.
2. Unbypassable sensitive tier; filename-only reporting.
3. Symlinks never followed; depth guard; root containment via `resolve()`.
4. Read-only source access; atomic destination writes.
5. Menu overwrite confirmation; non-interactive refusal without `--force`.
6. Invalid size strings rejected before any I/O.

---

## 6. Design Trade-Offs

- **Superset CLI vs. clean break:** keep legacy form working (existing tests
  + scripts) while documenting `dump` as primary. Cost: slightly larger
  parser. Benefit: zero regressions.
- **In-file timing removed:** console keeps `Duration`; file drops it so
  SHA-256 determinism holds.
- **Headings changed to README's:** `## Project Structure` / `## File:` /
  `## Excluded Files`; legacy `Table of Contents/Directory Tree/Repository
  Files/Omission Manifest` retired (one existing test updated).
- **Stdlib-only retained:** README permits any modular Python, but zero-dep
  preserves installability and auditability; no behavior needs third-party
  code (updater uses `urllib`/`webbrowser`/`importlib.metadata`).
- **Plain-text default:** Markdown stays available via `--format` so prior
  behavior is preserved opt-in; fence logic retained only for that format.
- **Updater honesty over automation:** with no published releases, the only
  live behavior is the unavailable state + manual route; the install path
  is fully implemented but proven by mocked tests, never by live runs.
- **Fixed wordmark, honest fidelity:** the launch shows a fixed green
  `CODE DUMPER` block-letter string (outlined, segmented style; builder-
  aligned columns; bold green + reset), not a redrawn image and not a
  generic `#` font. Glyph proportions were normalized to a fixed grid so
  the block fits common terminal widths; narrow terminals show the menu
  without it rather than a wrapped, misaligned logo.
- **Streaming writes, in-memory model kept:** the CLI persists via
  `iter_markdown_parts` + `write_dump_stream` (peak ≈ contents size, measured
  50.3 MB at 48.8 MB text), while `ScanResult` still holds file contents and
  `render_markdown` stays for library/test use. A two-pass (re-read at
  render) design could push further but was rejected as destabilizing for
  v1; workloads beyond the NFR-002 envelope are post-MVP future work.
