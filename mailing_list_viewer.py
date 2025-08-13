from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QApplication
from PySide6.QtCore import Qt
from mailing_list_manager import MailingListManager

class MailingListViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.db = MailingListManager()
        self.setLayout(QVBoxLayout())
        self.table = QTableWidget()
        self.layout().addWidget(self.table)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "✓", "Full Name", "Username", "Email", "City", "State", "Spent"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.load_data()

    def load_data(self):
        self.table.setRowCount(0)
        entries = self.db.get_all_entries(sort_by_spent=True)
        for row_idx, entry in enumerate(entries):
            entry_id = entry[0]
            checked = bool(entry[13])
            self.table.insertRow(row_idx)

            checkbox = QCheckBox()
            checkbox.setChecked(checked)
            checkbox.stateChanged.connect(lambda state, id=entry_id: self.toggle_checkbox(id, state))
            self.table.setCellWidget(row_idx, 0, checkbox)

            self.table.setItem(row_idx, 1, QTableWidgetItem(entry[1] or ""))
            self.table.setItem(row_idx, 2, QTableWidgetItem(entry[2] or ""))
            self.table.setItem(row_idx, 3, QTableWidgetItem(entry[3] or ""))
            self.table.setItem(row_idx, 4, QTableWidgetItem(entry[6] or ""))
            self.table.setItem(row_idx, 5, QTableWidgetItem(entry[7] or ""))
            self.table.setItem(row_idx, 6, QTableWidgetItem(f"${entry[12]:.2f}"))

    def toggle_checkbox(self, entry_id, state):
        self.db.set_entry_checked(entry_id, checked=state == Qt.Checked)
