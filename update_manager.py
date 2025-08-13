"""
SwiftSale Updater

Checks a JSON manifest, compares versions, downloads the installer with progress,
verifies SHA-256, then launches the installer and exits the app.

Works with gui_updater.py:
- load_manifest()
- is_update_available()
- run_update_flow(current_version, manifest_url=?, progress_cb=?)

Manifest shape (served at /updates/latest.json):
{
  "version": "4.0.2",
  "url": "https://.../SwiftSaleInstaller_402.exe",
  "sha256": "<64-hex>",
  "notes": "optional text",
  "min_os": "Windows-10",
  "force": false
}
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Optional, Callable, Any, Dict

from packaging.version import Version

# Prefer pulling the default URL from config, but allow explicit overrides
try:
    from config_qt import get_update_manifest_url
    DEFAULT_MANIFEST_URL = get_update_manifest_url()
except Exception:
    DEFAULT_MANIFEST_URL = ""

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


TIMEOUT = 20  # seconds for manifest; downloads use their own timeout


# ---------------------------
# Data model
# ---------------------------
@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""
    min_os: str = ""
    force: bool = False


# ---------------------------
# Helpers
# ---------------------------
def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_windows() -> bool:
    return os.name == "nt"


def _installer_args(installer_path: str) -> list[str]:
    """
    Construct installer arguments.
    We try silent switches common to NSIS/Inno; if not supported, installer just ignores them.
    """
    args = [installer_path]
    for flag in ("/VERYSILENT", "/SILENT", "/NORESTART"):
        args.append(flag)
    return args


def _launch_and_exit(installer_path: str) -> None:
    """Launch installer in a detached way (especially on Windows) and terminate current process."""
    try:
        args = _installer_args(installer_path)
        if _is_windows():
            DETACHED = 0x00000008
            subprocess.Popen(args, creationflags=DETACHED)
        else:
            subprocess.Popen(args)
    except Exception:
        # Fallback to plain launch without flags
        try:
            subprocess.Popen([installer_path])
        except Exception:
            pass
    # Hard-exit so files can be replaced by installer
    os._exit(0)


# ---------------------------
# Network / manifest
# ---------------------------
def load_manifest(manifest_url: str = DEFAULT_MANIFEST_URL) -> Optional[UpdateInfo]:
    """
    Fetch and parse the update manifest. Returns UpdateInfo or None on failure.
    """
    if not manifest_url:
        return None
    if requests is None:
        return None

    try:
        r = requests.get(manifest_url, timeout=TIMEOUT)
        r.raise_for_status()
        data: Dict[str, Any] = r.json() or {}
        # Some servers wrap the payload; accept both formats
        if data.get("status") == "success" and "version" not in data:
            # un-wrap if they nested it
            for k in ("data", "payload"):
                if isinstance(data.get(k), dict) and "version" in data[k]:
                    data = data[k]
                    break

        version = str(data.get("version", "")).strip()
        url = str(data.get("url", "")).strip()
        sha256 = str(data.get("sha256", "")).strip()

        if not (version and url and sha256):
            return None

        return UpdateInfo(
            version=version,
            url=url,
            sha256=sha256,
            notes=str(data.get("notes") or ""),
            min_os=str(data.get("min_os") or ""),
            force=bool(data.get("force", False)),
        )
    except Exception:
        return None


def is_update_available(current_version: str, info: Optional[UpdateInfo]) -> bool:
    if not info:
        return False
    try:
        return Version(str(info.version)) > Version(str(current_version))
    except Exception:
        return False


def download_with_progress(
    url: str,
    dst_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    chunk_size: int = 1024 * 256,
) -> str:
    """
    Stream a file to dst_path and report progress (downloaded_bytes, total_bytes).
    Returns dst_path on success.
    """
    if requests is None:
        raise RuntimeError("The 'requests' package is not installed.")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dst_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(downloaded, total)
                    except Exception:
                        pass
    return dst_path


# ---------------------------
# Public entry point
# ---------------------------
def run_update_flow(
    current_version: str,
    manifest_url: str = DEFAULT_MANIFEST_URL,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> Optional[str]:
    """
    End-to-end: check → download → verify → launch installer → exit.
    Returns a small status string or None if no update / failure before download.
    Raises on verification/download errors.
    """

    info = load_manifest(manifest_url)
    if not info:
        return None

    if not is_update_available(current_version, info):
        return None

    # Prepare temp destination
    tmpdir = tempfile.mkdtemp(prefix="swiftsale_upd_")
    # Try to derive a sane filename from URL (strip query)
    import ntpath
    filename = ntpath.basename(info.url.split("?")[0]) or ("SwiftSaleInstaller.exe" if _is_windows() else "SwiftSaleInstaller")
    dst = os.path.join(tmpdir, filename)

    # Download with optional progress callback
    download_with_progress(info.url, dst, progress_cb=progress_cb)

    # Verify SHA-256
    digest = _sha256_file(dst)
    if digest.lower() != info.sha256.lower():
        raise RuntimeError("Installer hash mismatch. Aborting update.")

    # Launch installer and exit current app
    _launch_and_exit(dst)
    return "Launching installer…"
