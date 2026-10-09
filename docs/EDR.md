# Engineering Design Review (EDR): CodeDumper

**Document Version:** 1.0.0  
**Status:** Approved  
**Review Lead:** Principal Systems Engineer  
**File:** `docs/EDR.md`  

---

## 1. Executive Summary

This Engineering Design Review evaluates the proposed architecture, specifications, and data models for **CodeDumper** as documented in `docs/PRD.md`, `docs/ERD.md`, `docs/TRD.md`, and `docs/DRD.md`. 

The objective of CodeDumper is to serialize an entire codebase into a clean, single-file Markdown artifact tailored for consumption by AI coding assistants. The review team assessed the technical feasibility, security boundaries, edge-case failure modes, performance, and cross-platform compatibility of the proposed design.

---

## 2. Requirements Completeness Review

The PRD establishes 18 functional requirements (`FR-001` to `FR-018`) and 10 non-functional requirements (`NFR-001` to `NFR-010`). 
- **Clarity & Specificity:** Scope boundaries are well demarcated. The distinction between MVP features and out-of-scope capabilities (e.g., direct API token submission, AST minification) is clearly established.
- **Testability:** Every requirement has concrete, binary verification criteria.
- **Completeness:** Core workflows (standard dump, dry run, exclusion rules, error handling) are comprehensively mapped.

---

## 3. Architecture & Modularity Review

The architecture decomposes the pipeline into cleanly decoupled modules:
- `codedumper.cli`: Orchestration & CLI lifecycle.
- `codedumper.scanner`: Traversal & node discovery.
- `codedumper.filter`: Rule evaluation engine.
- `codedumper.classifier`: Content inspection & syntax tagging.
- `codedumper.tree`: Hierarchical representation.
- `codedumper.renderer`: Markdown serialization.
- `codedumper.writer`: Atomic I/O management.
- `codedumper.reporter`: Telemetry and omission summaries.

**Evaluation:**
- **Cohesion:** High. Each module is focused on a single domain responsibility.
- **Coupling:** Low. Modules exchange data through immutable dataclasses (`ScanConfig`, `FileItem`, `OmissionRecord`, `ScanResult`).
- **Dependencies:** Unidirectional flow. No circular dependencies exist.
- **Complexity:** Minimal. Zero external runtime dependencies ensures negligible maintenance burden.

---

## 4. Data-Model Review

The ERD was critically examined for overengineering:
- **Persistence Verification:** Confirmed that no relational or document database is introduced. The application state is transient and purely functional.
- **Durable Deliverable:** The only persisted entity is the generated Markdown file on disk.
- **Memory Consumption:** Dataclasses represent lightweight metadata. File contents are loaded sequentially rather than hoarding the entire repository in memory indefinitely.

---

## 5. Technical Feasibility & Cross-Platform Review

- **Path Handling:** Windows backslashes (`\`) vs. POSIX forward slashes (`/`). Normalization to forward slashes across all Markdown output ensures cross-platform consistency.
- **Encoding Robustness:** Attempting strict `utf-8` with fallback to `utf-8` (`replace`) or `latin-1` ensures that mixed or legacy files will never cause unhandled crashes.
- **Dynamic Fences:** The variable code fence algorithm (`max(3, max_backticks + 1)`) reliably prevents Markdown parsing corruption when source code contains code blocks.

---

## 6. Security & Privacy Review

| Security Area | Risk Assessment | Mitigation in Design |
|---|---|---|
| **Secret Leakage** | High: Accidental inclusion of `.env`, SSH keys, certificates into AI prompt. | Strict, unbypassable default exclusion patterns for credentials and secrets (`.env*`, `*.pem`, `*.key`, `id_rsa*`). |
| **Path Traversal** | Medium: Malicious target or output paths attempting to read or overwrite `/etc` or `C:\Windows`. | Path resolution via `Path.resolve()` and relative path boundary verification. |
| **Accidental Overwrite** | High: Overwriting source files or pre-existing documentation. | Default refusal to overwrite existing destination files unless `--force` is explicitly provided. |
| **Symlink Attacks** | Medium: Recursive symlink loops causing infinite traversal or escaping repository root. | Symlinks are strictly not followed recursively. |
| **Partial / Corrupted Writes** | Medium: Process crash during write leaves half-written file. | Output is written to a sibling temporary file and swapped atomically using `os.replace`. |

---

## 7. Failure-Mode Analysis

| Failure Scenario | Effect | Detection Mechanism | Mitigation Strategy |
|---|---|---|---|
| **Permission Denied on Directory** | Traversal cannot access subdirectory. | `PermissionError` during filesystem read. | Catch exception, record omitted directory with reason `PERMISSION_DENIED`, continue scanning remaining folders. |
| **Destination File Already Exists** | Potential data destruction. | Pre-flight `output_path.exists()` check. | Halt immediately with Exit Code `1` and explanatory error message unless `--force` flag was passed. |
| **Invalid Character Encodings** | `UnicodeDecodeError` on binary or unusual text. | Multi-tier decode try-except block. | Detect binary via 8 KB sample; fallback decode with error replacement for text. |
| **SIGINT / Ctrl+C Interruption** | Incomplete output file on disk. | Signal handler intercepting `KeyboardInterrupt`. | Clean up temporary output file; exit cleanly with code `130`. |
| **Disk Full During Write** | Write operation fails midway. | `OSError` (ENOSPC). | Temporary file write fails; target file is not replaced; temp file deleted; return exit code `2`. |

---

## 8. Findings Register

| ID | Severity | Description | Recommended Action | Status |
|---|---|---|---|---|
| **EDR-001** | High | Default output path in repository root could accidentally be committed or overwrite existing README. | Default output path must be `<target_directory_name>.md` outside or inside with overwrite protection. | **Resolved** |
| **EDR-002** | High | Source files containing Markdown backticks cause fence collisions in standard triple-backtick output. | Implement dynamic fencing calculating maximum consecutive backticks plus one. | **Resolved** |
| **EDR-003** | Medium | Large media and binary assets inflate Markdown file size and crash LLM token contexts. | Implement 8 KB header sampling for null bytes and enforce 1 MB max file size default. | **Resolved** |
| **EDR-004** | Medium | Accidental inclusion of `.env` files in AI prompt leaks sensitive credentials. | Enforce hardcoded high-precedence blacklist for secret and credential file patterns. | **Resolved** |
| **EDR-005** | Low | Windows path separators in Markdown output break formatting consistency on Linux/macOS. | Normalize all relative paths to POSIX forward slashes (`/`). | **Resolved** |

---

## 9. Key Design Decisions

1. **Standard Library Only:** Zero third-party runtime dependencies chosen to guarantee security, fast startup, and universal compatibility.
2. **Stateless Processing:** Relational databases, local caches, and disk state files rejected as unnecessary complexity.
3. **Coexistence with Autocommit:** The existing `autocommit` package will be preserved as a companion module rather than deleted, respecting existing work.

---

## 10. Review Verdict

**VERDICT: APPROVED**

The engineering design for CodeDumper is approved for implementation. The requirements are complete, the architecture is sound, the security mitigations are verified, and all findings in the register are resolved.
