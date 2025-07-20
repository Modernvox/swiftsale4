from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem
import sqlite3

def sort_bins_ascending(self):
    try:
        sorted_items = sorted(self.bidder_manager.bidders.items(), key=lambda x: (x[1]["bin"] is None, x[1]["bin"]))
        sorted_dict = dict(sorted_items)
        self.populate_bidders_tree(bidders=sorted_dict)
        self.log_info("Sorted bidders by bin ascending")
    except Exception as e:
        self.log_error(f"Failed to sort bidders ascending: {e}")


def sort_bins_descending(self):
    try:
        sorted_items = sorted(self.bidder_manager.bidders.items(), key=lambda x: (x[1]["bin"] is None, -1 if x[1]["bin"] is None else -x[1]["bin"]))
        sorted_dict = dict(sorted_items)
        self.populate_bidders_tree(bidders=sorted_dict)
        self.log_info("Sorted bidders by bin descending")
    except Exception as e:
        self.log_error(f"Failed to sort bidders descending: {e}")

def bind_sorting_methods(gui):
    """Bind tree-based sorting methods to the GUI instance."""
    gui.sort_bins_ascending = sort_bins_ascending.__get__(gui, gui.__class__)
    gui.sort_bins_descending = sort_bins_descending.__get__(gui, gui.__class__)
