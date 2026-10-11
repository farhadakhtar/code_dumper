"""Self-update support for CodeDumper (callable update-check flow).

Single source of truth for release metadata: GitHub Releases of the
official repository::

    https://api.github.com/farhadakhtar/code_dumper/releases/latest

Only published **stable** releases from that repository are ever
considered (the ``/latest`` endpoint excludes drafts and prereleases by
definition). If no release is published yet, every check reports the
honest ``unavailable`` state with a safe manual-update route instead of
fabricating versions or URLs.

Safety properties:

- No network access happens at import time; only when a check runs.
- Downloaded files are never executed. Installation (when offered) goes
  through ``pip install <downloaded-wheel-file>`` with an argument list
  (never ``shell=True``), and only for assets whose URL is allow-listed to
  the official repository's release downloads.
- Editable / source checkouts keep their installation method: they always
  get the manual-update route, never a pip overwrite.
- Success is reported only after the installed distribution version is
  re-read and matches the release version.
- Failures (network, malformed metadata, download, permissions, install)
  are reported with the manual route; temporary files are cleaned up.
- Nothing outside a temporary directory and pip's own target is touched:
  user projects and existing dumps are never modified.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import codedumper

GITHUB_OWNER = "farhadakhtar"
GITHUB_REPO = "code_dumper"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RELEASES_LATEST_URL = (
    f"https://api.github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
# Only assets served from the official repository's release downloads are
# ever trusted for installation. Anything else is refused outright.
TRUSTED_ASSET_PREFIX = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
)

DISTRIBUTION_NAME = "code_dumper"
DOWNLOAD_TIMEOUT_SECONDS = 30
RELEASE_CHECK_TIMEOUT_SECONDS = 15
MAX_ASSET_BYTES = 50 * 1024 * 1024

MANUAL_UPDATE_STEPS = [
    f"Fetch the latest source: git clone {GITHUB_REPO_URL}.git "
    "(or `git pull` inside your existing checkout).",
    "Reinstall: `python -m pip install -e .` (or install a published "
    "release wheel once one exists).",
    "Verify: `codedumper --version`.",
]


class UpdateError(Exception):
    """Raised for download/install failures (never for plain check results)."""


@dataclass
class ReleaseInfo:
    """A parsed, validated stable release from the official source."""

    version: str
    tag: str
    name: str = ""
    prerelease: bool = False
    assets: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class UpdateCheck:
    """Outcome of :func:`check_for_updates`. Never raises."""

    state: str  # "up_to_date" | "available" | "unavailable"
    installed_version: str
    latest_version: Optional[str] = None
    release: Optional[ReleaseInfo] = None
    note: str = ""


def _version_tuple(version: str) -> Optional[Tuple[int, ...]]:
    """Parse ``1.2.3`` / ``v1.2.3`` into a comparable tuple.

    Returns ``None`` for anything that is not a plain dotted numeric
    version (we refuse to guess rather than mis-order releases).
    """
    cleaned = version.strip().lstrip("vV")
    if not re.fullmatch(r"\d+(?:\.\d+)*", cleaned):
        return None
    return tuple(int(part) for part in cleaned.split("."))


def _pad(parts: Tuple[int, ...], length: int) -> Tuple[int, ...]:
    return parts + (0,) * (length - len(parts))


def is_newer(latest: str, installed: str) -> Optional[bool]:
    """Compare two version strings. ``None`` if either is unparsable."""
    new_parts = _version_tuple(latest)
    old_parts = _version_tuple(installed)
    if new_parts is None or old_parts is None:
        return None
    width = max(len(new_parts), len(old_parts))
    return _pad(new_parts, width) > _pad(old_parts, width)


def _http_get_json(url: str, timeout: int) -> dict:
    """GET a JSON document. Raises :class:`UpdateError` on any failure."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CodeDumper/{codedumper.__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status == 404:
                raise UpdateError("no-published-release")
            if status < 200 or status >= 300:
                raise UpdateError(f"release-source-http-{status}")
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UpdateError(f"malformed-release-metadata: {exc}")
            if not isinstance(payload, dict):
                raise UpdateError("malformed-release-metadata: not-an-object")
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("no-published-release")
        raise UpdateError(f"release-source-http-{exc.code}")
    except urllib.error.URLError as exc:
        raise UpdateError(f"network-error: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        raise UpdateError(f"network-error: {exc}")


def fetch_latest_release(
    timeout: int = RELEASE_CHECK_TIMEOUT_SECONDS,
) -> ReleaseInfo:
    """Fetch and validate the latest stable release. Raises :class:`UpdateError`.

    Prereleases are never returned as installable: a ``prerelease: true``
    payload raises ``UpdateError("prerelease-ignored")`` so callers report
    "up to date" instead of offering it.
    """
    payload = _http_get_json(RELEASES_LATEST_URL, timeout)

    if payload.get("draft"):
        raise UpdateError("draft-ignored")
    if payload.get("prerelease"):
        raise UpdateError("prerelease-ignored")

    tag = payload.get("tag_name") or ""
    if _version_tuple(tag) is None:
        raise UpdateError(f"malformed-release-metadata: bad-tag-{tag!r}")

    assets = []
    raw_assets = payload.get("assets") or []
    if not isinstance(raw_assets, list):
        raise UpdateError("malformed-release-metadata: bad-assets")
    for entry in raw_assets:
        if isinstance(entry, dict) and entry.get("browser_download_url"):
            assets.append(
                {
                    "name": str(entry.get("name") or ""),
                    "url": str(entry.get("browser_download_url")),
                    "size": str(entry.get("size") or ""),
                }
            )

    return ReleaseInfo(
        version=tag.strip().lstrip("vV"),
        tag=tag,
        name=str(payload.get("name") or ""),
        prerelease=False,
        assets=assets,
    )


def check_for_updates(
    fetcher: Callable[[], ReleaseInfo] = fetch_latest_release,
) -> UpdateCheck:
    """Check the official release source. Never raises; never touches disk."""
    installed = codedumper.__version__
    try:
        release = fetcher()
    except UpdateError as exc:
        message = str(exc)
        if message in ("prerelease-ignored", "draft-ignored"):
            return UpdateCheck(
                state="up_to_date",
                installed_version=installed,
                note="The latest published release is a prerelease/draft, "
                "which is never installed automatically. You are on the "
                "latest stable behavior known to this updater.",
            )
        if message == "no-published-release":
            return UpdateCheck(
                state="unavailable",
                installed_version=installed,
                note="No published releases exist yet for the official "
                "repository, so automatic updating is not configured.",
            )
        return UpdateCheck(
            state="unavailable",
            installed_version=installed,
            note=f"Could not reach the release source ({message}).",
        )
    except Exception as exc:  # never let a check crash the menu
        return UpdateCheck(
            state="unavailable",
            installed_version=installed,
            note=f"Could not check for updates ({exc}).",
        )

    newer = is_newer(release.version, installed)
    if newer is None:
        return UpdateCheck(
            state="unavailable",
            installed_version=installed,
            latest_version=release.version,
            release=release,
            note="The release version could not be compared safely, so no "
            "update is offered.",
        )
    if not newer:
        return UpdateCheck(
            state="up_to_date",
            installed_version=installed,
            latest_version=release.version,
            release=release,
            note=f"Installed {installed}; latest stable is {release.version}.",
        )
    return UpdateCheck(
        state="available",
        installed_version=installed,
        latest_version=release.version,
        release=release,
        note=f"CodeDumper {release.version} is available (installed: {installed}).",
    )


def detect_install_method() -> str:
    """Describe how CodeDumper was installed (display + update routing).

    Returns one of: ``"editable:<path>"``, ``"git:<url>"``,
    ``"pypi"``, ``"other:<detail>"``, ``"unknown"``. Editable/source
    checkouts always take the manual-update route.
    """
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover - Python 3.10+ always has this
        return "unknown"
    try:
        dist = importlib_metadata.distribution(DISTRIBUTION_NAME)
    except Exception:
        # Not installed as a distribution (e.g. running from source).
        return "unknown"
    try:
        direct_url_text = dist.read_text("direct_url.json")
    except Exception:
        direct_url_text = None
    if direct_url_text:
        try:
            direct = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct = {}
        url = str(direct.get("url") or "")
        if direct.get("dir_info", {}).get("editable"):
            return f"editable:{url or dist.locate_file('')}"
        if url.startswith(("git+", "git://")) or url.endswith(".git"):
            return f"git:{url}"
        return f"other:{url or 'direct-url'}"
    try:
        installer = (dist.read_text("INSTALLER") or "").strip().lower()
    except Exception:
        installer = ""
    if installer == "pip":
        return "pypi"
    if installer:
        return f"other:{installer}"
    return "unknown"


def _wheel_assets(release: ReleaseInfo) -> List[Dict[str, str]]:
    return [a for a in release.assets if a["name"].endswith(".whl")]


def select_install_asset(release: ReleaseInfo) -> Optional[Dict[str, str]]:
    """Pick the wheel asset to install, enforcing the trust allow-list.

    Returns ``None`` when there is no usable trusted asset (caller then
    offers the manual route instead of installing anything).
    """
    for asset in _wheel_assets(release):
        url = asset.get("url") or ""
        if url.startswith(TRUSTED_ASSET_PREFIX):
            return asset
    return None


def download_asset(
    url: str,
    dest_dir: Path,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
    max_bytes: int = MAX_ASSET_BYTES,
) -> Path:
    """Download a trusted release asset to ``dest_dir``. Raises :class:`UpdateError`."""
    if not url.startswith(TRUSTED_ASSET_PREFIX):
        raise UpdateError(f"untrusted-update-source: {url!r}")
    if not url.endswith(".whl"):
        raise UpdateError(f"unsupported-asset-type: {url!r}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rsplit("/", 1)[-1] or "codedumper-update.whl"
    dest = dest_dir / filename
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"CodeDumper/{codedumper.__version__}"},
    )
    downloaded = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise UpdateError(f"download-http-{status}")
            with open(dest, "wb") as fh:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise UpdateError("download-too-large")
                    fh.write(chunk)
    except UpdateError:
        _quiet_unlink(dest)
        raise
    except urllib.error.URLError as exc:
        _quiet_unlink(dest)
        raise UpdateError(f"network-error: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        _quiet_unlink(dest)
        raise UpdateError(f"download-failed: {exc}")
    if downloaded == 0:
        _quiet_unlink(dest)
        raise UpdateError("download-empty")
    return dest


def _quiet_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def install_wheel_file(wheel_path: Path, timeout: int = 300) -> Tuple[bool, str]:
    """Install a local wheel via pip (argument list, no shell).

    Returns ``(success, output_tail)``. Never raises on pip failure.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", str(wheel_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return False, f"pip not available: {exc}"
    except subprocess.TimeoutExpired:
        return False, "pip install timed out."
    except OSError as exc:
        return False, f"could not launch pip: {exc}"
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    tail = "\n".join(output.splitlines()[-8:])
    return completed.returncode == 0, tail


def installed_dist_version() -> Optional[str]:
    """Re-read the installed distribution version (post-install check)."""
    try:
        import importlib
        from importlib import metadata as importlib_metadata
        importlib.invalidate_caches()
        return importlib_metadata.version(DISTRIBUTION_NAME)
    except Exception:
        return None


def print_manual_update_route() -> None:
    """Display the safe manual-update route (no changes made)."""
    print("Manual update route (safe, no changes made):")
    for step in MANUAL_UPDATE_STEPS:
        print(f"  - {step}")
    print(f"Release page (when published): {GITHUB_REPO_URL}/releases")


def run_update_interactive() -> int:
    """Menu option 4: full check → confirm → install → verify flow.

    Always returns to the menu (return code 0). Every failure path ends
    with the manual route and never claims success.
    """
    installed = codedumper.__version__
    print(f"Installed CodeDumper version: {installed}")
    print("Checking the official release source...")
    print(f"  Source: {RELEASES_LATEST_URL}")

    check = check_for_updates()

    if check.state == "unavailable":
        print(f"Update check unavailable: {check.note}")
        print()
        print_manual_update_route()
        return 0

    print(f"Latest stable version: {check.latest_version}")

    if check.state == "up_to_date":
        print("You are up to date.")
        if check.note:
            print(check.note)
        return 0

    # state == "available"
    release = check.release
    assert release is not None  # guaranteed for "available"
    method = detect_install_method()
    print(f"Detected installation method: {method}")

    asset = select_install_asset(release)
    if asset is None:
        print(
            f"CodeDumper {release.version} is available, but no verified "
            "installable wheel asset is published for this release."
        )
        print()
        print_manual_update_route()
        return 0

    if method != "pypi":
        # Preserve editable/source installations: never pip-overwrite them.
        print(
            f"CodeDumper {release.version} is available, but this copy was "
            f"not installed from PyPI ({method}), so automatic installation "
            "is skipped to preserve your installation method."
        )
        print()
        print_manual_update_route()
        return 0

    print(f"Ready to install CodeDumper {release.version} "
          f"({asset['name']}).")
    try:
        answer = input("Install this update now? [y/N]: ").strip().lower()
    except EOFError:
        print()
        print("Update canceled; no changes made.")
        return 0
    except KeyboardInterrupt:
        print("\nUpdate canceled; no changes made.", file=sys.stderr)
        return 0
    if answer not in ("y", "yes"):
        print("Update declined; no changes made.")
        return 0

    tmp_dir = Path(tempfile.mkdtemp(prefix="codedumper_update_"))
    try:
        try:
            print(f"Downloading {asset['name']}...")
            wheel = download_asset(asset["url"], tmp_dir)
        except UpdateError as exc:
            print(f"Download failed: {exc}")
            print()
            print_manual_update_route()
            return 0
        except KeyboardInterrupt:
            print("\nUpdate interrupted during download; no changes made.",
                  file=sys.stderr)
            return 0

        print("Installing (this may take a moment)...")
        try:
            ok, tail = install_wheel_file(wheel)
        except KeyboardInterrupt:
            print("\nUpdate interrupted during install. Your existing "
                  "installation may be unchanged; verify with "
                  "`codedumper --version`.", file=sys.stderr)
            return 0
        if tail:
            print(tail)
        final_version = installed_dist_version()
        if ok and final_version == release.version:
            print(f"SUCCESS: CodeDumper {final_version} is now installed.")
        else:
            print("Update FAILED: the installation did not complete. "
                  f"Installed version: {final_version or 'unknown'} "
                  f"(expected {release.version}).")
            print()
            print_manual_update_route()
            print("If files are locked (e.g. CodeDumper is running), close "
                  "it and retry, or follow the manual route above.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return 0
