"""
Patched GUI event handlers for SwiftSale.

Changes in this version:
- Dev code validation prefers cloud DB, then your Flask endpoint
  (/api/validate-dev-code), then offline fallback codes.
- Removed ANY Stripe API usage; upgrade opens static payment links by tier.
- No polling against Stripe; you can sync tier from your cloud DB after payment.
- Sell rate calculation delegates to bidder_manager.get_avg_sell_rate().
- More defensive error handling and UI updates.
"""

from datetime import datetime, timedelta
import hashlib
import threading
import time
import sqlite3
import requests
import re
import os
import webbrowser


from PySide6.QtCore import Qt, QTimer, QEasingCurve, QRect, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMessageBox, QApplication, QInputDialog,
    QCheckBox, QWidget, QFrame, QHBoxLayout, QLabel,
    QGraphicsOpacityEffect, QFileDialog
)

try:
    import ctypes
    _get_clip_seq = ctypes.windll.user32.GetClipboardSequenceNumber  # type: ignore[attr-defined]
except Exception:
    _get_clip_seq = None

from config_qt import save_install_info

from gui_help_qt import (
    show_telegram_help,
    show_import_csv_help,
    show_export_csv_help,
    show_sort_bin_desc_help,
    show_clear_bidders_help,
    show_top_buyer_help,
    show_flash_sale_text_help,
    
)

from utils_qt import safe_default_csv_path, sanitize_filename
# ---------------------------------------------------------------------------
# Payment links (Stripe-free)
# ---------------------------------------------------------------------------

def _payment_links_from_env() -> dict:
    """
    Pull per-tier payment/checkout links from environment.
    Define (for example) in .env or Render env:
      PAYMENT_LINK_BRONZE=https://buy.stripe.com/... or any external link
      PAYMENT_LINK_SILVER=...
      PAYMENT_LINK_GOLD=...
    If a link is missing, we fall back to a generic pricing page if provided:
      PRICING_URL=https://your-site/pricing
    """
    return {
        "Bronze": os.getenv("PAYMENT_LINK_BRONZE"),
        "Silver": os.getenv("PAYMENT_LINK_SILVER"),
        "Gold":   os.getenv("PAYMENT_LINK_GOLD"),
        "_fallback": os.getenv("PRICING_URL"),
    }

# ---------------------------------------------------------------------------
# Giveaway / Flash Sale helpers
# ---------------------------------------------------------------------------

def start_giveaway(self):
    """Copy the giveaway message from settings to clipboard."""
    if hasattr(self, "giveaway_entry"):
        message = (self.giveaway_entry.text() or "").strip()
        if message:
            QApplication.clipboard().setText(message)
            self.log_info(f"Copied giveaway message: {message}")
            self.show_temporary_message("Copied to Clipboard")
        else:
            self.log_error("No giveaway message set.")
    else:
        self.log_error("Giveaway input field not found.")

def start_flash_sale(self):
    """Copy the flash sale message from settings to clipboard."""
    if hasattr(self, "flash_sale_entry"):
        message = (self.flash_sale_entry.text() or "").strip()
        if message:
            QApplication.clipboard().setText(message)
            self.log_info(f"Copied flash sale message: {message}")
            self.show_temporary_message("Copied to Clipboard")
        else:
            self.log_error("No flash sale message set.")
    else:
        self.log_error("Flash sale input field not found.")

# ---------------------------------------------------------------------------
# Sell rate
# ---------------------------------------------------------------------------

def show_avg_sell_rate(self, show_message=True):
    """Display average sell rate in the UI and optionally show a message box."""
    if not self.bidder_manager.show_start_time:
        if show_message:
            QMessageBox.warning(self, "Warning", "Please click 'Start Show' first.")
        if hasattr(self, "stats_label"):
            self.stats_label.setText("Average Sell Rate: N/A")
        self.log_info("Sell rate not available: Show not started")
        return

    try:
        items_per_hour, items_per_minute, projected_2h, projected_3h, projected_4h = \
            self.bidder_manager.get_avg_sell_rate()
    except Exception as e:
        self.log_error(f"Sell rate calculation error: {e}")
        items_per_hour = items_per_minute = projected_2h = projected_3h = projected_4h = 0

    if items_per_minute and items_per_minute > 0:
        detailed_text = (
            f"Current sell rate is {items_per_minute:.2f}/min • "
            f"~{int(round(items_per_hour))}/hour • "
            f"{projected_3h}/3hr • {projected_4h}/4hr"
        )
        concise_text = f"Sell Rate: {items_per_minute:.2f}/min, {int(round(items_per_hour))}/hr"
        if show_message:
            QMessageBox.information(self, "Sell Rate", detailed_text)
    else:
        concise_text = "Average Sell Rate: N/A"
        if show_message:
            QMessageBox.information(self, "Sell Rate", "No valid transactions yet.")

    if hasattr(self, "stats_label"):
        self.stats_label.setText(concise_text)
    self.log_info(f"Updated sell rate: {concise_text}")

