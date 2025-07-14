from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSizePolicy, QCheckBox
from PySide6.QtCore import Qt
from gui_help_qt import show_telegram_help, show_top_buyer_help, show_giveaway_text_help, show_flash_sale_text_help
import sqlite3

def load_settings_from_db(self):
    """Load settings from the SQLite database."""
    try:
        with sqlite3.connect(self.bidders_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, multi_buyer_mode
                FROM settings WHERE email = ?
            """, (self.user_email,))
            result = cursor.fetchone()
            if result:
                self.chat_id, self.top_buyer_text, self.giveaway_announcement_text, self.flash_sale_announcement_text, self.multi_buyer_mode = result
                self.multi_buyer_mode = bool(self.multi_buyer_mode) if self.multi_buyer_mode is not None else False
            else:
                self.log_info("No settings found in database, using defaults")
            self.log_info("Settings loaded from database")
    except Exception as e:
        self.log_error(f"Failed to load settings: {e}")
        self.log_info("Using default settings")

def save_settings(self):
    """Save settings to the SQLite database."""
    try:
        with sqlite3.connect(self.bidders_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO settings (email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, multi_buyer_mode)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                self.user_email,
                self.chat_id_entry.text(),
                self.top_buyer_entry.text(),
                self.giveaway_entry.text(),
                self.flash_sale_entry.text(),
                self.multi_buyer_check.isChecked()
            ))
            conn.commit()
        self.chat_id = self.chat_id_entry.text()
        self.top_buyer_text = self.top_buyer_entry.text()
        self.giveaway_announcement_text = self.giveaway_entry.text()
        self.flash_sale_announcement_text = self.flash_sale_entry.text()
        self.multi_buyer_mode = self.multi_buyer_check.isChecked()
        self.log_info("Settings saved to database")
        QMessageBox.information(self, "Success", "Settings saved successfully")
    except Exception as e:
        self.log_error(f"Failed to save settings: {e}")
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
    top_buyer_help_button.clicked.connect(lambda: show_top_buyer_help(self))
    settings_layout.addWidget(top_buyer_help_button, 1, 2)

    # Row 2: Giveaway Text
    giveaway_label = QLabel("Giveaway Text:")
    giveaway_label.setMinimumWidth(120)  # Force label to take up space
    giveaway_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    settings_layout.addWidget(giveaway_label, 2, 0)

    self.giveaway_entry = QLineEdit(self.giveaway_announcement_text or "")
    self.giveaway_entry.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    self.giveaway_entry.setMinimumWidth(300)
    self.giveaway_entry.setStyleSheet("padding-left: 8px;")  # Optional for visual spacing
    settings_layout.addWidget(self.giveaway_entry, 2, 1)

    giveaway_text_help_button = QPushButton("?")
    giveaway_text_help_button.setFixedWidth(30)
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

    layout.addWidget(settings_group)
    layout.addStretch(1)
    self.log_info("Settings tab initialized")

def bind_settings_methods(gui):
    """Bind settings-related methods to the GUI instance."""
    gui.load_settings_from_db = load_settings_from_db.__get__(gui, gui.__class__)
    gui.save_settings = save_settings.__get__(gui, gui.__class__)
    gui.build_settings_ui = build_settings_ui.__get__(gui, gui.__class__)