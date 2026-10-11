"""Tests for the v1.1 UX refactor: new menu, `.txt` contract, updater.

- Interactive menu options 1-7 (with mocked browser/updater where needed).
- Plain-text output contract: no Markdown headings or fences, verbatim
  source, FILE/END FILE markers, metadata lines.
- Update flows: missing/existing dumps, confirmations, cancellation.
- Updater unit behavior with mocked network and installer: version
  comparison, all check states, prereleases, malformed metadata, untrusted
  sources, download/install success and failure, install-method routing.
- No project modification by dumping or update checks (hash verified).

Network access and package installation are always mocked here; nothing
leaves the process and no real install is performed.
"""

import hashlib
import io
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

import codedumper
from codedumper import updater
from codedumper.cli import main, run_interactive_menu
from codedumper.updater import UpdateCheck


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def work_project(tmp_path: Path) -> Path:
    proj = tmp_path / "work proj"
    proj.mkdir()
    src = proj / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "# sample comment\ndef main():\n    print('Hello')\n", encoding="utf-8"
    )
    (proj / ".env").write_text("TOKEN=secret-value\n", encoding="utf-8")
    return proj


def _available_check(tmp_path: Path) -> UpdateCheck:
    return UpdateCheck(
        state="available",
        installed_version="1.0.0",
        latest_version="9.9.9",
        release=updater.ReleaseInfo(
            version="9.9.9",
            tag="v9.9.9",
            assets=[{
                "name": "codedumper-9.9.9-py3-none-any.whl",
                "url": "https://github.com/farhadakhtar/code_dumper/releases/download/v9.9.9/codedumper-9.9.9-py3-none-any.whl",
                "size": "1234",
            }],
        ),
        note="available",
    )


class _FakeResponse:
    """Minimal urlopen() stand-in (context manager + read + status)."""

    def __init__(self, payload: bytes, status: int = 200):
        self._stream = io.BytesIO(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1):
        return self._stream.read(size)


# ---------------------------------------------------------------------------
# Plain-text output contract
# ---------------------------------------------------------------------------

