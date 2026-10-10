# Engineering Design Review (EDR): CodeDumper

**Document Version:** 2.0.0
**Status:** Approved
**Review Lead:** Principal Systems Engineer
**Scope:** `README.md` (working copy) vs. v1.x implementation/docs
**File:** `docs/EDR.md`

---

## 1. Executive Summary

The working-copy `README.md` normatively redefines CodeDumper: an
interactive `CODEDUMPER CLI` menu on bare invocation plus a `codedumper dump
…` subcommand (`--output/--dry-run/--include-hidden/--exclude/
--max-file-size/--help/--version`), a new Markdown layout (`# Codebase Dump`,
`## Project Structure`, `## File:`, exclusion reporting), and honesty,
safety, and test-coverage obligations. The v1.x implementation matches the
**superseded** HEAD README instead: direct-dump CLI, `--max-size` only, old
headings, no menu, no `dump` verb, and a license claim without a `LICENSE`
file. **Verdict: redesign approved; implementation must be rebuilt to the
v2 contract while preserving the engine and all still-valid safety
behavior.** PRD/ERD/TRD/DRD v2.0.0 (this review's basis) were rewritten from
the working-copy README and are approved below.

---

## 2. Requirements Completeness Review

- PRD v2: 20 functional (FR-001…FR-020) + 11 non-functional (NFR-001…NFR-011).
  Every README command, flag, output section, safety rule, and test bullet
  maps to at least one requirement; FR-020/NFR-011 close the compat/license
  gaps the README implies but never states outright.
- Each requirement has a binary gate in PRD §9 (release checklist).
- Out-of-scope and deferred items mirror the README roadmap; `autocommit` is
  explicitly fenced out of CodeDumper scope but preserved.

---

## 3. Architecture & Modularity Review

- Pipeline retained: `cli → scanner → filter → classifier → tree →
  renderer → writer → reporter`; immutable dataclass handoffs; one-way flow.
- New behavior folded into existing homes: menu + `dump` parsing in `cli.py`
  (no speculative `exporter/exclusions/safety/config.py` modules, per README
  "do not create unnecessary modules").
- Coupling/cohesion unchanged (high/low); no circular imports; stdlib-only
  runtime preserved.

---

## 4. Data-Model Review

- No database — reaffirmed (ERD v2 §1); session state in-memory; Markdown
  artifact the sole deliverable.
- `ScanSession` gains `invocation_mode` (`menu|dump|legacy`); timing stays in
  `ScanResult` for the console but is excluded from the file → determinism
  (NFR-006) holds by construction.
- Exclusion precedence single-sourced in TRD §5.2 / DRD §4.2; identical order
  in filter + scanner + classifier.

---

## 5. Technical Feasibility & Cross-Platform Review

- `argparse` subcommands + `input()` menu are portable; EOF/`KeyboardInterrupt`
  paths specified (exit `0`/`130`).
- Size grammar, POSIX/`\n` normalization, UTF-8→`latin-1`→`replace` fallback,
  dynamic fences, atomic writes — all standard, feasible on 3.10+.
- Menu testability via injected `input()` confirmed (contract tests patch
  `builtins.input`).

---

## 6. Security & Privacy Review

| Area | Risk | Mitigation (v2 design) |
|---|---|---|
| Secret leakage | High | Unbypassable sensitive tier incl. `--include-hidden`; filename-only reports; pre-share review disclaimer |
| Silent overwrite | High | Refuse w/o `--force` (CLI) / confirm (menu); atomic temp swap |
| Symlink escape/loops | Medium | Never follow; record omission; depth guard |
| Partial writes | Medium | `flush/fsync` + `os.replace`; cleanup on failure |
| Exfiltration | Low | Offline-only; no network imports |
| Fake stats | Low | Counts projected from `ScanResult`; README-derived honesty rule FR-017 |

---

## 7. Failure-Mode Analysis

| Scenario | Effect | Detection | Mitigation |
|---|---|---|---|
| `dump` target missing | usage error | `exists`/`is_dir` check | stderr + exit `1` |
| Bad `--max-file-size` | usage error | size grammar | stderr + exit `1` |
| Output exists, no `--force` | data-loss risk | pre-flight `exists()` | exit `1` (menu: confirm) |
| Unreadable file/dir | partial scan | `PermissionError`/`OSError` | omission record, continue |
| Non-UTF-8 content | decode risk | tiered fallback | `latin-1`/`replace`, never crash |
| Source with backticks | fence collision | `calculate_code_fence` | longer fence |
| `Ctrl+C` | interruption | `KeyboardInterrupt`/SIGINT | cleanup temp, exit `130` |
| Disk full | failed write | `OSError` | destination untouched, exit `2` |
| Menu EOF | closed stdin | `EOFError` | clean exit `0` |

---

## 8. Findings Register

| ID | Severity | Description | Action | Status |
|---|---|---|---|---|
| EDR-001 | High | No `dump` subcommand; bare invocation dumps instead of menu | Add `dump` subparser; bare → menu (FR-001/002) | **Approved for build** |
| EDR-002 | High | `--max-file-size` missing (only `--max-size`) | Primary `--max-file-size` + `--max-size` alias (FR-009) | **Approved for build** |
| EDR-003 | High | Markdown headings differ from README (`Directory Tree/Repository Files/Omission Manifest/TOC`) | Retire old headings; emit `Project Structure/File:/Excluded Files` (TRD §6) | **Approved for build** |
| EDR-004 | High | No interactive menu at all | Implement options `1..6` per TRD §4 (DRD §3.7) | **Approved for build** |
| EDR-005 | Medium | `LICENSE` missing while `pyproject.toml` claims MIT | Add MIT `LICENSE` (NFR-011) | **Approved for build** |
| EDR-006 | Medium | `Scan Duration` rendered into the file breaks byte-determinism | Keep timing console-only (already fixed; covered by TR-016) | **Resolved** |
| EDR-007 | Medium | `pyproject.toml` `readme = "Readme.md"` breaks case-sensitive builds | Use `README.md` (already fixed; TR-017) | **Resolved** |
| EDR-008 | Low | `run_watcher.py` docstring advertised `--config` with no such flag | Implement `--config` copy (already fixed) | **Resolved** |
| EDR-009 | Low | `requirements.txt` pinned `gitpython>=3.1.0` vs `pyproject` `>=3.1.40` | Align to `>=3.1.40` (already fixed) | **Resolved** |
| EDR-010 | Low | Tree shows sensitive filenames (contents never embedded) | Accepted: matches "layout incl. omitted paths"; names-only is consistent with exclusion-table reporting | **Accepted** |

---

## 9. Key Design Decisions

1. **Superset CLI:** support `dump` (documented) + legacy positional
   (compatible) rather than breaking existing users/tests.
2. **No new modules** for the README's suggested files; responsibilities map
   onto proven modules (DRD §3.8).
3. **Stdlib-only runtime** retained though README permits alternatives.
4. **`autocommit` preserved untouched** as a companion; excluded from
   CodeDumper scope.
5. **Honesty as a requirement** (FR-017): illustrative README numbers must
   never ship as hardcoded output.

---

## 10. Review Verdict

**VERDICT: APPROVED FOR BUILD.**

The v2 contract is complete, feasible, and internally consistent. Proceed to
Phase 4: implement the menu + `dump` subcommand + output format + `LICENSE` +
contract tests, keeping all existing safety behavior and the full v1 test
suite green (modulo the one retired-headings assertion).
