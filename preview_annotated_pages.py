import tempfile
import os
import webbrowser
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

def preview_annotated_pages(pdf_path, db_path, stamp_x, stamp_y):
    """
    Generates a temporary PDF with a sample shipping and pickup page
    with overlays for visual preview.
    """
    from reportlab.lib.units import inch
    PAGE_SIZE = (4 * inch, 6 * inch)
    font_name = "Helvetica-Bold"
    font_size_app = 10
    font_size_bin = 14
    font_size_first = 14
    font_size_default = 10

    import pdfplumber
    import sqlite3
    import io

    preview_writer = PdfWriter()
    shipping_done = pickup_done = False

    # Load bin assignments
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT username, bin_number FROM bin_assignments;")
    bin_map = {row[0].strip().lower(): row[1] for row in cursor.fetchall()}
    conn.close()

    with pdfplumber.open(pdf_path) as plumber_pdf:
        pdf_reader = PdfReader(pdf_path)

        for i, page in enumerate(plumber_pdf.pages):
            page_text = page.extract_text() or ""
            username, first_name = extract_username_and_pickup_firstname(page_text)
            if not username:
                continue

            bin_number = bin_map.get(username.lower())
            is_pickup = any(line.lower().strip().startswith("pickup") for line in page_text.splitlines())

            if (is_pickup and pickup_done) or (not is_pickup and shipping_done):
                continue  # skip if already previewed

            original_page = pdf_reader.pages[i]
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=PAGE_SIZE)
            can.setFont(font_name, font_size_app)
            can.drawString(stamp_x, stamp_y + font_size_bin + 4, "SwiftSale App:")

            if bin_number:
                can.setFont(font_name, font_size_bin)
                can.drawString(stamp_x, stamp_y, f"Bin {bin_number}")
                if is_pickup and first_name:
                    can.setFont(font_name, font_size_first)
                    can.drawString(1.8 * inch, 4.8 * inch, first_name)
            else:
                can.setFont(font_name, font_size_default)
                can.drawString(stamp_x, stamp_y, "Possible")
                can.drawString(stamp_x, stamp_y - font_size_default, "(Givvy/FlashSale)")

            can.save()
            packet.seek(0)
            overlay_pdf = PdfReader(packet)
            overlay_page = overlay_pdf.pages[0]
            original_page.merge_page(overlay_page)
            preview_writer.add_page(original_page)

            if is_pickup:
                pickup_done = True
            else:
                shipping_done = True

            if pickup_done and shipping_done:
                break

    # Write to temp file and open
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        preview_writer.write(tmp_file)
        tmp_path = tmp_file.name

    webbrowser.open(tmp_path)
