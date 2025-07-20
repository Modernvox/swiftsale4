import os
import json

BUSINESS_INFO_PATH = os.path.join(os.getenv("LOCALAPPDATA"), "SwiftSale", "business_info.json")

REQUIRED_FIELDS = [
    "business_name",
    "contact_name",
    "email",
    "phone",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "zip_code"
]

def load_business_info():
    data = {}
    if os.path.exists(BUSINESS_INFO_PATH):
        with open(BUSINESS_INFO_PATH, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                pass  # fallback to empty dict if corrupt file

    # Ensure all required fields are present (with empty string if missing)
    for field in REQUIRED_FIELDS:
        data.setdefault(field, "")

    return data

def save_business_info(info: dict):
    os.makedirs(os.path.dirname(BUSINESS_INFO_PATH), exist_ok=True)
    with open(BUSINESS_INFO_PATH, "w") as f:
        json.dump(info, f, indent=2)
