# Product Requirements Document (PRD): CodeDumper

**Document Version:** 1.0.0  
**Status:** Approved  
**Author:** Engineering Team  
**Target Repository:** `farhadakhtar/code_dumper`  
**File:** `docs/PRD.md`  

---

## 1. Product Overview

### 1.1 Product Name and Purpose
**CodeDumper** is a cross-platform command-line utility that exports a local software codebase into a single, standardized, and self-contained Markdown document. The generated document contains an architectural overview, an ASCII directory tree, and fully fenced file contents accompanied by an auditable omission report.

### 1.2 Problem Statement
Developers increasingly rely on Large Language Models (LLMs) and conversational AI coding assistants (e.g., Claude, Gemini, ChatGPT) for code reviews, architectural feedback, refactoring, and debugging. However, sharing multi-file repository context is burdened by friction:
- Manual copying and pasting of individual files is error-prone and time-consuming.
- File hierarchy and directory context are frequently lost.
- Proprietary or secret files (e.g., `.env`, credentials, private keys) are easily leaked by accident.
- Large binary files (compiled objects, media, SQLite databases) pollute prompts and waste token limits.
- Submissions often break markdown formatting when source files contain triple backticks.

### 1.3 Proposed Solution
CodeDumper automates codebase extraction into a deterministic Markdown file. It enforces security exclusions by default, detects binary assets and large files, generates a visual directory structure, and formats code blocks using dynamic code fencing to avoid syntax breakage.

### 1.4 Product Vision
To become the premier lightweight, dependency-free developer tool for packaging codebases into clean, auditable, and AI-ready Markdown representations.

### 1.5 Scope and Boundaries
- **In Scope:** Local directory traversal, rule-based filtering, secret pattern exclusion, text/binary classification, directory tree synthesis, dynamic Markdown generation, CLI execution, progress reporting, and exit code communication.
- **Out of Scope (Boundaries):** Direct integration with LLM APIs (no token sending), git network operations (cloning or remote fetching), code execution, code minification/obfuscation, and relational database persistence.

---

## 2. Users and Use Cases

### 2.1 Target Users
1. **AI-Assisted Developers:** Engineers providing complete, contextualized codebases to web-based or API-based AI models.
2. **Individual Developers & Freelancers:** Contractors creating complete snapshot archives of deliverables for clients.
3. **Software Engineering Students & Educators:** Learners and teachers sharing and assessing multi-file assignments in a single readable document.
4. **Repository Maintainers:** Project leads creating documentation archives or preparing repositories for external audits.
5. **Technical Reviewers & Auditors:** Security and code quality auditors requiring an offline, single-file view of all project text files.

### 2.2 Key Workflows
- **Standard Dump:** User executes `codedumper` in their repository root. The tool scans files, excludes noise (like `.git` and `node_modules`), writes `<project-name>.md`, and outputs a concise execution summary.
- **Targeted Subdirectory Dump:** User runs `codedumper ./src --output review.md` to dump only a specific module.
- **Dry-Run Inspection:** User runs `codedumper --dry-run` to preview the directory tree and verify exclusions before writing any file to disk.
- **Custom Filtering:** User runs `codedumper --exclude "*.tmp" --exclude "docs/*" --max-size 500KB`.

---

## 3. Functional Requirements

