import re
from datetime import datetime

def parse_packing_slip_address(page_text: str):
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]

    start_index = None
    full_name = username = None

    # Step 1: Find the line with (username) — the start of address
    for i, line in enumerate(lines):
        if "new buyer" in line.lower():
            continue
        match = re.search(r"(.+?)\s*\(([^)]+)\)", line)
        if match:
            full_name = match.group(1).strip()
            username = match.group(2).strip()
            start_index = i
            break

    if start_index is None or not full_name or not username:
        print("[DEBUG] Could not locate username/address starting line.")
        return None

    # Step 2: Join all lines from that point forward as address block
    address_block = " ".join(lines[start_index:])

    # Step 3: Extract the text AFTER the (username) for parsing
    after_username = re.split(r"\([^)]+\)", address_block, maxsplit=1)[-1].strip()

    # Step 4: Split address block into parts using punctuation
    parts = [p.strip() for p in re.split(r"[.,]", after_username) if p.strip()]
    if len(parts) < 4:
        print(f"[DEBUG] Not enough parts in address: {parts}")
        return None

    # Step 5: Smart address line 2 detection
    second = parts[1]
    known_keywords = ("ste", "apt", "unit", "fl", "bldg", "#")
    is_address_2 = (
        second.lower().startswith(known_keywords) or
        re.match(r"^(ste|apt|unit|fl|#)?\s?\d+[a-zA-Z]?$", second, re.IGNORECASE) or
        (second.isupper() and len(second.split()) <= 3)
    )

    if is_address_2 and len(parts) >= 6:
        address_line_1 = parts[0]
        address_line_2 = parts[1]
        city = parts[2]
        state = parts[3]
        zip_code = parts[4]
        country = parts[5] if len(parts) > 5 else "US"
    else:
        address_line_1 = parts[0]
        address_line_2 = ""
        city = parts[1]
        state = parts[2]
        zip_code = parts[3]
        country = parts[4] if len(parts) > 4 else "US"

    return {
        "full_name": full_name.title(),
        "username": username.lower(),
        "address_line_1": address_line_1.title(),
        "address_line_2": address_line_2.title(),
        "city": city.title(),
        "state": state.upper(),
        "zip_code": zip_code,
        "country": country.upper()
    }


import re

def extract_spent_amount(page_text: str) -> float:
    """
    Sums all 'Subtotal: $X.XX' values from a page, ensuring accurate totals
    for both pickup and shipping labels.
    """
    pattern = r"(?i)Subtotal:\s*\$([0-9]+\.[0-9]{2})"
    matches = re.findall(pattern, page_text)

    return sum(float(m) for m in matches)



"""
def parse_address_block(page_text: str):
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    order_id = None
    livestream_date = None

    # Step 1: Extract Order ID
    for line in lines:
        if line.lower().startswith("orders #"):
            order_id = line.split("#")[-1].strip()
            break

    # Step 2: Extract Livestream Date
    for line in lines:
        if line.lower().startswith("livestream date:"):
            date_part = line.split(":", 1)[1].strip()
            try:
                livestream_date = datetime.strptime(date_part, "%d %B, %Y").strftime("%Y-%m-%d")
            except ValueError:
                livestream_date = None
            break

    # Step 3: Determine if it's a Pickup or Ship-to label
    for i, line in enumerate(lines):
        if "pickup address:" in line.lower() or "ships to:" in line.lower():
            j = i + 1
            # Skip any NEW BUYER or blank lines
            while j < len(lines) and (
                "new buyer" in lines[j].lower() or not lines[j].strip()
            ):
                j += 1

            name_line = lines[j] if j < len(lines) else ""
            j += 1
            address_line = lines[j] if j < len(lines) else ""

            # Parse full name and username
            match = re.match(r"(.+?)\s*\(([^)]+)\)", name_line)
            if not match:
                print(f"[DEBUG] Failed to extract name/username from: {name_line}")
                return None

            full_name = match.group(1).strip()
            username = match.group(2).strip().lower()

            # Parse address
            address_match = re.match(
                r"^(.*?)\s*,?\s*([A-Za-z .]+),\s+([A-Z]{2})\.?\s+(\d{5}(?:-\d{4})?)",
                address_line
            )
            if not address_match:
                print(f"[DEBUG] Failed to extract address from: {address_line}")
                return None

            address_line_1 = address_match.group(1).strip()
            city = address_match.group(2).replace("Area.", "").replace(".", "").strip()
            state = address_match.group(3).strip()
            zip_code = address_match.group(4).strip()

            return {
                "full_name": full_name,
                "username": username,
                "address_line_1": address_line_1,
                "address_line_2": "",
                "city": city,
                "state": state,
                "zip_code": zip_code,
                "order_id": order_id,
                "order_date": livestream_date
            }

    print("[DEBUG] No recognizable address block found")
    return None
"""