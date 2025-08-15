import os
import hashlib
import logging
import requests
import subprocess
import sys

from datetime import timedelta, datetime
from gui_chatbot import AssistantDialog

import socketio
from PySide6.QtWidgets import (
    QMainWindow, QFrame, QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QTextEdit, QTableWidget, QTreeWidgetItem, QScrollBar, QTabWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QFileDialog, QMessageBox, QInputDialog,
    QTextBrowser, QDialog, QApplication, QSizePolicy, QListWidget, QListWidgetItem, QToolButton, QStyle
)
from PySide6.QtGui import QPixmap, QFont, QCursor, QClipboard, QKeySequence, QShortcut, QDesktopServices, QIcon
from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QSettings, QSize   # ← added QSize

from version import __version__
from cloud_database_qt import CloudDatabaseManager
from config_qt import (
    get_resource_path, load_config, get_config_value, DEFAULT_DATA_DIR,
    TIER_LIMITS, load_install_info, save_install_info
)
from bidder_manager_qt import BidderManager
from telegram_qt import TelegramService
# from flask_server_qt import FlaskServer  # (unused in this file)
# from stripe_service_qt import StripeService  # REMOVED
from reportlab.lib.units import inch
from annotate_labels_qt import annotate_whatnot_pdf_with_bins_and_firstname
from dotenv import load_dotenv
from gui_layout import setup_ui
from gui_help_qt import (
    show_giveaway_help, show_telegram_help, show_import_csv_help,
    show_export_csv_help, show_sort_bin_desc_help,
    show_clear_bidders_help, show_top_buyer_help, show_giveaway_text_help,
    show_flash_sale_text_help
)
from gui_timer import bind_timer_methods
from gui_settings import bind_settings_methods
from gui_events import bind_event_methods, bind_help_methods
from gui_bidders import bind_bidders_methods
from gui_sorting import bind_sorting_methods
from gui_updater import bind_updater_methods
from gui_toggle import bind_toggle_methods

load_dotenv()


class AutoPasteLineEdit(QLineEdit):
    autoPasted = Signal(str)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.setText(text)
            self.autoPasted.emit(text)