| Requirement ID | Title | Description | Priority |
|---|---|---|---|
| **FR-001** | Project Directory Selection | The system must accept an optional positional argument specifying the target directory. If omitted, it defaults to the current working directory (`.`). | High |
| **FR-002** | Recursive Directory Scanning | The system must recursively scan the target directory to discover all directories and files. | High |
| **FR-003** | Deterministic Traversal | The system must sort discovered directory entries lexicographically to guarantee identical, deterministic output across runs on identical filesystems. | High |
| **FR-004** | Directory Tree Generation | The system must generate an ASCII/Unicode directory tree reflecting the project layout (including all included and omitted paths). | High |
| **FR-005** | Source File Discovery & Ingestion | The system must open and read identified text source files, capturing their relative paths and contents. | High |
| **FR-006** | Text vs. Binary Detection | The system must inspect file content (sampling up to 8 KB) to detect binary files (presence of null bytes `\x00` or high non-text byte ratio) and omit them from code embedding. | High |
| **FR-007** | Default Noise Exclusions | The system must automatically exclude common VCS and build directories (`.git`, `node_modules`, `__pycache__`, `.pytest_cache`, `dist`, `build`, `.venv`, `venv`). | High |
| **FR-008** | Sensitive File Protection | The system must exclude known sensitive filenames and patterns by default (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `credentials.json`, `*.p12`). | Critical |
| **FR-009** | Hidden File Filtering | Files and directories beginning with a dot (`.`) must be excluded by default unless `--include-hidden` is explicitly passed. | High |
| **FR-010** | Custom Exclusion Rules | The system must support repeatable `--exclude` glob arguments to allow users to specify custom exclusion patterns. | Medium |
| **FR-011** | File Size Threshold Enforcement | The system must enforce a configurable maximum file size (default: 1 MB, flag `--max-size`). Files exceeding this size must be omitted with a documented reason. | High |
| **FR-012** | Configurable Output Destination | The system must support an `--output` (`-o`) option to specify the output Markdown filepath. If omitted, the default is `<project_dir_name>.md`. | High |
| **FR-013** | Overwrite Protection | The system must not overwrite an existing output file unless the `--force` (`-f`) flag is explicitly provided. | High |
| **FR-014** | Dynamic Markdown Code Fencing | The system must inspect file contents for backtick sequences and dynamically size code fences (e.g., using ```` ```` ```` or more) to ensure valid Markdown rendering. | High |
| **FR-015** | Dry-Run Mode | The system must support a `--dry-run` flag that executes scanning, tree generation, and reporting without writing any output file. | Medium |
| **FR-016** | Omission Reporting | The generated Markdown document and CLI output must include an auditable summary table detailing omitted files and their specific reasons (binary, size, secret, pattern). | High |
| **FR-017** | CLI Help and Version | The system must provide standard `--help` (`-h`) and `--version` (`-v`) flags. | High |
| **FR-018** | Exit Codes | The system must return standard exit codes: `0` for success, `1` for configuration/user input error, `2` for I/O/filesystem error, and `130` for user cancellation. | High |

---

## 4. Non-Functional Requirements

| Requirement ID | Category | Requirement Description | Acceptance Criteria |
|---|---|---|---|
| **NFR-001** | Performance | The scanning and generation process must be fast and responsive. | Must scan and process a 1,000-file repository in under 2.0 seconds on standard SSD hardware. |
| **NFR-002** | Memory Efficiency | File content must be streamed or written sequentially to avoid loading an entire large repository into memory simultaneously. | Peak process memory usage must remain under 100 MB when processing repositories up to 500 MB in total text. |
| **NFR-003** | Portability | The application must run without modification on Windows, Linux, and macOS. | All path operations use normalized separators; verified on Python 3.10, 3.11, and 3.12. |
| **NFR-004** | Security | Prevent path traversal attacks and accidental source code corruption. | Output path cannot point inside protected system areas without error; atomic write via temp file prevents corrupted output. |
| **NFR-005** | Reliability & Safety | Scanned repositories must remain read-only. CodeDumper must never modify, delete, or re-encode source files. | Source file checksums before and after execution are strictly identical. |
| **NFR-006** | Determinism | Repeated runs on an unchanged repository with identical flags must yield byte-for-byte identical output. | Multiple invocations produce identical SHA-256 hashes of the output file. |
| **NFR-007** | Dependency Minimization | The core runtime must use Python standard library packages only. | Zero external third-party dependencies required for production CLI execution. |
| **NFR-008** | Usability & Ergonomics | CLI output must be human-readable, showing scan stats, output path, and omitted count. | Standard stdout displays clear summary banner; errors are emitted to stderr. |
| **NFR-009** | Testability | The codebase must support automated unit and end-to-end testing via pytest. | Minimum 90% branch and line test coverage across all core modules. |
| **NFR-010** | Robust Encoding | Files with varying character encodings (UTF-8, Latin-1, ASCII) must be processed cleanly without unhandled exceptions. | Automatic fallback to Latin-1 or replacement encoding prevents crash on non-UTF-8 text. |

---

## 5. User Stories and Acceptance Criteria

### US-1: Export Entire Repository to Single Markdown
**User Story:** As an AI-assisted developer, I want to export my repository to a single Markdown file so that I can provide the complete readable codebase to an AI coding assistant.  
**Acceptance Criteria:**
1. Running `codedumper` in a directory creates `<project_name>.md`.
2. The generated file contains an introduction header, table of contents, ASCII directory tree, and formatted file sections.
3. Every included file has its relative path as a section header and content inside an appropriate language-tagged code block.
4. Output ends with a generation manifest containing file count, total lines, and omission summary.

### US-2: Automatic Exclusion of Secrets and Build Artifacts
**User Story:** As a developer, I want sensitive files and compiler noise excluded automatically so that I do not accidentally expose private keys or bloat the dump with build artifacts.  
**Acceptance Criteria:**
1. `.env`, `.env.local`, `id_rsa`, `*.pem`, and `*.key` files are never embedded into code sections.
2. Directories named `.git`, `node_modules`, `__pycache__`, and `dist` are pruned during traversal.
3. Excluded sensitive files are explicitly listed in the Omission Manifest with reason `Sensitive / Credential`.