# ---------------------------------------------------------------------------
# Top buyers
# ---------------------------------------------------------------------------

def copy_top_buyer_message(self, event):
    """Copy the top buyer message to the clipboard."""
    self.log_info("Entering copy_top_buyer_message")
    try:
        top_buyers = self.bidder_manager.get_top_buyers()
        self.log_info(f"Retrieved top_buyers: {top_buyers}")
        if not top_buyers:
            QMessageBox.warning(self, "Warning", "No top buyers found")
            return
        if not isinstance(top_buyers, (list, tuple)):
            self.log_error(f"Invalid top_buyers format: {type(top_buyers)} data: {top_buyers}")
            QMessageBox.warning(self, "Warning", "No top buyers found")
            return
        for buyer in top_buyers:
            if not isinstance(buyer, (list, tuple)) or len(buyer) != 2:
                self.log_error(f"Invalid buyer tuple: {buyer}")
                QMessageBox.warning(self, "Warning", "No top buyers found")
                return
        username, qty = top_buyers[0]
        message = (
            self.top_buyer_text.format(username=username, qty=qty)
            if getattr(self, "top_buyer_text", None)
            else f"{username} ({qty})"
        )
        QApplication.clipboard().setText(message)
        self.log_info(f"Copied top buyer message: {message}")
        QMessageBox.information(self, "Success", "Top buyer message copied to clipboard")
    except sqlite3.Error as e:
        self.log_error(f"Database error in copy_top_buyer_message: {e}")
        QMessageBox.warning(self, "Warning", "No top buyers found")
    except Exception as e:
        self.log_error(f"Unexpected error in copy_top_buyer_message: {e}")
        QMessageBox.warning(self, "Warning", "No top buyers found")

def on_username_changed(self):
    """Update add bidder button style based on username changes."""
    current_username = (self.username_entry.text() or "").strip()
    if getattr(self, "last_added_username", "") and current_username == self.last_added_username:
        self.add_bidder_button.setStyleSheet("background-color: yellow; font-weight: bold;")
    else:
        self.add_bidder_button.setStyleSheet("background-color: green; font-weight: bold;")
    self._last_seen_username = current_username

# ---------------------------------------------------------------------------
# Developer code dialog (Stripe-free)
# ---------------------------------------------------------------------------

_OFFLINE_DEV_CODES = {
    "devoffline": {"tier": "Gold", "license_key": "DEV_MODE"},
    "jclark": {"tier": "Gold", "license_key": "DEV_MODE"},
    "brandi9933": {"tier": "Gold", "license_key": "DEV_MODE"},
    "9933": {"tier": "Gold", "license_key": "DEV_MODE"},  # TEMPORARY override
}

def _try_validate_via_cloud(self, code: str):
    """Validate using CloudDatabaseManager if available. Should return dict or raise."""
    if getattr(self, "cloud_db", None):
        self.log_info("Validating dev code via cloud_db...")
        return self.cloud_db.validate_dev_code(code)  # expected to raise on failure
    return None

