# CodeDumper & Git Auto-Commit Suite

A developer utility suite for AI-assisted software engineering and repository automation.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-73%20Passed-brightgreen.svg)]()
[![Dependencies](https://img.shields.io/badge/Runtime%20Dependencies-0%20(Stdlib)-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

---

## Overview

This repository contains two complementary developer tools:

1. **`CodeDumper`** (`codedumper`): A cross-platform CLI that exports an entire local repository into a single, clean, structured Markdown document. Designed specifically to provide complete codebase context to AI coding assistants (Claude, ChatGPT, Gemini) with zero token-wasting noise, automatic secret protection, and dynamic code fencing.
2. **`Git Auto-Commit Watcher`** (`autocommit`): A companion background automation tool that monitors your repository for file modifications, debounces editor saves, and creates automated timestamped Git commits.

---

## 1. CodeDumper (`codedumper`)

### Features
- **Zero Runtime Dependencies:** Built strictly using Python's standard library (`pathlib`, `argparse`, `dataclasses`).
- **Deterministic Traversal:** Produces byte-for-byte identical output across repeated runs on unchanged repositories.
- **Hierarchical Directory Tree:** Emits an ASCII/Unicode visual tree representing the repository layout.
- **Dynamic Code Fencing:** Inspects source files for backticks and dynamically adjusts fence lengths (e.g. ```` ```` ````) to prevent nested code blocks from breaking Markdown syntax.
- **Strict Secret Protection:** Automatically excludes `.env*`, `*.pem`, `*.key`, `id_rsa*`, certificates, and credential files.
- **Intelligent Noise Pruning:** Skips VCS folders (`.git`), build directories (`dist`, `build`, `__pycache__`), package managers (`node_modules`), and package lockfiles.
- **Content Classification:** Samples file headers to detect and skip binary assets (`.png`, `.exe`, compiled bytecode).
- **Atomic File Writing:** Writes via temporary files and atomic swaps (`os.replace`) to prevent corrupted dumps on interrupted processes.
- **Omission Telemetry:** Generates an auditable manifest detailing every omitted file and the exact reason for omission.

### Quick Start

#### Installation
```bash
# Clone the repository
git clone https://github.com/farhadakhtar/code_dumper.git
cd code_dumper

# Install CodeDumper
pip install -e .
```

#### Basic Usage
```bash
# Export the current repository to <repo-name>.md
codedumper

# Or run directly via Python module
python -m codedumper

# Export a specific project to a custom output file
codedumper /path/to/my_project -o project_dump.md

# Preview directory tree and statistics without writing to disk
codedumper --dry-run
```

#### CLI Options
```text
usage: codedumper [-h] [-o OUTPUT_PATH] [-f] [-e EXCLUDE_PATTERNS]
                  [--include-hidden] [--max-size MAX_SIZE] [--no-tree]
                  [--dry-run] [-v]
                  [target_dir]

positional arguments:
  target_dir            Path to directory to export. (Default: current directory)

options:
  -h, --help            Show this help message and exit.
  -o, --output PATH     Destination filepath. (Default: <target_directory_name>.md)
  -f, --force           Overwrite destination file if it exists without prompting.
  -e, --exclude GLOB    Glob pattern to exclude (repeatable, e.g. -e "*.log" -e "docs/*").
  --include-hidden      Include hidden files and folders (starting with '.').
  --max-size SIZE       Maximum individual file size (e.g. '500KB', '2MB', default '1MB').
  --no-tree             Omit the directory tree section in the Markdown output.
  --dry-run             Scan and report without writing any file to disk.
  -v, --version         Show program version and exit.
```

---

## 2. Engineering Documentation

CodeDumper is engineered under strict specifications. The complete architectural, design, and review documentation is maintained in the `docs/` directory:

| Document | Description |
|---|---|
| [**docs/PRD.md**](docs/PRD.md) | **Product Requirements Document:** Scope, user personas, functional (`FR-001`..`FR-018`) and non-functional (`NFR-001`..`NFR-010`) requirements, and user stories. |
| [**docs/ERD.md**](docs/ERD.md) | **Entity Relationship & Data Model:** Persistence analysis (demonstrating why no database is required), runtime entity definitions, and data flow. |
| [**docs/TRD.md**](docs/TRD.md) | **Technical Requirements Document:** Architecture constraints, supported platforms, CLI contracts, encoding fallbacks, and security policies. |
| [**docs/DRD.md**](docs/DRD.md) | **Detailed Design Document:** Module interface contracts, dynamic fence algorithms, directory layouts, and execution workflows. |
| [**docs/EDR.md**](docs/EDR.md) | **Engineering Design Review:** Formal design review, risk analysis, failure modes, findings register, and engineering sign-off verdict. |
| [**docs/TRACEABILITY.md**](docs/TRACEABILITY.md) | **Traceability Matrix:** Full mapping from PRD requirements to TRD, DRD, tests, and verification status. |
| [**docs/ASSESSMENT.md**](docs/ASSESSMENT.md) | **Initial Assessment:** Baseline codebase analysis, gap identification, and recommended architecture. |

---

## 3. Companion: Git Auto-Commit Watcher (`autocommit`)

For continuous Git automation during live coding sessions, the repository includes the `autocommit` package:

```bash
# Install companion dependencies
pip install -r requirements.txt

# Start watcher on current repository
python run_watcher.py

# Point watcher at another repository
python run_watcher.py --repo "D:\PROJECTS\my_other_repo"
```

---

## 4. Testing & Validation

CodeDumper includes a test suite covering directory recursion, deterministic sorting, sensitive file exclusion, binary detection, encoding fallbacks, dynamic code fencing, size limits, overwrite protection, and CLI exit codes:

```bash
# Run the entire test suite (73 tests)
python -m pytest -v

# Run CodeDumper tests only
python -m pytest tests/test_codedumper.py -v
```

All 73 automated tests execute and pass in under 25 seconds.