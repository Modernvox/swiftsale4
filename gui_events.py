from PySide6.QtWidgets import QMessageBox, QApplication
import sqlite3  # <- required for database error handling



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
        self.log_error(f"Unexpected error in copy_top_buyer_message: {e}", exc_info=True)
        QMessageBox.warning(self, "Warning", "No top buyers found")

def on_username_changed(self):
    current_username = self.username_entry.text().strip()
    if hasattr(self, "last_added_username") and current_username == self.last_added_username:
        self.add_bidder_button.setStyleSheet("background-color: yellow; font-weight: bold;")
    else:
        self.add_bidder_button.setStyleSheet("background-color: green; font-weight: bold;")

    # Track for next change event
    self._last_seen_username = current_username


def bind_event_methods(gui):
    """Bind event-related methods to the GUI instance."""
    gui.start_giveaway = start_giveaway.__get__(gui, gui.__class__)
    gui.start_flash_sale = start_flash_sale.__get__(gui, gui.__class__)
    gui.show_avg_sell_rate = show_avg_sell_rate.__get__(gui, gui.__class__)
    gui.copy_top_buyer_message = copy_top_buyer_message.__get__(gui, gui.__class__)
    gui.on_username_changed = on_username_changed.__get__(gui, gui.__class__)
