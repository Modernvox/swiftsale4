import os
import sqlite3
import pdfplumber
import re
import io
import json
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from utils_qt import show_toast

from mailing_list_manager import MailingListManager
from datetime import datetime
from parse_utils import parse_packing_slip_address, extract_spent_amount

LABEL_WIDTH = 4 * inch
LABEL_HEIGHT = 6 * inch
PAGE_SIZE = (LABEL_WIDTH, LABEL_HEIGHT)
SETTINGS_FILE = os.path.join(os.getenv("LOCALAPPDATA"), "SwiftSale", "pdf_paths.json")


def extract_username_and_pickup_firstname(page_text: str):
    lines = page_text.splitlines()
    found_shipment_block = False
    for idx, line in enumerate(lines):
        trimmed = line.strip().lower()
        if (
            trimmed.startswith("ships to:") or
            trimmed.startswith("pickup to:") or
            trimmed.startswith("pickup address:")
        ):
            found_shipment_block = True
            for nxt in lines[idx + 1:]:
                if not nxt.strip():
                    continue
                m = re.search(r"([A-Za-z]+\s+[A-Za-z]+)?\s*\(([^)]+)\)", nxt.strip())
                if m:
                    first_name = m.group(1).strip() if m.group(1) else None
                    username = m.group(2).strip().lower()
                    if username != "new buyer!":
                        return username, first_name
                    else:
                        continue
            break
    return None, None


def remember_folder_path(folder):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"last_pdf_folder": folder}, f)


def get_last_folder():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f).get("last_pdf_folder")
    return os.path.expanduser("~")


def annotate_labels_qt(parent, db_path):
    folder_hint = get_last_folder()
    input_pdf_path, _ = QFileDialog.getOpenFileName(parent, "Select Whatnot PDF", folder_hint, "PDF Files (*.pdf)")
    if not input_pdf_path:
        return

    output_pdf_path, _ = QFileDialog.getSaveFileName(parent, "Save Annotated PDF", folder_hint, "PDF Files (*.pdf)")
    if not output_pdf_path:
        return

    remember_folder_path(os.path.dirname(output_pdf_path))

    try:
        skipped_pages = annotate_whatnot_pdf_with_bins_and_firstname(
            whatnot_pdf_path=input_pdf_path,
            bidders_db_path=db_path,
            output_pdf_path=output_pdf_path
        )

        QDesktopServices.openUrl(QUrl.fromLocalFile(output_pdf_path))

        msg = f"Annotated PDF created successfully."
        if skipped_pages:
            msg += f"\nSkipped {len(skipped_pages)} pages with unknown usernames."

        show_toast(parent, msg, icon_path="icons/stamp_icon.png")

    except Exception as e:
        QMessageBox.critical(parent, "Annotation Error", f"Failed to annotate PDF: {e}")