def _try_validate_via_flask(self, code: str):
    """Validate using local Flask endpoint /api/validate-dev-code (works in .exe)."""
    base = (getattr(self, "base_url", "") or "").rstrip("/")
    if not base:
        return None

    # IMPORTANT: pass the install_id (bind the code to this install)
    install_id = getattr(self, "install_id", "") or ""
    if not install_id:
        raise Exception("Missing install_id")

    url = f"{base}/api/validate-dev-code"
    try:
        r = requests.get(url, params={"code": code, "install_id": install_id}, timeout=8)
        # Try to extract a clean error from JSON even on 4xx
        try:
            payload = r.json()
        except Exception:
            payload = {}

        if not r.ok:
            msg = (payload.get("message") or payload.get("error") or f"HTTP {r.status_code}")
            raise Exception(msg)

        # Accept both envelope {"status":"success","data":{...}} and flat {"status":"success",...}
        status = payload.get("status")
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        valid = bool(body.get("valid"))
        tier = body.get("tier") or "Gold"
        email = body.get("email")

        if status == "success" and valid:
            return {"tier": tier, "license_key": "DEV_MODE", "email": email}

        raise Exception(body.get("message") or "Invalid or expired developer code.")
    except Exception as e:
        self.log_error(f"Flask dev-code validation failed: {e}")
        raise

def open_dev_code_dialog(self):
    """
    Prompt for a developer/promo code and activate without Stripe.
    Priority: cloud_db → local Flask → offline codes.
    """
    code, ok = QInputDialog.getText(self, "Enter Promo/Dev Code", "Code:")
    if not ok or not (code or "").strip():
        return
    code = code.strip()

    result = None
    # 1) Cloud
    try:
        res = _try_validate_via_cloud(self, code)
        if res:
            result = res
    except Exception as e:
        self.log_error(f"Cloud validation error: {e}")

    # 2) Local Flask
    if not result:
        try:
            res = _try_validate_via_flask(self, code)
            if res:
                result = res
        except Exception as e:
            self.log_error(f"Local validation error: {e}")

    # 3) Offline fallback
    if not result:
        offline = _OFFLINE_DEV_CODES.get(code.lower())
        if offline:
            result = {
                "tier": offline["tier"],
                "license_key": offline["license_key"],
                "email": getattr(self, "user_email", None)
            }

    if not result:
        QMessageBox.warning(self, "Invalid Code", "That code is invalid or expired.")
        return

    # Apply activation
    try:
        new_tier = result.get("tier", "Gold")
        self.tier = new_tier
        self.license_key = result.get("license_key", "DEV_MODE")

        # Persist locally
        save_install_info(self.user_email, self.install_id, self.tier)

        # Update local DB install record if available
        try:
            hashed_email = hashlib.sha256((self.user_email or "").encode()).hexdigest()
            if hasattr(self, "bidder_manager") and hasattr(self.bidder_manager, "update_install"):
                self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
        except Exception as e:
            self.log_error(f"Failed to update local install tier: {e}")

        # Reflect in UI
        if hasattr(self, "update_subscription_ui"):
            self.update_subscription_ui()
        if hasattr(self, "update_header_and_footer"):
            self.update_header_and_footer()

        try:
            self.show_temporary_message(f"✔ License Verified – {self.tier} Tier")
        except Exception:
            pass

        QMessageBox.information(self, "Success", f"Activation successful.\nTier: {self.tier}")
    except Exception as e:
        self.log_error(f"Activation apply failed: {e}")
        QMessageBox.critical(self, "Error", f"Activation failed:\n{e}")

# ---------------------------------------------------------------------------
# Success Toast (1s fade-out)
# ---------------------------------------------------------------------------

class _SuccessToast(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._frame = QFrame(self)
        self._frame.setObjectName("toastFrame")
        self._frame.setStyleSheet("""
            QFrame#toastFrame {
                background: #10B981;
                color: white;
                border-radius: 10px;
                padding: 10px 14px;
                border: 1px solid rgba(0,0,0,0.15);
            }
            QLabel { color: white; }
        """)
        layout = QHBoxLayout(self._frame)
        layout.setContentsMargins(12, 8, 12, 8)

        self._label = QLabel("Success")
        f = self._label.font()
        f.setBold(True)
        self._label.setFont(f)
        layout.addWidget(self._label)

        self._eff = QGraphicsOpacityEffect(self._frame)
        self._frame.setGraphicsEffect(self._eff)

        self._anim = QPropertyAnimation(self._eff, b"opacity", self)
        self._anim.setDuration(320)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self.hide)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_and_close)

        self.resize(self._frame.sizeHint())

    def show_success(self, text: str, duration_ms: int = 1000):
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.stop()
        self._eff.setOpacity(1.0)
        self._label.setText(text)

        self._frame.adjustSize()
        self.resize(self._frame.sizeHint())

        parent = self.parentWidget()
        if parent:
            pw, ph = parent.width(), parent.height()
            w, h = self.width(), self.height()
            x = int((pw - w) / 2)
            y = int(ph - h - 48)  # above status bar
            self.setGeometry(QRect(x, y, w, h))
        self._frame.move(0, 0)

        self.show()
        self.raise_()
        self._hide_timer.start(max(400, duration_ms))

    def _fade_and_close(self):
        self._anim.start()

