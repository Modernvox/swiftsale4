from PySide6.QtWidgets import QMessageBox, QFileDialog, QTableWidgetItem, QTreeWidgetItem
from PySide6.QtCore import Qt
from datetime import datetime, timezone
import sqlite3
import csv
import shutil

def add_bidder(self):
    """Add a bidder with the specified username, quantity, and optional giveaway/weight."""
    username = self.username_entry.text().strip()
    qty_text = self.qty_entry.text().strip()
    weight_text = self.weight_entry.text().strip()
    is_giveaway = self.giveaway_var.isChecked()

    if not username:
        QMessageBox.warning(self, "Error", "Username is required")
        return

    try:
        qty = int(qty_text) if qty_text else 1
        weight = float(weight_text) if weight_text else None
    except ValueError:
        QMessageBox.warning(self, "Error", "Invalid quantity or weight")
        return

    try:
        # ✅ Detect duplicate BEFORE adding
        is_duplicate = hasattr(self, "last_added_username") and self.last_added_username == username

        result = self.bidder_manager.add_bidder(
            username=username,
            qty=qty,
            weight=weight,
            is_giveaway=is_giveaway
        )

        bin_number = result[0] if isinstance(result, tuple) else result
        self.log_info(f"bidder_manager.add_bidder returned bin_number: {bin_number}, type: {type(bin_number)}")

        if not isinstance(qty, int):
            self.log_error(f"Quantity is not an integer: {qty}, type: {type(qty)}")
            raise ValueError("Quantity must be an integer")

        if not isinstance(bin_number, int):
            self.log_error(f"bin_number is not an integer: {bin_number}, type: {type(bin_number)}")
            raise ValueError("Bin number must be an integer")

        self.latest_bin_assignment = f"{username}: Bin {bin_number}"
        self.update_bins_used_display()
        self.update_latest_bidder_display()
        self.populate_bidders_tree()

        if self.telegram_service and self.chat_id:
            self.telegram_service.send_message(self.chat_id, f"New bidder: {username} | Bin: {bin_number}")

        self.log_info(f"Added bidder: {username}, Bin: {bin_number}, Qty: {qty}, Giveaway: {is_giveaway}, Weight: {weight}")

        # ✅ Update button color based on duplicate
        if is_duplicate:
            self.add_bidder_button.setStyleSheet("background-color: yellow; font-weight: bold; color: black;")
        else:
            self.add_bidder_button.setStyleSheet("background-color: lightgreen; font-weight: bold; color: black;")

        # ✅ Store last username
        self.last_added_username = username

    except Exception as e:
        self.log_error(f"Failed to add bidder: {e}")
        QMessageBox.critical(self, "Error", f"Failed to add bidder: {e}")


def clear_bidders(self):
    """Clear all bidders from the database, reset bidder_manager, and update UI."""
    reply = QMessageBox.question(
        self, "Confirm Clear", "Are you sure you want to clear all bidders? This action cannot be undone.",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply == QMessageBox.Yes:
        try:
            # Call bidder_manager.clear_bidders to clear bidders and bin_assignments
            self.bidder_manager.clear_all_bidders()

            # Reset UI elements
            self.latest_bin_assignment = "Waiting for bidder..."
            self.bidders_tree.clear()
            self.update_bins_used_display()
            self.update_top_buyers()  # Reset top buyers display
            self.update_latest_bidder_display()
            
            self.latest_bidder_label.setText("Latest: None")
            self.bin_number_label.setText("")

            # Clear any cached top_buyers in GUI if it exists
            if hasattr(self, "top_buyers"):
                self.top_buyers = []

            self.update_header_and_footer()
            self.log_info("Cleared all bidders and top buyers from database")
            QMessageBox.information(self, "Success", "All bidders cleared successfully")
        except Exception as e:
            self.log_error(f"Failed to clear bidders: {e}")
            QMessageBox.critical(self, "Error", f"Failed to clear bidders: {e}")


def import_csv(self):
    """Import bidders from a CSV file."""
    file_name, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)")
    if file_name:
        try:
            self.bidder_manager.import_csv(file_name)
            self.populate_bidders_tree()
            self.update_bins_used_display()
            self.update_top_buyers()
            self.log_info(f"Imported bidders from {file_name}")
            QMessageBox.information(self, "Success", "Bidders imported successfully")
        except Exception as e:
            self.log_error(f"Failed to import CSV: {e}")
            QMessageBox.critical(self, "Error", f"Failed to import CSV: {e}")

def export_csv(self):
    """Export bidders to a CSV file."""
    file_name, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
    if file_name:
        try:
            file_path = self.bidder_manager.export_csv()
            shutil.move(file_path, file_name)  # Move to user-selected location
            self.log_info(f"Exported bidders to {file_name}")
            QMessageBox.information(self, "Success", "Bidders exported successfully")
        except Exception as e:
            self.log_error(f"Failed to export CSV: {e}")
            QMessageBox.critical(self, "Error", f"Failed to export CSV: {e}")

def bind_bidders_methods(gui):
    """Bind bidder-related methods to the GUI instance."""
    gui.add_bidder = add_bidder.__get__(gui, gui.__class__)
    gui.clear_bidders = clear_bidders.__get__(gui, gui.__class__)
    gui.import_csv = import_csv.__get__(gui, gui.__class__)
    gui.export_csv = export_csv.__get__(gui, gui.__class__)