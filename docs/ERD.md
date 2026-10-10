# Entity Relationship Diagram & Data Model: CodeDumper

**Document Version:** 2.0.0
**Status:** Approved
**Author:** Engineering Team
**Source of Truth:** `README.md` + `docs/PRD.md` (v2.0.0)
**File:** `docs/ERD.md`

---

## 1. Persistence Assessment

### 1.1 Evaluated Storage Paradigms

1. **Relational / document database (SQLite, PostgreSQL, …):**
   *Assessment:* Rejected. CodeDumper is a stateless file-to-file CLI; a
   database adds migrations, locks, and dependencies for zero user benefit.
2. **Persistent scan cache / history:**
   *Assessment:* Rejected for MVP. Full deterministic traversal of 1,000 files
   takes <0.5 s; caches risk stale reads.
3. **Local configuration file (`.codedumperrc`):**
   *Assessment:* Deferred (post-MVP "configuration profiles"). Menu option `4`
   keeps patterns session-scoped in memory only.
4. **In-memory scan state:** **Required.** Discovered paths, exclusion
   verdicts, and classifications live in runtime dataclasses for one
   invocation.
5. **Output artifact:** **Required.** The single persistent deliverable is the
   generated Markdown file (`<project>.md`).

### 1.2 Persistence Conclusion

No database is introduced. The pipeline transforms local filesystem entries
into one Markdown artifact, plus console output. (`autocommit`'s own
`autocommit_state.json` is companion-scoped and untouched by this decision.)

---

## 2. Logical Entity Model

Runtime Python dataclasses — **not** database tables.

```mermaid
erDiagram
    Project ||--o{ ScanSession : "initiates"
    ScanSession ||--|{ DirectoryEntry : "discovers"
    ScanSession ||--o{ ExclusionRule : "applies"
    DirectoryEntry ||--o| FileEntry : "contains"
    FileEntry ||--|| FileClassification : "has"
    ScanSession ||--|| DumpArtifact : "generates"
    ScanSession ||--|| GenerationReport : "summarizes"
    GenerationReport ||--o{ OmissionRecord : "details"

    Project {
        string root_path PK
        string project_name
        timestamp analyzed_at
    }

    ScanSession {
        string session_id PK
        string target_dir
        string output_path
        boolean include_hidden
        int max_size_bytes
        boolean dry_run
        boolean no_tree
        boolean force_overwrite
        string invocation_mode
    }

    ExclusionRule {
        string rule_id PK
        string pattern
        string category
        boolean is_default
    }

    DirectoryEntry {
        string relative_path PK
        string entry_name
        boolean is_directory
        boolean is_symlink
        int depth
    }

    FileEntry {
        string relative_path PK
        int size_bytes
        string detected_language
        int line_count
    }

    FileClassification {
        string classification_type PK
        boolean is_text
        boolean is_binary
        string encoding
        boolean is_excluded
        string exclusion_reason
    }

    DumpArtifact {
        string output_path PK
        int total_files_dumped
        int total_bytes_written
        string sha256_hash
    }

    GenerationReport {
        int total_discovered
        int total_included
        int total_omitted
        int sensitive_skipped
        float elapsed_seconds
    }

    OmissionRecord {
        string relative_path PK
        string reason
        int file_size
    }
```

### 2.1 Entity Notes (materialized in `codedumper/models.py`)

- **Project:** validated root (`exists`, `is_dir`, readable); `project_name`
  = directory base name → default output `<name>.md` (PRD FR-014).
- **ScanSession:** extends the v1 session with `invocation_mode`
  (`menu | dump | legacy`) and `no_tree` / `force_overwrite` flags.
  `max_size_bytes` > 0 enforced; `--max-file-size` is the primary spelling,
  `--max-size` an alias (PRD FR-009/FR-020).
- **ExclusionRule categories:** `SENSITIVE` (unbypassable) · `DEFAULT_NOISE` ·
  `HIDDEN` · `USER_GLOB` (CLI `--exclude` + menu option-4 session patterns).
- **FileEntry:** `content` held transiently for rendering; never persisted
  except inside the output artifact.
- **DumpArtifact:** absent in `--dry-run` (PRD FR-016).
- **GenerationReport:** console counts (`Files discovered/included/excluded`,
  `Sensitive files skipped`) are projections of this entity — always measured,
  never fabricated (PRD FR-017). `elapsed_seconds` is console-only and
  excluded from the Markdown to preserve determinism (PRD NFR-006).

---

## 3. Relationships and Cardinality

1. **Project → ScanSession (1:N):** repeated scans with different flags are
   isolated sessions.
2. **ScanSession → DirectoryEntry (1:N):** entries belong to one session.
3. **DirectoryEntry → FileEntry (1:0..1).**
4. **FileEntry → FileClassification (1:1).**
5. **ScanSession → DumpArtifact (1:0..1):** zero in dry-run.
6. **ScanSession → GenerationReport (1:1)** → **OmissionRecord (1:N).**

---

## 4. Data Flow

```mermaid
flowchart TD
    FS[Local Filesystem] -->|Recursive sorted traversal| Scanner[Scanner]
    Scanner -->|Candidate entries| Filter[Exclusion Engine]
    Filter -->|Sensitive? Noise? Hidden? User glob? Size?| Verdict{Excluded?}
    Verdict -->|Yes| Omit[OmissionRecord]
    Verdict -->|No| Classify[Binary / encoding check]
    Classify -->|Binary / unreadable| Omit
    Classify -->|Text| Read[Read + normalize to LF]
    Read --> Tree[Project Structure tree]
    Read --> Render[Markdown renderer: title + tree + File sections + Excluded Files]
    Omit --> Render
    Render --> Persist{--dry-run?}
    Persist -->|Yes| Console[Console report only]
    Persist -->|No| Atomic[Atomic write via temp file + os.replace]
    Atomic --> Artifact[(<project>.md)]
    Omit --> Console
```

Exclusion precedence (normative): **sensitive > default noise > hidden >
user globs > size limit > binary/encoding** (PRD FR-009–FR-013).

---

## 5. Data Integrity and Privacy

1. Relative paths normalized to POSIX (`a/b.py`); `\n` line endings in output.
2. Deterministic sorting at every level; Markdown excludes wall-clock timing.
3. Symlinks never followed; traversal stays within the project root.
4. Exclusion report carries filenames + reasons only — never file contents or
   secret values.
5. Source tree opened read-only; output written atomically beside the
   destination.
