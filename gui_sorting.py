from collections import OrderedDict
from PySide6.QtWidgets import QMessageBox

def _safe_int(val):
    try:
        return int(val)
    except Exception:
        return None

def _capture_tree_state(tree):
    """Grab expanded parents, selected parents, and scroll position."""
    expanded, selected = set(), set()
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        name = item.text(0)
        if item.isExpanded():
            expanded.add(name)
        if item.isSelected():
            selected.add(name)
    vpos = tree.verticalScrollBar().value()
    return expanded, selected, vpos

def _restore_tree_state(tree, expanded, selected, vpos):
    """Re-apply expanded/selected state and scroll position."""
    try:
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            name = item.text(0)
            item.setExpanded(name in expanded)
            item.setSelected(name in selected)
        tree.verticalScrollBar().setValue(vpos)
    except Exception:
        # Best-effort; don't crash on restore issues
        pass

def _sorted_bidders_by_bin(bidders_dict, descending=False):
    """
    Return an OrderedDict of bidders sorted by bin.
    • Valid bin numbers first, then None (no bin yet).
    • For ties, keep original order (stable sort).
    """
    def key_fn(item):
        # item: (username_key, info)
        info = item[1] or {}
        raw_bin = info.get("bin", None)
        bin_num = _safe_int(raw_bin)
        # (no_bin_flag, bin_sort_value)
        if descending:
            # Valid bins first; larger bin numbers earlier
            return (bin_num is None, -(bin_num or 0))
        else:
            # Valid bins first; smaller bin numbers earlier
            return (bin_num is None, (bin_num or 0))

    # Python's sort is stable; preserve original order for ties
    sorted_items = sorted(bidders_dict.items(), key=key_fn)
    return OrderedDict(sorted_items)

def sort_bins_ascending(self):
    """Sort bidders by bin ascending; preserve UI state."""
    try:
        if not hasattr(self.bidder_manager, "bidders") or not isinstance(self.bidder_manager.bidders, dict):
            self.log_error("Cannot sort: bidder_manager.bidders missing or not a dict")
            return

        expanded, selected, vpos = _capture_tree_state(self.bidders_tree)
        sorted_dict = _sorted_bidders_by_bin(self.bidder_manager.bidders, descending=False)
        self.populate_bidders_tree(bidders=sorted_dict)
        _restore_tree_state(self.bidders_tree, expanded, selected, vpos)

        self.log_info("Sorted bidders by bin (ascending)")
    except Exception as e:
        self.log_error(f"Failed to sort bidders ascending: {e}")

def sort_bins_descending(self):
    """Sort bidders by bin descending; preserve UI state."""
    try:
        if not hasattr(self.bidder_manager, "bidders") or not isinstance(self.bidder_manager.bidders, dict):
            self.log_error("Cannot sort: bidder_manager.bidders missing or not a dict")
            return

        expanded, selected, vpos = _capture_tree_state(self.bidders_tree)
        sorted_dict = _sorted_bidders_by_bin(self.bidder_manager.bidders, descending=True)
        self.populate_bidders_tree(bidders=sorted_dict)
        _restore_tree_state(self.bidders_tree, expanded, selected, vpos)

        self.log_info("Sorted bidders by bin (descending)")
    except Exception as e:
        self.log_error(f"Failed to sort bidders descending: {e}")

def bind_sorting_methods(gui):
    """Bind tree-based sorting methods to the GUI instance."""
    gui.sort_bins_ascending = sort_bins_ascending.__get__(gui, gui.__class__)
    gui.sort_bins_descending = sort_bins_descending.__get__(gui, gui.__class__)
