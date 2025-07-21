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

        self.business_name_input = QLineEdit()
        self.contact_name_input = QLineEdit()
        self.email_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.addr1_input = QLineEdit()
        self.addr2_input = QLineEdit()
        self.city_input = QLineEdit()
        self.state_input = QLineEdit()
        self.zip_input = QLineEdit()

        layout.addWidget(QLabel("Business Name:"))
        layout.addWidget(self.business_name_input)

        layout.addWidget(QLabel("Contact Name:"))
        layout.addWidget(self.contact_name_input)

        layout.addWidget(QLabel("Email:"))
        layout.addWidget(self.email_input)

        layout.addWidget(QLabel("Phone:"))
        layout.addWidget(self.phone_input)

        layout.addWidget(QLabel("Address Line 1:"))
        layout.addWidget(self.addr1_input)

        layout.addWidget(QLabel("Address Line 2 (optional):"))
        layout.addWidget(self.addr2_input)

        layout.addWidget(QLabel("City:"))
        layout.addWidget(self.city_input)

        layout.addWidget(QLabel("State:"))
        layout.addWidget(self.state_input)

        layout.addWidget(QLabel("ZIP Code:"))
        layout.addWidget(self.zip_input)

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
        self.business_name_input.setText(saved.get("business_name", ""))
        self.contact_name_input.setText(saved.get("contact_name", ""))
        self.email_input.setText(saved.get("email", ""))
        self.phone_input.setText(saved.get("phone", ""))
        self.addr1_input.setText(saved.get("address_line_1", ""))
        self.addr2_input.setText(saved.get("address_line_2", ""))
        self.city_input.setText(saved.get("city", ""))
        self.state_input.setText(saved.get("state", ""))
        self.zip_input.setText(saved.get("zip_code", ""))

    def save_info(self):
        info = {
            "business_name": self.business_name_input.text().strip(),
            "contact_name": self.contact_name_input.text().strip(),
            "email": self.email_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "address_line_1": self.addr1_input.text().strip(),
            "address_line_2": self.addr2_input.text().strip(),
            "city": self.city_input.text().strip(),
            "state": self.state_input.text().strip(),
            "zip_code": self.zip_input.text().strip()
        }
        save_business_info(info)
        self.accept()
