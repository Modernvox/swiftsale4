from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QTextBrowser
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

def create_help_dialog(gui, title, help_text):
    """Create a help dialog styled with style.qss."""
    dialog = QDialog(gui)
    dialog.setObjectName("HelpDialog")  # Apply HelpDialog styles from style.qss
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)

    # Title label
    title_label = QLabel(title)
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)

    # Help content
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)

    # Close button
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)

    return dialog

def show_giveaway_help(gui):
    """Show help dialog for giveaways."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Handling Unrecorded Giveaways (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "SwiftSale assigns bins sequentially (1-500) to winning bidders, not giveaway winners, unless manually recorded during the show (not recommended).\n\n"
        "If you assign bins 1-20 but skip 2 giveaways, bins are still assigned 1-20 to bidders in order.\n\n"
        "SwiftSale's Annotated Labels tool will mark giveaway's and (or) flash sales as such automatically.\n\n"
        )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed giveaway help pop-up")

def show_telegram_help(gui):
    """Show help dialog for Telegram notifications."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Telegram Notifications (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "SwiftSale sends bin assignment notifications to a Telegram chat in real-time.\n\n"
        "**Note**: Chat ID is optional; leave blank to disable.\n\n"
        "**Steps**:\n"
        "1. **Get Chat ID**:\n"
        "   - Create/add bot to a Telegram group.\n"
        "   - Use @getidsbot to get the Chat ID (@public or numeric).\n"
        "2. **Enter Chat ID**:\n"
        "   - Input in 'Settings' > 'Telegram Chat ID' and save.\n"
        "3. **Notifications**:\n"
        "   - New bin assignments send messages (e.g., 'Username: testuser | Bin: 5').\n\n"
        "**Notes**:\n"
        "- Ensure bot has message permissions.\n"
        "- Notifications only for new bins, not giveaways.\n"
        "- Check ID/permissions if notifications fail."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed Telegram Help pop-up")


def show_import_csv_help(gui):
    """Show help dialog for importing CSV."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Importing CSV (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Import CSV' button allows you to import bidder data from a CSV file.\n\n"
        "**CSV Format**:\n"
        "- Columns: username, qty, is_giveaway, weight (optional)\n"
        "- Example: username,qty,is_giveaway,weight\n"
        "  testuser,2,False,1.5\n\n"
        "**Steps**:\n"
        "1. Click 'Import CSV' and select a .csv file.\n"
        "2. The system will add bidders and assign bins.\n"
        "3. The bidders table and bins used display will update.\n\n"
        "**Notes**:\n"
        "- Ensure the CSV has the correct headers.\n"
        "- Invalid entries will be skipped with an error message."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed import CSV help pop-up")

def show_export_csv_help(gui):
    """Show help dialog for exporting CSV."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Exporting CSV (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Export CSV' button saves the current bidders list to a CSV file.\n\n"
        "**CSV Format**:\n"
        "- Columns: username, qty, bin_number, is_giveaway, weight, timestamp\n"
        "- Example: username,qty,bin_number,is_giveaway,weight,timestamp\n"
        "  testuser,2,5,False,1.5,2025-07-11 17:06:00\n\n"
        "**Steps**:\n"
        "1. Click 'Export CSV' and choose a save location.\n"
        "2. The system will save the bidders table data to the file.\n\n"
        "**Notes**:\n"
        "- The exported CSV can be used for backups or re-importing."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed export CSV help pop-up")

def show_sort_bin_asc_help(gui):
    """Show help dialog for sorting by bin ascending."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Sort by Bin Ascending (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Sort by Bin ↑' button sorts the bidders table by bin number in ascending order.\n\n"
        "**Steps**:\n"
        "1. Click 'Sort by Bin ↑' to reorder the table.\n"
        "2. Bidders will be listed from lowest to highest bin number.\n\n"
        "**Notes**:\n"
        "- Sorting updates the table display only.\n"
        "- Use 'Sort by Bin ↓' for descending order."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed sort by bin ascending help pop-up")

def show_sort_bin_desc_help(gui):
    """Show help dialog for sorting by bin descending."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Sort by Bin Descending (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Sort by Bin ↓' button sorts the bidders table by bin number in descending order.\n\n"
        "**Steps**:\n"
        "1. Click 'Sort by Bin ↓' to reorder the table.\n"
        "2. Bidders will be listed from highest to lowest bin number.\n\n"
        "**Notes**:\n"
        "- Sorting updates the table display only.\n"
        "- Use 'Sort by Bin ↑' for ascending order."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed sort by bin descending help pop-up")

def show_clear_bidders_help(gui):
    """Show help dialog for clearing bidders."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Clearing Bidders (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Clear Bidders' button removes all bidders from the database and resets the UI.\n\n"
        "**Steps**:\n"
        "1. Click 'Clear Bidders'.\n"
        "2. Confirm the action in the dialog.\n"
        "3. The bidders table, bins used display, and latest bidder display will reset.\n\n"
        "**Notes**:\n"
        "- This action cannot be undone.\n"
        "- Use with caution to avoid losing bidder data."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed clear bidders help pop-up")

def show_top_buyer_help(gui):
    """Show help dialog for top buyer message."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Top Buyer Message (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Click to copy top buyer(s) message' label copies a formatted message of top buyers to the clipboard.\n\n"
        "**Steps**:\n"
        "1. Click the label to copy the message.\n"
        "2. The message uses the template in 'Settings' > 'Top Buyer Text'.\n\n"
        "**Notes**:\n"
        "- Top buyers are determined by the number of bins assigned.\n"
        "- Ensure a message template is set in Settings."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed top buyer help pop-up")

def show_giveaway_text_help(gui):
    """Show help dialog for giveaway text."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Giveaway Text (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Giveaway Text' field in Settings defines the message copied when clicking 'Start Giveaway'.\n\n"
        "**Steps**:\n"
        "1. Set the giveaway message in 'Settings' > 'Giveaway Text'.\n"
        "2. Click 'Start Giveaway' to copy the message to the clipboard.\n\n"
        "**Notes**:\n"
        "- Ensure the message is set to avoid errors.\n"
        "- The message is used for announcing giveaways during the show."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed giveaway text help pop-up")

def show_flash_sale_text_help(gui):
    """Show help dialog for flash sale text."""
    dialog = QDialog(gui)
    dialog.setWindowTitle("SwiftSale Help")
    dialog.setFixedSize(600, 400)
    layout = QVBoxLayout(dialog)
    title_label = QLabel("Flash Sale Text (SwiftSale)")
    title_label.setFont(QFont("Arial", 12, QFont.Bold))
    title_label.setWordWrap(True)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)
    help_text = (
        "The 'Flash Sale Text' field in Settings defines the message copied when clicking 'Start Flash Sale'.\n\n"
        "**Steps**:\n"
        "1. Set the flash sale message in 'Settings' > 'Flash Sale Text'.\n"
        "2. Click 'Start Flash Sale' to copy the message to the clipboard.\n\n"
        "**Notes**:\n"
        "- Ensure the message is set to avoid errors.\n"
        "- The message is used for announcing flash sales during the show."
    )
    help_content = QTextBrowser()
    help_content.setPlainText(help_text)
    layout.addWidget(help_content)
    close_button = QPushButton("Close")
    close_button.clicked.connect(dialog.accept)
    layout.addWidget(close_button)
    dialog.exec()
    gui.log_info("Displayed flash sale text help pop-up")