# ---------------------------------------------------------------------------
# Clipboard Auto-capture (submit once per copy)
# ---------------------------------------------------------------------------

def install_clipboard_capture(self):
    self._success_toast = _SuccessToast(self)

    # once-per-copy tracking
    self._last_clip_text = ""
    self._last_clip_at = 0.0
    self._once_window_sec = 1.2

    # Windows clipboard sequence number
    import ctypes
    try:
        self._get_clip_seq = ctypes.windll.user32.GetClipboardSequenceNumber  # None on non-Windows
    except Exception:
        self._get_clip_seq = None
    self._clip_seq_last = self._get_clip_seq() if self._get_clip_seq else None

    # Qt clipboard
    from PySide6.QtGui import QGuiApplication, QClipboard
    self._clipboard = QGuiApplication.clipboard()

    # Polling fallback — becomes the primary path
    from PySide6.QtCore import QTimer
    self._clip_poll = QTimer(self)
    self._clip_poll.setInterval(200)  # 5x/sec
    self._clip_poll.timeout.connect(self._poll_clipboard)
    self._clip_poll.start()

    if not hasattr(self, "auto_submit_new_bidder"):
        self.auto_submit_new_bidder = True

    try:
        self.statusBar().showMessage("Clipboard capture: ON (polling)", 1500)
    except Exception:
        pass

def _poll_clipboard(self):
    from PySide6.QtGui import QClipboard
    seq_now = self._get_clip_seq() if getattr(self, "_get_clip_seq", None) else None
    if seq_now is not None and seq_now == self._clip_seq_last:
        return  # no new copy

    text = (self._clipboard.text(QClipboard.Clipboard) or "").strip()
    now = time.monotonic()

    # If no Windows seq, guard on same-text-within-window
    if seq_now is None and text == self._last_clip_text and (now - self._last_clip_at) < self._once_window_sec:
        return

    if self._maybe_submit_username(text, source="clipboard"):
        self._last_clip_text = text
        self._last_clip_at = now
        if seq_now is not None:
            self._clip_seq_last = seq_now

def _on_clipboard_change(self):
    """Signal path; also respects Windows sequence when available."""
    if hasattr(self, "auto_capture_checkbox") and not self.auto_capture_checkbox.isChecked():
        return

    text = (self._clipboard.text(QClipboard.Clipboard) or "").strip()
    now = time.monotonic()

    seq_now = _get_clip_seq() if _get_clip_seq else None
    if seq_now is not None and seq_now == self._clip_seq_last:
        return

    if self._maybe_submit_username(text, source="clipboard"):
        self._last_clip_text = text
        self._last_clip_at = now
        if seq_now is not None:
            self._clip_seq_last = seq_now

def _maybe_submit_username(self, raw: str, source: str) -> bool:
    username = _extract_username(raw)
    if not username:
        return False
    try:
        inp = getattr(self, "username_entry", None) or getattr(self, "bidder_input", None)
        if not inp:
            self.statusBar().showMessage("Username input not found", 1500)
            return False

        inp.setText(username)

        bin_no = None
        if self.auto_submit_new_bidder:
            try:
                bin_no = self.add_bidder()  # your GUI add_bidder returns bin
            except TypeError:
                self.add_bidder()
                bin_no = getattr(self, "_last_assigned_bin", None)
        else:
            bin_no = _resolve_bin_for_username(self, username)

        if bin_no is not None:
            self._success_toast.show_success(f"✅ Added @{username} • BIN {bin_no}", 1000)
        else:
            self._success_toast.show_success(f"✅ Added @{username}", 1000)

        self.statusBar().showMessage(f"Added @{username} ({source})", 1100)
        return True
    except Exception as e:
        self.statusBar().showMessage(f"Add failed: {e}", 3000)
        return False

