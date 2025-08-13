# -*- coding: utf-8 -*-
import os
import json
from PySide6.QtWidgets import QMessageBox
from config_qt import DEFAULT_DATA_DIR

_UI_PREFS_FILE = os.path.join(DEFAULT_DATA_DIR, "ui_prefs.json")
_UI_PREFS_KEY = "bidders_tree_visible"  # True/False


def _load_ui_prefs() -> dict:
    try:
        if not os.path.exists(_UI_PREFS_FILE):
            return {}
        with open(_UI_PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_ui_prefs(prefs: dict) -> None:
    try:
        os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)
        with open(_UI_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        # Non-fatal; don't block UI on prefs write failure
        pass


def apply_treeview_pref(self):
    """
    Apply the saved visibility preference to the bidders tree (if widgets exist).
    Safe to call anytime; no-op if UI isn't ready yet.
    """
    try:
        if not hasattr(self, "tree_frame") or not hasattr(self, "toggle_button"):
            return
        prefs = _load_ui_prefs()
        visible = prefs.get(_UI_PREFS_KEY, True)
        self.tree_frame.setVisible(bool(visible))
        # Use U+2212 (minus) so it matches the existing style
        self.toggle_button.setText("−" if visible else "+")
        self.toggle_button.setToolTip("Hide bidders list" if visible else "Show bidders list")
        self.log_info(f"Applied bidders table visibility from prefs: {visible}")
    except Exception as e:
        # Best-effort; never crash here
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to apply treeview preference: {e}")


def toggle_treeview(self):
    """Toggle the visibility of the bidders table and persist the preference."""
    try:
        if not hasattr(self, "tree_frame") or not hasattr(self, "toggle_button"):
            if hasattr(self, "log_error"):
                self.log_error("toggle_treeview: required UI elements not found")
            return

        new_visible = not self.tree_frame.isVisible()
        self.tree_frame.setVisible(new_visible)
        self.toggle_button.setText("−" if new_visible else "+")
        self.toggle_button.setToolTip("Hide bidders list" if new_visible else "Show bidders list")

        # Persist preference
        prefs = _load_ui_prefs()
        prefs[_UI_PREFS_KEY] = bool(new_visible)
        _save_ui_prefs(prefs)

        if hasattr(self, "log_info"):
            self.log_info(f"Bidders table visibility: {new_visible}")
    except Exception as e:
        if hasattr(self, "log_error"):
            self.log_error(f"Failed to toggle bidders table: {e}")


def _schedule_apply(gui):
    """
    Schedule a one-shot application of the saved preference.
    This runs after the event loop starts, ensuring widgets exist.
    """
    try:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: apply_treeview_pref(gui))
    except Exception:
        # If QTimer import fails for any reason, ignore silently.
        pass


def bind_toggle_methods(gui):
    """Bind toggle-related methods to the GUI instance and apply saved state."""
    gui.toggle_treeview = toggle_treeview.__get__(gui, gui.__class__)
    gui.apply_treeview_pref = apply_treeview_pref.__get__(gui, gui.__class__)
    _schedule_apply(gui)