### US-3: Dynamic Markdown Code Fencing
**User Story:** As a developer, I want files containing backticks to be formatted properly so that the resulting Markdown file does not break when viewed in Markdown viewers or fed to an LLM.  
**Acceptance Criteria:**
1. If a source file contains ```` ``` ````, CodeDumper wraps it in ```` ```` ````.
2. If a file contains `N` backticks, CodeDumper uses `max(3, N + 1)` backticks for the fence.

### US-4: Dry-Run and Custom Filtering
**User Story:** As a technical reviewer, I want to preview what will be exported before writing to disk and specify custom exclusion rules.  
**Acceptance Criteria:**
1. Running `codedumper --dry-run` displays the directory tree and scan summary on stdout without creating any file.
2. Passing `--exclude "*.spec.ts"` excludes matching files and reports them as `Custom Exclusion Pattern`.

### US-5: Safe Overwrite Protection
**User Story:** As a user, I want CodeDumper to warn me if the destination file already exists so that I do not accidentally destroy existing files.  
**Acceptance Criteria:**
1. If the target output file exists, CodeDumper halts with exit code `1` and prints an error message.
2. If `--force` is supplied, CodeDumper overwrites the existing file atomically.

---

## 6. CLI Interface

### 6.1 Command Syntax
```bash
codedumper [TARGET_DIR] [OPTIONS]
```

### 6.2 Positional Arguments
- `TARGET_DIR` (optional): Path to the target repository directory. Defaults to `.` (current working directory).

### 6.3 Options and Flags
- `-o, --output <PATH>`: Destination filepath for the generated Markdown dump. Default: `./<target_directory_name>.md`.
- `-f, --force`: Overwrite output file if it already exists. Default: `false`.
- `-e, --exclude <PATTERN>`: Additional glob pattern to exclude. Can be specified multiple times.
- `--include-hidden`: Include hidden files and directories (names starting with `.`). Default: `false`.
- `--max-size <BYTES|KB|MB>`: Maximum individual file size to include (e.g., `500KB`, `2MB`). Default: `1MB` (1,048,576 bytes).
- `--no-tree`: Omit the directory tree section from the Markdown dump. Default: `false`.
- `--dry-run`: Perform traversal, classification, and report generation without creating the output file. Default: `false`.
- `-v, --version`: Show program version number and exit.
- `-h, --help`: Show help message and exit.

### 6.4 Exit Codes
- `0`: Successful execution.
- `1`: Validation error (invalid target directory, output file already exists without `--force`, invalid arguments).
- `2`: File system or permission error.
- `130`: Interrupted by user (`SIGINT` / `Ctrl+C`).

---

## 7. Scope Management

### 7.1 MVP Requirements
- Recursive filesystem scanner with deterministic sorting.
- Default ignore lists for build artifacts, VCS, and sensitive files.
- Text/binary content classifier.
- Dynamic Markdown code block fencing.
- ASCII directory tree generator.
- Atomic writer with overwrite protection.
- CLI argument parsing, progress summary, and exit codes.
- Zero runtime dependencies outside Python 3.10+ standard library.

### 7.2 Post-MVP Enhancements
- Gitignore integration (parsing `.gitignore` rules dynamically).
- Token counter estimation (estimating GPT-4/Claude token counts).
- Chunking/splitting mode for extremely large codebases (e.g., splitting into multiple 200k-token files).
- Interactive TUI for file selection.

### 7.3 Explicitly Out of Scope
- Uploading data directly to third-party LLM APIs.
- Background filesystem watching / daemon mode (addressed separately by companion tools).
- Modifying or transforming source code.
- Relational database storage.

---

## 8. Risks and Assumptions

### 8.1 Product Risks
- **Overly Broad Exclusions:** Users may complain when legitimate files (e.g., `.env.example`) are excluded. *Mitigation:* Allow explicit glob overrides and document all default exclusion rules.

### 8.2 Technical Risks
- **Encoding Crashes:** Files with non-standard or corrupt encodings could cause uncaught exceptions. *Mitigation:* Multi-tier fallback decoding (`utf-8` with `replace`, or `latin-1`).
- **Path Separation on Windows vs. POSIX:** Inconsistent path delimiters in Markdown output. *Mitigation:* Strict normalization to forward slashes (`/`) for all relative paths in Markdown.

### 8.3 Security Risks
- **Secret Exposure:** Inadvertent inclusion of high-entropy credentials or environment files. *Mitigation:* Conservative default blacklist blocking `.env*`, `*.pem`, `*.key`, `id_rsa*`. Explicit documentation that CodeDumper is not a replacement for a static secret scanner.
- **Symlink Recursion:** Malicious symlinks pointing to parent directories or `/dev/urandom`. *Mitigation:* Do not follow symbolic links during traversal; represent them as metadata.
