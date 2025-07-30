import os
import sqlite3
from datetime import datetime

# Derive a default path for the mailing list database.  On Windows the
# ``LOCALAPPDATA`` environment variable points to the user's local application
# data directory.  However, this variable may be undefined on other
# platforms (e.g. Linux/macOS).  In those cases fall back to the user's
# home directory to ensure the application still functions without raising
# ``TypeError`` when ``os.path.join`` receives ``None``.  The database
# itself is stored under a ``SwiftSale`` subdirectory.
_appdata = os.getenv("LOCALAPPDATA")
if not _appdata:
    _appdata = os.path.expanduser("~")
MAILING_DB_PATH = os.path.join(_appdata, "SwiftSale", "mailing_list.db")


class MailingListManager:
    def __init__(self, db_path=MAILING_DB_PATH):
        self.db_path = db_path
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mailing_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT,
                    username TEXT,
                    email TEXT,
                    address_line_1 TEXT,
                    address_line_2 TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,
                    order_date TEXT,
                    order_id TEXT,
                    num_orders INTEGER DEFAULT 1,
                    spent REAL DEFAULT 0.0,
                    checked INTEGER DEFAULT 0
                )
            """)
            cursor.execute("PRAGMA table_info(mailing_list);")
            existing_columns = [col[1] for col in cursor.fetchall()]
            if "email" not in existing_columns:
                cursor.execute("ALTER TABLE mailing_list ADD COLUMN email TEXT;")
            if "spent" not in existing_columns:
                cursor.execute("ALTER TABLE mailing_list ADD COLUMN spent REAL DEFAULT 0.0;")
            if "checked" not in existing_columns:
                cursor.execute("ALTER TABLE mailing_list ADD COLUMN checked INTEGER DEFAULT 0;")
            conn.commit()

    def add_or_update_entry(self, entry):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM mailing_list
                WHERE full_name = ? AND address_line_1 = ? AND city = ? AND state = ? AND zip_code = ?
            """, (
                entry["full_name"],
                entry["address_line_1"],
                entry["city"],
                entry["state"],
                entry["zip_code"]
            ))
            if cursor.fetchone():
                print(f"[INFO] Duplicate mailing entry skipped for {entry['full_name']}")
            else:
                cursor.execute("""
                    INSERT INTO mailing_list 
                    (full_name, username, email, address_line_1, address_line_2, city, state, zip_code, spent, order_date, order_id, checked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    entry["full_name"],
                    entry["username"],
                    entry["email"],
                    entry["address_line_1"],
                    entry["address_line_2"],
                    entry["city"],
                    entry["state"],
                    entry["zip_code"],
                    entry.get("spent", 0.0),
                    entry.get("order_date"),
                    entry.get("order_id")
                ))
            conn.commit()
        finally:
            conn.close()

    def set_entry_checked(self, entry_id, checked=True):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE mailing_list SET checked = ? WHERE id = ?",
                (1 if checked else 0, entry_id)
            )
            print(f"[DEBUG] DB updated: entry {entry_id} -> checked={checked}")
            conn.commit()

    def get_checked_entries(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mailing_list WHERE checked = 1")
            return cursor.fetchall()

    def search_entries(self, filters=None, sort_by_spent=False):
        """
        Retrieve mailing list entries matching the provided filter criteria.

        Parameters
        ----------
        filters : dict, optional
            Mapping of filter fields to values.  Supported keys include

            - ``name``: substring to match anywhere in the full name.
            - ``username``: substring to match anywhere in the username.
            - ``city``: substring to match anywhere in the city name.
            - ``state``: substring to match anywhere in the state abbreviation.
            - ``spent_min``: lower bound on the ``spent`` amount (inclusive).
            - ``spent_max``: upper bound on the ``spent`` amount (inclusive).
            - ``date``: exact match on the order date.

        sort_by_spent : bool, default False
            Whether to sort results descending by amount spent.  If false,
            results are sorted alphabetically by ``full_name``.

        Returns
        -------
        list of tuple
            Rows from the ``mailing_list`` table matching the filters.
        """
        query = "SELECT * FROM mailing_list WHERE 1=1"
        params = []
        if filters:
            # Name substring (first or last name)
            name_filter = filters.get("name")
            if name_filter:
                query += " AND full_name LIKE ?"
                params.append(f"%{name_filter}%")
            # Username substring
            username_filter = filters.get("username")
            if username_filter:
                query += " AND username LIKE ?"
                params.append(f"%{username_filter}%")
            # City substring
            city_filter = filters.get("city")
            if city_filter:
                query += " AND city LIKE ?"
                params.append(f"%{city_filter}%")
            # State substring or exact match
            state_filter = filters.get("state")
            if state_filter:
                query += " AND state LIKE ?"
                params.append(f"%{state_filter}%")
            # Spent boundaries
            spent_min = filters.get("spent_min")
            if spent_min is not None:
                query += " AND spent >= ?"
                params.append(spent_min)
            spent_max = filters.get("spent_max")
            if spent_max is not None:
                query += " AND spent <= ?"
                params.append(spent_max)
            # Exact order date match
            date_filter = filters.get("date")
            if date_filter:
                query += " AND order_date = ?"
                params.append(date_filter)
        # Sorting
        if sort_by_spent:
            query += " ORDER BY spent DESC"
        else:
            query += " ORDER BY full_name COLLATE NOCASE ASC"
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_all_entries(self, sort_by_spent=False):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            order_clause = "ORDER BY spent DESC" if sort_by_spent else "ORDER BY full_name COLLATE NOCASE ASC"
            cursor.execute(f"SELECT * FROM mailing_list {order_clause}")
            return cursor.fetchall()

    def bulk_import_emails_from_csv(self, csv_path):
        import csv
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        updated = 0
        added = 0
        skipped = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)
                all_headers = set(reader.fieldnames or [])
                required_headers = {"full_name", "email"}
                optional_headers = {
                    "address_line_1", "city", "state", "zip_code",
                    "order_id", "order_date"
                }
                missing_required = required_headers - all_headers
                missing_optional = optional_headers - all_headers
                if missing_required:
                    raise ValueError(f"Missing required CSV headers: {', '.join(missing_required)}")
                if missing_optional:
                    print(f"Warning: Optional headers missing: {', '.join(missing_optional)}")
                for row in reader:
                    full_name = row.get("full_name", "").strip()
                    email = row.get("email", "").strip()
                    address_line_1 = row.get("address_line_1", "").strip()
                    city = row.get("city", "").strip()
                    state = row.get("state", "").strip()
                    zip_code = row.get("zip_code", "").strip()
                    order_id = row.get("order_id", "").strip()
                    order_date = row.get("order_date", "").strip()
                    if not full_name or not email:
                        skipped += 1
                        continue
                    cursor.execute("""
                        SELECT id FROM mailing_list
                        WHERE full_name = ? AND address_line_1 = ? AND city = ? AND state = ? AND zip_code = ?
                    """, (full_name, address_line_1, city, state, zip_code))
                    match = cursor.fetchone()
                    if match:
                        cursor.execute("UPDATE mailing_list SET email = ? WHERE id = ?", (email, match[0]))
                        updated += 1
                    else:
                        cursor.execute("""
                            INSERT INTO mailing_list (
                                full_name, username, email, address_line_1, address_line_2,
                                city, state, zip_code, order_date, order_id, num_orders, checked
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                        """, (
                            full_name, '', email, address_line_1, '',
                            city, state, zip_code, order_date, order_id
                        ))
                        added += 1
            conn.commit()
        return {"updated": updated, "added": added, "skipped": skipped}

    def clear_all_entries(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mailing_list")
            conn.commit()

    def get_entry_by_id(self, entry_id):
        """
        Retrieve a single mailing list entry by its unique identifier.

        Args:
            entry_id (int): The primary key of the desired mailing list record.

        Returns:
            tuple | None: A tuple containing the row data if found, otherwise
            ``None``.

        This helper method allows consumers of ``MailingListManager`` to fetch
        complete address information for an individual row. It is especially
        useful when the user interface only retains a subset of columns (e.g.
        when rendering a table with limited fields) but still needs the full
        record for operations like label generation.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mailing_list WHERE id = ?", (entry_id,))
            return cursor.fetchone()

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QPushButton, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

# NOTE: ``MailingListManager`` is defined above in this module.  We avoid
# re-importing it from ``mailing_list_manager`` here to prevent circular
# imports and duplicate definitions which can lead to subtle bugs.  See
# https://docs.python.org/3/faq/programming.html#how-can-i-have-a-variable- and
# maintain a single copy across modules for further discussion.

class MailingListViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mailing List Viewer")
        self.setMinimumSize(800, 600)

        self.db = MailingListManager()
        layout = QVBoxLayout(self)

        # ------------------------------------------------------------------
        # Search controls
        # ------------------------------------------------------------------
        # Create a small grid of inputs to allow users to filter the mailing
        # list by name, username, city, state and spending range.  When the
        # search button is clicked, the results are loaded into the table.
        from PySide6.QtWidgets import QLabel, QLineEdit, QGridLayout

        search_grid = QGridLayout()
        row = 0
        # Name (matches anywhere in full_name)
        search_grid.addWidget(QLabel("Name:"), row, 0)
        self.search_name_edit = QLineEdit()
        self.search_name_edit.setPlaceholderText("First or last name")
        search_grid.addWidget(self.search_name_edit, row, 1)
        # Username
        search_grid.addWidget(QLabel("Username:"), row, 2)
        self.search_username_edit = QLineEdit()
        self.search_username_edit.setPlaceholderText("Username")
        search_grid.addWidget(self.search_username_edit, row, 3)
        row += 1
        # City
        search_grid.addWidget(QLabel("City:"), row, 0)
        self.search_city_edit = QLineEdit()
        self.search_city_edit.setPlaceholderText("City")
        search_grid.addWidget(self.search_city_edit, row, 1)
        # State
        search_grid.addWidget(QLabel("State:"), row, 2)
        self.search_state_edit = QLineEdit()
        self.search_state_edit.setPlaceholderText("State")
        search_grid.addWidget(self.search_state_edit, row, 3)
        row += 1
        # Spent range
        search_grid.addWidget(QLabel("Min Spent:"), row, 0)
        self.search_spent_min_edit = QLineEdit()
        self.search_spent_min_edit.setPlaceholderText("e.g. 50.00")
        search_grid.addWidget(self.search_spent_min_edit, row, 1)
        search_grid.addWidget(QLabel("Max Spent:"), row, 2)
        self.search_spent_max_edit = QLineEdit()
        self.search_spent_max_edit.setPlaceholderText("e.g. 200.00")
        search_grid.addWidget(self.search_spent_max_edit, row, 3)
        row += 1
        # Search and reset buttons
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.apply_search)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_search)
        search_grid.addWidget(self.search_button, row, 0, 1, 2)
        search_grid.addWidget(self.reset_button, row, 2, 1, 2)
        # Add search controls to the main layout
        layout.addLayout(search_grid)

        # ------------------------------------------------------------------
        # Table and buttons
        # ------------------------------------------------------------------
        self.table = QTableWidget()
        layout.addWidget(self.table)

        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "✓", "Full Name", "Username", "Email",
            "Address 1", "Address 2", "City", "State", "Spent"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.export_button = QPushButton("Export Checked Labels (PDF)")
        self.export_button.clicked.connect(self.export_labels)
        # Add a 'Select All' button to allow users to quickly select or clear
        # all rows for export.  When all checkboxes are already checked the
        # button will act as "Clear All" to toggle them off.
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all_rows)

        # Use a horizontal layout for the action buttons to keep them aligned.
        from PySide6.QtWidgets import QHBoxLayout
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.select_all_button)
        button_layout.addWidget(self.export_button)
        layout.addLayout(button_layout)

        self.load_data()

    def apply_search(self):
        """
        Gather values from the search fields and reload the table with
        matching entries.  Empty fields are ignored.  Numeric values for
        spending filters are validated; invalid input is skipped.
        """
        filters = {}
        name = self.search_name_edit.text().strip()
        if name:
            filters['name'] = name
        username = self.search_username_edit.text().strip()
        if username:
            filters['username'] = username
        city = self.search_city_edit.text().strip()
        if city:
            filters['city'] = city
        state = self.search_state_edit.text().strip()
        if state:
            filters['state'] = state
        spent_min_text = self.search_spent_min_edit.text().strip()
        if spent_min_text:
            try:
                filters['spent_min'] = float(spent_min_text)
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Min Spent must be a number.")
                return
        spent_max_text = self.search_spent_max_edit.text().strip()
        if spent_max_text:
            try:
                filters['spent_max'] = float(spent_max_text)
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Max Spent must be a number.")
                return
        # If both min and max are provided and min > max, show a warning
        if 'spent_min' in filters and 'spent_max' in filters and filters['spent_min'] > filters['spent_max']:
            QMessageBox.warning(self, "Invalid Range", "Min Spent cannot be greater than Max Spent.")
            return
        self.load_data(filters)

    def reset_search(self):
        """Clear all search fields and reload the complete mailing list."""
        self.search_name_edit.clear()
        self.search_username_edit.clear()
        self.search_city_edit.clear()
        self.search_state_edit.clear()
        self.search_spent_min_edit.clear()
        self.search_spent_max_edit.clear()
        self.load_data()

    def select_all_rows(self):
        """
        Select or deselect all checkboxes in the table.  If at least one
        checkbox is unchecked, this will check all boxes.  Otherwise, it
        clears all selections.  The method also updates the underlying
        database flags via the existing ``toggle_checkbox`` mechanism.
        """
        # Determine if we should select or clear all
        all_checked = True
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if isinstance(checkbox, QCheckBox) and not checkbox.isChecked():
                all_checked = False
                break
        # Toggle each checkbox accordingly
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if isinstance(checkbox, QCheckBox):
                # Changing the check state triggers ``toggle_checkbox`` which
                # updates the database accordingly.
                checkbox.setChecked(not all_checked)

    def load_data(self, filters=None):
        """
        Populate the table with mailing list entries.  If a ``filters``
        dictionary is provided, only matching entries are loaded; otherwise
        all entries are displayed sorted by amount spent.

        Parameters
        ----------
        filters : dict, optional
            Same format as accepted by ``MailingListManager.search_entries``.
        """
        self.table.setRowCount(0)
        if filters:
            entries = self.db.search_entries(filters=filters, sort_by_spent=True)
        else:
            entries = self.db.get_all_entries(sort_by_spent=True)
        for row_idx, entry in enumerate(entries):
            entry_id = entry[0]
            checked = bool(entry[13])
            self.table.insertRow(row_idx)

            checkbox = QCheckBox()
            checkbox.setChecked(checked)
            # Persist the entry ID on the widget so it can be retrieved later
            # without relying on external state or database flags.  Using a
            # property avoids the need for hidden columns while still
            # providing direct access to the underlying record on export.
            checkbox.setProperty("entry_id", entry_id)
            # Use a lambda to capture the current entry_id; include Qt in
            # default arguments to avoid late binding issues.
            checkbox.stateChanged.connect(lambda state, id=entry_id, qt=Qt: self.toggle_checkbox(id, state == qt.Checked))
            self.table.setCellWidget(row_idx, 0, checkbox)

            # Populate text columns; guard against missing or None values
            self.table.setItem(row_idx, 1, QTableWidgetItem(entry[1] or ""))
            self.table.setItem(row_idx, 2, QTableWidgetItem(entry[2] or ""))
            self.table.setItem(row_idx, 3, QTableWidgetItem(entry[3] or ""))
            self.table.setItem(row_idx, 4, QTableWidgetItem(entry[4] or ""))
            self.table.setItem(row_idx, 5, QTableWidgetItem(entry[5] or ""))
            self.table.setItem(row_idx, 6, QTableWidgetItem(entry[6] or ""))
            self.table.setItem(row_idx, 7, QTableWidgetItem(entry[7] or ""))
            # Format spent as currency
            spent = entry[12] if len(entry) > 12 and entry[12] is not None else 0.0
            self.table.setItem(row_idx, 8, QTableWidgetItem(f"${spent:.2f}"))

    def toggle_checkbox(self, entry_id, is_checked):
        print(f"[DEBUG] DB updated: entry {entry_id} -> checked={is_checked}")
        self.db.set_entry_checked(entry_id, checked=is_checked)

    def export_labels(self):
        """
        Export checked entries as mailing labels in a PDF.

        Instead of relying solely on the ``checked`` flag stored in the
        database, this method inspects the state of each checkbox in the
        table at the time the export button is pressed.  This ensures that
        recently toggled checkboxes are respected even if the database update
        has not yet completed or the application is using an older database
        schema.  Each ``QCheckBox`` stores its associated record ID as a
        property so the corresponding entry can be fetched from the
        ``MailingListManager`` when needed.
        """
        # Collect the selected rows by inspecting checkbox widgets directly.
        selected_entries = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if not isinstance(checkbox, QCheckBox):
                continue
            if checkbox.isChecked():
                entry_id = checkbox.property("entry_id")
                if entry_id is None:
                    continue
                entry = self.db.get_entry_by_id(entry_id)
                if entry is not None:
                    selected_entries.append(entry)

        if not selected_entries:
            QMessageBox.warning(self, "No Entries", "No checked entries to export.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", "", "PDF Files (*.pdf)"
        )
        if not save_path:
            return

        # Try to use the enhanced label generator provided in ``export_labels.py``.
        try:
            from export_labels import generate_labels_pdf  # type: ignore
        except Exception:
            generate_labels_pdf = None

        if generate_labels_pdf:
            # ``generate_labels_pdf`` handles all drawing and formatting.  It
            # accepts a list of database tuples and the destination file path.
            generate_labels_pdf(selected_entries, save_path)
        else:
            # Fallback to a minimal label format if the helper is not available.
            label_width = 4 * inch
            label_height = 6 * inch
            c = canvas.Canvas(save_path, pagesize=(label_width, label_height))
            for entry in selected_entries:
                full_name = entry[1] or ""
                address_1 = entry[4] or ""
                address_2 = entry[5] or ""
                city = entry[6] or ""
                state = entry[7] or ""
                zip_code = entry[8] or ""
                y = label_height - 0.5 * inch
                c.setFont("Helvetica-Bold", 14)
                c.drawString(0.5 * inch, y, full_name)
                c.setFont("Helvetica", 12)
                y -= 0.3 * inch
                c.drawString(0.5 * inch, y, address_1)
                if address_2:
                    y -= 0.25 * inch
                    c.drawString(0.5 * inch, y, address_2)
                y -= 0.25 * inch
                city_state_zip = ", ".join(filter(None, [city, state]))
                if zip_code:
                    city_state_zip = f"{city_state_zip} {zip_code}" if city_state_zip else zip_code
                c.drawString(0.5 * inch, y, city_state_zip)
                c.showPage()
            c.save()
        QMessageBox.information(self, "Success", "PDF Labels exported successfully.")



if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication([])
    viewer = MailingListViewer()
    viewer.show()
    app.exec()