class SwiftSaleGUI(QMainWindow):
    def _find_doubleclickcopy_path(self):
        """
        Locate helpers/DoubleClickCopy.exe in dev and frozen builds.
        Returns absolute path or None.
        """
        candidates = []

        # If bundled (PyInstaller build)
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
            candidates.append(os.path.join(base, "helpers", "DoubleClickCopy.exe"))

        # Next to this file (dev mode)
        here = os.path.dirname(__file__)
        candidates.append(os.path.join(here, "helpers", "DoubleClickCopy.exe"))

        # Project root (fallback)
        candidates.append(os.path.join(os.getcwd(), "helpers", "DoubleClickCopy.exe"))

        for p in candidates:
            if os.path.isfile(p):
                return os.path.abspath(p)

        return None

    def _is_process_running(self, image_name: str) -> bool:
        """
        Lightweight Windows check using tasklist (no extra deps).
        Returns True if a process named image_name is running.
        """
        if sys.platform != "win32":
            return False  # helper is Windows-only
        try:
            out = subprocess.check_output(
                ['tasklist', '/FI', f'IMAGENAME eq {image_name}'],
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            return image_name.encode('utf-8') in out
        except Exception:
            return False

    def ensure_doubleclickcopy_running(self):
        """
        Start helpers/DoubleClickCopy.exe if not already running.
        Records whether we started it so we can stop it on exit.
        """
        # Track per-run state (don’t clobber if already set)
        if not hasattr(self, "_dcc_proc"):
            self._dcc_proc = None
        if not hasattr(self, "_dcc_started_by_app"):
            self._dcc_started_by_app = False

        if sys.platform != "win32":
            self.log_info("DoubleClickCopy.exe is Windows-only; skipping start.")
            return

        exe_path = self._find_doubleclickcopy_path()
        if not exe_path:
            self.log_error("DoubleClickCopy.exe not found under helpers/ — skipping auto-launch.")
            return

        if self._is_process_running("DoubleClickCopy.exe"):
            self.log_info("DoubleClickCopy.exe already running — leaving it running.")
            return

        try:
            self._dcc_proc = subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path),
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            self._dcc_started_by_app = True
            self.log_info(f"Started helper: {exe_path}")
        except Exception as e:
            self.log_error(f"Failed to start DoubleClickCopy.exe: {e}")

    def __init__(
        self, api_token, user_email, base_url, dev_unlock_code,
        telegram_bot_token, telegram_chat_id, dev_access_granted, log_info,
        log_error, bidder_manager, bidders_db_path, subs_db_path
    ):
        super().__init__()

        # ... keep the rest of your existing __init__ body unchanged ...


    def __init__(
        self, api_token, user_email, base_url, dev_unlock_code,
        telegram_bot_token, telegram_chat_id, dev_access_granted, log_info,
        log_error, bidder_manager, bidders_db_path, subs_db_path
    ):
        super().__init__()

        self.default_x_offset_in = .40
        self.default_y_offset_in = 5.4

        self.current_version = __version__
        self.dev_access_granted = dev_access_granted
        self.log_info = log_info
        self.log_error = log_error
        # self.stripe_service = stripe_service  # REMOVED
        self.api_token = api_token.strip()
        self.base_url = (base_url or "").rstrip("/")
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.cloud_db = None
        self.bidder_manager = bidder_manager
        self.bidders_db_path = bidders_db_path
        self.subs_db_path = subs_db_path

        # Bridge runtime state (read from server on launch)
        self.bridge_enabled = False
        self.bridge_mode = "manual"  # "auto" | "manual" (default Manual unless server says otherwise)

        # App settings (persist UI prefs)
        self.qsettings = QSettings("SwiftSaleApp", "SwiftSaleAppV4")

        config = load_config()
        install_config = load_install_info()

        # Normalize environment
        self.env = os.getenv("FLASK_ENV", config.get("FLASK_ENV", "production")).lower()

        # Force production if running as frozen .exe
        import sys
        if getattr(sys, 'frozen', False):
            self.env = "production"
            self.log_info("Forced production mode due to frozen .exe build")

        self.is_dev_mode = self.env != "production"
        self.log_info(f"Environment: {self.env} | is_dev_mode: {self.is_dev_mode}")

        # Load email, install ID, tier from local JSON or fallback config
        self.user_email = install_config.get('email', '') or config.get('email', '') or user_email
        self.install_id = install_config.get('install_id', '')
        self.tier = install_config.get('tier', 'Trial')
        self.license_key = ""

        # Expired local promo -> downgrade to Trial
        promo_exp = install_config.get("promo_expiration")
        if promo_exp and isinstance(promo_exp, datetime) and promo_exp < datetime.utcnow():
            self.log_info(f"Promo expired for {self.user_email}; downgrading tier")
            self.tier = "Trial"
            install_config["promo_expiration"] = None
            save_install_info(self.user_email, self.install_id, self.tier)

        # If no email, prompt the user now
        if not self.user_email:
            self.user_email = self.prompt_for_email()
            if self.user_email:
                save_install_info(self.user_email, self.install_id, self.tier)
                self.log_info(f"User entered email: {self.user_email}")

        # Determine if we should verify subscription
        should_verify = self.user_email and "@" in self.user_email and not self.user_email.startswith("trial@")

        # Production cloud sync
        if self.env == 'production':
            try:
                self.cloud_db = CloudDatabaseManager(log_info, log_error)
                if should_verify:
                    hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                    cloud_install = self.cloud_db.get_install(hashed_email)  # returns (install_id, tier) or None
                    if cloud_install:
                        remote_install_id, remote_tier = cloud_install
                        # Sync local with cloud
                        if remote_install_id:
                            self.install_id = remote_install_id
                        if remote_tier:
                            self.tier = remote_tier
                        save_install_info(self.user_email, self.install_id, self.tier)
                        self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                        self.log_info(
                            f"✅ Synced install from cloud: {self.user_email}, "
                            f"ID: {self.install_id}, Tier: {self.tier}"
                        )
                    else:
                        self.log_info(f"No cloud record found for {self.user_email}, using local data")

                    # If still Trial, optionally ask the local bridge for status (no Stripe)
                    if self.tier.lower() == "trial":
                        try:
                            r = requests.get(
                                f"{self._bridge_base()}/subscription-status",
                                params={"email": self.user_email},
                                timeout=5
                            )
                            if r.ok:
                                data = r.json() or {}
                                remote_tier = str(data.get("tier", "")).strip()
                                if remote_tier and remote_tier.lower() != "trial":
                                    self.tier = remote_tier
                                    self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                                    save_install_info(self.user_email, self.install_id, self.tier)
                                    if self.cloud_db:
                                        self.cloud_db.update_install_tier(hashed_email, self.tier)
                                    self.log_info(f"Updated tier via bridge status to {self.tier} for {self.user_email}")
                        except Exception as _e:
                            # Non-fatal; continue with Trial
                            self.log_info("Bridge subscription-status not available; continuing with Trial")
            except Exception as e:
                self.log_error(f"Cloud sync or bridge status check failed: {e}")
                self.cloud_db = None

        self.telegram_service = None
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=0)  # infinite attempts
        self.latest_bin_assignment = '<span style="color:#90ee90;">Waiting for bidder...</span>'
        self.settings_initialized = False
        self.subscription_initialized = False
        self.annotate_initialized = False
        self._is_blinking = False
        self._blink_job = None

        # Initialize default settings
        self.chat_id = ""
        self.top_buyer_text = "WTG {username} you nabbed {qty} auctions so far!"
        self.giveaway_announcement_text = "Givvy is up! Make sure you LIKE & SHARE! Winner announced shortly!"
        self.flash_sale_announcement_text = "Flash Sale! Grab these deals before they sell out!"
        self.multi_buyer_mode = False

        # Initialize timer attributes
        self.show_start_time = None
        self.is_timer_paused = False
        self.elapsed_before_pause = timedelta(0)
        self.timer = QTimer(self)

        # Bind methods that define UI-related functions
        bind_toggle_methods(self)
        self.log_info("bind_toggle_methods completed, checking toggle_treeview: " + str(hasattr(self, "toggle_treeview")))
        bind_settings_methods(self)
        self.log_info("bind_settings_methods completed, checking build_settings_ui: " + str(hasattr(self, "build_settings_ui")))
        bind_event_methods(self)
        self.log_info("bind_event_methods completed, checking on_upgrade: " + str(hasattr(self, "on_upgrade")))

        # Setup UI after binding methods
        setup_ui(self, self.is_dev_mode)
        self.log_info("setup_ui completed, checking giveaway_help_button: " + str(hasattr(self, "giveaway_help_button")))
        self.log_info("Checking toggle_button: " + str(hasattr(self, "toggle_button")))

        # Bind other methods after UI setup
        bind_timer_methods(self)
        bind_help_methods(self)
        self.log_info("bind_help_methods completed")
        bind_bidders_methods(self)
        bind_sorting_methods(self)
        bind_updater_methods(self)  # provides self.check_for_updates & updater UI hooks
        self.log_info("bind_updater_methods completed")

        # Connect timer
        self.timer.timeout.connect(self.update_timer_display)

        # Load settings from database once
        try:
            settings = self.bidder_manager.get_settings(self.user_email)
            if settings:
                self.chat_id = settings.get("chat_id", self.chat_id)
                self.top_buyer_text = settings.get("top_buyer_text", self.top_buyer_text)
                # fixed typo: ggiveaway_announcement_text -> giveaway_announcement_text
                self.giveaway_announcement_text = settings.get("giveaway_announcement_text", self.giveaway_announcement_text)
                self.flash_sale_announcement_text = settings.get("flash_sale_announcement_text", self.flash_sale_announcement_text)
                self.multi_buyer_mode = settings.get("multi_buyer_mode", self.multi_buyer_mode)
                self.log_info(f"Retrieved settings: {settings}")
        except Exception as e:
            self.log_error(f"Failed to load settings: {e}")

        self.log_info(f"Initialized user {self.user_email}: tier={self.tier}, license={self.license_key}")

        # Status bar widgets (Auto-capture checkbox)
        self._init_status_bar()
        self.install_clipboard_capture()

        # --- Assistant button (placed in HEADER bar, not status bar) ---
        guide_path = os.path.join(os.path.dirname(__file__), "site", "guide.html")
        self.assistant = AssistantDialog(self, parent=self, guide_path=guide_path)

        self.chat_btn = QToolButton(self)
        self.chat_btn.setToolTip("Assistant")
        self.chat_btn.setAutoRaise(True)

        try:
            icon_path = get_resource_path("assets/ss_bot_icon.png")
            if not os.path.exists(icon_path):
                raise FileNotFoundError(f"Bot icon not found at {icon_path}")

            pixmap = QPixmap(icon_path)
            if pixmap.isNull():
                raise FileNotFoundError(f"Bot icon failed to load: {icon_path}")

            pixmap = pixmap.scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.chat_btn.setIcon(QIcon(pixmap))
            self.chat_btn.setIconSize(QSize(48, 48))
            self.chat_btn.setFixedSize(QSize(48, 48))
            self.chat_btn.setStyleSheet("QToolButton { padding: 0px; margin: 0px; border: none; }")
        except Exception as e:
            self.log_error(f"Assistant icon error: {e}")
            self.chat_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogHelpButton))
            # Ensure the button is still visible with a reasonable size
            self.chat_btn.setIconSize(QSize(32, 32))
            self.chat_btn.setFixedSize(QSize(36, 36))

        self.chat_btn.clicked.connect(self.assistant.show)

        if hasattr(self, "header_action_layout"):
            self.header_action_layout.addWidget(self.chat_btn)
            self.header_action_layout.setContentsMargins(0, 0, 0, 0)
            self.header_action_layout.setSpacing(4)
        else:
            self.statusBar().addPermanentWidget(self.chat_btn)
            self.log_error("header_action_layout not found; placed Assistant button in status bar.")
        self.chat_btn.show()  # ← make sure it's visible
        # --- end Assistant button ---

        # Setup connections and shortcuts
        self.setup_connections()
        self.setup_shortcuts()

        # Bridge + Socket
        self.refresh_bridge_status()  # sync with server; falls back to Manual if server down
        self.connect_socketio()

        self.show()
        self.raise_()

        # In case header_action_layout is constructed/adjusted late in some themes/layouts
        self._attach_assistant_to_header()

        self.ensure_doubleclickcopy_running()

    def _attach_assistant_to_header(self):
        """
        Always attach the Assistant button to the header_action_layout.
        Assumes setup_ui() has already created header_action_layout.
        """
        try:
            if hasattr(self, "header_action_layout"):
                # Avoid duplicates: remove if already present, then add
                try:
                    self.header_action_layout.removeWidget(self.chat_btn)
                except Exception:
                    pass
                self.header_action_layout.addWidget(self.chat_btn)
                self.chat_btn.setVisible(True)
            else:
                # Absolute fallback: put it in the status bar
                self.statusBar().addPermanentWidget(self.chat_btn)
                self.log_error("header_action_layout not found; placed Assistant button in status bar.")
        except Exception as e:
            self.log_error(f"Failed to attach Assistant button: {e}")

    def _build_shortcuts_html(self) -> str:
        return """
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; color:#eaeaea; background:#111; }
      h2 { margin:.2rem 0 .6rem 0; font-size:1.05rem; color:#fff; }
      table { width:100%; border-collapse:collapse; }
      td { padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }
      .k { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background:#1b1b1b; padding:2px 6px; border-radius:6px; }
      .g { color:#9aa0a6; }
    </style>
    <h2>General</h2>
    <table>
      <tr><td><span class="k">Ctrl+/</span></td><td>Open this shortcuts panel</td></tr>
      <tr><td><span class="k">F1</span></td><td>Open shortcuts panel</td></tr>
      <tr><td><span class="k">Ctrl+C</span></td><td>Clear username/qty/weight</td></tr>
      <tr><td><span class="k">Ctrl+B</span></td><td>Add bidder</td></tr>
    </table>
    <h2>Bridge / Capture</h2>
    <table>
      <tr><td><span class="k">Ctrl+Shift+J</span></td><td>Enable/Disable Bridge</td></tr>
      <tr><td><span class="k">Ctrl+Shift+K</span></td><td>Toggle Auto ↔ Manual</td></tr>
    </table>
    <h2>Queue & Sticky</h2>
    <table>
      <tr><td><span class="k">Ctrl+Shift+M</span></td><td>Open "Needs Username" queue</td></tr>
      <tr><td><span class="k">Ctrl+Shift+W</span></td><td>Apply sticky winner now</td></tr>
    </table>
    <h2>Promo Code</h2>
    <table>
      <tr><td><span class="k">Ctrl+Alt+D</span></td><td>Enter Promo Code</td></tr>
    </table>
    <p class="g">Tip: Use the status-bar checkbox to switch Auto-capture on/off quickly.</p>
    """

    def open_shortcuts_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        layout = QVBoxLayout(dlg)
        view = QTextBrowser()
        view.setHtml(self._build_shortcuts_html())
        view.setOpenExternalLinks(True)
        layout.addWidget(view)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, alignment=Qt.AlignRight)
        dlg.resize(560, 460)
        dlg.exec()

    # ---------- Helpers: Bridge base URL ----------
    def _bridge_base(self) -> str:
        """HTTP base for bridge endpoints; default to localhost if base_url unset."""
        return self.base_url or "http://127.0.0.1:10000"

    # ---------- Status bar + Auto-capture ----------
    def _init_status_bar(self):
        """Add the Auto-capture checkbox to the status bar and bind it."""
        sb = self.statusBar()
        # Restore last saved mode (default Manual)
        saved_mode = str(self.qsettings.value("bridge/mode", "manual")).lower()
        if saved_mode not in ("auto", "manual"):
            saved_mode = "manual"
        self.bridge_mode = saved_mode

        self.auto_capture_checkbox = QCheckBox("Auto-capture usernames", self)
        self.auto_capture_checkbox.setChecked(self.bridge_mode == "auto")
        self.auto_capture_checkbox.setToolTip("Checked = Auto, Unchecked = Manual")
        self.auto_capture_checkbox.stateChanged.connect(self.on_auto_capture_toggled)

        # Keep some spacing so messages still visible
        spacer = QLabel("   ")
        sb.addPermanentWidget(spacer)
        sb.addPermanentWidget(self.auto_capture_checkbox)

        # Reflect in header/footer initially
        self.update_header_and_footer()

    def _sync_checkbox_from_state(self):
        """Keep the checkbox in sync with current bridge_mode without firing signals."""
        if not hasattr(self, "auto_capture_checkbox"):
            return
        self.auto_capture_checkbox.blockSignals(True)
        self.auto_capture_checkbox.setChecked(self.bridge_mode == "auto")
        self.auto_capture_checkbox.setToolTip(f"Checked = Auto, Unchecked = Manual (Bridge is {'ON' if self.bridge_enabled else 'OFF'})")
        self.auto_capture_checkbox.blockSignals(False)

    def on_auto_capture_toggled(self, state: int):
        """POST /bridge/mode with {enabled, mode} when user toggles the checkbox."""
        desired_mode = "auto" if state == Qt.Checked else "manual"
        payload = {
            "enabled": bool(self.bridge_enabled),
            "mode": desired_mode
        }
        try:
            r = requests.post(f"{self._bridge_base()}/bridge/mode", json=payload, timeout=3)
            if r.ok and r.json().get("status") == "success":
                # Accept any server-normalized values if present
                self.bridge_enabled = bool(r.json().get("enabled", self.bridge_enabled))
                self.bridge_mode = str(r.json().get("mode", desired_mode))
                # Persist UI preference
                self.qsettings.setValue("bridge/mode", self.bridge_mode)
                self.qsettings.setValue("bridge/auto_capture", self.bridge_mode == "auto")
                self.statusBar().showMessage(f"Capture mode: {self.bridge_mode.upper()}", 2000)
            else:
                QMessageBox.warning(self, "Bridge", "Failed to update capture mode on server.")
                # Revert checkbox to actual state
                self._sync_checkbox_from_state()
        except Exception as e:
            self.log_error(f"Auto-capture toggle failed: {e}")
            QMessageBox.warning(self, "Bridge", f"Failed to reach bridge: {e}")
            # Revert UI; do not crash
            self._sync_checkbox_from_state()
        finally:
            self.update_header_and_footer()

    def prompt_for_email(self):
        """Prompt user for email and optionally skip in future if 'Don't ask again' is checked."""
        from config_qt import get_or_create_install_info, save_install_info
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox

        info = get_or_create_install_info()
        email = info.get("email", "").strip().lower()

        # If already saved and not trial, return immediately
        if email and email != "trial@swiftsaleapp.com":
            return email

        # Show dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Enter Email")
        layout = QVBoxLayout(dialog)

        label = QLabel("Please enter your email address:")
        email_input = QLineEdit()
        dont_ask_checkbox = QCheckBox("Don't ask again (continue in Trial mode)")
        submit_button = QPushButton("Submit")

        layout.addWidget(label)
        layout.addWidget(email_input)
        layout.addWidget(dont_ask_checkbox)
        layout.addWidget(submit_button)
        dialog.setLayout(layout)

        result = {}

        def on_submit():
            entered = email_input.text().strip()
            if '@' in entered:
                result["email"] = entered.lower()
                dialog.accept()
            elif dont_ask_checkbox.isChecked():
                result["email"] = "trial@swiftsaleapp.com"
                dialog.accept()
            else:
                label.setText("Invalid email address. Please try again:")

        submit_button.clicked.connect(on_submit)
        dialog.exec()

        email = result.get("email", "trial@swiftsaleapp.com")
        info["email"] = email
        save_install_info(info["email"], info["install_id"], info["tier"])
        return email

    def open_mailing_list_dialog(self):
        from mailing_list_manager import MailingListViewer
        self.mailing_viewer = MailingListViewer()
        self.mailing_viewer.show()

    def register_install(self):
        """Register install with backend and save response."""
        try:
            response = requests.post(
                f"{self._bridge_base()}/register-install",
                json={"email": self.user_email},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                self.install_id = data["install_id"]
                self.tier = data["tier"]
                save_install_info(self.user_email, self.install_id, self.tier)
                self.log_info(f"Registered install: email={self.user_email}, install_id={self.install_id}, tier={self.tier}")
            else:
                self.log_error(f"Install registration failed: {response.text}")
                QMessageBox.critical(self, "Error", "Failed to register install")
        except Exception as e:
            self.log_error(f"Error registering install: {e}")
            QMessageBox.critical(self, "Error", f"Error registering install: {e}")

    def setup_connections(self):
        """Connect all UI buttons and signals to their respective handlers."""
        if hasattr(self, "add_bidder_button"):
            self.add_bidder_button.clicked.connect(self.add_bidder)
        if hasattr(self, "clear_bidders_button"):
            self.clear_bidders_button.clicked.connect(self.clear_bidders)
        if hasattr(self, "top_buyer_copy_label"):
            self.top_buyer_copy_label.mousePressEvent = self.copy_top_buyer_message
        if hasattr(self, "start_show_button"):
            self.start_show_button.clicked.connect(self.start_show)
        if hasattr(self, "pause_button"):
            self.pause_button.clicked.connect(self.pause_timer)
        if hasattr(self, "stop_button"):
            self.stop_button.clicked.connect(self.stop_timer)
        if hasattr(self, "import_csv_button"):
            self.import_csv_button.clicked.connect(self.import_csv)
        if hasattr(self, "export_csv_button"):
            self.export_csv_button.clicked.disconnect() if hasattr(self.export_csv_button, "clicked") else None
            self.export_csv_button.clicked.connect(self.export_bidders_csv)
        if hasattr(self, "toggle_tabs_btn"):
            self.toggle_tabs_btn.clicked.connect(self.toggle_settings_tabs)
        if hasattr(self, "update_btn"):
            self.update_btn.clicked.connect(self.check_for_updates)  # provided by gui_updater
        if hasattr(self, "show_sell_rate_button"):
            self.show_sell_rate_button.clicked.connect(self.show_avg_sell_rate)
        if hasattr(self, "start_giveaway_button"):
            self.start_giveaway_button.clicked.connect(self.start_giveaway)
        if hasattr(self, "start_flash_sale_button"):
            self.start_flash_sale_button.clicked.connect(self.start_flash_sale)
        if hasattr(self, "sort_bin_asc_button"):
            self.sort_bin_asc_button.clicked.connect(self.sort_bins_ascending)
        if hasattr(self, "sort_bin_desc_button"):
            self.sort_bin_desc_button.clicked.connect(self.sort_bins_descending)
        if hasattr(self, "save_settings_button"):
            self.save_settings_button.clicked.connect(self.save_user_config)
        if hasattr(self, "username_entry"):
            self.username_entry.textChanged.connect(self.on_username_changed)
        if hasattr(self, "clear_button"):
            self.clear_button.clicked.connect(self.clear_username)

    def closeEvent(self, event):
        """Stop the timer, disconnect sockets, and close helper on exit."""
        try:
            if self.timer.isActive():
                self.timer.stop()
        except Exception:
            pass

        try:
            if self.sio.connected:
                try:
                    self.sio.disconnect()
                except Exception:
                    pass
        except Exception:
            pass

        # Gracefully stop DoubleClickCopy if we launched it
        if sys.platform == "win32":
            try:
                if getattr(self, "_dcc_started_by_app", False) and getattr(self, "_dcc_proc", None):
                    self._dcc_proc.terminate()
                    try:
                        self._dcc_proc.wait(timeout=2)
                    except Exception:
                        # Force kill if it didn't terminate
                        subprocess.call(
                            ['taskkill', '/F', '/IM', 'DoubleClickCopy.exe', '/T'],
                            creationflags=0x08000000  # CREATE_NO_WINDOW
                        )
            except Exception as e:
                self.log_error(f"Error stopping DoubleClickCopy.exe: {e}")

        event.accept()

    def auto_paste_username(self, event):
        """Auto-paste username from clipboard."""
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.username_entry.setText(text)
        super(QLineEdit, self.username_entry).focusInEvent(event)
        self.log_info("Auto-pasted username from clipboard")

    def clear_username(self):
        """Clear the username, quantity, and weight fields."""
        self.username_entry.clear()
        self.qty_entry.setText("1")
        self.weight_entry.clear()
        self.giveaway_var.setChecked(False)
        self.log_info("Cleared username, quantity, and weight fields")

    def toggle_settings_tabs(self):
        """Toggle visibility of the settings tab widget."""
        visible = self.notebook.isVisible()
        self.notebook.setVisible(not visible)
        self.toggle_tabs_btn.setText("Hide Settings" if not visible else "Settings")
        self.log_info(f"Settings tab toggled to {'visible' if not visible else 'hidden'}")

    def build_subscription_ui(self, parent_frame):
        """Build Subscription tab UI (external billing only)."""
        layout = QVBoxLayout(parent_frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        subscription_group = QGroupBox("Subscription")
        subscription_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        subscription_layout = QGridLayout()
        subscription_layout.setContentsMargins(12, 12, 12, 12)
        subscription_layout.setSpacing(10)
        subscription_group.setLayout(subscription_layout)

        label = QLabel("Select Tier:")
        label.setObjectName("subscriptionLabel")
        subscription_layout.addWidget(label, 0, 0)

        self.tier_combo = QComboBox()
        self.tier_combo.setObjectName("tierComboBox")
        self.tier_combo.addItems(["Trial", "Bronze", "Silver", "Gold"])
        self.tier_combo.setCurrentText(self.tier)
        self.tier_combo.setEnabled(False)  # No in-app tier changes
        subscription_layout.addWidget(self.tier_combo, 0, 1)

        # Display status and next billing (if fetched successfully)
        try:
            r = requests.get(f"{self._bridge_base()}/subscription-status", params={"email": self.user_email}, timeout=5)
            data = r.json() if r.ok else {}
            status = data.get("status", "N/A")
            next_billing = data.get("next_billing_date", "N/A")
        except Exception as e:
            self.log_error(f"Failed to fetch subscription status: {e}")
            status, next_billing = "N/A", "N/A"

        self.status_label = QLabel(f"Status: {status}")
        self.next_billing_label = QLabel(f"Next Billing: {next_billing}")
        subscription_layout.addWidget(self.status_label, 1, 0)
        subscription_layout.addWidget(self.next_billing_label, 1, 1)

        # External-only actions
        def open_portal():
            QDesktopServices.openUrl(QUrl("https://swiftsaleapp.com"))

        self.manage_subscription_button = QPushButton("Manage Subscription")
        self.manage_subscription_button.setFixedWidth(220)
        self.manage_subscription_button.setToolTip("Opens external site to manage your billing and plan.")
        self.manage_subscription_button.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
        """)
        self.manage_subscription_button.clicked.connect(open_portal)
        subscription_layout.addWidget(self.manage_subscription_button, 2, 0, 1, 2)

        layout.addWidget(subscription_group)
        layout.addStretch(1)
        self.log_info("Subscription tab initialized (external billing mode)")

    def build_annotate_ui(self, parent_frame):
        """Build Annotate Labels tab UI."""
        layout = QVBoxLayout(parent_frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        annotate_group = QGroupBox("Annotate Whatnot Labels")
        annotate_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        annotate_layout = QGridLayout()
        annotate_layout.setContentsMargins(12, 12, 12, 12)
        annotate_layout.setSpacing(10)
        annotate_group.setLayout(annotate_layout)

        annotate_layout.addWidget(QLabel("X Offset:"), 0, 0)
        self.x_offset_entry = QLineEdit(f"{self.default_x_offset_in:.2f}")
        self.x_offset_entry.setFixedWidth(70)
        annotate_layout.addWidget(self.x_offset_entry, 0, 1)
        annotate_layout.addWidget(QLabel("inches"), 0, 2)

        annotate_layout.addWidget(QLabel("Y Offset:"), 0, 3)
        self.y_offset_entry = QLineEdit(f"{self.default_y_offset_in:.2f}")
        self.y_offset_entry.setFixedWidth(70)
        annotate_layout.addWidget(self.y_offset_entry, 0, 4)
        annotate_layout.addWidget(QLabel("inches"), 0, 5)

        self.annotate_button = QPushButton("Annotate 4\"×6\" Labels (SwiftSale App: Bin #)")
        self.annotate_button.setObjectName("annotateButton")
        self.annotate_button.clicked.connect(self.on_annotate_labels_clicked)
        annotate_layout.addWidget(self.annotate_button, 1, 0, 1, 6)

        layout.addWidget(annotate_group)
        layout.addStretch(1)
        self.log_info("Annotate Labels tab initialized")

    def show_temporary_message(self, message: str, duration_ms: int = 2000):
        """Show a temporary label that fades after a duration."""
        if hasattr(self, "_copy_notice") and self._copy_notice:
            self._copy_notice.hide()
        self._copy_notice = QLabel(message, self)
        self._copy_notice.setStyleSheet("""
            background-color: #333;
            color: white;
            padding: 6px 12px;
            border-radius: 8px;
        """)
        self._copy_notice.setWindowFlags(self._copy_notice.windowFlags() | Qt.ToolTip)
        self._copy_notice.adjustSize()
        self._copy_notice.move(
            self.width() // 2 - self._copy_notice.width() // 2,
            self.height() - 80
        )
        self._copy_notice.show()
        QTimer.singleShot(duration_ms, self._copy_notice.hide)

    def update_top_buyers(self):
        """Update the top buyers text display."""
        try:
            top_buyers = self.bidder_manager.get_top_buyers()
            if not top_buyers:
                self.top_buyers_text.setText("No top buyers")
                return
            display_text = ", ".join(f"{name} ({count})" for name, count in top_buyers)
            self.top_buyers_text.setText(display_text)
            self.log_info(f"Updated top buyers display: {display_text}")
        except Exception as e:
            self.log_error(f"Failed to update top buyers: {e}")
            self.top_buyers_text.setText("No top buyers")

    def update_bins_used_display(self):
        try:
            bins_used = self.bidder_manager.count_total_bins_assigned()
            max_bins = TIER_LIMITS.get(self.tier, {}).get("bins", 20)
            usage_ratio = bins_used / max_bins if max_bins else 0
            self.bins_used_label.setStyleSheet(
                "color: red; font-weight: bold;" if usage_ratio >= 0.75 else "color: white; font-weight: bold;"
            )
            self.bins_used_label.setText(f"Bins Used: {bins_used}/{max_bins}")
            self.log_info(f"Updated bins used display: {bins_used}/{max_bins}")
        except Exception as e:
            self.log_error(f"Failed to update bins used display: {e}")
            self.bins_used_label.setText("Bins Used: Error")

    def refresh_bin_usage_display(self):
        """Refresh both bin usage label and footer display."""
        try:
            self.update_bins_used_display()  # updates the "Bins Used: X/Y" label

            # Then update the footer
            bins_used = self.bidder_manager.count_total_bins_assigned()
            max_bins = TIER_LIMITS.get(self.tier, {}).get("bins", 20)
            shield = "🛡️"
            color = {
                "Trial": "#CCCCCC",
                "Bronze": "#cd7f32",
                "Silver": "#c0c0c0",
                "Gold": "#ffd700"
            }.get(self.tier, "#FFFFFF")

            self.footer_label.setText(f"{shield} {self.tier} | Bins Used: {bins_used}/{max_bins} | Install ID: {self.install_id}")
            self.footer_label.setStyleSheet(f"color: {color}")
            self.footer_label.setToolTip(f"Install ID: {self.install_id} – {self.tier} Tier")
            self.log_info(f"Refreshed bin usage: {bins_used}/{max_bins}")

        except Exception as e:
            self.log_error(f"Failed to refresh bin usage: {e}")

    def update_latest_bidder_display(self):
        """Update the latest bidder display."""
        try:
            latest_bidder = self.bidder_manager.get_latest_bidder()
            if not latest_bidder:
                self.latest_bidder_label.setText("Latest: None")
                self.bin_number_label.setText("")
            else:
                self.latest_bidder_label.setText(f"Latest: {latest_bidder['username']}")
                self.bin_number_label.setText(str(latest_bidder['bin_number']))
                self.log_info(f"Updated latest bidder: {latest_bidder['username']} (Bin {latest_bidder['bin_number']})")
            self.update_header_and_footer()
        except Exception as e:
            self.log_error(f"Failed to update latest bidder: {e}")
            self.latest_bidder_label.setText("Latest: None")
            self.bin_number_label.setText("")

    def populate_bidders_tree(self, bidders=None):
        """Populate the bidders_tree QTreeWidget with collapsed children in manual order."""
        try:
            self.bidders_tree.setSortingEnabled(False)
            self.bidders_tree.clear()
            self.bidders_tree.setHeaderLabels(["Username", "Qty", "Bin", "Giveaway", "Weight", "Timestamp"])

            if bidders is None:
                self.bidder_manager.print_bidders()
                bidders = self.bidder_manager.bidders

            for username, info in bidders.items():
                parent = QTreeWidgetItem([
                    info["original_username"],
                    "",
                    str(info["bin"]) if info["bin"] is not None else "",
                    "", "", ""
                ])
                parent.setExpanded(False)
                self.bidders_tree.addTopLevelItem(parent)

                for t in info["transactions"]:
                    child = QTreeWidgetItem([
                        "", str(t["qty"]), "",
                        "Yes" if t["giveaway"] else "No",
                        str(t["weight"]) if t["weight"] else "",
                        t["timestamp"]
                    ])
                    parent.addChild(child)

            self.bidders_tree.resizeColumnToContents(0)
            self.log_info("Updated bidders tree")

        except Exception as e:
            self.log_error(f"Failed to populate bidders tree: {e}")
            QMessageBox.critical(self, "Error", f"Failed to update bidders: {e}")

    def clear_bidders(self):
        """Clear all bidders and update UI."""
        confirm = QMessageBox.question(
            self, "Confirm Clear", "Are you sure you want to clear all bidders and bin assignments?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            try:
                self.bidder_manager.clear_all_bidders()
                self.populate_bidders_tree()
                self.update_bins_used_display()
                self.update_latest_bidder_display()
                QMessageBox.information(self, "Success", "All bidders cleared.")
                self.log_info("All bidders cleared")
            except Exception as e:
                self.log_error(f"Failed to clear bidders: {e}")
                QMessageBox.critical(self, "Error", f"Failed to clear bidders: {e}")

    def update_header_and_footer(self):
        """Update header and footer labels with tier color, install ID, and bin info."""
        try:
            tier_colors = {
                "Trial": "#CCCCCC",
                "Bronze": "#cd7f32",
                "Silver": "#c0c0c0",
                "Gold": "#ffd700"
            }
            color = tier_colors.get(self.tier, "#FFFFFF")
            shield = "🛡️"

            # Header: User email, tier, and slogan
            self.header_label.setText(
                f"SwiftSale - {self.user_email} ({self.tier}) | Build Whatnot Orders in Realtime"
            )

            # Compose footer: Tier, Install ID, Bins Used, Latest Bin, Bridge
            try:
                bins_used = self.bidder_manager.count_total_bins_assigned()
                max_bins = TIER_LIMITS.get(self.tier, {}).get("bins", 20)
                bins_part = f" | Bins Used: {bins_used}/{max_bins}"
            except Exception:
                bins_part = ""

            latest_part = f" | Latest Bin: {self.latest_bin_assignment}" if self.latest_bin_assignment else ""
            bridge_part = f" | Bridge: {'ON' if self.bridge_enabled else 'OFF'} ({self.bridge_mode})"

            self.footer_label.setText(
                f"{shield} {self.tier} | Install ID: {self.install_id}{bins_part}{latest_part}{bridge_part}"
            )
            self.footer_label.setStyleSheet(f"color: {color}")
            self.footer_label.setToolTip(
                f"Install ID: {self.install_id} – {self.tier} Tier\n"
                f"Bridge: {'ON' if self.bridge_enabled else 'OFF'} ({self.bridge_mode})"
            )

            # Settings tab license label
            if hasattr(self, "license_status_label"):
                self.license_status_label.setText(f"{shield} License Verified – {self.tier} Tier")
                self.license_status_label.setStyleSheet(f"color: {color}")
                self.license_status_label.setToolTip(f"Install ID: {self.install_id}")

            # Keep checkbox in sync with current state
            self._sync_checkbox_from_state()

            # De-dupe the noisy info log (log at most ~once per 0.75s)
            import time
            now = time.monotonic()
            last = getattr(self, "_last_hf_log_ts", 0.0)
            if now - last > 0.75:
                self._last_hf_log_ts = now
                self.log_info("Updated header, footer, and license label")

        except Exception as e:
            self.log_error(f"Failed to update header/footer/license: {e}")

    def on_annotate_labels_clicked(self):
        """Annotate Whatnot labels with bin numbers."""
        try:
            x_offset = float(self.x_offset_entry.text()) * inch if self.x_offset_entry.text() else self.default_x_offset_in * inch
            y_offset = float(self.y_offset_entry.text()) * inch if self.y_offset_entry.text() else self.default_y_offset_in * inch
            file_name, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
            if file_name:
                output_file = file_name.replace(".pdf", "_annotated.pdf")
                annotate_whatnot_pdf_with_bins_and_firstname(
                    whatnot_pdf_path=file_name,
                    bidders_db_path=self.bidders_db_path,
                    output_pdf_path=output_file,
                    stamp_x=x_offset,
                    stamp_y=y_offset
                )
                QMessageBox.information(self, "Success", f"Labels annotated and saved to {output_file}")
                self.log_info(f"Annotated labels saved to {output_file}")
        except Exception as e:
            self.log_error(f"Failed to annotate labels: {e}")
            QMessageBox.critical(self, "Error", f"Failed to annotate labels: {e}")

    # =========================
    # Shortcuts / Hotkeys
    # =========================
    def setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+B"), self, self.add_bidder)
        QShortcut(QKeySequence("Ctrl+C"), self, self.clear_username)

        # Dev dialog
        dev_shortcut = QShortcut(QKeySequence("Ctrl+Alt+D"), self)
        dev_shortcut.activated.connect(self.open_dev_code_dialog)

        # Bridge: enable/disable
        QShortcut(QKeySequence("Ctrl+Shift+J"), self, self.toggle_bridge_enabled)

        # Bridge: toggle auto/manual
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, self.toggle_bridge_mode)

        # Miss Queue dialog
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, self.open_miss_queue_dialog)

        # Sticky winner apply
        QShortcut(QKeySequence("Ctrl+Shift+W"), self, self.apply_sticky_winner)
     
        self.log_info("Keyboard shortcuts set up")

    # =========================
    # Bridge status + controls
    # =========================
    def refresh_bridge_status(self):
        """Query Flask bridge for status and update footer text. Fallback to Manual if unreachable."""
        try:
            r = requests.get(f"{self._bridge_base()}/bridge/status", timeout=2)
            if r.ok:
                data = r.json().get("status") == "success" and r.json() or {}
                # If wrapped in {'status':'success', ...}, merge properly
                if data.get("status") == "success":
                    data = {k: v for k, v in data.items() if k != "status"}
                self.bridge_enabled = bool(data.get("enabled", self.bridge_enabled))
                self.bridge_mode = str(data.get("mode", self.bridge_mode or "manual"))
            else:
                # Server reachable but not OK -> safe fallback
                self.bridge_enabled = False
                self.bridge_mode = "manual"
        except Exception as e:
            self.log_error(f"Bridge status failed: {e}")
            self.bridge_enabled = False
            self.bridge_mode = "manual"
        finally:
            # Persist the last-known UI preference (even if server down, we keep Manual)
            self.qsettings.setValue("bridge/mode", self.bridge_mode)
            self.qsettings.setValue("bridge/auto_capture", self.bridge_mode == "auto")
            self._sync_checkbox_from_state()
            self.update_header_and_footer()

    def toggle_bridge_enabled(self):
        """Enable/disable the local browser bridge. Always send {enabled, mode}."""
        try:
            new_enabled = not self.bridge_enabled
            payload = {"enabled": new_enabled, "mode": self.bridge_mode}
            r = requests.post(f"{self._bridge_base()}/bridge/mode", json=payload, timeout=3)
            if r.ok and r.json().get("status") == "success":
                self.bridge_enabled = bool(r.json().get("enabled", new_enabled))
                self.bridge_mode = str(r.json().get("mode", self.bridge_mode))
                # Persist mode (enabled is runtime only)
                self.qsettings.setValue("bridge/mode", self.bridge_mode)
                self.qsettings.setValue("bridge/auto_capture", self.bridge_mode == "auto")
                self.show_temporary_message(f"Bridge {'ENABLED' if self.bridge_enabled else 'DISABLED'}")
            else:
                QMessageBox.warning(self, "Bridge", "Failed to toggle bridge. Is the server running?")
        except Exception as e:
            self.log_error(f"toggle_bridge_enabled failed: {e}")
            QMessageBox.warning(self, "Bridge", f"Failed to toggle bridge: {e}")
        finally:
            self._sync_checkbox_from_state()
            self.update_header_and_footer()

    def toggle_bridge_mode(self):
        """Toggle Auto/Manual capture mode on the server. Always send {enabled, mode}."""
        new_mode = "manual" if self.bridge_mode == "auto" else "auto"
        try:
            payload = {"enabled": bool(self.bridge_enabled), "mode": new_mode}
            r = requests.post(f"{self._bridge_base()}/bridge/mode", json=payload, timeout=3)
            if r.ok and r.json().get("status") == "success":
                self.bridge_enabled = bool(r.json().get("enabled", self.bridge_enabled))
                self.bridge_mode = str(r.json().get("mode", new_mode))
                self.qsettings.setValue("bridge/mode", self.bridge_mode)
                self.qsettings.setValue("bridge/auto_capture", self.bridge_mode == "auto")
                self.show_temporary_message(f"Capture mode: {self.bridge_mode.upper()}")
            else:
                QMessageBox.warning(self, "Bridge", "Failed to change capture mode.")
        except Exception as e:
            self.log_error(f"toggle_bridge_mode failed: {e}")
            QMessageBox.warning(self, "Bridge", f"Failed to change capture mode: {e}")
        finally:
            self._sync_checkbox_from_state()
            self.update_header_and_footer()

    # =========================
    # Socket.IO (winner events)
    # =========================
    def connect_socketio(self):
        """Connect to local Flask-SocketIO and subscribe to events."""
        try:
            # The base_url is something like http://127.0.0.1:10000
            url = self.base_url or "http://127.0.0.1:10000"

            @self.sio.event
            def connect():
                self.log_info("Socket.IO connected")
                self.show_temporary_message("Bridge connected")

            @self.sio.event
            def disconnect():
                self.log_info("Socket.IO disconnected")

            @self.sio.on("winner")
            def on_winner(payload):
                try:
                    username = payload.get("username", "")
                    result = payload.get("result", {}) or {}
                    action = result.get("action", "received")
                    conf = payload.get("confidence", 0)
                    source = payload.get("source", "unknown")
                    mode = payload.get("mode", self.bridge_mode)

                    msg = f"Winner: {username} • {action} • {source} • conf={conf:.2f} • mode={mode}"
                    self.statusBar().showMessage(msg, 3000)
                    self.log_info(msg)

                    # Update footer/bins
                    self.refresh_bin_usage_display()
                    self.update_latest_bidder_display()
                except Exception as e:
                    self.log_error(f"on_winner handler failed: {e}")

            self.sio.connect(url, transports=["websocket", "polling"])
        except Exception as e:
            self.log_error(f"Socket.IO connect failed: {e}")
            # Non-fatal. UI still works; user can retry by toggling bridge or restarting.

    # =========================
    # Miss Queue dialog
    # =========================
    def open_miss_queue_dialog(self):
        """Simple dialog to process queued winner events."""
        try:
            items = self.bidder_manager.list_miss_queue()
        except Exception as e:
            self.log_error(f"list_miss_queue failed: {e}")
            items = []

        dlg = QDialog(self)
        dlg.setWindowTitle("Needs Username — Queue")
        vbox = QVBoxLayout(dlg)

        info = QLabel("Review items below. Select one and choose Apply or Skip.")
        vbox.addWidget(info)

        lst = QListWidget()
        for evt in items:
            ts = evt.get("ts")
            ts_str = ""
            try:
                ts_dt = datetime.fromtimestamp(int(ts)/1000) if ts else None
                ts_str = ts_dt.strftime("%H:%M:%S") if ts_dt else ""
            except Exception:
                ts_str = ""
            text = f"{evt.get('username','')}  |  src={evt.get('source','?')}  |  conf={evt.get('confidence',0):.2f}  |  {ts_str}"
            QListWidgetItem(text, lst)
        vbox.addWidget(lst)

        hbox = QHBoxLayout()
        btn_apply = QPushButton("Apply to Bin")
        btn_skip = QPushButton("Skip")
        btn_close = QPushButton("Close")
        hbox.addWidget(btn_apply)
        hbox.addWidget(btn_skip)
        hbox.addStretch(1)
        hbox.addWidget(btn_close)
        vbox.addLayout(hbox)

        def apply_selected():
            row = lst.currentRow()
            if row < 0:
                QMessageBox.information(dlg, "Queue", "Select an item first.")
                return
            try:
                next_item = self.bidder_manager.pop_next_miss()
            except Exception as e:
                self.log_error(f"pop_next_miss failed: {e}")
                QMessageBox.warning(dlg, "Queue", "Failed to pop next item.")
                return
            if not next_item:
                QMessageBox.information(dlg, "Queue", "Queue is empty.")
                return
            # Assign bin to that username
            try:
                bin_code = self.bidder_manager.apply_sticky_to_username(next_item.get("username"))
                if bin_code:
                    self.show_temporary_message(f"Assigned bin {bin_code} → {next_item.get('username')}")
                    self.refresh_bin_usage_display()
                    self.update_latest_bidder_display()
                    lst.takeItem(row)
                else:
                    QMessageBox.warning(dlg, "Queue", "No bin assigned (sticky empty or error).")
            except Exception as e:
                self.log_error(f"apply_selected failed: {e}")
                QMessageBox.critical(dlg, "Queue", f"Failed to assign bin: {e}")

        def skip_selected():
            row = lst.currentRow()
            if row < 0:
                QMessageBox.information(dlg, "Queue", "Select an item first.")
                return
            # Pop and discard
            try:
                _ = self.bidder_manager.pop_next_miss()
                lst.takeItem(row)
            except Exception as e:
                self.log_error(f"skip_selected failed: {e}")

        btn_apply.clicked.connect(apply_selected)
        btn_skip.clicked.connect(skip_selected)
        btn_close.clicked.connect(dlg.accept)

        dlg.resize(520, 360)
        dlg.exec()

    # =========================
    # Sticky winner hotkey
    # =========================
    def apply_sticky_winner(self):
        """Apply the last sticky winner to a bin immediately."""
        try:
            bin_code = self.bidder_manager.apply_sticky_to_username()
            if bin_code:
                self.show_temporary_message(f"Applied sticky → Bin {bin_code}")
                self.refresh_bin_usage_display()
                self.update_latest_bidder_display()
            else:
                self.show_temporary_message("No sticky winner available")
        except Exception as e:
            self.log_error(f"apply_sticky_winner failed: {e}")
            QMessageBox.warning(self, "Sticky", f"Failed to apply sticky: {e}")

    # =========================
    # Existing UI / features
    # =========================
    def setup_shortcuts_legacy(self):
        """(kept for compatibility if referenced elsewhere)"""
        self.setup_shortcuts()

    def save_user_config(self):
        """Save current user settings to database."""
        try:
            self.bidder_manager.save_settings(
                self.user_email, self.chat_id, self.top_buyer_text,
                self.giveaway_announcement_text, self.flash_sale_announcement_text,
                self.multi_buyer_mode
            )
            self.log_info("User config saved to database")
        except Exception as e:
            self.log_error(f"Failed to save user config: {e}")

    # ==== Existing main entry ====
    # (unchanged)
if __name__ == "__main__":
    import sys
    from main_qt import main
    app = QApplication(sys.argv)
    try:
        with open(get_resource_path("style.qss"), "r") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        logging.error(f"Failed to load stylesheet: {e}")
    main()
