"""
Patched GUI event handlers for SwiftSale.

Changes in this version:
- Dev code validation prefers cloud DB, then your Flask endpoint
  (/api/validate-dev-code), then offline fallback codes.
- Removed direct Postgres credential usage from the client.
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

from PySide6.QtCore import Qt, QTimer, QEasingCurve, QRect, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut   # ← QShortcut here
from PySide6.QtWidgets import (
    QMessageBox, QApplication, QInputDialog, QProgressDialog,
    QCheckBox, QWidget, QFrame, QHBoxLayout, QLabel,               # ← no QShortcut here
    QGraphicsOpacityEffect,                                        # ← lives in QtWidgets
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
# Developer code dialog
# ---------------------------------------------------------------------------

_OFFLINE_DEV_CODES = {
    "devoffline": {"tier": "Gold", "license_key": "DEV_MODE"},
    "jclark": {"tier": "Gold", "license_key": "DEV_MODE"},
    "brandi9933": {"tier": "Gold", "license_key": "DEV_MODE"},
    "9933": {"tier": "Gold", "license_key": "DEV_MODE"},  # TEMPORARY override
}

def _try_validate_via_cloud(self, code: str):
    """Validate using CloudDatabaseManager if available."""
    if getattr(self, "cloud_db", None):
        self.log_info("Validating dev code via cloud_db...")
        return self.cloud_db.validate_dev_code(code)  # should raise on failure
    return None

def _try_validate_via_flask(self, code: str):
    """Validate using local Flask endpoint /api/validate-dev-code."""
    base = (getattr(self, "base_url", "") or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/api/validate-dev-code"
    try:
        r = requests.get(url, params={"code": code}, timeout=6)
        if not r.ok:
            # Bubble up JSON error if present
            try:
                err = r.json().get("error")
                if err:
                    raise Exception(err)
            except Exception:
                pass
            r.raise_for_status()
        data = r.json() or {}
        if data.get("status") == "success" and data.get("valid"):
            # Normalize a consistent shape
            return {
                "tier": "Gold",            # server doesn’t send tier; treat dev as Gold by policy
                "license_key": "DEV_MODE", # dev unlock is not a billable license
                "email": data.get("email")
            }
        # Older server variant returns {"valid": True, "email": "..."}
        if data.get("valid"):
            return {
                "tier": "Gold",
                "license_key": "DEV_MODE",
                "email": data.get("email")
            }
        raise Exception(data.get("error") or "Invalid or expired developer code.")
    except Exception as e:
        self.log_error(f"Flask dev-code validation failed: {e}")
        raise

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
                background: #10B981;            /* emerald-500 */
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
        # reset animation/opacity
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

# --- inside gui_events.py ---

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

    # 🔒 Disable the signal path to remove the race with polling
    # self._clipboard.dataChanged.connect(self._on_clipboard_change)

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



def open_dev_code_dialog(self):
    """Prompt user to enter the developer unlock code."""
    code, ok = QInputDialog.getText(self, "Enter Dev Code", "Enter Promo Code:")
    if not (ok and (code or "").strip()):
        return

    code = code.strip()          # preserve case if your codes are case-sensitive
    install_id = self.install_id or "unknown-device"

    # 1) Offline quick path
    if code in _OFFLINE_DEV_CODES:
        result = _OFFLINE_DEV_CODES[code]
        self.dev_access_granted = True
        self.tier = result["tier"]
        self.license_key = result["license_key"]
        save_install_info(self.user_email, self.install_id, self.tier)
        hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
        self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
        if getattr(self, "cloud_db", None):
            try:
                self.cloud_db.update_install_tier(hashed_email, self.tier, install_id=self.install_id)
            except Exception as e:
                self.log_error(f"Cloud sync (offline dev) failed: {e}")
        self.log_info(f"Offline dev code used – {code} | install_id={install_id}")
        QMessageBox.information(self, "Access Granted", f"Developer access enabled – {self.tier} Tier.")
        self.update_subscription_ui()
        self.update_header_and_footer()
        self.refresh_bin_usage_display()
        return

    # 2) Cloud / 3) Flask endpoint
    try:
        result = None
        # prefer cloud DB
        try:
            result = _try_validate_via_cloud(self, code)
        except Exception as e:
            self.log_error(f"Cloud dev-code validation failed: {e}")

        # fallback to Flask endpoint
        if not result:
            result = _try_validate_via_flask(self, code)

        # Adopt results
        self.dev_access_granted = True
        self.tier = result.get("tier", "Gold")
        self.license_key = result.get("license_key", "DEV_MODE")
        new_email = result.get("email")
        if new_email:
            self.user_email = new_email

        # 15-day promo window
        promo_expiration = datetime.utcnow() + timedelta(days=15)
        save_install_info(self.user_email, self.install_id, self.tier, promo_expiration=promo_expiration)

        hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
        self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)

        if getattr(self, "cloud_db", None):
            try:
                self.cloud_db.update_install_tier(
                    hashed_email,
                    self.tier,
                    install_id=self.install_id,
                    promo_expiration=promo_expiration,
                )
            except Exception as e:
                self.log_error(f"Cloud sync (dev) failed: {e}")

        self.log_info(
            f"Dev code validated – {code} | {self.user_email} | install_id={install_id} | "
            f"expires {promo_expiration}"
        )
        QMessageBox.information(
            self,
            "Access Granted",
            f"Developer access enabled – {self.tier} Tier.\n\n"
            f"This promo will expire on {promo_expiration.strftime('%Y-%m-%d')}",
        )
        self.update_subscription_ui()
        self.update_header_and_footer()
        self.refresh_bin_usage_display()
    except Exception as e:
        self.log_error(f"Dev unlock failed: {e}")
        QMessageBox.warning(self, "Access Denied", str(e))


# ---------------------------------------------------------------------------
# Upgrade flow (unchanged logic; small cleanup)
# ---------------------------------------------------------------------------

def on_upgrade(self):
    """Handle clicking the Upgrade button in the Subscription tab with real-time refresh."""
    new_tier = self.tier_combo.currentText()
    if new_tier == self.tier:
        QMessageBox.information(self, "Info", f"You are already on the {new_tier} tier.")
        return

    if not self.user_email:
        QMessageBox.critical(self, "Error", "Missing email. Please set your email before upgrading.")
        return

    try:
        self.log_info(f"Creating Stripe checkout session for {self.user_email} upgrading to {new_tier}")
        response, status = self.stripe_service.create_checkout_session(
            tier=new_tier,
            user_email=self.user_email,
            request_url_root="https://swiftsale4.onrender.com/",
        )

        if status == 200 and response.get("url"):
            import webbrowser
            webbrowser.open(response["url"])
            self.log_info(f"Opened Stripe Checkout URL: {response['url']}")

            QMessageBox.information(
                self, "Upgrade",
                "Stripe Checkout has opened in your browser.\n\nWe'll check your upgrade status shortly.",
            )

            self.polling_dialog = QProgressDialog("Verifying upgrade...", None, 0, 0, self)
            self.polling_dialog.setWindowTitle("Please Wait")
            self.polling_dialog.setCancelButton(None)
            self.polling_dialog.setWindowModality(Qt.ApplicationModal)
            self.polling_dialog.setMinimumDuration(0)
            self.polling_dialog.setAutoClose(False)
            self.polling_dialog.show()

            threading.Thread(target=self._poll_subscription_status, args=(new_tier,), daemon=True).start()
        else:
            error_msg = response.get("error", "Upgrade failed: No checkout URL returned.")
            self.log_error(f"Stripe checkout creation failed: {error_msg}")
            QMessageBox.critical(self, "Error", error_msg)

    except Exception as e:
        self.log_error(f"Upgrade error: {e}")
        QMessageBox.critical(self, "Error", f"Failed to upgrade subscription: {e}")


def _poll_subscription_status(self, expected_tier, max_retries=6, delay=4):
    """Poll Stripe for subscription status every few seconds until upgraded or timeout."""
    self.log_info(f"🔁 Polling subscription status for upgrade to {expected_tier}")
    try:
        for _ in range(max_retries):
            time.sleep(delay)
            status, _ = self.stripe_service.get_subscription_status(self.license_key)
            if status and status.lower() == expected_tier.lower():
                self.tier = expected_tier
                self.log_info(f"✅ Upgrade confirmed: {self.tier}")
                save_install_info(self.user_email, self.install_id, self.tier)
                hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                if getattr(self, "cloud_db", None):
                    try:
                        self.cloud_db.update_install_tier(hashed_email, self.tier)
                    except Exception as e:
                        self.log_error(f"Failed to sync updated tier to cloud DB: {e}")
                self.update_subscription_ui()
                self.update_header_and_footer()
                break
        else:
            self.log_info("🔁 Upgrade confirmation timed out")
    finally:
        if hasattr(self, "polling_dialog"):
            self.polling_dialog.cancel()


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
    gui._poll_clipboard           = _poll_clipboard.__get__(gui, gui.__class__)
    gui._maybe_submit_username = _maybe_submit_username.__get__(gui, gui.__class__)

def bind_help_methods(gui):
    """Bind help button click events to their respective help functions."""
    gui.telegram_help_button.clicked.connect(lambda: show_telegram_help(gui))
    gui.export_csv_help_button.clicked.connect(lambda: show_export_csv_help(gui))
    gui.sort_bin_desc_help_button.clicked.connect(lambda: show_sort_bin_desc_help(gui))
    gui.clear_bidders_help_button.clicked.connect(lambda: show_clear_bidders_help(gui))
    gui.top_buyer_help_button.clicked.connect(lambda: show_top_buyer_help(gui))
    gui.flash_sale_text_help_button.clicked.connect(lambda: show_flash_sale_text_help(gui))
