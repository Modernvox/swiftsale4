def setup_ui(main_window):
    """Initialize the GUI layout and widgets with improved spacing and scalability."""
    from PySide6.QtWidgets import (
        QFrame, QLabel, QPushButton, QLineEdit, QCheckBox, QTextEdit, QTextBrowser,
        QTableWidget, QScrollBar, QTabWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QGroupBox, QSizePolicy, QTreeWidget, QTreeWidgetItem,
        QSpacerItem, QWidget
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QFont, QCursor
    from config_qt import get_resource_path

    main_window.setWindowTitle("SwiftSale")
    main_window.setMinimumSize(800, 650)

    # Load external stylesheet
    try:
        with open(get_resource_path("style.qss"), "r") as f:
            main_window.setStyleSheet(f.read())
    except Exception as e:
        main_window.log_error(f"Failed to load stylesheet: {e}")

    central_widget = QFrame()
    main_window.setCentralWidget(central_widget)
    main_layout = QVBoxLayout(central_widget)
    main_layout.setContentsMargins(10, 10, 10, 10)
    main_layout.setSpacing(10)

    # Header section
    header_frame = QFrame()
    header_frame.setObjectName("headerFrame")
    header_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    header_layout = QHBoxLayout(header_frame)
    header_layout.setContentsMargins(5, 5, 5, 5)
    header_layout.setSpacing(10)

    logo_path = get_resource_path("swiftsale_logo.png")
    try:
        logo_pixmap = QPixmap(logo_path).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label = QLabel()
        logo_label.setPixmap(logo_pixmap)
        logo_label.setFixedSize(50, 50)
        header_layout.addWidget(logo_label)
    except Exception as e:
        main_window.log_error(f"Failed to load logo: {e}")
        logo_label = QLabel("SwiftSale")
        logo_label.setFont(QFont("Arial", 14))
        logo_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        header_layout.addWidget(logo_label)

    main_window.header_label = QLabel(f"SwiftSale - {main_window.user_email} ({main_window.tier}) | Build Whatnot Orders in Realtime")
    main_window.header_label.setObjectName("headerLabel")
    main_window.header_label.setFont(QFont("Arial", 14, QFont.Bold))
    main_window.header_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    header_layout.addWidget(main_window.header_label)
    header_layout.addStretch(1)
    main_layout.addWidget(header_frame)

    # Main content split into left/right
    content_frame = QFrame()
    content_layout = QHBoxLayout(content_frame)
    content_layout.setContentsMargins(5, 5, 5, 5)
    content_layout.setSpacing(10)

    # Left panel frame
    left_frame = QFrame()
    left_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    left_layout = QVBoxLayout(left_frame)
    left_layout.setContentsMargins(5, 5, 5, 5)
    left_layout.setSpacing(10)

    # ─── Add Bidder Section ──────────────────────────────────────
    input_group = QGroupBox("Add Bidder")
    input_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    input_layout = QGridLayout(input_group)
    input_layout.setContentsMargins(10, 10, 10, 10)
    input_layout.setSpacing(8)

    input_layout.addWidget(QLabel("Username:"), 0, 0)
    main_window.username_entry = QLineEdit()
    main_window.username_entry.focusInEvent = main_window.auto_paste_username
    main_window.username_entry.setMinimumWidth(100)
    main_window.username_entry.setFixedHeight(32)
    input_layout.addWidget(main_window.username_entry, 0, 1)

    main_window.add_bidder_button = QPushButton("Add Bidder")
    main_window.add_bidder_button.setMinimumWidth(100)
    main_window.add_bidder_button.setStyleSheet("""
        QPushButton {
            background-color: #4CAF50;
            color: white;
            font-weight: bold;
            border-radius: 4px;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background-color: #45a049;
        }
    """)
    input_layout.addWidget(main_window.add_bidder_button, 0, 2)


    main_window.clear_button = QPushButton("Clear")
    main_window.clear_button.setObjectName("danger")
    main_window.clear_button.setMinimumWidth(80)
    input_layout.addWidget(main_window.clear_button, 0, 3)

    input_layout.addWidget(QLabel("Quantity:"), 1, 0)
    main_window.qty_entry = QLineEdit("1")
    input_layout.addWidget(main_window.qty_entry, 1, 1)

    input_layout.addWidget(QLabel("Weight:"), 2, 0)
    main_window.weight_entry = QLineEdit()
    input_layout.addWidget(main_window.weight_entry, 2, 1)

    main_window.giveaway_var = QCheckBox("Giveaway")
    input_layout.addWidget(main_window.giveaway_var, 3, 0, 1, 2)

    left_layout.addWidget(input_group)

    # ─── Analytics Section ──────────────────────────────────────
    analytics_group = QGroupBox("Analytics")
    analytics_layout = QVBoxLayout(analytics_group)
    analytics_layout.setContentsMargins(10, 10, 10, 10)
    analytics_layout.setSpacing(8)

    analytics_layout.addWidget(QLabel("Top Buyers:"))
    main_window.top_buyers_text = QTextEdit()
    main_window.top_buyers_text.setFixedHeight(150)
    analytics_layout.addWidget(main_window.top_buyers_text)

    main_window.top_buyer_copy_label = QLabel("Click to copy top buyer(s) message")
    main_window.top_buyer_copy_label.setCursor(QCursor(Qt.PointingHandCursor))
    analytics_layout.addWidget(main_window.top_buyer_copy_label)

    main_window.stats_label = QLabel("Avg Sell Rate: N/A")
    main_window.stats_label.setFont(QFont("Arial", 14, QFont.Bold))
    analytics_layout.addWidget(main_window.stats_label)

    analytics_btn_row = QFrame()
    analytics_btn_layout = QHBoxLayout(analytics_btn_row)
    analytics_btn_layout.setSpacing(5)

    main_window.show_sell_rate_button = QPushButton("Show Sell Rate")
    analytics_btn_layout.addWidget(main_window.show_sell_rate_button)

    main_window.start_show_button = QPushButton("Start Show")
    main_window.start_show_button.setObjectName("green")
    analytics_btn_layout.addWidget(main_window.start_show_button)

    # Timer Label (shows elapsed time)
    main_window.timer_label = QLabel("00:00:00")
    main_window.timer_label.setObjectName("timerLabel")
    main_window.timer_label.setAlignment(Qt.AlignCenter)
    main_window.timer_label.setFont(QFont("Arial", 16, QFont.Bold))
    main_window.timer_label.setFixedHeight(30)
    left_layout.addWidget(main_window.timer_label)


    main_window.pause_button = QPushButton("Pause Timer")
    main_window.pause_button.setObjectName("yellow")
    analytics_btn_layout.addWidget(main_window.pause_button)

    main_window.stop_button = QPushButton("Stop Timer")
    main_window.stop_button.setObjectName("danger")
    analytics_btn_layout.addWidget(main_window.stop_button)

    main_window.start_giveaway_button = QPushButton("Start Giveaway")
    analytics_btn_layout.addWidget(main_window.start_giveaway_button)

    main_window.start_flash_sale_button = QPushButton("Start Flash Sale")
    analytics_btn_layout.addWidget(main_window.start_flash_sale_button)

    analytics_layout.addWidget(analytics_btn_row)

    main_window.giveaway_help_button = QPushButton("?")
    main_window.giveaway_help_button.setFixedWidth(30)
    analytics_layout.addWidget(main_window.giveaway_help_button, alignment=Qt.AlignLeft)

    left_layout.addWidget(analytics_group)
    left_layout.addStretch(1)

    content_layout.addWidget(left_frame, stretch=1)

    # ─── Right Panel: Bidders and Tree Table ─────────────────────
    right_frame = QFrame()
    right_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    right_layout = QVBoxLayout(right_frame)
    right_layout.setContentsMargins(5, 5, 5, 5)
    right_layout.setSpacing(10)

    # ─── Bins Used Label ─────────────────────────────────────────
    main_window.bins_used_frame = QFrame()
    bins_used_layout = QHBoxLayout(main_window.bins_used_frame)
    bins_used_layout.setContentsMargins(5, 5, 5, 5)
    bins_used_layout.setSpacing(5)

    main_window.bins_used_label = QLabel("Bins Used: 0/20")
    main_window.bins_used_label.setFont(QFont("Arial", 12, QFont.Bold))
    bins_used_layout.addStretch(1)
    bins_used_layout.addWidget(main_window.bins_used_label, alignment=Qt.AlignCenter)
    bins_used_layout.addStretch(1)

    right_layout.addWidget(main_window.bins_used_frame)

    # ─── Bidders Table ───────────────────────────────────────────
    bidders_group = QGroupBox("Bidders")
    bidders_layout = QVBoxLayout(bidders_group)
    bidders_layout.setContentsMargins(10, 10, 10, 10)
    bidders_layout.setSpacing(8)

    # Header + Toggle
    header_frame = QFrame()
    header_layout = QHBoxLayout(header_frame)
    header_layout.setSpacing(5)
    header_layout.addWidget(QLabel("Bidders"))

    main_window.toggle_button = QPushButton("+")
    main_window.toggle_button.setFixedWidth(30)
    header_layout.addWidget(main_window.toggle_button)
    header_layout.addStretch(1)
    bidders_layout.addWidget(header_frame)
    main_window.toggle_button.clicked.connect(main_window.toggle_treeview)


    # Latest bidder display
    latest_bidder_box = QFrame()
    main_window.latest_bidder_layout = QHBoxLayout(latest_bidder_box)
    main_window.latest_bidder_label = QLabel("Latest: None")
    main_window.latest_bidder_label.setFont(QFont("Arial", 18, QFont.Bold))
    main_window.latest_bidder_layout.addWidget(main_window.latest_bidder_label)

    main_window.bin_number_label = QLabel("")
    main_window.bin_number_label.setFont(QFont("Arial", 24, QFont.Bold))
    main_window.latest_bidder_layout.addWidget(main_window.bin_number_label)
    main_window.latest_bidder_layout.addStretch(1)

    bidders_layout.addWidget(latest_bidder_box)

    # Tree/Table widget
    main_window.tree_frame = QFrame()
    tree_layout = QHBoxLayout(main_window.tree_frame)
    bidders_layout.addWidget(main_window.tree_frame)

    main_window.bidders_tree = QTreeWidget()  # Use bidders_tree consistently
    main_window.bidders_tree.setColumnCount(6)
    main_window.bidders_tree.setHeaderLabels([
        "Username", "Qty", "Bin", "Giveaway", "Weight", "Timestamp"
    ])
    main_window.bidders_tree.setMinimumSize(400, 200)
    main_window.bidders_tree.header().setStretchLastSection(True)


    tree_layout.addWidget(main_window.bidders_tree)
    main_window.scrollbar = QScrollBar(Qt.Vertical)
    main_window.bidders_tree.setVerticalScrollBar(main_window.scrollbar)
    tree_layout.addWidget(main_window.scrollbar)

    bidders_layout.addWidget(main_window.tree_frame)

    # ─── Export / Import Buttons ─────────────────────────────────
    button_row = QFrame()
    button_row_layout = QHBoxLayout(button_row)

    main_window.print_bidders_button = QPushButton("Print Bidders")
    button_row_layout.addWidget(main_window.print_bidders_button)

    main_window.import_csv_button = QPushButton("Import CSV")
    button_row_layout.addWidget(main_window.import_csv_button)

    main_window.export_csv_button = QPushButton("Export CSV")
    button_row_layout.addWidget(main_window.export_csv_button)

    button_row_layout.addStretch(1)
    bidders_layout.addWidget(button_row)

    # ─── Sort and Clear ──────────────────────────────────────────
    sort_bin_frame = QFrame()
    sort_bin_layout = QHBoxLayout(sort_bin_frame)

    main_window.sort_bin_asc_button = QPushButton("Sort by Bin ↑")
    sort_bin_layout.addWidget(main_window.sort_bin_asc_button)

    main_window.sort_bin_desc_button = QPushButton("Sort by Bin ↓")
    sort_bin_layout.addWidget(main_window.sort_bin_desc_button)

    main_window.clear_bidders_button = QPushButton("Clear Bidders")
    main_window.clear_bidders_button.setObjectName("danger")
    sort_bin_layout.addWidget(main_window.clear_bidders_button)

    sort_bin_layout.addStretch(1)
    bidders_layout.addWidget(sort_bin_frame)

    right_layout.addWidget(bidders_group, stretch=1)
    content_layout.addWidget(right_frame, stretch=2)
    main_layout.addWidget(content_frame, stretch=1)

    # ─── Settings Toggle Button ───────────────────────────────────
    main_window.toggle_tabs_btn = QPushButton(" Settings")
    main_window.toggle_tabs_btn.setFixedWidth(100)
    main_layout.addWidget(main_window.toggle_tabs_btn, alignment=Qt.AlignRight)

    # ─── Settings Tabs (Hidden by Default) ───────────────────────
    main_window.notebook = QTabWidget()
    main_window.notebook.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    main_window.notebook.setMinimumHeight(400)

    main_window.settings_frame = QFrame()
    main_window.subscription_frame = QFrame()
    main_window.annotate_frame = QFrame()



    main_window.notebook.addTab(main_window.settings_frame, "Settings")
    main_window.notebook.addTab(main_window.subscription_frame, "Subscription")
    main_window.notebook.addTab(main_window.annotate_frame, "Annotate Labels")
    main_window.notebook.setVisible(False)
        # ─── How to Use Tab ─────────────────────────────────────────────
    howto_tab = QWidget()
    howto_layout = QVBoxLayout(howto_tab)
    howto_layout.setContentsMargins(20, 20, 20, 20)

    howto_text = QTextBrowser()
    howto_text.setOpenExternalLinks(True)
    howto_text.setStyleSheet("font-size: 13px; line-height: 1.6;")
    howto_text.setHtml("""
        <h2>📘 Getting Started with SwiftSale</h2>

        <h3>Step 1: After install, activate DoubleclickCopy.exe</h3>
        <p>After you've installed swiftsale navigate to your app's directory C:\\Users\\User(your user name)\\AppData\\Roaming\\SwiftSaleApp\\_internal\\helpers. Inside your helpers folder double click on DoubleClickCopy.exe (This activates the double click to copy feature in swiftsale which allows you to quickly copy Whatnot usernames by simply double clicking on each. Then all you need to do is click into the add bidder uername field to auto paste the winning buyers username and click Add bidder button to auto assign the user with next available bin number) To check if DoubleClickCopy.exe is running simply click on the ^ arrow on your windows taskbar located along the bottom of your screen. You'll see a symbol "H" running. That's it! You can now run swiftsale using the DoubleClickCopy Feature. You can disable the feature at anytime by right clicking on the file in your taskbar and selecting exit.</p>

        <h3>Step 2: Start Your Whatnot Show</h3>
        <p>Begin your live sale on the Whatnot app as you normally would. SwiftSale runs in parallel and is not directly connected to Whatnot — so you control the pace.</p>

        <h3>Step 3: Click "Start Show"</h3>
        <p>This activates the in-app timer and resets all live stats. It also enables bin tracking and unlocks real-time seller tools like giveaways and flash sales.</p>

        <h3>Step 4: Add Winning Bidders with "Add Bidder"</h3>
        <p>Copy winning buyers username from Whatnot, and autto-paste into the username field in SwiftSale by clicking into the field. The system assigns them to the next available bin from 1-500. Additionally, you can update/change Quantity(Set to 1 by default), Weight(optional and set "null" by default), and giveaway winner(s) (NOTE: Givvy's are optional, but we don't recommend recording them as Swiftsale will automatically mark unrecorded Giveaways or Flashsales as such during the annotate labels process after your show). </p>

        <h3>Step 5: Real-Time Bin Assignment</h3>
        <p>Every added buyer appears in the Bidders tab with their bin number. You can double-click rows to view each buyers transactions. Bins are tracked against your tier limits (Trial: 20, Bronze: 50, Silver: 150, Gold: 500). The Latest Bidder window keeps sellers updated in realtime so they can mark bin numbers as they sell.</p>

        <h3>Step 6: Use "Print Labels" or "Annotate Labels"</h3>
        <p>After the show, choose <b>Print Bidders</b> to generate a buyer list for packing, or use *Recommended: <b>Annotate Labels</b> to digitally stamp your Whatnot PDF labels with your assigned bin numbers(That Swiftsale assigned to each username during your show) and first names on local pickup slips for effecient organizing local pickups by first name and alphabetical sorting and retrieval.</p>

        <h3>Step 7: Export/Import Data</h3>
        <p>Use <b>Export CSV</b> to save a record of all bidders and bins. You can also <b>Import CSV</b> later to resume or rebuild an entire show or sync with a remote assistant. This helps with record keeping, duplicating shows or shipping handoffs.</p>

        <h3>Bonus Features:</h3>
        <ul>
            <li><b>Giveaway Mode:</b>Use preset messages to announce time-sensitive deals and copy them instantly to clipboard. Messages can be edited under in the settings tab by simply editing and saving your custom message. Default message is: "Givvy is up! Make sure you LIKE & SHARE! Winner announced shortly!"</li>
            <li><b>Flash Sale Mode:</b> Use preset messages to announce time-sensitive deals and copy them instantly to clipboard. Messages can be edited under in the settings tab by simply editing and saving your custom message. Default message is: "Flash Sale is Live! Grab these deals before they sell out!"</li>
            <li><b>Sell Rate Tracking:</b> Displays your live and average sell rate per minute along with estimated 2,3 and 4 hour sell rate in real time.</li>
            <li><b>Top Buyer Shoutouts:</b> Automatically analyzes top repeat buyers for end-of-show thank yous.</li>
        </ul>

        <p>For more tutorials and updates, visit:<br>
        <a href='https://swiftsaleapp.com'>https://swiftsaleapp.com</a></p>
    """)

    howto_layout.addWidget(howto_text)
    

    main_window.notebook.addTab(howto_tab, "How to Use")

    main_layout.addWidget(main_window.notebook, stretch=1)

    # ─── Initialize Tab Content ──────────────────────────────────
    main_window.build_settings_ui(main_window.settings_frame)
    main_window.settings_initialized = True

    main_window.build_subscription_ui(main_window.subscription_frame)
    main_window.subscription_initialized = True

    main_window.build_annotate_ui(main_window.annotate_frame)
    main_window.annotate_initialized = True


    # ─── Update Button ───────────────────────────────────────────
    main_window.update_btn = QPushButton("Check for Updates")
    main_window.update_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ─── Footer ──────────────────────────────────────────────────
    footer_frame = QFrame()
    footer_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    footer_layout = QHBoxLayout(footer_frame)
    footer_layout.setContentsMargins(5, 5, 5, 5)

    spacer = QSpacerItem(100, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
    footer_layout.addItem(spacer)

    main_window.footer_label = QLabel(
        f"SwiftSale - {main_window.tier} Tier - Latest Bin: {main_window.latest_bin_assignment}"
    )
    main_window.footer_label.setFont(QFont("Arial", 10))
    footer_layout.addWidget(main_window.footer_label)
    footer_layout.addStretch(1)
    main_layout.addWidget(footer_frame)


    # ─── Credit Section ──────────────────────────────────────────
    credit_frame = QFrame()
    credit_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    credit_layout = QHBoxLayout(credit_frame)
    credit_layout.setContentsMargins(5, 5, 5, 5)

    credit_label = QLabel("Developed By Michael St Pierre, ©2025")
    credit_layout.addWidget(credit_label, alignment=Qt.AlignCenter)
    main_layout.addWidget(credit_frame)

    # ─── Final UI Updates ────────────────────────────────────────
    main_window.update_header_and_footer()
    main_window.update_top_buyers()
    main_window.populate_bidders_tree()
    main_window.update_bins_used_display()