def annotate_whatnot_pdf_with_bins_and_firstname(
    whatnot_pdf_path: str,
    bidders_db_path: str,
    output_pdf_path: str,
    stamp_x: float = .40 * inch,
    stamp_y: float = 5.4 * inch,
    font_name: str = "Helvetica-Bold",
    font_size_app: int = 14,
    font_size_bin: int = 15,
    font_size_first: int = 19,
    font_size_default: int = 10
) -> list:
    conn = sqlite3.connect(bidders_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT username, bin_number FROM bin_assignments;")
    bin_map = {row[0].strip().lower(): row[1] for row in cursor.fetchall()}
    conn.close()

    mailing_list = MailingListManager()

    pdf_reader = PdfReader(whatnot_pdf_path)
    pdf_writer = PdfWriter()
    skipped_pages = []

    saved_usernames = set()

    with pdfplumber.open(whatnot_pdf_path) as plumber_pdf:
        current_buyer = None
        current_first_name = None
        current_spent_total = 0.0
        current_address_data = None

        for page_index, (original_page, plumber_page) in enumerate(zip(pdf_reader.pages, plumber_pdf.pages)):
            page_text = plumber_page.extract_text() or ""
            page_text_lower = page_text.lower()

            is_pickup = "local pickup order" in page_text_lower or "pickup address:" in page_text_lower
            is_packing_slip = "packing slip" in page_text_lower
            is_new_label = is_pickup or is_packing_slip

            spent = extract_spent_amount(page_text)
            print(f"[DEBUG] Page {page_index + 1} subtotal: ${spent:.2f}")

            if is_new_label:
                if current_buyer and current_address_data:
                    mailing_entry = {
                        **current_address_data,
                        "spent": current_spent_total,
                        "order_date": datetime.today().strftime("%Y-%m-%d"),
                        "order_id": f"PG{page_index:03}"
                    }
                    print(f"[DEBUG] Final mailing entry: {mailing_entry}")
                    if current_buyer not in saved_usernames:
                        mailing_list.add_or_update_entry(mailing_entry)
                        saved_usernames.add(current_buyer)
                    current_spent_total = 0.0  # 🔧 Reset to avoid duplicate subtotal accumulation


                username, full_name = extract_username_and_pickup_firstname(page_text)
                if not username:
                    skipped_pages.append((page_index, "no_username"))
                    pdf_writer.add_page(original_page)
                    continue

                address_data = parse_packing_slip_address(page_text)
                if not address_data:
                    skipped_pages.append((page_index, "no_address_data"))
                    print(f"[DEBUG] Skipped: address parse failed for {username}")
                    pdf_writer.add_page(original_page)
                    continue

                current_buyer = username.lower()
                current_first_name = full_name

                pickup_note = "PICK UP" if is_pickup else address_data.get("address_line_2", "")
                current_address_data = {
                    "full_name": address_data["full_name"],
                    "username": current_buyer,
                    "email": "",
                    "address_line_1": address_data["address_line_1"],
                    "address_line_2": pickup_note,
                    "city": address_data["city"],
                    "state": address_data["state"],
                    "zip_code": address_data["zip_code"]
                }
                current_spent_total = spent
            else:
                if current_buyer:
                    current_spent_total += spent

            draw_overlay = is_new_label
            bin_number = bin_map.get(current_buyer)

            if draw_overlay:
                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=PAGE_SIZE)

                if bin_number:
                    label_text = "SwiftSale App Bin: "
                    can.setFont(font_name, font_size_app)
                    can.drawString(stamp_x, stamp_y + font_size_first + 4, label_text)
                
                    label_width = can.stringWidth(label_text, font_name, font_size_app)
                    can.setFont(font_name, font_size_bin + 16)  # e.g., 19
                    can.drawString(stamp_x + label_width + 30, stamp_y + font_size_first - 4, f"#{bin_number}")

                    if is_pickup and current_first_name:
                        can.setFont(font_name, font_size_first)
                        can.drawString(0.40 * inch, 4.72 * inch, f"****{current_first_name}****")
                else:
                    skipped_pages.append((page_index, current_buyer or "unknown"))
                    can.setFont(font_name, font_size_app)
                    app_label = "SwiftSale App:"
                    can.drawString(stamp_x, stamp_y + font_size_first + 8, app_label)
                    text_width = can.stringWidth(app_label, font_name, font_size_app)
                    can.setFont(font_name, font_size_default)
                    can.drawString(stamp_x + text_width + 10, stamp_y + font_size_first + 4, "Givvy or Flash Sale?")
                    

                can.save()
                packet.seek(0)
                overlay_pdf = PdfReader(packet)
                overlay_page = overlay_pdf.pages[0]
                original_page.merge_page(overlay_page)

            pdf_writer.add_page(original_page)

        if current_buyer and current_address_data and current_buyer not in saved_usernames:
            mailing_entry = {
                **current_address_data,
                "spent": current_spent_total,
                "order_date": datetime.today().strftime("%Y-%m-%d"),
                "order_id": f"PG{len(pdf_reader.pages):03}"
            }
            print(f"[DEBUG] Final mailing entry (EOF): {mailing_entry}")
            mailing_list.add_or_update_entry(mailing_entry)

    with open(output_pdf_path, "wb") as out_f:
        pdf_writer.write(out_f)

    return skipped_pages
