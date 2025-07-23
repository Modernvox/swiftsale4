from cloud_database_qt import CloudDatabaseManager
from PySide6.QtWidgets import QMessageBox, QApplication, QInputDialog, QProgressDialog
import sqlite3
from gui_help_qt import (
    show_telegram_help,
    show_import_csv_help,
    show_export_csv_help, 
    show_sort_bin_desc_help,
    show_clear_bidders_help,
    show_top_buyer_help,
    show_flash_sale_text_help
)
import hashlib
import threading
import time
import os

def start_giveaway(self):
    """Copy the giveaway message from settings to clipboard."""
    if hasattr(self, "giveaway_entry"):
        message = self.giveaway_entry.text().strip()
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
        message = self.flash_sale_entry.text().strip()
        if message:
            QApplication.clipboard().setText(message)
            self.log_info(f"Copied flash sale message: {message}")
            self.show_temporary_message("Copied to Clipboard")
        else:
            self.log_error("No flash sale message set.")
    else:
        self.log_error("Flash sale input field not found.")

def get_avg_sell_rate(self):
    """Calculate average sell rate based on bidder data."""
    try:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT timestamp, quantity FROM bidders
            WHERE timestamp IS NOT NULL
            ORDER BY timestamp ASC
        """)
        rows = cursor.fetchall()
        if not rows or len(rows) < 2 or not self.show_start_time:
            return (0.0, 0.0, 0.0, 0.0, 0.0)

        total_items = sum(int(qty) for _, qty in rows)
        end_ts = int(rows[-1][0])
        duration_sec = max(end_ts - int(self.show_start_time), 1)

        items_per_minute = total_items / (duration_sec / 60)
        items_per_hour = items_per_minute * 60

        return (
            items_per_hour,
            items_per_minute,
            items_per_hour * 2,
            items_per_hour * 3,
            items_per_hour * 4
        )
    except Exception as e:
        self.log_error(f"Sell rate calculation error: {e}")
        return (0.0, 0.0, 0.0, 0.0, 0.0)

def show_avg_sell_rate(self, show_message=True):
    """Display average sell rate in the UI and optionally show a message box."""
    if not self.bidder_manager.show_start_time:
        if show_message:
            QMessageBox.warning(self, "Warning", "Please click 'Start Show' first.")
        self.stats_label.setText("Average Sell Rate: N/A")
        self.log_info("Sell rate not available: Show not started")
        return

    rates = self.bidder_manager.get_avg_sell_rate()
    items_per_hour, items_per_minute, projected_2h, projected_3h, projected_4h = rates

    if items_per_minute > 0:
        detailed_text = (
            f"Current sell rate is {items_per_minute:.2f}/min "
            f"estimated {int(round(items_per_hour))} per hour, "
            f"{int(round(projected_3h))}/3hr show, {int(round(projected_4h))}/4hr show"
        )
        concise_text = f"Sell Rate: {items_per_minute:.2f}/min, {int(round(items_per_hour))}/hr"

        if show_message:
            QMessageBox.information(self, "Sell Rate", detailed_text)
    else:
        concise_text = "Average Sell Rate: N/A"
        detailed_text = "No valid transactions for sell rate."
        if show_message:
            QMessageBox.warning(self, "Warning", detailed_text)

    self.stats_label.setText(concise_text)
    self.log_info(f"Updated sell rate: {concise_text}")

def copy_top_buyer_message(self, event):
    """Copy the top buyer message to the clipboard."""
    self.log_info("Entering copy_top_buyer_message")
    try:
        top_buyers = self.bidder_manager.get_top_buyers()
        self.log_info(f"Retrieved top_buyers: {top_buyers}")
        if not top_buyers:
            self.log_info("No top buyers found (empty list)")
            QMessageBox.warning(self, "Warning", "No top buyers found")
            return
        if not isinstance(top_buyers, (list, tuple)):
            self.log_error(f"Invalid top_buyers format: expected list/tuple, got {type(top_buyers)}, data: {top_buyers}")
            QMessageBox.warning(self, "Warning", "No top buyers found")
            return
        for buyer in top_buyers:
            if not isinstance(buyer, (list, tuple)) or len(buyer) != 2:
                self.log_error(f"Invalid buyer format: expected (name, count), got {buyer}")
                QMessageBox.warning(self, "Warning", "No top buyers found")
                return
        username, qty = top_buyers[0]
        message = self.top_buyer_text.format(username=username, qty=qty) if self.top_buyer_text else f"{username} ({qty})"
        clipboard = QApplication.clipboard()
        clipboard.setText(message)
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
    current_username = self.username_entry.text().strip()
    if hasattr(self, "last_added_username") and current_username == self.last_added_username:
        self.add_bidder_button.setStyleSheet("background-color: yellow; font-weight: bold;")
    else:
        self.add_bidder_button.setStyleSheet("background-color: green; font-weight: bold;")

    self._last_seen_username = current_username

def open_dev_code_dialog(self):
    """Prompt user to enter the developer unlock code."""
    code, ok = QInputDialog.getText(self, "Enter Dev Code", "Enter Developer Code:")
    if not (ok and code.strip()):
        return

    code = code.strip().lower()
    install_id = self.install_id or "unknown-device"

    # ✅ Local fallback codes always accepted (TEMP override here)
    local_fallback_codes = {
        "devoffline": {"tier": "Gold", "license_key": "DEV_MODE"},
        "letmein": {"tier": "Gold", "license_key": "DEV_MODE"},
        "brandi9933": {"tier": "Gold", "license_key": "DEV_MODE"},
        "9933": {"tier": "Gold", "license_key": "DEV_MODE"},  # TEMPORARY override
    }

    if code in local_fallback_codes:
        self.dev_access_granted = True
        self.tier = local_fallback_codes[code]["tier"]
        self.license_key = local_fallback_codes[code]["license_key"]

        self.log_info(f"Offline dev code used – {code} | install_id={install_id}")
        QMessageBox.information(self, "Access Granted", f"Developer access enabled – {self.tier} Tier.")
        self.update_subscription_ui()
        self.update_header_and_footer()
        self.refresh_bin_usage_display()
        return

    try:
        result = validate_remote_dev_code(code)
        self.dev_access_granted = True
        self.tier = result["tier"]
        self.license_key = result["license_key"]
        self.log_info(f"Dev code validated via DB – {code} | {result['email']} | install_id={install_id}")
        QMessageBox.information(self, "Access Granted", f"Developer access enabled – {self.tier} Tier.")
        self.update_subscription_ui()
        self.update_header_and_footer()
        self.refresh_bin_usage_display()
    except Exception as e:
        self.log_error(f"Dev unlock failed: {e}")
        QMessageBox.warning(self, "Access Denied", str(e))


def get_dev_db_connection():
    return psycopg2.connect(
        dbname='swiftsaleapp4_db',
        user='dev_reader',
        password='OnlyCheckDevCodes123!',  # Replace with your actual safe password
        host='dpg-d1qaevvfte5s73d4h9ng-a.ohio-postgres.render.com',
        port='5432',
        sslmode='require'
    )

def validate_remote_dev_code(code: str) -> dict:
    with get_dev_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, expires_at, used, assigned_to, device_id, tier, license_key, frozen
                FROM dev_codes
                WHERE code = %s
            """, (code,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Invalid or unrecognized developer code.")

            email, expires_at, used, assigned_to, bound_device, tier, license_key, frozen = row

            if used:
                raise ValueError("Code already used.")
            if frozen:
                raise ValueError("Code is frozen.")
            if expires_at and datetime.utcnow() > expires_at:
                raise ValueError("Code expired.")

            return {
                "tier": tier or "Gold",
                "license_key": license_key or "DEV_MODE",
                "email": email or "dev@swiftsaleapp.com"
            }

def on_upgrade(self):
    """Handle clicking the Upgrade button in the Subscription tab with real-time refresh."""
    new_tier = self.tier_combo.currentText()
    if new_tier == self.tier:
        QMessageBox.information(self, "Info", f"You are already on the {new_tier} tier.")
        return

    if not self.user_email or not self.license_key:
        if self.is_dev_mode:
            QMessageBox.information(self, "Dev Mode", "Upgrade skipped — running in dev mode.")
            self.log_info("Dev mode: Skipping upgrade due to missing email or license key.")
            return
        else:
            QMessageBox.critical(self, "Error", "Missing email or license key.")
            return

    try:
        self.log_info(f"Creating Stripe checkout session for {self.user_email} upgrading to {new_tier}")
        response, status = self.stripe_service.create_checkout_session(
            tier=new_tier,
            user_email=self.user_email,
            request_url_root="https://swiftsale4.onrender.com/"
        )

        if status == 200 and response.get("url"):
            checkout_url = response["url"]
            import webbrowser
            webbrowser.open(checkout_url)
            self.log_info(f"Opened Stripe Checkout URL: {checkout_url}")

            QMessageBox.information(
                self, "Upgrade",
                "Stripe Checkout has opened in your browser.\n\nWe'll check your upgrade status shortly."
            )

            # Show loading dialog
            self.polling_dialog = QProgressDialog("Verifying upgrade...", None, 0, 0, self)
            self.polling_dialog.setWindowTitle("Please Wait")
            self.polling_dialog.setCancelButton(None)
            self.polling_dialog.setWindowModality(Qt.ApplicationModal)
            self.polling_dialog.setMinimumDuration(0)
            self.polling_dialog.setAutoClose(False)
            self.polling_dialog.show()

            # Start polling in background
            threading.Thread(
                target=self._poll_subscription_status,
                args=(new_tier,),
                daemon=True
            ).start()

        else:
            error_msg = response.get("error", "Upgrade failed: No checkout URL returned.")
            self.log_error(f"Stripe checkout creation failed: {error_msg}")
            QMessageBox.critical(self, "Error", error_msg)

    except Exception as e:
        self.log_error(f"Upgrade error: {e}")
        QMessageBox.critical(self, "Error", f"Failed to upgrade subscription: {e}")

def _poll_subscription_status(self, expected_tier, max_retries=24, delay=5):
    """Poll Stripe for subscription status every few seconds until upgraded or timeout."""
    self.log_info(f"🔁 Polling subscription status for upgrade to {expected_tier}")

    try:
        for attempt in range(max_retries):
            time.sleep(delay)
            status, _ = self.stripe_service.get_subscription_status(self.license_key)

            if status and status.lower() == expected_tier.lower():
                self.tier = expected_tier
                self.log_info(f"✅ Upgrade confirmed: {self.tier}")
                save_install_info(self.user_email, self.install_id, self.tier)

                # Local DB update
                self.bidder_manager.update_install(
                    hashlib.sha256(self.user_email.encode()).hexdigest(),
                    self.install_id,
                    self.tier
                )

                # Cloud DB update
                if self.cloud_db:
                    self.cloud_db.update_install_tier(
                        hashlib.sha256(self.user_email.encode()).hexdigest(),
                        self.tier
                    )

                # Finalize with Stripe backend
                try:
                    self.stripe_service.upgrade_subscription(
                        user_email=self.user_email,
                        new_tier=expected_tier,
                        license_key=self.license_key
                    )
                except Exception as e:
                    self.log_error(f" Stripe upgrade_subscription failed: {e}")

                QTimer.singleShot(0, self.update_subscription_ui)
                QTimer.singleShot(0, lambda: self.polling_dialog.cancel())
                QTimer.singleShot(0, lambda: self.show_temporary_message(f" Subscription upgraded to {self.tier}"))
                return

        self.log_info("⌛ Upgrade not detected after polling timeout.")
        QTimer.singleShot(0, lambda: self.polling_dialog.cancel())

    except Exception as e:
        tb = traceback.format_exc()
        self.log_error(f" _poll_subscription_status failed:\n{tb}")
        QTimer.singleShot(0, lambda: self.polling_dialog.cancel())
        QTimer.singleShot(0, lambda: QMessageBox.critical(self, "Upgrade Error", f"An error occurred:\n{str(e)}"))

def on_downgrade(self):
    """Handle clicking the Downgrade button in the Subscription tab."""
    new_tier = self.tier_combo.currentText()
    if new_tier == self.tier:
        QMessageBox.information(self, "Info", f"You are already on the {new_tier} tier.")
        return
    try:
        success = self.stripe_service.downgrade_subscription(self.user_email, self.tier, new_tier, self.license_key)
        if success:
            self.tier = new_tier
            hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
            self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
            save_install_info(self.user_email, self.install_id, self.tier)
            if self.cloud_db:
                self.cloud_db.update_install_tier(hashed_email, self.tier)
            self.log_info(f"Downgraded subscription to {new_tier} for {self.user_email}")
            QMessageBox.information(self, "Success", f"Subscription downgraded to {new_tier}!")
            self.update_subscription_ui()
        else:
            self.log_error(f"Failed to downgrade subscription to {new_tier} for {self.user_email}")
            QMessageBox.critical(self, "Error", "Failed to downgrade subscription. Please try again or contact support.")
    except Exception as e:
        self.log_error(f"Unexpected error downgrading subscription to {new_tier}: {e}")
        QMessageBox.critical(self, "Error", f"Unexpected error: {str(e)}")

def on_cancel(self):
    """Handle clicking the Cancel button in the Subscription tab."""
    confirm = QMessageBox.question(
        self,
        "Confirm Cancellation",
        "Are you sure you want to cancel your subscription? You will revert to the Trial tier.",
        QMessageBox.Yes | QMessageBox.No
    )
    if confirm == QMessageBox.Yes:
        try:
            success = self.stripe_service.cancel_subscription(self.user_email, self.license_key)
            if success:
                self.tier = "Trial"
                hashed_email = hashlib.sha256(self.user_email.encode()).hexdigest()
                self.bidder_manager.update_install(hashed_email, self.install_id, self.tier)
                save_install_info(self.user_email, self.install_id, self.tier)
                if self.cloud_db:
                    self.cloud_db.update_install_tier(hashed_email, "free")
                self.log_info(f"Cancelled subscription for {self.user_email}")
                QMessageBox.information(self, "Success", "Subscription cancelled. Reverted to Trial tier.")
                self.update_subscription_ui()
            else:
                self.log_error(f"Failed to cancel subscription for {self.user_email}")
                QMessageBox.critical(self, "Error", "Failed to cancel subscription. Please try again or contact support.")
        except Exception as e:
            self.log_error(f"Unexpected error cancelling subscription: {e}")
            QMessageBox.critical(self, "Error", f"Unexpected error: {str(e)}")

def update_subscription_ui(self):
    """Update the Subscription tab and header/footer labels with current subscription info."""
    if hasattr(self, "header_label"):
        self.header_label.setText(f"SwiftSale - {self.user_email} ({self.tier})")
    if hasattr(self, "footer_label") and hasattr(self, "status_label") and hasattr(self, "next_billing_label"):
        status, next_billing = self.stripe_service.get_subscription_status(self.license_key)
        self.status_label.setText(f"Status: {status}")
        self.next_billing_label.setText(f"Next Billing: {next_billing}")
        self.footer_label.setText(f"Status: {status} | Next Billing: {next_billing}")

def bind_event_methods(gui):
    """Bind event-related methods to the GUI instance."""
    gui.start_giveaway = start_giveaway.__get__(gui, gui.__class__)
    gui.start_flash_sale = start_flash_sale.__get__(gui, gui.__class__)
    gui.get_avg_sell_rate = get_avg_sell_rate.__get__(gui, gui.__class__)
    gui.show_avg_sell_rate = show_avg_sell_rate.__get__(gui, gui.__class__)
    gui.copy_top_buyer_message = copy_top_buyer_message.__get__(gui, gui.__class__)
    gui.on_username_changed = on_username_changed.__get__(gui, gui.__class__)
    gui.open_dev_code_dialog = open_dev_code_dialog.__get__(gui, gui.__class__)
    gui.on_upgrade = on_upgrade.__get__(gui, gui.__class__)
    gui.on_downgrade = on_downgrade.__get__(gui, gui.__class__)
    gui.on_cancel = on_cancel.__get__(gui, gui.__class__)
    gui.update_subscription_ui = update_subscription_ui.__get__(gui, gui.__class__)

def bind_help_methods(gui):
    """Bind help button click events to their respective help functions."""
    gui.telegram_help_button.clicked.connect(lambda: show_telegram_help(gui))
    gui.export_csv_help_button.clicked.connect(lambda: show_export_csv_help(gui))
    gui.sort_bin_desc_help_button.clicked.connect(lambda: show_sort_bin_desc_help(gui))
    gui.clear_bidders_help_button.clicked.connect(lambda: show_clear_bidders_help(gui))
    gui.top_buyer_help_button.clicked.connect(lambda: show_top_buyer_help(gui))
    gui.flash_sale_text_help_button.clicked.connect(lambda: show_flash_sale_text_help(gui))