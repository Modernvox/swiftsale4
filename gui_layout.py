# -*- coding: utf-8 -*-
import os
import re
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QLineEdit, QCheckBox, QTextEdit, QTextBrowser,
    QTableWidget, QScrollBar, QTabWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QSizePolicy, QTreeWidget, QTreeWidgetItem,
    QSpacerItem, QWidget, QStatusBar, QApplication
)
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QPixmap, QFont, QCursor, QRegularExpressionValidator
from config_qt import get_resource_path

def setup_ui(main_window, is_dev_mode=None):
    """Initialize the GUI layout and widgets for SwiftSaleApp with optimized layout."""
    if is_dev_mode is None:
        is_dev_mode = os.getenv("FLASK_ENV", "production").lower() != "production"

    main_window.setWindowTitle("SwiftSale")
    main_window.setFixedWidth(960)  # Set window width
    main_window.setMinimumHeight(700)

    # Load external stylesheet for dark theme
    try:
        with open(get_resource_path("style.qss"), "r") as f:
            main_window.setStyleSheet(f.read())
    except Exception as e:
        main_window.log_error(f"Failed to load stylesheet: {e}")

    # Central widget and main layout
    central_widget = QFrame()
    main_window.setCentralWidget(central_widget)
    main_layout = QVBoxLayout(central_widget)
    main_layout.setContentsMargins(8, 8, 8, 8)
    main_layout.setSpacing(8)

    # Header section
    header_frame = QFrame()
    header_frame.setObjectName("headerFrame")
    header_layout = QHBoxLayout(header_frame)
    header_layout.setContentsMargins(4, 4, 4, 4)
    header_layout.setSpacing(8)

    logo_path = get_resource_path("ssa_logo.png")
    try:
        spacer = QSpacerItem(20, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        header_layout.addItem(spacer)
        logo_pixmap = QPixmap(logo_path).scaled(75, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label = QLabel()
        logo_label.setPixmap(logo_pixmap)
        logo_label.setFixedSize(75, 75)
        header_layout.addWidget(logo_label)
        spacer = QSpacerItem(180, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        header_layout.addItem(spacer)
    except Exception as e:
        main_window.log_error(f"Failed to load logo: {e}")
        logo_label = QLabel("SwiftSale")
        logo_label.setFont(QFont("Arial", 12))
        header_layout.addWidget(logo_label)

    main_window.header_label = QLabel(f"SwiftSale App V4 - {main_window.user_email} ({main_window.tier})")
    main_window.header_label.setObjectName("headerLabel")
    main_window.header_label.setFont(QFont("Arial", 12, QFont.Bold))
    header_layout.addWidget(main_window.header_label)
    header_layout.addStretch(1)
    main_layout.addWidget(header_frame)

    # Main content split into left/right
    content_frame = QFrame()
    content_layout = QHBoxLayout(content_frame)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(8)

    # Left panel (Add Bidder + Analytics, fixed width 280–300px)
    left_frame = QFrame()
    left_frame.setFixedWidth(290)  # Fixed width for left panel
    left_layout = QVBoxLayout(left_frame)
    left_layout.setContentsMargins(4, 4, 4, 4)
    left_layout.setSpacing(8)

    # Add Bidder Section
    input_group = QGroupBox("Add Bidder")
    input_group.setFixedWidth(280)
    input_layout = QGridLayout(input_group)
    input_layout.setContentsMargins(8, 8, 8, 8)
    input_layout.setSpacing(6)

    input_layout.addWidget(QLabel("Username:"), 0, 0)

    main_window.username_entry = QLineEdit()
    main_window.username_entry.setObjectName("usernameEntry")
    main_window.username_entry.setFixedHeight(28)

    # Apply alphanumeric validator (letters and numbers only, max 40 characters)
    regex = QRegularExpression(r"^[A-Za-z0-9_]{0,40}$")
    validator = QRegularExpressionValidator(regex)
    main_window.username_entry.setValidator(validator)

    # Custom focusInEvent to sanitize pasted text
    def focus_in_event_override(event):
        clipboard = QApplication.clipboard()
        raw_text = clipboard.text().strip()
        sanitized = re.sub(r'[^A-Za-z0-9]', '', raw_text)[:40]
        main_window.username_entry.setText(sanitized)
        QLineEdit.focusInEvent(main_window.username_entry, event)

    main_window.username_entry.focusInEvent = focus_in_event_override

    input_layout.addWidget(main_window.username_entry, 0, 1, 1, 3)

    main_window.add_bidder_button = QPushButton("Add Bidder")
    main_window.add_bidder_button.setStyleSheet("""
        QPushButton {
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            border-radius: 4px;
            padding: 4px 8px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
    """)
    input_layout.addWidget(main_window.add_bidder_button, 1, 1)
    main_window.clear_button = QPushButton("Clear")
    main_window.clear_button.setObjectName("danger")
    input_layout.addWidget(main_window.clear_button, 1, 2)

    input_layout.addWidget(QLabel("Quantity:"), 2, 0)
    main_window.qty_entry = QLineEdit("1")
    input_layout.addWidget(main_window.qty_entry, 2, 1, 1, 3)

    input_layout.addWidget(QLabel("Weight:"), 3, 0)
    main_window.weight_entry = QLineEdit()
    input_layout.addWidget(main_window.weight_entry, 3, 1, 1, 3)

    main_window.giveaway_var = QCheckBox("Giveaway")
    input_layout.addWidget(main_window.giveaway_var, 4, 0, 1, 2)

    main_window.giveaway_help_button = QPushButton("?")
    main_window.giveaway_help_button.setFixedWidth(20)
    main_window.giveaway_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.giveaway_help_button.setAccessibleName("help")
    input_layout.addWidget(main_window.giveaway_help_button, 4, 2)

    left_layout.addWidget(input_group)

    # Analytics Section
    analytics_group = QGroupBox("Analytics & Timer")
    analytics_group.setFixedWidth(280)
    analytics_layout = QVBoxLayout(analytics_group)
    analytics_layout.setContentsMargins(8, 8, 8, 8)
    analytics_layout.setSpacing(6)

    analytics_layout.addWidget(QLabel("Top Buyers:"))
    main_window.top_buyers_text = QTextEdit()
    main_window.top_buyers_text.setFixedHeight(100)
    analytics_layout.addWidget(main_window.top_buyers_text)

    top_buyer_row = QHBoxLayout()
    main_window.top_buyer_copy_label = QLabel("Click to copy top buyer(s)")
    main_window.top_buyer_copy_label.setCursor(QCursor(Qt.PointingHandCursor))
    top_buyer_row.addWidget(main_window.top_buyer_copy_label)
    main_window.top_buyer_help_button = QPushButton("?")
    main_window.top_buyer_help_button.setFixedWidth(20)
    main_window.top_buyer_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.top_buyer_help_button.setAccessibleName("help")
    top_buyer_row.addWidget(main_window.top_buyer_help_button)
    analytics_layout.addLayout(top_buyer_row)

    telegram_row = QHBoxLayout()
    main_window.telegram_label = QLabel("Telegram Integration")
    telegram_row.addWidget(main_window.telegram_label)
    main_window.telegram_help_button = QPushButton("?")
    main_window.telegram_help_button.setFixedWidth(20)
    main_window.telegram_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.telegram_help_button.setAccessibleName("help")
    telegram_row.addWidget(main_window.telegram_help_button)
    analytics_layout.addLayout(telegram_row)

    main_window.stats_label = QLabel("Avg Sell Rate: N/A")
    main_window.stats_label.setFont(QFont("Arial", 12, QFont.Bold))
    analytics_layout.addWidget(main_window.stats_label)

    main_window.timer_label = QLabel("00:00:00")
    main_window.timer_label.setObjectName("timerLabel")
    main_window.timer_label.setAlignment(Qt.AlignCenter)
    main_window.timer_label.setFont(QFont("Arial", 14, QFont.Bold))
    main_window.timer_label.setFixedHeight(28)
    analytics_layout.addWidget(main_window.timer_label)

    analytics_btn_row = QFrame()
    analytics_btn_layout = QHBoxLayout(analytics_btn_row)
    analytics_btn_layout.setSpacing(4)

    main_window.show_sell_rate_button = QPushButton("Sell Rate")
    analytics_btn_layout.addWidget(main_window.show_sell_rate_button)

    main_window.start_show_button = QPushButton("Start")
    main_window.start_show_button.setObjectName("green")
    analytics_btn_layout.addWidget(main_window.start_show_button)

    main_window.pause_button = QPushButton("Pause")
    main_window.pause_button.setObjectName("yellow")
    analytics_btn_layout.addWidget(main_window.pause_button)

    main_window.stop_button = QPushButton("Stop")
    main_window.stop_button.setObjectName("danger")
    analytics_btn_layout.addWidget(main_window.stop_button)

    analytics_layout.addWidget(analytics_btn_row)

    giveaway_btn_row = QFrame()
    giveaway_btn_layout = QHBoxLayout(giveaway_btn_row)
    giveaway_btn_layout.setSpacing(4)

    main_window.start_giveaway_button = QPushButton("Giveaway")
    giveaway_btn_layout.addWidget(main_window.start_giveaway_button)

    main_window.start_flash_sale_button = QPushButton("Flash Sale")
    giveaway_btn_layout.addWidget(main_window.start_flash_sale_button)

    main_window.flash_sale_text_help_button = QPushButton("?")
    main_window.flash_sale_text_help_button.setFixedWidth(20)
    main_window.flash_sale_text_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.flash_sale_text_help_button.setAccessibleName("help")
    giveaway_btn_layout.addWidget(main_window.flash_sale_text_help_button)

    analytics_layout.addWidget(giveaway_btn_row)
    left_layout.addWidget(analytics_group)
    left_layout.addStretch(1)

    content_layout.addWidget(left_frame)

    # Right panel (Bidders, expanding)
    right_frame = QFrame()
    right_layout = QVBoxLayout(right_frame)
    right_layout.setContentsMargins(4, 4, 4, 4)
    right_layout.setSpacing(8)

    # Bins Used Label
    main_window.bins_used_frame = QFrame()
    bins_used_layout = QHBoxLayout(main_window.bins_used_frame)
    bins_used_layout.setContentsMargins(4, 4, 4, 4)
    main_window.bins_used_label = QLabel("Bins Used: 0/20")
    main_window.bins_used_label.setFont(QFont("Arial", 10, QFont.Bold))
    bins_used_layout.addWidget(main_window.bins_used_label, alignment=Qt.AlignCenter)
    right_layout.addWidget(main_window.bins_used_frame)

    # Bidders Table
    bidders_group = QGroupBox("Bidders")
    bidders_layout = QVBoxLayout(bidders_group)
    bidders_layout.setContentsMargins(8, 8, 8, 8)
    bidders_layout.setSpacing(6)

    header_frame = QFrame()
    header_layout = QHBoxLayout(header_frame)
    header_layout.addWidget(QLabel("Bidders"))
    main_window.toggle_button = QPushButton("+")
    main_window.toggle_button.setFixedWidth(25)
    header_layout.addWidget(main_window.toggle_button)
    header_layout.addStretch(1)
    bidders_layout.addWidget(header_frame)
    main_window.toggle_button.clicked.connect(main_window.toggle_treeview)

    latest_bidder_box = QFrame()
    main_window.latest_bidder_layout = QHBoxLayout(latest_bidder_box)
    main_window.latest_bidder_label = QLabel("Latest: None")
    main_window.latest_bidder_label.setFont(QFont("Arial", 16, QFont.Bold))
    main_window.latest_bidder_layout.addWidget(main_window.latest_bidder_label)
    main_window.bin_number_label = QLabel("")
    main_window.bin_number_label.setFont(QFont("Arial", 28, QFont.Bold))
    main_window.latest_bidder_layout.addWidget(main_window.bin_number_label)
    main_window.latest_bidder_layout.addStretch(1)
    bidders_layout.addWidget(latest_bidder_box)

    main_window.tree_frame = QFrame()
    tree_layout = QHBoxLayout(main_window.tree_frame)
    main_window.bidders_tree = QTreeWidget()
    main_window.bidders_tree.setColumnCount(6)
    main_window.bidders_tree.setHeaderLabels([
        "Username", "Qty", "Bin", "Giveaway", "Weight", "Timestamp"
    ])
    main_window.bidders_tree.header().setStretchLastSection(True)
    tree_layout.addWidget(main_window.bidders_tree)
    main_window.scrollbar = QScrollBar(Qt.Vertical)
    main_window.bidders_tree.setVerticalScrollBar(main_window.scrollbar)
    tree_layout.addWidget(main_window.scrollbar)
    bidders_layout.addWidget(main_window.tree_frame, stretch=1)

    # Combined button row for import, export, sort bin, and clear
    button_row = QFrame()
    button_row_layout = QHBoxLayout(button_row)
    button_row_layout.setSpacing(4)
    button_row_layout.setContentsMargins(0, 0, 0, 0)

    main_window.import_csv_button = QPushButton("Import")
    main_window.import_csv_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    button_row_layout.addWidget(main_window.import_csv_button)

    main_window.export_csv_button = QPushButton("Export")
    main_window.export_csv_button.setObjectName("exportCsvButton")
    main_window.export_csv_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    button_row_layout.addWidget(main_window.export_csv_button)

    main_window.export_csv_help_button = QPushButton("?")
    main_window.export_csv_help_button.setFixedWidth(20)
    main_window.export_csv_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.export_csv_help_button.setAccessibleName("help")
    button_row_layout.addWidget(main_window.export_csv_help_button)

    main_window.sort_bin_asc_button = QPushButton("Sort Bin ↑")
    main_window.sort_bin_asc_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    button_row_layout.addWidget(main_window.sort_bin_asc_button)

    main_window.sort_bin_desc_button = QPushButton("Sort Bin ↓")
    main_window.sort_bin_desc_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    button_row_layout.addWidget(main_window.sort_bin_desc_button)

    main_window.sort_bin_desc_help_button = QPushButton("?")
    main_window.sort_bin_desc_help_button.setFixedWidth(20)
    main_window.sort_bin_desc_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.sort_bin_desc_help_button.setAccessibleName("help")
    button_row_layout.addWidget(main_window.sort_bin_desc_help_button)

    main_window.clear_bidders_button = QPushButton("Clear")
    main_window.clear_bidders_button.setObjectName("danger")
    main_window.clear_bidders_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    button_row_layout.addWidget(main_window.clear_bidders_button)

    main_window.clear_bidders_help_button = QPushButton("?")
    main_window.clear_bidders_help_button.setFixedWidth(20)
    main_window.clear_bidders_help_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    main_window.clear_bidders_help_button.setAccessibleName("help")
    button_row_layout.addWidget(main_window.clear_bidders_help_button)

    bidders_layout.addWidget(button_row)

    right_layout.addWidget(bidders_group, stretch=1)
    content_layout.addWidget(right_frame, stretch=2)
    main_layout.addWidget(content_frame, stretch=1)

    # Settings Tabs
    main_window.notebook = QTabWidget()
    main_window.notebook.setObjectName("settingsNotebook")
    main_window.notebook.setMinimumHeight(500)
    main_window.notebook.setVisible(False)

    howto_tab = QWidget()
    howto_layout = QVBoxLayout(howto_tab)
    howto_tab.setObjectName("howtoTab")

    howto_text = QTextBrowser()
    howto_text.setOpenExternalLinks(True)
    howto_text.setStyleSheet("font-size: 14px; line-height: 1.5;")
    howto_text.setHtml("""
        <h2>Getting Started with SwiftSale</h2>
        <p><b>Step 1: Activate DoubleclickCopy.exe</b><br>Run DoubleClickCopy.exe from helpers folder to enable double-click copy mode.</p>
        <p><b>Step 2: Start Your Whatnot Show</b><br>SwiftSale tracks winning bidders alongside your live sale.</p>
        <p><b>Step 3: Click "Start Show"</b><br>Starts timer and clears previous data.</p>
        <p><b>Step 4: Add Winning Bidders</b><br>Auto-paste usernames and assign bins.</p>
        <p><b>Step 5: Real-Time Bin Assignment</b><br>Track bins used and buyer details.</p>
        <p><b>Step 6: Annotate or Print Labels</b><br>Stamp bin numbers or generate CSV packing lists.</p>
        <p><b>Step 7: Export/Import Shows</b><br>Save or resume show data via CSV.</p>
        <p><b>Bonus Tools:</b> Giveaway, Flash Sale, Sell Rate, Top Buyer shoutouts.</p>
        <p><b>More help at <a href="https://swiftsaleapp.com">swiftsaleapp.com</a></p>
    """)
    howto_layout.addWidget(howto_text)
    main_window.notebook.addTab(howto_tab, "How to Use")

    main_window.settings_frame = QFrame()
    main_window.settings_frame.setObjectName("settingsTab")
    main_window.subscription_frame = QFrame()
    main_window.subscription_frame.setObjectName("subscriptionTab")
    main_window.annotate_frame = QFrame()
    main_window.annotate_frame.setObjectName("annotateTab")
    main_window.notebook.addTab(main_window.settings_frame, "Settings")
    main_window.notebook.addTab(main_window.subscription_frame, "Subscription")
    main_window.notebook.addTab(main_window.annotate_frame, "Annotate Labels")
    main_layout.addWidget(main_window.notebook)

    # Initialize tab content
    main_window.build_settings_ui(main_window.settings_frame)
    main_window.settings_initialized = True
    main_window.build_subscription_ui(main_window.subscription_frame)
    main_window.subscription_initialized = True
    main_window.build_annotate_ui(main_window.annotate_frame)
    main_window.annotate_initialized = True

    status_bar = QStatusBar()
    footer_text = f"{main_window.tier} | Install ID: {main_window.install_id} | Synced"
    if is_dev_mode:
        footer_text += "  ⚠ DEV MODE – No Payments Required"
    main_window.footer_label = QLabel(footer_text)
    main_window.footer_label.setFont(QFont("Arial", 9))
    main_window.footer_label.setTextFormat(Qt.RichText)
    main_window.footer_label.setStyleSheet("padding-bottom: 10px; padding-left: 12px;")
    main_window.footer_label.setText(footer_text)
    status_bar.addWidget(main_window.footer_label)

    main_window.toggle_tabs_btn = QPushButton("Settings")
    main_window.toggle_tabs_btn.setFixedWidth(120)
    main_window.toggle_tabs_btn.setObjectName("settingsButton")
    status_bar.addPermanentWidget(main_window.toggle_tabs_btn)
    main_window.setStatusBar(status_bar)

    # Final UI updates
    main_window.update_header_and_footer()
    main_window.update_top_buyers()
    main_window.populate_bidders_tree()
    main_window.update_bins_used_display()