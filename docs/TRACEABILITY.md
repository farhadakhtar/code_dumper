# Requirements Traceability Matrix (RTM): CodeDumper

**Document Version:** 2.1.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + PRD/TRD/DRD/EDR (v2.1.0); ERD unchanged (v2.0.0)
**File:** `docs/TRACEABILITY.md`

---

## 1. Functional Requirements Traceability

| Requirement ID | PRD Source | TRD Source | DRD Module / Section | ERD Reference | Test ID(s) | Status |
|---|---|---|---|---|---|---|
| FR-001 | PRD §3 | TR-001/TR-022 | `cli.py` menu 1–7 (§3.7) + fixed wordmark | `ScanSession.invocation_mode` | `test_menu_*`, `test_bare_main_launches_menu`, `tests/test_wordmark.py` | Verified |
| FR-002 | PRD §3 | TR-002 | `cli.py` `dump` subparser | `ScanSession` | `test_dump_subcommand_*` | Verified |
| FR-003 | PRD §3 | TR-003 | `scanner.py` | `DirectoryEntry`, `FileEntry` | `test_scan_repository_comprehensive`, `test_empty_project` | Verified |
| FR-004 | PRD §3 | TR-003 | `scanner.py` + `tree.py` | `ScanSession` ordering | `test_scan_determinism`, SHA-256 + byte-identity tests | Verified |
| FR-005 | PRD §3 | TR-004 | `tree.py` | `DirectoryEntry` | `test_tree_generation` | Verified |
| FR-006 | PRD §3 | TR-005 | `renderer.py` text parts | `FileEntry` | `test_txt_contract_exact_layout`, txt menu/dump tests | Verified |
| FR-007 | PRD §3 | TR-005 | `renderer.py` fences | — (serialization) | `test_calculate_code_fence_*`, `test_markdown_format_still_supported`, `test_output_layout_matches_readme` | Verified |
| FR-008 | PRD §3 | TR-006 | `classifier.py` | `FileClassification` | `test_binary_detection_*` | Verified |
| FR-009 | PRD §3 | TR-007 | `cli.py` size grammar + `filter.py` | `ScanSession.max_size_bytes` | `test_parse_size_str_*`, `test_filter_max_size`, `--max-file-size` tests | Verified |
| FR-010 | PRD §3 | TR-008 | `filter.py` | `ExclusionRule` (noise) | `test_filter_default_noise_exclusion` | Verified |
| FR-011 | PRD §3 | TR-008 | `filter.py` sensitive tier | `ExclusionRule` (sensitive) | `test_filter_sensitive_credentials`, include-hidden + txt secret tests | Verified |
| FR-012 | PRD §3 | TR-008 | `filter.py` | `ExclusionRule` (hidden) | `test_filter_hidden_file_handling` | Verified |
| FR-013 | PRD §3 | TR-008 | `filter.py` | `ExclusionRule` (user) | `test_filter_custom_user_globs`, `test_dump_subcommand_exclude` | Verified |
| FR-014 | PRD §3 | TR-009 | `cli.py` defaults + `writer.py` | `DumpArtifact` | default-path-inside + self-exclusion + temp-exclusion + rescan + custom-output tests | Verified |
| FR-015 | PRD §3 | TR-009 | `writer.py` + menu confirm | `DumpArtifact` | `test_writer_*`, `test_cli_overwrite_refusal`, menu confirm/decline tests | Verified |
| FR-016 | PRD §3 | TR-010 | `cli.py` dry-run | `ScanSession.dry_run` | `test_cli_dry_run`, `dump --dry-run` tests | Verified |
| FR-017 | PRD §3 | TR-011 | `renderer.py`, `reporter.py` | `GenerationReport`, `OmissionRecord` | txt/markdown layout + console-report tests | Verified |
| FR-018 | PRD §3 | TR-012 | `cli.py` | — (CLI) | `test_cli_help_and_version` + `dump --help` | Verified |
| FR-019 | PRD §3 | TR-012 | `cli.py` | — (process) | exit-code + invalid-arg/size/format tests | Verified |
| FR-020 | PRD §3 | TR-002 | `cli.py` legacy path | `ScanSession.invocation_mode` | `test_legacy_form_still_works` et al. | Verified |
| FR-021 | PRD §3 | TR-020 | `cli.py` update flow | `DumpArtifact` | `test_menu_update_*` (confirm/decline/missing/legacy) | Verified |
| FR-022 | PRD §3 | TR-020 | `cli.py` browser opener | — (CLI) | `test_menu_open_github_success/failure` | Verified |
| FR-023 | PRD §3 | TR-021 | `updater.py` check | — (process) | update-state tests (mocked fetchers) | Verified |
| FR-024 | PRD §3 | TR-021 | `updater.py` install | — (process) | install accept/decline/success/failure/asset/method tests (mocked) | Verified |
| FR-025 | PRD §3 | TR-021 | `updater.py` isolation | — (process) | no-network-in-suite (fast suite), untouched-project test | Verified |