def _extract_username(text: str) -> str | None:
    text = (text or "").strip().strip(",.;:!?)(")
    m = re.search(r'@?([A-Za-z0-9](?:[A-Za-z0-9._-]{0,28}[A-Za-z0-9])?)', text)
    if not m:
        return None
    u = m.group(1)
    return u if len(u) >= 2 else None

def _resolve_bin_for_username(self, username: str):
    bm = getattr(self, "bidder_manager", None)
    for meth in ("get_bin_for_username", "get_bin_for_handle", "get_bin", "bin_for"):
        if bm and hasattr(bm, meth) and callable(getattr(bm, meth)):
            try:
                return getattr(bm, meth)(username)
            except Exception:
                pass
    return getattr(self, "_last_assigned_bin", None)

def export_bidders_csv(self, _checked=False):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    import os

    suggested = safe_default_csv_path("bidders_export")
    file_name, _ = QFileDialog.getSaveFileName(
        self, "Export CSV", suggested, "CSV Files (*.csv)"
    )
    if not file_name:
        return

    # sanitize and normalize the chosen path
    dirpath = os.path.dirname(file_name) or os.getcwd()
    basename = sanitize_filename(os.path.basename(file_name), default_ext=".csv")
    normalized_path = os.path.join(dirpath, basename)

    try:
        self.bidder_manager.export_csv(normalized_path)
        self.log_info(f"Exported bidders to {normalized_path}")
        QMessageBox.information(self, "Success", "Bidders exported successfully")
    except Exception as e:
        self.log_error(f"Failed to export CSV: {e}")
        QMessageBox.critical(self, "Error", f"Failed to export CSV: {e}")



# ---------------------------------------------------------------------------
# Upgrade flow (Stripe-free)
# ---------------------------------------------------------------------------

def on_upgrade(self):
    """
    Handle Upgrade click:
    - Open a static payment link for the selected tier (from env).
    - Show instructions to return and click “Sync License” (your UI) after payment.
    """
    new_tier = self.tier_combo.currentText()
    if new_tier == self.tier:
        QMessageBox.information(self, "Info", f"You are already on the {new_tier} tier.")
        return

    if not self.user_email:
        QMessageBox.critical(self, "Error", "Missing email. Please set your email before upgrading.")
        return

    links = _payment_links_from_env()
    url = links.get(new_tier) or links.get("_fallback")

    if not url:
        QMessageBox.critical(
            self,
            "Upgrade",
            "No payment link configured. Set PAYMENT_LINK_BRONZE/SILVER/GOLD or PRICING_URL in your environment."
        )
        return

    try:
        webbrowser.open(url)
        self.log_info(f"Opened payment link for {new_tier}: {url}")
        QMessageBox.information(
            self,
            "Upgrade",
            "Your upgrade page has opened in the browser.\n\n"
            "After completing payment, click 'Sync License' (or restart) to refresh your tier."
        )
    except Exception as e:
        self.log_error(f"Failed to open payment link: {e}")
        QMessageBox.critical(self, "Error", f"Could not open payment link:\n{e}")

def _poll_subscription_status(self, expected_tier, max_retries=6, delay=4):
    """
    Deprecated when Stripe API is removed; kept as a soft helper:
    Try to detect a tier change by checking the local DB/cloud sync.
    """
    self.log_info(f"Polling for tier change to {expected_tier} (Stripe-free mode)")
    try:
        for _ in range(max_retries):
            time.sleep(delay)
            # Try cloud sync if available
            if getattr(self, "cloud_db", None) and getattr(self, "user_email", None):
                try:
                    self.cloud_db.sync_with_local(self.bidder_manager, self.user_email)
                except Exception as e:
                    self.log_error(f"Cloud sync during poll failed: {e}")

            # Read tier from local manager
            try:
                current = self.bidder_manager.get_tier_for_user(self.user_email) or self.tier
            except Exception:
                current = self.tier

            if current and current.lower() == expected_tier.lower():
                self.tier = current
                self.log_info(f"Upgrade confirmed by local/cloud: {self.tier}")
                save_install_info(self.user_email, self.install_id, self.tier)
                hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                try:
                    self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                except Exception as e:
                    self.log_error(f"Failed to write updated tier locally: {e}")
                if hasattr(self, "update_subscription_ui"):
                    self.update_subscription_ui()
                if hasattr(self, "update_header_and_footer"):
                    self.update_header_and_footer()
                break
        else:
            self.log_info("Tier change not detected during polling window.")
    except Exception as e:
        self.log_error(f"Tier poll error: {e}")

