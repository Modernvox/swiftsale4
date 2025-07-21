from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from business_info import load_business_info

def generate_labels_pdf(entries, output_path):
    label_width = 4 * inch
    label_height = 6 * inch
    c = canvas.Canvas(output_path, pagesize=(label_width, label_height))

    # Load saved business (FROM) info
    from_info = load_business_info()
    from_name = from_info.get("name", "Your Business")
    from_address = from_info.get("address", "")
    from_city = from_info.get("city", "")
    from_state = from_info.get("state", "")
    from_zip = from_info.get("zip", "")  # <- was missing

    for entry in entries:
        full_name = entry[1]
        address_1 = entry[4]
        address_2 = entry[5]
        city = entry[6]
        state = entry[7]
        zip_code = entry[8]

        # Draw FROM (business) info at top-left
        y_from = 5.75 * inch
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(0.3 * inch, y_from, from_name)

        c.setFont("Helvetica", 8)
        y_from -= 0.14 * inch
        c.drawString(0.3 * inch, y_from, from_address)
        y_from -= 0.14 * inch
        c.drawString(0.3 * inch, y_from, f"{from_city}, {from_state} {from_zip}")

        # Draw TO (recipient) info
        y = 4.5 * inch
        c.setFont("Helvetica-Bold", 12)
        c.drawString(0.5 * inch, y, full_name)

        y -= 0.3 * inch
        c.setFont("Helvetica", 12)
        c.drawString(0.5 * inch, y, address_1)
        if address_2:
            y -= 0.3 * inch
            c.drawString(0.5 * inch, y, address_2)

        y -= 0.3 * inch
        c.drawString(0.5 * inch, y, f"{city}, {state} {zip_code}")

        c.showPage()

    c.save()