def test_txt_contract_exact_layout(work_project: Path, tmp_path: Path):
    out = tmp_path / "dump.txt"
    rc = main(["dump", str(work_project), "-o", str(out), "--force"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "CODEBASE DUMP: work proj"
    assert "PROJECT STRUCTURE" in lines
    # Plain-text contract: no Markdown heading markers or code fences.
    # (Source lines like "# sample comment" are content, not headings.)
    assert "## " not in text
    assert "```" not in text
    # File section with metadata + verbatim source + end marker.
    assert "FILE: src/main.py" in lines
    assert "Language: Python" in lines
    src_size = (work_project / "src" / "main.py").stat().st_size
    assert f"Size: {src_size} bytes" in lines
    assert "Lines: 3" in lines
    assert "# sample comment" in text  # source preserved exactly
    assert "    print('Hello')" in text  # indentation preserved
    assert "END FILE: src/main.py" in lines
    # Secrets excluded, reasons reported in plain text.
    assert "secret-value" not in text
    assert "EXCLUDED FILES" in lines
    env_size = (work_project / ".env").stat().st_size
    assert f".env | SENSITIVE_CREDENTIAL | {env_size} bytes" in text


def test_txt_output_deterministic(work_project: Path, tmp_path: Path):
    from codedumper.models import ScanConfig
    from codedumper.renderer import render_text
    from codedumper.scanner import scan_repository

    def build(name: str) -> str:
        cfg = ScanConfig(target_dir=work_project, output_path=tmp_path / name)
        return render_text(cfg, scan_repository(cfg))

    assert build("a.txt") == build("b.txt")


def test_markdown_format_still_supported(work_project: Path, tmp_path: Path):
    out = tmp_path / "dump.md"
    rc = main(["dump", str(work_project), "-o", str(out), "--force",
               "--format", "markdown"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Codebase Dump: work proj")
    assert "```python" in text


def test_invalid_format_rejected(work_project: Path, tmp_path: Path, capsys):
    from codedumper.cli import execute_dump
    rc = execute_dump(str(work_project),
                      output_path=str(tmp_path / "x.txt"),
                      dump_format="pdf")
    assert rc == 1
    assert "Unknown format" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Updater flows reachable without the menu (mocked; no real network)
# ---------------------------------------------------------------------------

def test_update_check_unavailable_reports_manual_route(monkeypatch, capsys):
    monkeypatch.setattr(
        updater, "check_for_updates",
        lambda: UpdateCheck(state="unavailable", installed_version="1.1.0",
                            note="No published releases exist yet."))
    assert updater.run_update_interactive() == 0
    out = capsys.readouterr().out
    assert "No published releases exist yet." in out
    assert "Manual update route" in out


def test_update_check_up_to_date_reports_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(
        updater, "check_for_updates",
        lambda: UpdateCheck(state="up_to_date", installed_version="1.1.0",
                            latest_version="1.1.0", note="current"),
    )
    assert updater.run_update_interactive() == 0
    assert "up to date" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Updater: version comparison
# ---------------------------------------------------------------------------

def test_is_newer_cases():
    assert updater.is_newer("1.1.0", "1.0.0") is True
    assert updater.is_newer("1.1.0", "1.1.0") is False
    assert updater.is_newer("1.0.0", "2.0.0") is False
    assert updater.is_newer("v1.2.0", "1.1.9") is True
    assert updater.is_newer("1.1", "1.1.0") is False  # equal after padding
    assert updater.is_newer("not-a-version", "1.0.0") is None
    assert updater.is_newer("1.0.0", "bogus") is None


def test_check_states_with_injected_fetcher(monkeypatch):
    monkeypatch.setattr(codedumper, "__version__", "1.0.0")

    up = updater.check_for_updates(
        fetcher=lambda: updater.ReleaseInfo(version="1.0.0", tag="v1.0.0"))
    assert up.state == "up_to_date"

    new = updater.check_for_updates(
        fetcher=lambda: updater.ReleaseInfo(version="2.0.0", tag="v2.0.0"))
    assert new.state == "available"
    assert new.latest_version == "2.0.0"

    def boom():
        raise updater.UpdateError("network-error: down")
    missing = updater.check_for_updates(fetcher=boom)
    assert missing.state == "unavailable"
    assert "network-error" in missing.note

    def crash():
        raise RuntimeError("surprise")
    assert updater.check_for_updates(fetcher=crash).state == "unavailable"

    weird = updater.check_for_updates(
        fetcher=lambda: updater.ReleaseInfo(version="xx", tag="xx"))
    assert weird.state == "unavailable"


def test_check_ignores_prerelease_and_draft(monkeypatch):
    monkeypatch.setattr(codedumper, "__version__", "1.0.0")

    def pre():
        raise updater.UpdateError("prerelease-ignored")
    assert updater.check_for_updates(fetcher=pre).state == "up_to_date"

    def draft():
        raise updater.UpdateError("draft-ignored")
    assert updater.check_for_updates(fetcher=draft).state == "up_to_date"


def test_fetch_network_error_and_malformed(monkeypatch):
    def fail(url, timeout=None):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fail)
    with pytest.raises(updater.UpdateError, match="network-error"):
        updater.fetch_latest_release()

    def bad_json(url, timeout=None):
        return _FakeResponse(b"this is not json {{{")
    monkeypatch.setattr(updater.urllib.request, "urlopen", bad_json)
    with pytest.raises(updater.UpdateError, match="malformed"):
        updater.fetch_latest_release()

    def not_found(url, timeout=None):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(updater.urllib.request, "urlopen", not_found)
    with pytest.raises(updater.UpdateError, match="no-published-release"):
        updater.fetch_latest_release()

    def bad_tag(url, timeout=None):
        return _FakeResponse(b'{"tag_name": "yesterday", "assets": []}')
    monkeypatch.setattr(updater.urllib.request, "urlopen", bad_tag)
    with pytest.raises(updater.UpdateError, match="malformed"):
        updater.fetch_latest_release()


def test_fetch_prerelease_flagged(monkeypatch):
    def pre(url, timeout=None):
        return _FakeResponse(
            b'{"tag_name": "v9.9.9-rc.1", "prerelease": true, "assets": []}')
    monkeypatch.setattr(updater.urllib.request, "urlopen", pre)
    with pytest.raises(updater.UpdateError, match="prerelease-ignored"):
        updater.fetch_latest_release()


def test_fetch_valid_release_parsed(monkeypatch):
    def good(url, timeout=None):
        return _FakeResponse(
            b'{"tag_name": "v2.3.0", "name": "Two", "prerelease": false,'
            b' "assets": [{"name": "a.whl",'
            b' "browser_download_url": "https://x/y.whl", "size": 10}]}')
    monkeypatch.setattr(updater.urllib.request, "urlopen", good)
    assert "api.github.com" in updater.RELEASES_LATEST_URL
    rel = updater.fetch_latest_release()
    assert (rel.version, rel.tag) == ("2.3.0", "v2.3.0")
    assert rel.assets[0]["name"] == "a.whl"


# ---------------------------------------------------------------------------
# Updater: asset trust, download, install
# ---------------------------------------------------------------------------

def test_select_install_asset_trust_allowlist():
    trusted = {
        "name": "codedumper-9.9.9-py3-none-any.whl",
        "url": "https://github.com/farhadakhtar/code_dumper/releases/download/v9.9.9/codedumper-9.9.9-py3-none-any.whl",
        "size": "1",
    }
    foreign = {
        "name": "codedumper-9.9.9-py3-none-any.whl",
        "url": "https://evil.example.com/codedumper-9.9.9-py3-none-any.whl",
        "size": "1",
    }
    lookalike = {
        "name": "codedumper-9.9.9-py3-none-any.whl",
        "url": "https://github.com.evil.example.com/farhadakhtar/code_dumper/releases/download/v9.9.9/a.whl",
        "size": "1",
    }
    rel = updater.ReleaseInfo(version="9.9.9", tag="v9.9.9",
                              assets=[foreign, lookalike, trusted])
    assert updater.select_install_asset(rel) == trusted

    assert updater.select_install_asset(
        updater.ReleaseInfo(version="9.9.9", tag="v9.9.9",
                            assets=[foreign])) is None
    assert updater.select_install_asset(
        updater.ReleaseInfo(version="9.9.9", tag="v9.9.9", assets=[
            {"name": "notes.txt",
             "url": updater.TRUSTED_ASSET_PREFIX + "v9/notes.txt",
             "size": "1"}])) is None
    assert updater.select_install_asset(
        updater.ReleaseInfo(version="9.9.9", tag="v9.9.9",
                            assets=[])) is None


def test_download_refuses_untrusted_and_non_wheel(tmp_path: Path):
    with pytest.raises(updater.UpdateError, match="untrusted-update-source"):
        updater.download_asset("https://evil.example.com/x.whl", tmp_path)
    with pytest.raises(updater.UpdateError, match="untrusted-update-source"):
        updater.download_asset(
            "https://github.com/other/repo/releases/download/v1/a.whl",
            tmp_path)
    with pytest.raises(updater.UpdateError, match="unsupported-asset-type"):
        updater.download_asset(
            updater.TRUSTED_ASSET_PREFIX + "v1/setup.exe", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_success_and_size_cap(monkeypatch, tmp_path: Path):
    def good(url, timeout=None):
        return _FakeResponse(b"WHEELBYTES" * 100)
    monkeypatch.setattr(updater.urllib.request, "urlopen", good)
    dest = updater.download_asset(
        updater.TRUSTED_ASSET_PREFIX + "v9/a.whl", tmp_path)
    assert dest.read_bytes() == b"WHEELBYTES" * 100

    def huge(url, timeout=None):
        return _FakeResponse(b"Z" * 10)
    monkeypatch.setattr(updater.urllib.request, "urlopen", huge)
    with pytest.raises(updater.UpdateError, match="download-too-large"):
        updater.download_asset(
            updater.TRUSTED_ASSET_PREFIX + "v9/b.whl", tmp_path,
            max_bytes=5)
    assert not (tmp_path / "b.whl").exists()


def test_install_wheel_reports_success_and_failure(monkeypatch, tmp_path: Path):
    import subprocess as std_subprocess

    class Done:
        def __init__(self, code):
            self.returncode = code
            self.stdout = "ok-output"
            self.stderr = ""

    monkeypatch.setattr(
        updater.subprocess, "run", lambda *a, **k: Done(0))
    ok, tail = updater.install_wheel_file(tmp_path / "a.whl")
    assert ok is True and "ok-output" in tail

    monkeypatch.setattr(
        updater.subprocess, "run", lambda *a, **k: Done(1))
    ok, _ = updater.install_wheel_file(tmp_path / "a.whl")
    assert ok is False

    def missing(*a, **k):
        raise FileNotFoundError("no pip")
    monkeypatch.setattr(updater.subprocess, "run", missing)
    ok, tail = updater.install_wheel_file(tmp_path / "a.whl")
    assert ok is False and "pip" in tail


def test_installed_dist_version_live_and_missing(monkeypatch):
    assert updater.installed_dist_version() == codedumper.__version__

    import importlib.metadata as md
    monkeypatch.setattr(md, "version", lambda name: (_ for _ in ()).throw(
        md.PackageNotFoundError()))
    assert updater.installed_dist_version() is None


def test_detect_install_method_variants(monkeypatch):
    import importlib.metadata as md

    class Dist:
        def __init__(self, files):
            self._files = files

        def read_text(self, name):
            if name in self._files:
                return self._files[name]
            return None

        def locate_file(self, _):
            return "site-packages"

    monkeypatch.setattr(
        md, "distribution",
        lambda name: Dist({"direct_url.json": '{"dir_info": {"editable": true}}'}))
    assert updater.detect_install_method().startswith("editable:")

    monkeypatch.setattr(
        md, "distribution",
        lambda name: Dist({"direct_url.json": '{"url": "git+https://x/y.git"}'}))
    assert updater.detect_install_method().startswith("git:")

    monkeypatch.setattr(
        md, "distribution", lambda name: Dist({"INSTALLER": "pip\n"}))
    assert updater.detect_install_method() == "pypi"

    def nodist(name):
        raise md.PackageNotFoundError()
    monkeypatch.setattr(md, "distribution", nodist)
    assert updater.detect_install_method() == "unknown"


# ---------------------------------------------------------------------------
# Updater: interactive install flows (all mocked)
# ---------------------------------------------------------------------------

def test_update_decline_makes_no_changes(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method", lambda: "pypi")
    called = []
    monkeypatch.setattr(updater, "download_asset",
                        lambda *a, **k: called.append(1) or Path("x"))
    with patch("builtins.input", return_value="n"):
        assert updater.run_update_interactive() == 0
    assert called == []
    assert "no changes made" in capsys.readouterr().out.lower()


def test_update_accept_install_success_verified(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method", lambda: "pypi")
    wheel = tmp_path / "pkg.whl"
    wheel.write_bytes(b"fake-wheel")
    monkeypatch.setattr(updater, "download_asset",
                        lambda url, dest, **k: wheel)
    monkeypatch.setattr(updater, "install_wheel_file",
                        lambda path, **k: (True, "installed"))
    monkeypatch.setattr(updater, "installed_dist_version",
                        lambda: "9.9.9")
    with patch("builtins.input", return_value="y"):
        assert updater.run_update_interactive() == 0
    out = capsys.readouterr().out
    assert "SUCCESS" in out and "9.9.9" in out


def test_update_accept_install_failure_reported(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method", lambda: "pypi")
    wheel = tmp_path / "pkg.whl"
    wheel.write_bytes(b"fake-wheel")
    monkeypatch.setattr(updater, "download_asset",
                        lambda url, dest, **k: wheel)
    monkeypatch.setattr(updater, "install_wheel_file",
                        lambda path, **k: (False, "permission denied"))
    monkeypatch.setattr(updater, "installed_dist_version",
                        lambda: "1.0.0")
    with patch("builtins.input", return_value="yes"):
        assert updater.run_update_interactive() == 0
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "Manual update route" in out
    assert "SUCCESS" not in out


def test_update_accept_download_failure_reported(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method", lambda: "pypi")

    def fail_download(url, dest, **k):
        raise updater.UpdateError("network-error: down")
    monkeypatch.setattr(updater, "download_asset", fail_download)
    with patch("builtins.input", return_value="y"):
        assert updater.run_update_interactive() == 0
    out = capsys.readouterr().out
    assert "Download failed" in out
    assert "Manual update route" in out


def test_update_no_asset_offers_manual_route(monkeypatch, capsys, tmp_path: Path):
    check = UpdateCheck(
        state="available", installed_version="1.0.0", latest_version="9.9.9",
        release=updater.ReleaseInfo(version="9.9.9", tag="v9.9.9",
                                    assets=[]),
        note="available")
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    with patch("builtins.input") as mock_input:
        assert updater.run_update_interactive() == 0
    mock_input.assert_not_called()  # never even asks: nothing safe to install
    assert "Manual update route" in capsys.readouterr().out


def test_update_editable_install_keeps_method(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method",
                        lambda: "editable:C:/src")
    with patch("builtins.input") as mock_input:
        assert updater.run_update_interactive() == 0
    mock_input.assert_not_called()
    out = capsys.readouterr().out
    assert "preserve your installation method" in out
    assert "Manual update route" in out


def test_update_confirm_eof_cancels(monkeypatch, capsys, tmp_path: Path):
    check = _available_check(tmp_path)
    monkeypatch.setattr(updater, "check_for_updates", lambda: check)
    monkeypatch.setattr(updater, "detect_install_method", lambda: "pypi")
    with patch("builtins.input", side_effect=EOFError):
        assert updater.run_update_interactive() == 0
    assert "no changes made" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Dumping and update checks never modify the project
# ---------------------------------------------------------------------------

def test_dump_leaves_project_untouched(tmp_path: Path, monkeypatch):
    proj = tmp_path / "pristine"
    proj.mkdir()
    (proj / "a.py").write_text("print(1)\n", encoding="utf-8")
    (proj / "data.txt").write_text("hello\n", encoding="utf-8")
    before = _hash_tree(proj)

    monkeypatch.chdir(proj)
    with patch("builtins.input", side_effect=["1", "", "7"]):
        assert run_interactive_menu() == 0

    assert _hash_tree(proj) == before
    assert (tmp_path / "pristine.txt").exists()  # dump went outside