def update_subscription_ui(self):
    """Update the Subscription tab and header/footer labels with current info."""
    try:
        email_display = self.user_email or "Unknown Email"
        tier_display = self.tier or "Unknown"
        install_id = self.install_id or "N/A"

        status_text = (
            "Trial Mode – Upgrade Required"
            if self.tier and self.tier.lower() == "trial"
            else f"✔ Verified – {self.tier} Tier"
        )
        billing_text = "Billing Managed Externally"

        if hasattr(self, "header_label"):
            self.header_label.setText(f"SwiftSale - {email_display} ({tier_display})")

        if hasattr(self, "footer_label"):
            self.footer_label.setText(f"Tier: {tier_display} | Install ID: {install_id} | {status_text}")

        if hasattr(self, "subscription_status_label"):
            self.subscription_status_label.setText(f"Status: {status_text}")

        if hasattr(self, "next_billing_label"):
            self.next_billing_label.setText(f"Next Billing: {billing_text}")

        self.log_info(f"Updated subscription UI: {tier_display}, {status_text}")
    except Exception as e:
        self.log_error(f"Failed to update subscription UI: {e}")

# ---------------------------------------------------------------------------
# Binders
# ---------------------------------------------------------------------------

def bind_event_methods(gui):
    """Bind event-related methods to the GUI instance."""
    gui.start_giveaway = start_giveaway.__get__(gui, gui.__class__)
    gui.start_flash_sale = start_flash_sale.__get__(gui, gui.__class__)
    gui.show_avg_sell_rate = show_avg_sell_rate.__get__(gui, gui.__class__)
    gui.copy_top_buyer_message = copy_top_buyer_message.__get__(gui, gui.__class__)
    gui.on_username_changed = on_username_changed.__get__(gui, gui.__class__)
    gui.open_dev_code_dialog = open_dev_code_dialog.__get__(gui, gui.__class__)
    gui.update_subscription_ui = update_subscription_ui.__get__(gui, gui.__class__)
    gui._poll_subscription_status = _poll_subscription_status.__get__(gui, gui.__class__)
    gui.on_upgrade = on_upgrade.__get__(gui, gui.__class__)
    gui.install_clipboard_capture = install_clipboard_capture.__get__(gui, gui.__class__)
    gui._on_clipboard_change = _on_clipboard_change.__get__(gui, gui.__class__)
    gui._poll_clipboard = _poll_clipboard.__get__(gui, gui.__class__)
    gui._maybe_submit_username = _maybe_submit_username.__get__(gui, gui.__class__)
    gui.export_bidders_csv = export_bidders_csv.__get__(gui, gui.__class__)
    # Hook up if present (safe if widgets/actions don’t exist)
    for attr in ("btn_export_csv", "button_export_csv", "export_csv_button"):
        try:
            getattr(gui, attr).clicked.connect(gui.export_bidders_csv)
        except Exception:
            pass
    for attr in ("actionExportCSV", "action_export_csv"):
        try:
            getattr(gui, attr).triggered.connect(gui.export_bidders_csv)
        except Exception:
            pass


def bind_help_methods(gui):
    """Bind help button click events to their respective help functions."""
    gui.telegram_help_button.clicked.connect(lambda: show_telegram_help(gui))
    gui.export_csv_help_button.clicked.connect(lambda: show_export_csv_help(gui))
    gui.sort_bin_desc_help_button.clicked.connect(lambda: show_sort_bin_desc_help(gui))
    gui.clear_bidders_help_button.clicked.connect(lambda: show_clear_bidders_help(gui))
    gui.top_buyer_help_button.clicked.connect(lambda: show_top_buyer_help(gui))
    gui.flash_sale_text_help_button.clicked.connect(lambda: show_flash_sale_text_help(gui))
