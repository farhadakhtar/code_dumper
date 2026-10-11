# Requirements Traceability Matrix (RTM): CodeDumper

**Document Version:** 2.0.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + PRD/ERD/TRD/DRD/EDR (v2.0.0)
**File:** `docs/TRACEABILITY.md`

---

## 1. Functional Requirements Traceability

| Requirement ID | PRD Source | TRD Source | DRD Module / Section | ERD Reference | Test ID(s) | Status |
|---|---|---|---|---|---|---|
| FR-001 | PRD §3 | TR-001 | `cli.py` menu (§3.7) | `ScanSession.invocation_mode` | `test_menu_*`, `test_interactive_*` | To verify |
| FR-002 | PRD §3 | TR-002 | `cli.py` `dump` subparser | `ScanSession` | `test_dump_subcommand_*` | To verify |
| FR-003 | PRD §3 | TR-003 | `scanner.py` | `DirectoryEntry`, `FileEntry` | `test_scan_repository_comprehensive`, `test_empty_project` | Verified (v1 suite) |
| FR-004 | PRD §3 | TR-003 | `scanner.py` + `tree.py` | `ScanSession` ordering | `test_scan_determinism` + SHA-256 contract test | To verify |
| FR-005 | PRD §3 | TR-004 | `tree.py` | `DirectoryEntry` | `test_tree_generation` + `Project Structure` assertion | To verify |
| FR-006 | PRD §3 | TR-005 | `scanner.py`, `classifier.py`, `renderer.py` | `FileEntry` | `test_source_file_content_reading` et al. | To verify |
| FR-007 | PRD §3 | TR-005 | `renderer.py` `calculate_code_fence` | — (serialization) | `test_calculate_code_fence_*` | Verified (v1 suite) |
| FR-008 | PRD §3 | TR-006 | `classifier.py` | `FileClassification` | `test_binary_detection_*` | Verified (v1 suite) |
| FR-009 | PRD §3 | TR-007 | `cli.py` size grammar + `filter.py` | `ScanSession.max_size_bytes` | `test_parse_size_str_*`, `test_filter_max_size`, `--max-file-size` tests | To verify |
| FR-010 | PRD §3 | TR-008 | `filter.py` | `ExclusionRule` (noise) | `test_filter_default_noise_exclusion` | Verified (v1 suite) |
| FR-011 | PRD §3 | TR-008 | `filter.py` sensitive tier | `ExclusionRule` (sensitive) | `test_filter_sensitive_credentials` + include-hidden secret test | To verify |
| FR-012 | PRD §3 | TR-008 | `filter.py` | `ExclusionRule` (hidden) | `test_filter_hidden_file_handling` | Verified (v1 suite) |
| FR-013 | PRD §3 | TR-008 | `filter.py` + menu session globs | `ExclusionRule` (user) | `test_filter_custom_user_globs` + menu option-4 test | To verify |
| FR-014 | PRD §3 | TR-009 | `cli.py`, `writer.py` | `DumpArtifact` | `test_writer_*`, `test_cli_run_success` | To verify |
| FR-015 | PRD §3 | TR-009 | `writer.py` + menu confirm | `DumpArtifact` | `test_writer_overwrite*`, `test_cli_overwrite_refusal` | Verified (v1 suite) |
| FR-016 | PRD §3 | TR-010 | `cli.py` dry-run | `ScanSession.dry_run` | `test_cli_dry_run` + `dump --dry-run` test | To verify |
| FR-017 | PRD §3 | TR-011 | `renderer.py`, `reporter.py` | `GenerationReport`, `OmissionRecord` | `test_reporter_omission_manifest`, exclusion-section tests | To verify |
| FR-018 | PRD §3 | TR-012 | `cli.py` | — (CLI) | `test_cli_help_and_version` + `dump --help` | To verify |
| FR-019 | PRD §3 | TR-012 | `cli.py` | — (process) | `test_cli_exit_codes` et al. | Verified (v1 suite) |
| FR-020 | PRD §3 | TR-002 | `cli.py` legacy path | `ScanSession.invocation_mode` | full v1 legacy suite (kept green) | Verified (v1 suite) |

Retired v1 headings (`Table of Contents`, `Directory Tree`, `Repository
Files`, `Omission Manifest`): replaced by `Project Structure`, `File:`,
`Excluded Files` per TRD §6; the single v1 assertion referencing them is
updated in Phase 4.

---

## 2. Non-Functional Requirements Traceability

| ID | Category | TRD | DRD / Section | Verification | Status |
|---|---|---|---|---|---|
| NFR-001 | Performance | TR-013 | scanner/renderer | `tests/test_performance.py` (1,000 files < 2.0 s) | To verify |
| NFR-002 | Memory | TR-013 | renderer/writer | `tests/test_performance.py` (tracemalloc peak < 100 MB) | To verify |
| NFR-003 | Portability | TR-014 | models/scanner | POSIX/`\n` tests, 3.10–3.12; clean-venv wheel install + arbitrary-cwd run | To verify |
| NFR-004 | Security | TR-015 | writer/scanner | no-upload, no-follow, read-only, filename-only reports | To verify |
| NFR-005 | Reliability | TR-015 | scanner/writer | checksums, atomic-write tests | Verified (v1 suite) |
| NFR-006 | Determinism | TR-016 | scanner/renderer | SHA-256 equality (timing console-only) | To verify |
| NFR-007 | Zero-deps | TR-017 | `pyproject.toml` | import surface check | Verified |
| NFR-008 | Usability | TR-012 | cli/reporter | menu + `[INFO]`/`[OK]` format tests | To verify |
| NFR-009 | Testability | TR-018 | `tests/` | pytest suite incl. contract tests | To verify |
| NFR-010 | Encoding | TR-014 | classifier | UTF-8/Latin-1/mixed tests | Verified (v1 suite) |
| NFR-011 | License honesty | TR-019 | `LICENSE` + metadata | file-exists check | To verify (Phase 4) |

---

## 3. Cross-Document Consistency (v2)

1. CLI vocabulary (`dump`, `--output`, `--dry-run`, `--include-hidden`,
   `--exclude`, `--max-file-size`, `--help`, `--version`, menu `1..6`)
   identical across README/PRD/TRD/DRD.
2. Exclusion precedence identical everywhere:
   sensitive > noise > hidden > user globs > size > binary.
3. Markdown layout identical everywhere: `# Codebase Dump` → `## Project
   Structure` → `## File:` × N → `## Excluded Files`.
4. Zero-runtime-dependency + offline-only guarantees repeated in all docs.
5. Honesty rule (real stats, no secret values, pre-share review) in
   README/PRD/TRD/DRD/EDR.
