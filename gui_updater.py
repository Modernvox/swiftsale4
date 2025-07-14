from PySide6.QtWidgets import QMessageBox
import requests

def check_for_updates(self):
    """Check for software updates."""
    try:
        r = requests.get(f"{self.base_url}/version", timeout=5)
        if r.ok:
            latest_version = r.json().get("version", self.current_version)
            if latest_version > self.current_version:
                QMessageBox.information(self, "Update Available", f"New version {latest_version} is available. Please update.")
                self.log_info(f"Update available: {latest_version}")
            else:
                QMessageBox.information(self, "No Update", "You are running the latest version.")
                self.log_info("No update available")
        else:
            raise Exception("Failed to check version")
    except Exception as e:
        self.log_error(f"Failed to check for update: {e}")
        QMessageBox.critical(self, "Error", f"Failed to check for update: {e}")

def on_upgrade(self):
    """Handle subscription upgrade."""
    try:
        new_tier = self.tier_combo.currentText()
        if new_tier != self.tier:
            self.stripe_service.upgrade_subscription(self.user_email, new_tier)
            self.tier = new_tier
            self.bidder_manager.update_user_tier(self.user_email, new_tier)
            self.update_header_and_footer()
            QMessageBox.information(self, "Success", f"Upgraded to {new_tier} tier")
            self.log_info(f"Upgraded subscription to {new_tier}")
        else:
            QMessageBox.information(self, "Info", "Already on this tier")
    except Exception as e:
        self.log_error(f"Failed to upgrade subscription: {e}")
        QMessageBox.critical(self, "Error", f"Failed to upgrade subscription: {e}")

def on_downgrade(self):
    """Handle subscription downgrade."""
    try:
        new_tier = self.tier_combo.currentText()
        if new_tier != self.tier:
            self.stripe_service.downgrade_subscription(self.user_email, new_tier)
            self.tier = new_tier
            self.bidder_manager.update_user_tier(self.user_email, new_tier)
            self.update_header_and_footer()
            QMessageBox.information(self, "Success", f"Downgraded to {new_tier} tier")
            self.log_info(f"Downgraded subscription to {new_tier}")
        else:
            QMessageBox.information(self, "Info", "Already on this tier")
    except Exception as e:
        self.log_error(f"Failed to downgrade subscription: {e}")
        QMessageBox.critical(self, "Error", f"Failed to downgrade subscription: {e}")

def on_cancel(self):
    """Handle subscription cancellation."""
    reply = QMessageBox.question(self, "Confirm Cancel", "Are you sure you want to cancel your subscription?",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if reply == QMessageBox.Yes:
        try:
            self.stripe_service.cancel_subscription(self.user_email)
            self.tier = "Trial"
            self.bidder_manager.update_user_tier(self.user_email, "Trial")
            self.update_header_and_footer()
            QMessageBox.information(self, "Success", "Subscription cancelled")
            self.log_info("Cancelled subscription")
        except Exception as e:
            self.log_error(f"Failed to cancel subscription: {e}")
            QMessageBox.critical(self, "Error", f"Failed to cancel subscription: {e}")

def bind_updater_methods(gui):
    """Bind update and subscription-related methods to the GUI instance."""
    gui.check_for_updates = check_for_updates.__get__(gui, gui.__class__)
    gui.on_upgrade = on_upgrade.__get__(gui, gui.__class__)
    gui.on_downgrade = on_downgrade.__get__(gui, gui.__class__)
    gui.on_cancel = on_cancel.__get__(gui, gui.__class__)