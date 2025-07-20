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

def bind_updater_methods(gui):
    """Bind only the version check to the GUI instance."""
    gui.check_for_updates = check_for_updates.__get__(gui, gui.__class__)
