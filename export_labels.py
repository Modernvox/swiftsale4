from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
import os

def generate_labels_pdf(entries, output_path):
    width = 4 * inch
    height = 6 * inch
    c = canvas.Canvas(output_path, pagesize=(width, height))

    for entry in entries:
        if not entry or len(entry) < 9:
            continue

        full_name = entry[1]
        address_1 = entry[4]
        address_2 = entry[5]
        city = entry[6]
        state = entry[7]
        zip_code = entry[8]

        if address_2 and "PICK UP" in address_2.upper():
            continue

        # Margins
        left = 0.2 * inch
        right = width - 0.2 * inch
        top = height - 0.2 * inch
        line_height = 0.18 * inch

        # Draw 'S' in top left box
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left, top - 0.4 * inch, "SwiftSale Sample")
        c.setFont("Helvetica", 18)
        c.drawString(left, top - 0.6 * inch, "(Demo)")

        # USPS logo box
        c.setStrokeColor(colors.black)
        c.rect(right - 1.6 * inch, top - 0.8 * inch, 1.4 * inch, 0.7 * inch)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(right - 0.9 * inch, top - 0.3 * inch, "USPS GROUND ADVANTAGE")
        c.drawCentredString(right - 0.9 * inch, top - 0.42 * inch, "U.S. POSTAGE PAID")
        c.drawCentredString(right - 0.9 * inch, top - 0.54 * inch, "Permit 7032")
        c.drawCentredString(right - 0.9 * inch, top - 0.66 * inch, "ePostage")

        # Header Bar
        c.setFillColor(colors.black)
        c.rect(left, top - 1.1 * inch, width - 0.4 * inch, 0.3 * inch, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(width / 2, top - 1.0 * inch, "USPS GROUND ADVANTAGE")

        # FROM Address
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 8)
        c.drawString(left, top - 1.4 * inch, "SCD SALES")
        c.drawString(left, top - 1.4 * inch - line_height, "AREA")
        c.drawString(left, top - 1.4 * inch - 2 * line_height, "123 LIQUIDATION LANE")
        c.drawString(left, top - 1.4 * inch - 3 * line_height, "SPRINGFIELD IL 62704-1234")

        # Right side info
        c.drawRightString(right, top - 1.4 * inch, "Ship Date: 07/20/25")
        c.drawRightString(right, top - 1.4 * inch - line_height, "Weight: 11 oz")

        # QR placeholder
        c.rect(left, top - 3.4 * inch, 0.75 * inch, 0.75 * inch)

        # TO Address
        c.setFont("Helvetica-Bold", 10)
        to_left = left + 0.85 * inch
        y = top - 3.1 * inch
        c.drawString(to_left, y, full_name.upper())
        y -= line_height
        c.setFont("Helvetica", 10)
        c.drawString(to_left, y, address_1)
        y -= line_height
        if address_2:
            c.drawString(to_left, y, address_2)
            y -= line_height
        c.drawString(to_left, y, f"{city.upper()} {state} {zip_code}")

        # USPS Tracking header
        y -= 0.4 * inch
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(width / 2, y, "USPS TRACKING # EP")

        # Barcode placeholder
        y -= 0.25 * inch
        c.rect(left + 0.2 * inch, y, width - 0.4 * inch, 0.6 * inch)

        # Fake tracking number
        y -= 0.3 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width / 2, y, "9200 1903 4784 2730 0330 0768 95")

        # Bottom-right QR placeholder
        c.rect(right - 0.7 * inch, 0.2 * inch, 0.5 * inch, 0.5 * inch)
        c.setFont("Helvetica", 6)
        c.drawCentredString(right - 0.45 * inch, 0.2 * inch - 0.1 * inch, f"Q_{full_name[:8].upper()}")

        c.showPage()  # Only after all drawing for one label

    c.save()
