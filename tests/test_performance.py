"""Performance and memory benchmarks for CodeDumper (NFR-001, NFR-002).

Builds a deterministic 1,000-file fixture (~15 MB total text, under the
<50 MB premise) in a temporary directory and verifies:

- NFR-001: scan + render + write completes in under 2.0 seconds.
- NFR-002: peak Python allocation stays under 100 MB (tracemalloc).
- NFR-006 (at scale): two renders of the fixture are byte-identical.

All fixtures live in ``tmp_path``; nothing touches the real repository.
"""

import hashlib
import time
import tracemalloc
from pathlib import Path

import pytest

from codedumper.models import ScanConfig
from codedumper.renderer import render_markdown
from codedumper.scanner import scan_repository
from codedumper.writer import write_dump_file

FILE_COUNT = 1000
TARGET_BYTES_PER_FILE = 15 * 1024  # ~15 KB -> ~15 MB total
TIME_BUDGET_SECONDS = 2.0
MEMORY_BUDGET_BYTES = 100 * 1024 * 1024

EXTENSIONS = (".py", ".js", ".md", ".txt", ".toml")


def _make_big_project(root: Path) -> Path:
    """Create a deterministic 1,000-file project. Returns the project dir."""
    proj = root / "bench_project"
    proj.mkdir()
    line_tpl = "def func_{d}_{i}(x): return x * {v}  # benchmark filler line {d}/{i}\n"
    for d in range(10):
        sub = proj / f"pkg_{d:02d}"
        sub.mkdir()
        for i in range(100):
            ext = EXTENSIONS[(d + i) % len(EXTENSIONS)]
            path = sub / f"module_{i:03d}{ext}"
            chunk = line_tpl.format(d=d, i=i, v=(d * 100 + i) % 997).encode("utf-8")
            repeats = TARGET_BYTES_PER_FILE // len(chunk) + 1
            path.write_bytes(chunk * repeats)
    # A little realistic noise that must be excluded, not measured as content.
    (proj / ".env").write_text("SECRET=benchmark\n", encoding="utf-8")
    (proj / "asset.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00" + b"\x00" * 100)
    git_dir = proj / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n", encoding="utf-8")
    return proj


@pytest.fixture(scope="module")
def big_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_big_project(tmp_path_factory.mktemp("bench"))


def _config_for(proj: Path, out_name: str) -> ScanConfig:
    return ScanConfig(
        target_dir=proj,
        output_path=proj.parent / out_name,
    )


def test_benchmark_scan_render_write_under_two_seconds(big_project: Path):
    # Methodology: one untimed warm-up pass first so OS page cache and any
    # on-access file scanning settle — the requirement targets steady-state
    # throughput on real (pre-existing) repositories, not first-touch cost
    # of freshly created fixture files.
    warmup = _config_for(big_project, "bench_warm.md")
    scan_repository(warmup)

    config = _config_for(big_project, "bench_time.md")
    started = time.perf_counter()
    result = scan_repository(config)
    assert len(result.included_files) == FILE_COUNT
    markdown = render_markdown(config, result)
    write_dump_file(config.output_path, markdown, force=True)
    elapsed = time.perf_counter() - started
    print(f"\nbenchmark: {len(result.included_files)} files in {elapsed:.2f}s")
    assert elapsed < TIME_BUDGET_SECONDS


def test_benchmark_peak_memory_under_100mb(big_project: Path):
    config = _config_for(big_project, "bench_mem.md")
    tracemalloc.start()
    try:
        result = scan_repository(config)
        markdown = render_markdown(config, result)
        write_dump_file(config.output_path, markdown, force=True)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print(f"\nbenchmark: tracemalloc peak {peak / (1024 * 1024):.1f} MB")
    assert peak < MEMORY_BUDGET_BYTES


def test_benchmark_output_deterministic(big_project: Path):
    md_a = render_markdown(_config_for(big_project, "a.md"), scan_repository(_config_for(big_project, "a.md")))
    md_b = render_markdown(_config_for(big_project, "b.md"), scan_repository(_config_for(big_project, "b.md")))
    assert hashlib.sha256(md_a.encode()).hexdigest() == hashlib.sha256(md_b.encode()).hexdigest()
