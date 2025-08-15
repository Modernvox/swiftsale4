# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QMessageBox, QFileDialog
from PySide6.QtCore import Qt
from datetime import datetime
import csv
import shutil
import re
import time

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _sanitize_username(s: str) -> str:
    """Mirror the UI validator: keep letters/numbers/underscore; trim to 40."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^A-Za-z0-9_]", "", s).strip()[:40]


def _format_latest_assignment(username: str, bin_number, giveaway_num):
    if giveaway_num is not None:
        return f"{username}: Giveaway #{giveaway_num}"
    if isinstance(bin_number, int):
        return f"{username}: Bin {bin_number}"
    return f"{username}: (no bin)"


# -------------------------------------------------------------------
# Public: manual Add button handler
# -------------------------------------------------------------------
def add_bidder(self):
    """Add a bidder from the UI fields (manual mode) and return the assigned bin."""
    username_raw = self.username_entry.text().strip()
    username = _sanitize_username(username_raw)
    qty_text = self.qty_entry.text().strip()
    weight_text = self.weight_entry.text().strip()
    is_giveaway = self.giveaway_var.isChecked()

    if not username:
        QMessageBox.warning(self, "Error", "Username is required")
        return None

    try:
        qty = int(qty_text) if qty_text else 1
    except ValueError:
        QMessageBox.warning(self, "Error", "Invalid quantity")
        return None

    weight = weight_text if weight_text else None
    is_duplicate = getattr(self, "last_added_username", None) == username

    try:
        # Do the add (your existing core)
        result = _add_bidder_core(
            self,
            username=username,
            qty=qty,
            weight=weight,
            is_giveaway=is_giveaway,
            source="manual",
            original_username=username,
            auction_id=None,
            first_name=None,
        )

        # Determine the bin number from the result, with safe fallbacks
        bin_num = None
        try:
            if isinstance(result, tuple) and len(result) >= 1:
                bin_num = result[0]
            elif isinstance(result, dict):
                bin_num = result.get("bin") or result.get("bin_number")
            elif isinstance(result, int):
                bin_num = result
        except Exception:
            bin_num = None

        if bin_num is None:
            # Fallback: ask the manager (works because core just inserted/assigned)
            try:
                bin_num = self.bidder_manager.get_bin_for_username(username)
            except Exception:
                bin_num = None

        # Style feedback
        if is_duplicate:
            self.add_bidder_button.setStyleSheet(
                "background-color: yellow; font-weight: bold; color: black;"
            )
        else:
            self.add_bidder_button.setStyleSheet(
                "background-color: lightgreen; font-weight: bold; color: black;"
            )

        self.last_added_username = username

        # ✅ Make the bin available to the toast/clipboard flow
        self._last_assigned_bin = bin_num
        return bin_num

    except Exception as e:
        self.log_error(f"Failed to add bidder: {e}")
        QMessageBox.critical(self, "Error", f"Failed to add bidder: {e}")
        return None



# -------------------------------------------------------------------
# Public: Clear / Import / Export (unchanged behavior, sturdier logs)
# -------------------------------------------------------------------
def clear_bidders(self):
    """Clear all bidders from the database, reset bidder_manager, and update UI."""
    reply = QMessageBox.question(
        self,
        "Confirm Clear",
        "Are you sure you want to clear all bidders? This action cannot be undone.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return

    try:
        self.bidder_manager.clear_all_bidders()

        self.latest_bin_assignment = "Waiting for bidder..."
        self.bidders_tree.clear()
        self.update_bins_used_display()
        self.update_top_buyers()
        self.update_latest_bidder_display()

        self.latest_bidder_label.setText("Latest: None")
        self.bin_number_label.setText("")

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
    if not file_name:
        return
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


def export_csv(self, out_path: str) -> str:
    """
    Write bidders to CSV directly at out_path.
    Adjust the query/headers to match your schema.
    """
    import csv, os, sqlite3
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    try:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT username, bin_number
            FROM bin_assignments
            ORDER BY bin_number ASC
        """)
        rows = cur.fetchall()
    except sqlite3.Error as e:
        raise RuntimeError(f"DB read failed: {e}") from e

    headers = ["username", "bin_number"]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return out_path

