import os
import json
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSizePolicy, QCheckBox
from PySide6.QtCore import Qt
from config_qt import DEFAULT_DATA_DIR as USER_DATA_DIR
from gui_help_qt import show_telegram_help, show_top_buyer_help, show_giveaway_text_help, show_flash_sale_text_help
from gui_mailing_list import MailingListWindow

import sqlite3

SETTINGS_FILE = os.path.join(USER_DATA_DIR, "settings.json")

def load_settings_from_json(self):
    """Load settings from local JSON file."""
    try:
        if not os.path.exists(SETTINGS_FILE):
            self.log_info("No settings.json found, using defaults")
            return
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        self.chat_id = data.get("chat_id", "")
        self.top_buyer_text = data.get("top_buyer_text", "")
        self.giveaway_announcement_text = data.get("giveaway_announcement_text", "")
        self.flash_sale_announcement_text = data.get("flash_sale_announcement_text", "")
        self.multi_buyer_mode = data.get("multi_buyer_mode", False)
        self.log_info("Settings loaded from settings.json")
    except Exception as e:
        self.log_error(f"Failed to load settings.json: {e}")
        self.log_info("Using default settings")

def save_settings_to_json(self):
    """Save settings to local JSON file."""
    try:
        data = {
            "chat_id": self.chat_id_entry.text(),
            "top_buyer_text": self.top_buyer_entry.text(),
            "giveaway_announcement_text": self.giveaway_entry.text(),
            "flash_sale_announcement_text": self.flash_sale_entry.text(),
            "multi_buyer_mode": self.multi_buyer_check.isChecked(),
        }
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)

        # Also update runtime attributes
        self.chat_id = data["chat_id"]
        self.top_buyer_text = data["top_buyer_text"]
        self.giveaway_announcement_text = data["giveaway_announcement_text"]
        self.flash_sale_announcement_text = data["flash_sale_announcement_text"]
        self.multi_buyer_mode = data["multi_buyer_mode"]

        self.log_info("Settings saved to settings.json")
        QMessageBox.information(self, "Success", "Settings saved successfully")
    except Exception as e:
        self.log_error(f"Failed to save settings.json: {e}")
        QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
def build_settings_ui(self, parent_frame):
    """Build Settings tab UI."""
    layout = QVBoxLayout(parent_frame)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)

    settings_group = QGroupBox("Settings")
    settings_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    settings_layout = QGridLayout()
    settings_layout.setContentsMargins(12, 12, 12, 12)
    settings_layout.setSpacing(10)
    settings_group.setLayout(settings_layout)

    # Row 0: Telegram Chat ID
    settings_layout.addWidget(QLabel("Telegram Chat ID:"), 0, 0)
    self.chat_id_entry = QLineEdit(self.chat_id or "")
    self.chat_id_entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.chat_id_entry.setMinimumWidth(200)
    settings_layout.addWidget(self.chat_id_entry, 0, 1)
    telegram_help_button = QPushButton("?")
    telegram_help_button.setFixedWidth(30)
    telegram_help_button.setAccessibleName("help")
    telegram_help_button.clicked.connect(lambda: show_telegram_help(self))
    settings_layout.addWidget(telegram_help_button, 0, 2)

    # Row 1: Top Buyer Text
    settings_layout.addWidget(QLabel("Top Buyer Text:"), 1, 0)
    self.top_buyer_entry = QLineEdit(self.top_buyer_text or "")
    self.top_buyer_entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.top_buyer_entry.setMinimumWidth(200)
    settings_layout.addWidget(self.top_buyer_entry, 1, 1)
    top_buyer_help_button = QPushButton("?")
    top_buyer_help_button.setFixedWidth(30)
    top_buyer_help_button.setAccessibleName("help")
    top_buyer_help_button.clicked.connect(lambda: show_top_buyer_help(self))
    settings_layout.addWidget(top_buyer_help_button, 1, 2)

    # Row 2: Giveaway Text
    giveaway_label = QLabel("Giveaway Text:")
    giveaway_label.setMinimumWidth(120)
    giveaway_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    settings_layout.addWidget(giveaway_label, 2, 0)
    self.giveaway_entry = QLineEdit(self.giveaway_announcement_text or "")
    self.giveaway_entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.giveaway_entry.setMinimumWidth(300)
    self.giveaway_entry.setStyleSheet("padding-left: 8px;")
    settings_layout.addWidget(self.giveaway_entry, 2, 1)
    giveaway_text_help_button = QPushButton("?")
    giveaway_text_help_button.setFixedWidth(30)
    giveaway_text_help_button.setAccessibleName("help")
    giveaway_text_help_button.clicked.connect(lambda: show_giveaway_text_help(self))
    settings_layout.addWidget(giveaway_text_help_button, 2, 2)

    # Row 3: Flash Sale Text
    settings_layout.addWidget(QLabel("Flash Sale Text:"), 3, 0)
    self.flash_sale_entry = QLineEdit(self.flash_sale_announcement_text or "")
    self.flash_sale_entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.flash_sale_entry.setMinimumWidth(200)
    settings_layout.addWidget(self.flash_sale_entry, 3, 1)
    flash_sale_text_help_button = QPushButton("?")
    flash_sale_text_help_button.setFixedWidth(30)
    flash_sale_text_help_button.setAccessibleName("help")
    flash_sale_text_help_button.clicked.connect(lambda: show_flash_sale_text_help(self))
    settings_layout.addWidget(flash_sale_text_help_button, 3, 2)

    # Row 4: Multi-Buyer checkbox
    self.multi_buyer_check = QCheckBox("Multi-Buyer Top Message")
    self.multi_buyer_check.setChecked(self.multi_buyer_mode)
    self.multi_buyer_check.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    settings_layout.addWidget(self.multi_buyer_check, 4, 0, 1, 2)

    # Row 5: Save button
    save_settings_button = QPushButton("Save Settings")
    save_settings_button.setObjectName("green")
    save_settings_button.setFixedWidth(150)
    save_settings_button.clicked.connect(self.save_settings)
    settings_layout.addWidget(save_settings_button, 5, 0, 1, 2, alignment=Qt.AlignCenter)

    # Row 6: Open Mailing List
    mailing_list_button = QPushButton("Open Mailing List")
    mailing_list_button.setObjectName("blue")
    mailing_list_button.setFixedWidth(200)
    mailing_list_button.clicked.connect(self.open_mailing_list_dialog)
    layout.addWidget(mailing_list_button, alignment=Qt.AlignCenter)


    layout.addWidget(settings_group)
    layout.addStretch(1)
    self.log_info("Settings tab initialized")

def bind_settings_methods(gui):
    """Bind settings-related methods to the GUI instance."""
    gui.load_settings = load_settings_from_json.__get__(gui, gui.__class__)
    gui.save_settings = save_settings_to_json.__get__(gui, gui.__class__)
    gui.build_settings_ui = build_settings_ui.__get__(gui, gui.__class__)

