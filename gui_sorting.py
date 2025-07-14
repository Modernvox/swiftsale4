from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem
import sqlite3

def sort_bins_ascending(self):
    """Sort bidders by bin number ascending and update the tree widget."""
    try:
        cursor = self.bidder_manager.conn.cursor()
        cursor.execute("""
            SELECT b.username, b.quantity, ba.bin_number, b.is_giveaway, b.weight, b.last_assigned
            FROM bidders b
            LEFT JOIN bin_assignments ba ON b.username = ba.username
            ORDER BY ba.bin_number ASC
        """)
        bidders = cursor.fetchall()

        self.bidders_tree.clear()
        for row in bidders:
            uname, qty, bin_num, is_giveaway, weight, timestamp = row
            values = [
                uname,
                str(qty),
                str(bin_num) if bin_num is not None else "",
                "Yes" if is_giveaway else "No",
                weight or "",
                timestamp or ""
            ]
            item = QTreeWidgetItem(values)
            self.bidders_tree.addTopLevelItem(item)

        self.bidders_tree.resizeColumnToContents(0)
        self.log_info("Sorted bidders tree by bin ascending")

    except Exception as e:
        self.log_error(f"Failed to sort bidders tree: {e}")
        QMessageBox.critical(self, "Error", f"Failed to sort bidders tree: {e}")

def sort_bins_descending(self):
    """Sort bidders by bin number descending and update the tree widget."""
    try:
        cursor = self.bidder_manager.conn.cursor()
        cursor.execute("""
            SELECT b.username, b.quantity, ba.bin_number, b.is_giveaway, b.weight, b.last_assigned
            FROM bidders b
            LEFT JOIN bin_assignments ba ON b.username = ba.username
            ORDER BY ba.bin_number DESC
        """)
        bidders = cursor.fetchall()

        self.bidders_tree.clear()
        for row in bidders:
            uname, qty, bin_num, is_giveaway, weight, timestamp = row
            values = [
                uname,
                str(qty),
                str(bin_num) if bin_num is not None else "",
                "Yes" if is_giveaway else "No",
                weight or "",
                timestamp or ""
            ]
            item = QTreeWidgetItem(values)
            self.bidders_tree.addTopLevelItem(item)

        self.bidders_tree.resizeColumnToContents(0)
        self.log_info("Sorted bidders tree by bin descending")

    except Exception as e:
        self.log_error(f"Failed to sort bidders tree: {e}")
        QMessageBox.critical(self, "Error", f"Failed to sort bidders tree: {e}")

def bind_sorting_methods(gui):
    """Bind tree-based sorting methods to the GUI instance."""
    gui.sort_bins_ascending = sort_bins_ascending.__get__(gui, gui.__class__)
    gui.sort_bins_descending = sort_bins_descending.__get__(gui, gui.__class__)