# -------------------------------------------------------------------
# NEW: Auto-capture entry point (call this from your extension/SIO listener)
# -------------------------------------------------------------------
def add_bidder_from_capture(
    self,
    username: str,
    qty: int = 1,
    *,
    weight: str | None = None,
    is_giveaway: bool = False,
    original_username: str | None = None,
    first_name: str | None = None,
    auction_id: str | None = None,
):
    """
    Programmatic add (no blocking dialogs). Safe to call from a Socket.IO or local
    extension callback when a winner is detected.

    - Debounces rapid duplicates by (username, auction_id) for ~8 seconds.
    - Never raises UI dialogs; logs errors and shows a small toast if available.
    """
    try:
        username = _sanitize_username(username or "")
        if not username:
            return

        if not isinstance(qty, int):
            try:
                qty = int(qty)
            except Exception:
                qty = 1
        if qty < 0:
            qty = 0

        # Normalize weight for DB
        if weight is not None and not isinstance(weight, str):
            weight = str(weight)

        # quick duplicate suppression
        now = time.time()
        if not hasattr(self, "_recent_captures"):
            self._recent_captures = {}  # {(username, auction_id): timestamp}

        key = (username, auction_id or "")
        last_ts = self._recent_captures.get(key)
        if last_ts and (now - last_ts) < 8.0:
            # Duplicate event (e.g., page updated twice) — ignore silently
            return
        self._recent_captures[key] = now

        _add_bidder_core(
            self,
            username=username,
            qty=qty,
            weight=weight,
            is_giveaway=is_giveaway,
            source="auto",
            original_username=original_username or username,
            auction_id=auction_id,
            first_name=first_name,
        )

        # non-blocking visual hint if available
        if hasattr(self, "show_temporary_message"):
            tag = f"Bin {self.bin_number_label.text()}" if self.bin_number_label.text() else "Recorded"
            self.show_temporary_message(f"Captured: {username} • {tag}", duration_ms=1500)

    except Exception as e:
        self.log_error(f"Auto-capture add failed: {e}")


# -------------------------------------------------------------------
# Core impl used by both manual and auto flows
# -------------------------------------------------------------------
def _add_bidder_core(
    self,
    *,
    username: str,
    qty: int,
    weight: str | None,
    is_giveaway: bool,
    source: str,
    original_username: str | None,
    auction_id: str | None,
    first_name: str | None,
):
    """
    Single path that writes to DB and refreshes UI.
    NOTE: current BidderManager.add_transaction does not persist first_name/auction_id;
          this call is forward-compatible once BidderManager gains those fields.
    """
    # Write to DB
    # Prefer add_transaction to pass email explicitly (keeps per-user data clean)
    bin_number, giveaway_num = self.bidder_manager.add_transaction(
        username=username,
        original_username=original_username or username,
        qty=qty,
        weight=weight,
        is_giveaway=is_giveaway,
        email=getattr(self, "user_email", "") or "trial@swiftsaleapp.com",
    )

    # Update UI model
    self.latest_bin_assignment = _format_latest_assignment(username, bin_number, giveaway_num)
    self.update_bins_used_display()
    self.update_latest_bidder_display()
    self.populate_bidders_tree()

    # Telegram (best-effort)
    try:
        if self.telegram_service and self.chat_id:
            if giveaway_num is not None:
                self.telegram_service.send_message(
                    self.chat_id, f"Giveaway winner: {username} • Giveaway #{giveaway_num}"
                )
            elif isinstance(bin_number, int):
                self.telegram_service.send_message(
                    self.chat_id, f"New bidder: {username} | Bin: {bin_number}"
                )
            else:
                self.telegram_service.send_message(
                    self.chat_id, f"Recorded: {username}"
                )
    except Exception as e:
        self.log_error(f"Telegram notify failed: {e}")

    # Header/footer status
    self.update_header_and_footer()


# -------------------------------------------------------------------
# Binder
# -------------------------------------------------------------------
def bind_bidders_methods(gui):
    """Bind bidder-related methods to the GUI instance."""
    gui.add_bidder = add_bidder.__get__(gui, gui.__class__)
    gui.clear_bidders = clear_bidders.__get__(gui, gui.__class__)
    gui.import_csv = import_csv.__get__(gui, gui.__class__)
    gui.export_csv = export_csv.__get__(gui, gui.__class__)
    # new entry point for auto-capture integrations
    gui.add_bidder_from_capture = add_bidder_from_capture.__get__(gui, gui.__class__)
