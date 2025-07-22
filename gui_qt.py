import os
import socketio
import hashlib
import logging
import requests
from datetime import timedelta
from cloud_database_qt import CloudDatabaseManager
from PySide6.QtWidgets import (
    QMainWindow, QFrame, QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
    QTextEdit, QTableWidget, QTreeWidgetItem, QScrollBar, QTabWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QGroupBox, QFileDialog, QMessageBox, QInputDialog,
    QTextBrowser, QDialog, QApplication, QSizePolicy
)
from cloud_database_qt import CloudDatabaseManager

from PySide6.QtGui import QPixmap, QFont, QCursor, QClipboard, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QTimer, Signal
from config_qt import get_resource_path, load_config, get_config_value, DEFAULT_DATA_DIR, TIER_LIMITS, load_install_info, save_install_info
from bidder_manager_qt import BidderManager
from telegram_qt import TelegramService
from flask_server_qt import FlaskServer
from stripe_service_qt import StripeService
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
    def __init__(self, stripe_service, api_token, user_email, base_url, dev_unlock_code, telegram_bot_token, telegram_chat_id, dev_access_granted, log_info, log_error, bidder_manager, bidders_db_path, subs_db_path):
        super().__init__()

        self.default_x_offset_in = .40
        self.default_y_offset_in = 5.4

        self.current_version = "4"
        self.dev_access_granted = dev_access_granted
        self.log_info = log_info
        self.log_error = log_error
        self.stripe_service = stripe_service
        self.api_token = api_token.strip()
        self.base_url = base_url
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.cloud_db = None
        self.bidder_manager = bidder_manager
        self.bidders_db_path = bidders_db_path
        self.subs_db_path = subs_db_path

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

        # Load from local JSON first
        self.user_email = install_config.get('email', '') or config.get('email', '') or user_email
        self.install_id = install_config.get('install_id', '')
        self.tier = install_config.get('tier', 'Trial')
        self.license_key = ""

        # Determine if we should verify subscription
        should_verify = self.user_email and "@" in self.user_email and not self.user_email.startswith("trial@")

        # Production cloud sync
        if self.env == 'production':
            try:
                self.cloud_db = CloudDatabaseManager(log_info, log_error)
                if should_verify:
                    hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                    cloud_install = self.cloud_db.get_install_by_hashed_email(hashed_email)
                    if cloud_install:
                        self.install_id = cloud_install['install_id']
                        self.tier = cloud_install['tier']
                        self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                        save_install_info(self.user_email, self.install_id, self.tier)
                        self.log_info(f"Synced install from cloud: {self.user_email}, ID: {self.install_id}, Tier: {self.tier}")
                    else:
                        self.log_info(f"No cloud record found for {self.user_email}, using local data")
            except Exception as e:
                self.log_error(f"Cloud sync failed: {e}")
                self.cloud_db = None
        # Skip verification if no email — user remains in Trial mode
        if should_verify:
            try:
                self.tier, self.license_key = self.stripe_service.verify_subscription(self.user_email, self.tier, self.install_id)
                if self.tier != install_config.get('tier'):
                    hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                    self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                    save_install_info(self.user_email, self.install_id, self.tier)
                    if self.cloud_db:
                        self.cloud_db.update_install_tier(hashed_email, self.tier)
                    self.log_info(f"Updated tier to {self.tier} for {self.user_email}")
            except Exception as e:
                self.log_error(f"Failed to verify subscription: {e}")
                self.tier = "Trial"
                self.license_key = ""

        # If no email, we prompt in GUI — not here
        if not self.user_email:
            self.log_info("No email detected — starting in Trial mode.")


        self.telegram_service = None
        self.sio = socketio.Client()
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
        bind_updater_methods(self)
        self.log_info("bind_updater_methods completed")

        # Connect timer
        self.timer.timeout.connect(self.update_timer_display)

        # Load settings from database
        try:
            settings = self.bidder_manager.get_settings(self.user_email)
            if settings:
                self.chat_id = settings.get("chat_id", self.chat_id)
                self.top_buyer_text = settings.get("top_buyer_text", self.top_buyer_text)
                self.giveaway_announcement_text = settings.get("giveaway_announcement_text", self.giveaway_announcement_text)
                self.flash_sale_announcement_text = settings.get("flash_sale_announcement_text", self.flash_sale_announcement_text)
                self.multi_buyer_mode = settings.get("multi_buyer_mode", self.multi_buyer_mode)
                self.log_info(f"Retrieved settings: {settings}")
        except Exception as e:
            self.log_error(f"Failed to load settings: {e}")

        self.log_info(f"Initialized user {self.user_email}: tier={self.tier}, license={self.license_key}")

        # Setup connections and shortcuts
        self.setup_connections()
        self.setup_shortcuts()
        self.show()
        self.raise_()
        try:
            settings = self.bidder_manager.get_settings(self.user_email)
            if settings:
                self.chat_id = settings.get("chat_id", self.chat_id)
                self.top_buyer_text = settings.get("top_buyer_text", self.top_buyer_text)
                self.giveaway_announcement_text = settings.get("giveaway_announcement_text", self.giveaway_announcement_text)
                self.flash_sale_announcement_text = settings.get("flash_sale_announcement_text", self.flash_sale_announcement_text)
                self.multi_buyer_mode = settings.get("multi_buyer_mode", self.multi_buyer_mode)
                self.log_info(f"Retrieved settings: {settings}")
        except Exception as e:
            self.log_error(f"Failed to load settings: {e}")

        self.log_info(f"Initialized user {self.user_email}: tier={self.tier}, license={self.license_key}")
  
    def prompt_for_email(self):
        """Show dialog to collect user email."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Enter Email")
        layout = QVBoxLayout()
        label = QLabel("Please enter your email address:")
        email_input = QLineEdit()
        submit_button = QPushButton("Submit")
        layout.addWidget(label)
        layout.addWidget(email_input)
        layout.addWidget(submit_button)
        dialog.setLayout(layout)

        def on_submit():
            email = email_input.text().strip()
            if '@' in email:
                dialog.accept()
                return email
            else:
                label.setText("Invalid email address. Please try again:")


    def open_mailing_list_dialog(self):
        from gui_mailing_list import MailingListWindow

        dialog = MailingListWindow(self)
        dialog.exec()
 
    def register_install(self):
        """Register install with backend and save response."""
        try:
            base_url = get_config_value("APP_BASE_URL")
            response = requests.post(f"{self.base_url}/register-install", json={"email": self.user_email})
            if response.status_code == 200:
                data = response.json()
                self.install_id = data["install_id"]
                self.tier = data["tier"]
                save_install_info(self.user_email, self.install_id, self.tier)
                self.log_info(f"Registered install: email={self.user_email}, install_id={self.install_id}, tier={self.tier}")
            else:
                self.log_error(f"Install registration failed: {response.json()}")
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
            self.export_csv_button.clicked.connect(self.export_csv)
        if hasattr(self, "toggle_tabs_btn"):
            self.toggle_tabs_btn.clicked.connect(self.toggle_settings_tabs)
        if hasattr(self, "update_btn"):
            self.update_btn.clicked.connect(self.check_for_updates)
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
        """Stop the timer and close database when closing the window."""
        if self.timer.isActive():
            self.timer.stop()
        if self.stripe_service and self.stripe_service.db_manager:
            self.stripe_service.db_manager.close()
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
        """Build Subscription tab UI."""
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
        tiers = ["Trial", "Bronze", "Silver", "Gold"]
        self.tier_combo.addItems(tiers)
        self.tier_combo.setCurrentText(self.tier)
        subscription_layout.addWidget(self.tier_combo, 0, 1)
        try:
            r = requests.get(f"{self.base_url}/subscription-status", params={"email": self.user_email}, timeout=5)
            if r.ok:
                data = r.json()
                status = data.get("status", "N/A")
                next_billing = data.get("next_billing_date", "N/A")
            else:
                status, next_billing = "N/A", "N/A"
        except Exception as e:
            self.log_error(f"Failed to fetch subscription status: {e}")
            status, next_billing = "N/A", "N/A"
        subscription_layout.addWidget(QLabel(f"Status: {status}"), 1, 0)
        subscription_layout.addWidget(QLabel(f"Next Billing: {next_billing}"), 1, 1)
        upgrade_button = QPushButton("Upgrade")
        upgrade_button.setObjectName("upgradeButton")
        upgrade_button.clicked.connect(self.on_upgrade)
        subscription_layout.addWidget(upgrade_button, 2, 0)
        downgrade_button = QPushButton("Downgrade")
        downgrade_button.setObjectName("downgradeButton")
        downgrade_button.clicked.connect(self.on_downgrade)
        subscription_layout.addWidget(downgrade_button, 2, 1)
        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("cancelButton")
        cancel_button.clicked.connect(self.on_cancel)
        subscription_layout.addWidget(cancel_button, 3, 0, 1, 2)
        layout.addWidget(subscription_group)
        layout.addStretch(1)
        self.log_info("Subscription tab initialized")

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
            self.update_bins_used_display()  # <- THIS updates the "Bins Used: X/Y" label

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

            # Ensure the order of insertion respects the incoming bidders dict
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
            # NOTE: Do NOT re-enable Qt sorting here — it will override our custom order
            # self.bidders_tree.setSortingEnabled(True)

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
            self.header_label.setText(f"SwiftSale - {self.user_email} ({self.tier}) | Build Whatnot Orders in Realtime")

            # Footer: Tier, Install ID, and latest bin
            self.footer_label.setText(f"{shield} {self.tier} | Install ID: {self.install_id} | Latest Bin: {self.latest_bin_assignment}")
            self.footer_label.setStyleSheet(f"color: {color}")
            self.footer_label.setToolTip(f"Install ID: {self.install_id} – {self.tier} Tier")

            # Settings tab license label
            if hasattr(self, "license_status_label"):
                self.license_status_label.setText(f"{shield} License Verified – {self.tier} Tier")
                self.license_status_label.setStyleSheet(f"color: {color}")
                self.license_status_label.setToolTip(f"Install ID: {self.install_id}")

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

    def setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+B"), self, self.add_bidder)
        QShortcut(QKeySequence("Ctrl+C"), self, self.clear_username)

        dev_shortcut = QShortcut(QKeySequence("Ctrl+Alt+D"), self)
        dev_shortcut.activated.connect(self.open_dev_code_dialog)
        self.log_info("Keyboard shortcuts set up")

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

if __name__ == "__main__":
    from main_qt import main
    app = QApplication(sys.argv)
    try:
        with open(get_resource_path("style.qss"), "r") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        logging.error(f"Failed to load stylesheet: {e}")
    main()