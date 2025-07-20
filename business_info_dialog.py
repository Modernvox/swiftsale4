from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton
)
from business_info import load_business_info, save_business_info

class BusinessInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Business Info")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        self.name_input = QLineEdit()
        self.addr_input = QLineEdit()
        self.city_input = QLineEdit()
        self.state_input = QLineEdit()

        layout.addWidget(QLabel("Business Name:"))
        layout.addWidget(self.name_input)
        layout.addWidget(QLabel("Street Address:"))
        layout.addWidget(self.addr_input)
        layout.addWidget(QLabel("City:"))
        layout.addWidget(self.city_input)
        layout.addWidget(QLabel("State:"))
        layout.addWidget(self.state_input)

        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_info)
        close_btn = QPushButton("Cancel")
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # Populate saved values
        saved = load_business_info()
        self.name_input.setText(saved.get("name", ""))
        self.addr_input.setText(saved.get("address", ""))
        self.city_input.setText(saved.get("city", ""))
        self.state_input.setText(saved.get("state", ""))

    def save_info(self):
        info = {
            "name": self.name_input.text().strip(),
            "address": self.addr_input.text().strip(),
            "city": self.city_input.text().strip(),
            "state": self.state_input.text().strip()
        }
        save_business_info(info)
        self.accept()