Retired in v2.1: old 1–6 menu options (dump-another, session globs,
help-printer) and the default `.md` output; Markdown remains via
`--format markdown` with its assertions intact.

---

## 2. Non-Functional Requirements Traceability

| ID | Category | TRD | DRD / Section | Verification | Status |
|---|---|---|---|---|---|
| NFR-001 | Performance | TR-013 | scanner/renderer | `tests/test_performance.py`: warm 1,000 files (~15 MB) < 4.0 s best-of-3; cold correctness + <60 s guardrail | Verified (quiet ~1.0 s; contended ~2.5 s, code-identical) |
| NFR-002 | Memory | TR-013 | renderer/writer | `tests/test_performance.py`: ~50 MB text, tracemalloc peak < 100 MB, streaming path | Verified (48.8 MB → 50.3 MB peak) |
| NFR-003 | Portability | TR-014 | models/scanner | POSIX/`\n` tests; suite executed on 3.11 + 3.12 (3.10 unavailable here); clean-venv wheel install + arbitrary-cwd run | Verified |
| NFR-004 | Security | TR-015 | writer/scanner/updater | no-upload, no-follow, read-only, filename-only reports, allow-listed updates | Verified (all suites) |
| NFR-005 | Reliability | TR-015 | scanner/writer | checksums, atomic-write tests, no-corruption update test | Verified |
| NFR-006 | Determinism | TR-016 | scanner/renderer | SHA-256 equality + stream/render byte-identity | Verified |
| NFR-007 | Zero-deps | TR-017 | `pyproject.toml` | import surface check (incl. updater stdlib-only) | Verified |
| NFR-008 | Usability | TR-012 | cli/reporter | exact menu + `[INFO]`/`[OK]` + confirmation tests | Verified |
| NFR-009 | Testability | TR-018 | `tests/` | pytest suite incl. contract + ux + perf tests | Verified |
| NFR-010 | Encoding | TR-014 | classifier | UTF-8/Latin-1/mixed tests | Verified |
| NFR-011 | License honesty | TR-019 | `LICENSE` + metadata | file-exists check | Verified |

---

## 3. Cross-Document Consistency (v2.1)

1. CLI vocabulary (menu `1..7`, `dump`, `--output`, `--format`, `--dry-run`,
   `--include-hidden`, `--exclude`, `--max-file-size`, `--help`,
   `--version`) identical across README/PRD/TRD/DRD.
2. Default output identical everywhere: `<name>.txt` inside the scanned
   project root (self-excluded on rescan); Markdown only via `--format markdown`.
3. Plain-text layout identical everywhere: `CODEBASE DUMP:` →
   `PROJECT STRUCTURE` → `FILE:`/`END FILE:` × N → `EXCLUDED FILES`.
4. Exclusion precedence identical everywhere: self-output > sensitive >
   noise > hidden > user globs > size > binary.
5. Updater contract identical everywhere: official GitHub Releases source,
   stable-only, allow-listed wheel installs, editable→manual route, honest
   unavailable state (no releases published).
6. Zero-runtime-dependency + offline-dumping guarantees in all docs.
7. Honesty rule (real stats, no secret values, no fabricated releases,
   pre-share review) in README/PRD/TRD/DRD/EDR.
