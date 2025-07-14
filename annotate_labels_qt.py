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
from PySide6.QtGui import QDesktopServices, QPixmap, QIcon
from PySide6.QtCore import QUrl
from utils_qt import show_toast  # Assumes toast + stamp icon handler lives in utils_qt.py

LABEL_WIDTH = 4 * inch
LABEL_HEIGHT = 6 * inch
PAGE_SIZE = (LABEL_WIDTH, LABEL_HEIGHT)
SETTINGS_FILE = os.path.join(os.getenv("LOCALAPPDATA"), "SwiftSale", "pdf_paths.json")

def extract_username_and_pickup_firstname(page_text: str):
    lines = page_text.splitlines()
    for idx, line in enumerate(lines):
        trimmed = line.strip().lower()
        is_pickup = (
            trimmed.startswith("pickup to:") or
            trimmed.startswith("pickup address:")
        )
        if trimmed.startswith("ships to:") or is_pickup:
            for nxt in lines[idx + 1:]:
                if not nxt.strip():
                    continue
                m = re.search(r"([A-Za-z]+)\s+[A-Za-z]+\s+\(([^)]+)\)", nxt)
                if m:
                    first_name = m.group(1)
                    username = m.group(2).strip().lower()
                    if username != "new buyer!":
                        return username, first_name if is_pickup else None
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
    stamp_x: float = 2.3 * inch,
    stamp_y: float = 5.6 * inch,
    font_name: str = "Helvetica-Bold",
    font_size_app: int = 10,
    font_size_bin: int = 14,
    font_size_first: int = 14,
    font_size_default: int = 10
) -> list:
    conn = sqlite3.connect(bidders_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT username, bin_number FROM bin_assignments;")
    bin_map = {row[0].strip().lower(): row[1] for row in cursor.fetchall()}
    conn.close()

    pdf_reader = PdfReader(whatnot_pdf_path)
    pdf_writer = PdfWriter()
    skipped_pages = []

    shipping_page = None
    pickup_page = None

    with pdfplumber.open(whatnot_pdf_path) as plumber_pdf:
        for page_index in range(len(pdf_reader.pages)):
            original_page = pdf_reader.pages[page_index]
            plumber_page = plumber_pdf.pages[page_index]
            page_text = plumber_page.extract_text() or ""

            username, first_name = extract_username_and_pickup_firstname(page_text)
            if not username:
                pdf_writer.add_page(original_page)
                continue

            bin_number = bin_map.get(username.lower())

            if not shipping_page and not first_name:
                shipping_page = original_page
            elif not pickup_page and first_name:
                pickup_page = original_page

            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=PAGE_SIZE)

            can.setFont(font_name, font_size_app)
            can.drawString(stamp_x, stamp_y + font_size_bin + 4, "SwiftSale App:")

            if bin_number is None:
                skipped_pages.append((page_index, username))
                can.setFont(font_name, font_size_default)
                can.drawString(stamp_x, stamp_y, "Possible")
                can.drawString(stamp_x, stamp_y - font_size_default, "(Givvy/FlashSale)")
            else:
                can.setFont(font_name, font_size_bin)
                can.drawString(stamp_x, stamp_y, f"Bin {bin_number}")
                if first_name:
                    can.setFont(font_name, font_size_first)
                    can.drawString(1.8 * inch, 4.8 * inch, first_name)

            can.save()
            packet.seek(0)
            overlay_pdf = PdfReader(packet)
            overlay_page = overlay_pdf.pages[0]
            original_page.merge_page(overlay_page)
            pdf_writer.add_page(original_page)

    with open(output_pdf_path, "wb") as out_f:
        pdf_writer.write(out_f)

    return skipped_pages
