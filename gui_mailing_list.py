import os
import csv
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QComboBox
)
from PySide6.QtCore import Qt
from mailing_list_manager import MailingListManager
from export_labels import generate_labels_pdf  
from business_info_dialog import BusinessInfoDialog


class MailingListWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mailing List")
        self.resize(1300, 720)

        try:
            with open("light_theme.qss", "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Failed to apply light theme: {e}")

        self.manager = MailingListManager()
        self.build_ui()
        self.load_entries()

    def build_ui(self):
        layout = QVBoxLayout(self)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search by name, city, state, or date (YYYY-MM-DD)")
        self.search_bar.textChanged.connect(self.apply_filter)
        layout.addWidget(self.search_bar)

        self.sort_dropdown = QComboBox()
        self.sort_dropdown.addItems(["Sort by Name (A–Z)", "Sort by Spent (High to Low)"])
        self.sort_dropdown.currentIndexChanged.connect(self.apply_filter)
        layout.addWidget(self.sort_dropdown)

        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels([
            "", "Full Name", "Username", "Email", "Address 1", "Address 2",
            "City", "State", "Zip", "Order Date", "Order ID", "# Orders", "Spent"
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.total_label = QLabel("Total Customers: 0")
        self.total_label.setAlignment(Qt.AlignCenter)
        font = self.total_label.font()
        font.setPointSize(16)
        font.setBold(True)
        self.total_label.setFont(font)
        layout.addWidget(self.total_label)

        button_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.toggle_select_all)

        self.export_btn = QPushButton("Export Labels")
        self.export_btn.clicked.connect(self.export_selected_labels)

        self.import_button = QPushButton("Import Emails from CSV")
        self.import_button.clicked.connect(self.import_emails)

        self.clear_button = QPushButton("Clear Mailing List")
        self.clear_button.setStyleSheet("background-color: #b33939; color: white;")
        self.clear_button.clicked.connect(self.clear_mailing_list)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        self.business_button = QPushButton("Business Details")
        self.business_button.clicked.connect(self.open_business_info_dialog)

        button_layout.addWidget(self.select_all_btn)
        button_layout.addWidget(self.export_btn)
        button_layout.addWidget(self.import_button)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.business_button)

        layout.addLayout(button_layout)

    def load_entries(self, filters=None, sort_by_spent=False):
        self.table.blockSignals(True)
        entries = self.manager.search_entries(filters, sort_by_spent=sort_by_spent)
        self.table.setRowCount(len(entries))

        medal_emojis = ["🥇", "🥈", "🥉"]

        for row_idx, row in enumerate(entries):
            entry_id = row[0]

            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(
                Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsEditable
            )
            checkbox_item.setCheckState(Qt.Unchecked)
            checkbox_item.setData(Qt.UserRole, entry_id)
            self.table.setItem(row_idx, 0, checkbox_item)
            self.table.setColumnWidth(0, 40)

            for col_idx in range(12):
                value = row[col_idx + 1]
                if col_idx == 11:
                    display_value = f"${float(value):.2f}"
                    if sort_by_spent and row_idx < 3:
                        display_value = f"{medal_emojis[row_idx]} {display_value}"
                else:
                    display_value = str(value)

                item = QTableWidgetItem(display_value)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row_idx, col_idx + 1, item)

        self.table.blockSignals(False)
        self.table.setColumnWidth(0, 40)
        self.update_total_customers()
        self.update_select_all_button_text()

    def apply_filter(self):
        text = self.search_bar.text().strip()
        filters = {}

        if "-" in text and len(text) == 10:
            filters["date"] = text
        elif len(text) == 2 and text.isalpha():
            filters["state"] = text.upper()
        elif text:
            filters["name"] = text
            filters["city"] = text

        sort_by_spent = self.sort_dropdown.currentIndex() == 1
        self.load_entries(filters=filters, sort_by_spent=sort_by_spent)

    def toggle_select_all(self):
        all_selected = all(
            self.table.item(row, 0).checkState() == Qt.Checked
            for row in range(self.table.rowCount())
        )
        new_state = Qt.Unchecked if all_selected else Qt.Checked

        for row in range(self.table.rowCount()):
            checkbox_item = self.table.item(row, 0)
            if checkbox_item:
                checkbox_item.setCheckState(new_state)

        self.update_select_all_button_text()

    def update_select_all_button_text(self):
        if all(
            self.table.item(row, 0).checkState() == Qt.Checked
            for row in range(self.table.rowCount())
        ):
            self.select_all_btn.setText("Unselect All")
        else:
            self.select_all_btn.setText("Select All")

    def export_selected_labels(self):
        selected_ids = []
        for row in range(self.table.rowCount()):
            checkbox_item = self.table.item(row, 0)
            if checkbox_item and checkbox_item.checkState() == Qt.Checked:
                selected_ids.append(checkbox_item.data(Qt.UserRole))

        if not selected_ids:
            QMessageBox.warning(self, "No Selection", "Please select at least one row.")
            return

        entries = [e for e in self.manager.get_all_entries() if e[0] in selected_ids]

        save_path, _ = QFileDialog.getSaveFileName(self, "Save Labels PDF", "labels.pdf", "PDF Files (*.pdf)")
        if save_path:
            try:
                generate_labels_pdf(entries, save_path)
                QMessageBox.information(self, "Success", f"Labels exported to:\n{save_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def import_emails(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return

        try:
            result = self.manager.bulk_import_emails_from_csv(file_path)
            self.load_entries()
            QMessageBox.information(
                self, "Import Complete",
                f"Emails Imported:\nUpdated: {result['updated']}\nAdded: {result['added']}\nSkipped: {result['skipped']}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import CSV:\n{e}")

    def clear_mailing_list(self):
        reply = QMessageBox.question(
            self,
            "Confirm Clear",
            "This will permanently delete all entries from the mailing list.\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.manager.clear_all_entries()
                self.load_entries()
                QMessageBox.information(self, "Success", "Mailing list cleared.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to clear mailing list:\n{e}")

    def update_total_customers(self):
        row_count = self.table.rowCount()
        self.total_label.setText(f"Total Customers: {row_count}")

    def open_business_info_dialog(self):
        dialog = BusinessInfoDialog(self)
        dialog.exec()
