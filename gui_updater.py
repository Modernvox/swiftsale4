# -*- coding: utf-8 -*-
import os
import sys
import hashlib
import tempfile
import platform
import subprocess
import threading
import requests
from dataclasses import dataclass
from typing import Optional, Callable

from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import Qt, QTimer
from packaging.version import Version

from config_qt import get_update_manifest_url

# Optional external updater (if you decide to keep a separate module)
try:
    from update_manager import load_manifest as ext_load_manifest, is_update_available as ext_is_update_available, run_update_flow as ext_run_update_flow
    _EXT_UPDATER = True
except Exception:
    _EXT_UPDATER = False


# -----------------------------------------------------------------------------
# Built-in updater (used when external module isn't available)
# -----------------------------------------------------------------------------
@dataclass
class ManifestInfo:
    version: str
    url: str
    sha256: str
    notes: str = ""
    force: bool = False
    min_os: str = ""  # e.g., "Windows-10"

class UpdateError(Exception):
    pass

def _human_bytes(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def _show_progress_dialog(parent):
    """Create a simple modal progress dialog and return (dialog, progress_bar, label)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Updating SwiftSale")
    layout = QVBoxLayout(dlg)
    lbl = QLabel("Downloading update…")
    bar = QProgressBar()
    bar.setRange(0, 100)
    layout.addWidget(lbl)
    layout.addWidget(bar)
    dlg.setModal(True)
    return dlg, bar, lbl

def _parse_manifest(data: dict) -> Optional[ManifestInfo]:
    try:
        version = str(data.get("version", "")).strip()
        url = str(data.get("url", "")).strip()
        sha = str(data.get("sha256", "")).strip().lower()
        notes = str(data.get("notes", "") or "")
        force = bool(data.get("force", False))
        min_os = str(data.get("min_os", "") or "")
        if not version or not url or not sha:
            return None
        # basic hex sanity check
        if any(c not in "0123456789abcdef" for c in sha):
            return None
        return ManifestInfo(version=version, url=url, sha256=sha, notes=notes, force=force, min_os=min_os)
    except Exception:
        return None

def load_manifest(url: str) -> Optional[ManifestInfo]:
    try:
        r = requests.get(url, timeout=10)
        if not r.ok:
            return None
        data = r.json()
        # Some servers may wrap; handle {"available": False} gracefully
        if isinstance(data, dict) and data.get("available") is False:
            return None
        return _parse_manifest(data)
    except Exception:
        return None

def _platform_ok(min_os: str) -> bool:
    if not min_os:
        return True
    # Only a light check for Windows for now (server manifests say "Windows-10")
    if platform.system() != "Windows":
        return False if min_os.lower().startswith("windows") else True
    if "windows-10" in min_os.lower():
        # Windows 10+ release names include "10" or "11"/"12"; accept all >= 10
        try:
            rel = platform.release()
            # Fall back: treat unknown as OK (don't block updates unnecessarily)
            return rel.isdigit() and int(rel) >= 10 or rel in ("10", "11")
        except Exception:
            return True
    return True

def is_update_available(current_version: str, m: ManifestInfo) -> bool:
    try:
        return Version(str(m.version)) > Version(str(current_version))
    except Exception:
        # If parsing fails, be conservative and allow update prompt
        return True

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _download_with_progress(url: str, dest: str, progress_cb: Optional[Callable[[int, int], None]] = None) -> None:
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0") or 0)
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb and total:
                    try:
                        progress_cb(downloaded, total)
                    except Exception:
                        pass

def _launch_installer(installer_path: str) -> None:
    # On Windows, launching the .exe is enough; allow elevation dialog to prompt if needed
    if platform.system() == "Windows":
        try:
            os.startfile(installer_path)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    # Cross-platform fallback
    subprocess.Popen([installer_path], shell=(platform.system() == "Windows"))

def run_update_flow(
    current_version: str,
    manifest_url: Optional[str] = None,
    manifest: Optional[ManifestInfo] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None
):
    """
    Download, verify, and launch installer. Raises UpdateError on any failure.
    """
    if manifest is None:
        if not manifest_url:
            raise UpdateError("No manifest URL provided")
        manifest = load_manifest(manifest_url)
        if not manifest:
            raise UpdateError("Could not load update manifest")

    # Check platform constraint
    if not _platform_ok(manifest.min_os):
        raise UpdateError(f"This update requires {manifest.min_os} or later.")

    # Compare versions
    if not is_update_available(current_version, manifest):
        raise UpdateError("You already have the latest version.")

    # Prepare temp path
    tmp_dir = tempfile.mkdtemp(prefix="swiftsale_update_")
    installer_name = os.path.basename(manifest.url) or f"SwiftSale_{manifest.version}.exe"
    dest_path = os.path.join(tmp_dir, installer_name)

    # Download
    try:
        _download_with_progress(manifest.url, dest_path, progress_cb)
    except Exception as e:
        raise UpdateError(f"Download failed: {e}")

    # Verify
    try:
        digest = _sha256_file(dest_path)
        if digest.lower() != manifest.sha256.lower():
            raise UpdateError("Downloaded file failed integrity check (SHA-256 mismatch).")
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Failed to verify installer: {e}")

    # Launch installer
    try:
        _launch_installer(dest_path)
    except Exception as e:
        raise UpdateError(f"Failed to launch installer: {e}")


# -----------------------------------------------------------------------------
# GUI glue
# -----------------------------------------------------------------------------
def check_for_updates(self):
    """Check for software updates using the manifest and optionally run the installer."""
    try:
        manifest_url = get_update_manifest_url()

        # Load manifest (prefer external manager if available)
        if _EXT_UPDATER:
            info = ext_load_manifest(manifest_url)
            # ext_load_manifest could return a dict or an object; normalize
            if info and isinstance(info, dict):
                info = _parse_manifest(info)
        else:
            info = load_manifest(manifest_url)

        if not info:
            QMessageBox.warning(self, "Update Check", "Could not load update manifest.")
            self.log_error("Manifest load failed or incomplete.")
            return

        current = Version(str(self.current_version))
        latest = Version(str(info.version))

        # Up-to-date?
        if latest <= current:
            QMessageBox.information(self, "No Update", "You are running the latest version.")
            self.log_info(f"No update available (current {current}, latest {latest})")
            return

        # Platform constraint
        if not _platform_ok(info.min_os):
            QMessageBox.warning(self, "Not Supported", f"This update requires {info.min_os} or later.")
            self.log_info(f"Update blocked by platform; requires {info.min_os}")
            return

        # Build prompt text
        notes = f"\n\nWhat's new:\n{info.notes}" if getattr(info, "notes", None) else ""
        if getattr(info, "force", False):
            # Forced update; no skip option
            QMessageBox.information(
                self,
                "Update Required",
                f"A required update ({info.version}) is available.{notes}\n\nClick OK to update now."
            )
            user_accepts = True
        else:
            resp = QMessageBox.question(
                self,
                "Update Available",
                f"A new version ({info.version}) is available.{notes}\n\nUpdate now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            user_accepts = (resp == QMessageBox.Yes)

        if not user_accepts:
            self.log_info("User skipped update.")
            return

        # Progress dialog
        dlg, bar, lbl = _show_progress_dialog(self)

        def progress_cb(downloaded, total):
            if total > 0:
                pct = int((downloaded / total) * 100)
                bar.setValue(pct)
                lbl.setText(f"Downloading update…  {pct}%  ({_human_bytes(downloaded)} of {_human_bytes(total)})")

        # Ensure we have a UI-thread marshaller
        if not hasattr(self, "invoke_on_ui"):
            self.invoke_on_ui = lambda fn: QTimer.singleShot(0, fn)

        def _run():
            try:
                if _EXT_UPDATER:
                    ext_run_update_flow(str(self.current_version), manifest_url=manifest_url, progress_cb=progress_cb)
                else:
                    run_update_flow(str(self.current_version), manifest_url=manifest_url, progress_cb=progress_cb)

                # Notify success and quit app so installer can proceed
                def _ok():
                    try:
                        QMessageBox.information(self, "Installer Launched", "The installer has started. SwiftSale will now exit.")
                    except Exception:
                        pass
                    # Graceful quit
                    QTimer.singleShot(300, lambda: sys.exit(0))
                self.invoke_on_ui(_ok)

            except Exception as e:
                def _err():
                    try:
                        QMessageBox.critical(self, "Update failed", str(e))
                    except Exception:
                        pass
                    dlg.reject()
                self.invoke_on_ui(_err)

        threading.Thread(target=_run, daemon=True).start()
        dlg.exec()

    except Exception as e:
        self.log_error(f"Failed to check for update: {e}")
        QMessageBox.critical(self, "Error", f"Failed to check for update: {e}")


def bind_updater_methods(gui):
    """Bind update-check (and run) to the GUI instance."""
    gui.check_for_updates = check_for_updates.__get__(gui, gui.__class__)
