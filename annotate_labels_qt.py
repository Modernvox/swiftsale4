# -*- coding: utf-8 -*-
import os
import io
import re
import json
import sqlite3
import logging
from collections import defaultdict
from datetime import datetime

import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl

from utils_qt import show_toast
from mailing_list_manager import MailingListManager
from parse_utils import parse_packing_slip_address, extract_spent_amount

# Prefer app’s data dir for settings storage (cross-platform safe)
try:
    from config_qt import DEFAULT_DATA_DIR as _SSA_DATA_DIR
except Exception:
    _SSA_DATA_DIR = os.path.join(os.path.expanduser("~"), "SwiftSaleApp")

logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# PDF + UI constants
# ------------------------------------------------------------
LABEL_WIDTH = 4 * inch
LABEL_HEIGHT = 6 * inch
PAGE_SIZE = (LABEL_WIDTH, LABEL_HEIGHT)
SETTINGS_FILE = os.path.join(_SSA_DATA_DIR, "pdf_paths.json")

# ------------------------------------------------------------
# Username extraction: robust, layout-aware
# ------------------------------------------------------------
USERNAME_RE            = re.compile(r"\(([A-Za-z0-9._-]+)\)")
USERNAME_INLINE_RE     = re.compile(r"(.+?)\s*\(([A-Za-z0-9._-]+)\)")
START_USERNAME_RE      = re.compile(r"^\(\s*([A-Za-z0-9._-]+)\s*\)")
NEW_BUYER_PARENS_RE    = re.compile(r"\(\s*new\s+buyer\s*!\s*\)", re.IGNORECASE)

ANCHOR_KEYWORDS = [
    "ships to:", "ship to:", "pickup to:", "pickup address:", "pickup:",
    "shipping address:", "sold to:"
]

def _norm_username(u):
    """Normalize usernames for consistent DB lookups."""
    try:
        return str(u).strip().lower().lstrip('@')
    except Exception:
        return None

def _group_words_into_lines(plumber_page, y_tol=2.0):
    """Group words into visual lines using vertical proximity."""
    words = plumber_page.extract_words(use_text_flow=True, keep_blank_chars=False)
    if not words:
        return []
    words.sort(key=lambda w: (w.get("top", 0), w.get("x0", 0)))
    lines, current_line = [], [words[0]]
    current_y = words[0].get("top", 0)
    for w in words[1:]:
        y = w.get("top", 0)
        if abs(y - current_y) <= y_tol:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
            current_y = y
    if current_line:
        lines.append(current_line)
    return lines

def _line_text_from_words(line_words):
    s = " ".join(w.get("text", "") for w in line_words)
    s = s.replace("( ", "(").replace(" )", ")")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def _find_anchor_rows(lines_text_lower):
    return [i for i, txt in enumerate(lines_text_lower) if any(kw in txt for kw in ANCHOR_KEYWORDS)]

def _prev_nonempty_nonanchor_line(lines_text, lines_text_lower, i, anchors_set):
    j = i - 1
    while j >= 0:
        if j not in anchors_set and lines_text[j].strip() and not NEW_BUYER_PARENS_RE.fullmatch(lines_text_lower[j]):
            return lines_text[j]
        j -= 1
    return None

def _extract_username_from_lines(lines_text, lines_text_lower, start_idx=0, max_ahead=8):
    """
    Scan forward from an anchor line for:
      A) Name (username)
      B) (username) alone on a line
      C) (username) at start of a line followed by address
    Returns (username_lower, first_name) or (None, None)
    """
    anchors_set = set(_find_anchor_rows(lines_text_lower))
    for offset in range(1, max_ahead + 1):
        i = start_idx + offset
        if i >= len(lines_text):
            break

        line = lines_text[i]
        line_lower = lines_text_lower[i]

        if NEW_BUYER_PARENS_RE.fullmatch(line_lower):
            continue

        m_inline = USERNAME_INLINE_RE.search(line)
        if m_inline:
            u = m_inline.group(2).strip().lower()
            if u != "new buyer!":
                first = (m_inline.group(1) or "").strip().split()[0] or None
                return u, first

        m_only = re.fullmatch(r"\(\s*([A-Za-z0-9._-]+)\s*\)", line)
        if m_only:
            u = m_only.group(1).strip().lower()
            if u != "new buyer!":
                prev_line = _prev_nonempty_nonanchor_line(lines_text, lines_text_lower, i, anchors_set)
                first = prev_line.split()[0] if prev_line else None
                return u, first

        m_start = START_USERNAME_RE.match(line)
        if m_start:
            u = m_start.group(1).strip().lower()
            if u != "new buyer!":
                prev_line = _prev_nonempty_nonanchor_line(lines_text, lines_text_lower, i, anchors_set)
                first = prev_line.split()[0] if prev_line else None
                return u, first
    return None, None

def extract_username_and_pickup_firstname_from_page(plumber_page):
    """Primary extractor using positioned words; falls back to text-only."""
    lines_words = _group_words_into_lines(plumber_page, y_tol=2.0)
    if not lines_words:
        page_text = plumber_page.extract_text() or ""
        return extract_username_and_pickup_firstname(page_text)

    lines_text = [_line_text_from_words(ws) for ws in lines_words]
    lines_text_lower = [lt.lower() for lt in lines_text]

    for anchor_idx in _find_anchor_rows(lines_text_lower):
        u, first = _extract_username_from_lines(lines_text, lines_text_lower, start_idx=anchor_idx, max_ahead=10)
        if u:
            return u, first

    # global fallback pass
    for i, line in enumerate(lines_text):
        ll = lines_text_lower[i]
        if NEW_BUYER_PARENS_RE.fullmatch(ll):
            continue
        m_inline = USERNAME_INLINE_RE.search(line)
        if m_inline:
            u = m_inline.group(2).strip().lower()
            if u != "new buyer!":
                first = (m_inline.group(1) or "").strip().split()[0] or None
                return u, first
        m_only = re.fullmatch(r"\(\s*([A-Za-z0-9._-]+)\s*\)", line)
        if m_only:
            u = m_only.group(1).strip().lower()
            if u != "new buyer!":
                prev_line = lines_text[i - 1] if i - 1 >= 0 else None
                first = prev_line.split()[0] if prev_line else None
                return u, first
        m_start = START_USERNAME_RE.match(line)
        if m_start:
            u = m_start.group(1).strip().lower()
            if u != "new buyer!":
                prev_line = lines_text[i - 1] if i - 1 >= 0 else None
                first = prev_line.split()[0] if prev_line else None
                return u, first

    # last resort
    page_text = plumber_page.extract_text() or ""
    return extract_username_and_pickup_firstname(page_text)

def extract_username_and_pickup_firstname(page_text: str):
    """Legacy text-only extractor as a backstop."""
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    lowers = [l.lower() for l in lines]

    anchor_idxs = [i for i, l in enumerate(lowers) if any(kw in l for kw in ANCHOR_KEYWORDS)]
    if anchor_idxs:
        idx = anchor_idxs[0]
        for offset in range(1, 10):
            i = idx + offset
            if i >= len(lines):
                break
            cur = lines[i]
            curl = lowers[i]

            if NEW_BUYER_PARENS_RE.fullmatch(curl):
                continue

            m2 = USERNAME_INLINE_RE.search(cur)
            if m2:
                first = (m2.group(1) or "").strip().split()[0] or None
                u = m2.group(2).strip().lower()
                if u != "new buyer!":
                    return u, first

            m_only = re.fullmatch(r"\(\s*([A-Za-z0-9._-]+)\s*\)", cur)
            if m_only:
                u = m_only.group(1).strip().lower()
                if u != "new buyer!":
                    prev = lines[i - 1] if i - 1 >= 0 else ""
                    if prev and not any(kw in prev.lower() for kw in ANCHOR_KEYWORDS):
                        first = prev.split()[0] if prev else None
                    else:
                        first = None
                    return u, first

            m_start = START_USERNAME_RE.match(cur)
            if m_start:
                u = m_start.group(1).strip().lower()
                if u != "new buyer!":
                    prev = lines[i - 1] if i - 1 >= 0 else ""
                    if prev and not any(kw in prev.lower() for kw in ANCHOR_KEYWORDS):
                        first = prev.split()[0]
                    else:
                        first = None
                    return u, first

    # global fallback
    for i, line in enumerate(lines):
        ll = lowers[i]
        if NEW_BUYER_PARENS_RE.fullmatch(ll):
            continue

        m2 = USERNAME_INLINE_RE.search(line)
        if m2:
            first = (m2.group(1) or "").strip().split()[0] or None
            u = m2.group(2).strip().lower()
            if u != "new buyer!":
                return u, first

        m_only = re.fullmatch(r"\(\s*([A-Za-z0-9._-]+)\s*\)", line)
        if m_only:
            u = m_only.group(1).strip().lower()
            if u != "new buyer!":
                prev = lines[i - 1] if i - 1 >= 0 else ""
                first = prev.split()[0] if prev else None
                return u, first

        m_start = START_USERNAME_RE.match(line)
        if m_start:
            u = m_start.group(1).strip().lower()
            if u != "new buyer!":
                prev = lines[i - 1] if i - 1 >= 0 else ""
                first = prev.split()[0] if prev else None
                return u, first

    return None, None

# ------------------------------------------------------------
# Settings helpers
# ------------------------------------------------------------
def remember_folder_path(folder):
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_pdf_folder": folder}, f)
    except Exception as e:
        logger.warning(f"Failed to remember folder path: {e}")

def get_last_folder():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("last_pdf_folder") or os.path.expanduser("~")
    except Exception as e:
        logger.warning(f"Failed to load last folder path: {e}")
    return os.path.expanduser("~")

# ------------------------------------------------------------
# Qt entry
# ------------------------------------------------------------
def annotate_labels_qt(parent, db_path):
    """Qt front-end: prompt for input PDF + output path, run annotator, and show toast."""
    folder_hint = get_last_folder()
    input_pdf_path, _ = QFileDialog.getOpenFileName(parent, "Select Whatnot PDF", folder_hint, "PDF Files (*.pdf)")
    if not input_pdf_path:
        return

    # Suggest an annotated filename by default
    base_dir, base_name = os.path.dirname(input_pdf_path), os.path.basename(input_pdf_path)
    suggested = os.path.join(base_dir, base_name.replace(".pdf", "_annotated.pdf"))
    output_pdf_path, _ = QFileDialog.getSaveFileName(parent, "Save Annotated PDF", suggested, "PDF Files (*.pdf)")
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

        msg = "Annotated PDF created successfully."
        if skipped_pages:
            msg += f"\nSkipped {len(skipped_pages)} page(s) with unknown usernames or addresses."
        show_toast(parent, msg, icon_path="icons/stamp_icon.png")
    except Exception as e:
        logger.exception("Annotation failed")
        QMessageBox.critical(parent, "Annotation Error", f"Failed to annotate PDF:\n\n{e}")

# ------------------------------------------------------------
# DB map loader (robust, normalized)
# ------------------------------------------------------------
def _load_bin_and_firstname_maps(bidders_db_path: str):
    """
    Load:
      • bin_map: normalized username -> bin_number
      • fname_map: normalized username -> first_name (latest non-null)
    Falls back to latest non-null bin from bidders when bin_assignments is empty/missing.
    Handles schemas where the column is named 'bin' or 'bin_number'.
    """
    bin_map, fname_map = {}, {}
    if not bidders_db_path or not os.path.exists(bidders_db_path):
        logger.warning("bidders_db_path missing or not found: %s", bidders_db_path)
        return bin_map, fname_map

    def _table_has_cols(cur, table, *cols):
        try:
            cur.execute(f"PRAGMA table_info({table});")
            names = {r[1].lower() for r in cur.fetchall()}
            return all(c.lower() in names for c in cols)
        except sqlite3.Error:
            return False

    try:
        conn = sqlite3.connect(bidders_db_path)
        cur = conn.cursor()

        # ---------- Primary: bin_assignments ----------
        if _table_has_cols(cur, "bin_assignments", "username", "bin_number") or _table_has_cols(cur, "bin_assignments", "username", "bin"):
            col = "bin_number" if _table_has_cols(cur, "bin_assignments", "bin_number") else "bin"
            try:
                cur.execute(f"SELECT username, {col} FROM bin_assignments;")
                for u, b in cur.fetchall():
                    nu = _norm_username(u)
                    if nu and b is not None:
                        bin_map[nu] = b
            except sqlite3.Error:
                pass

        # ---------- Fallback: latest non-null bin from bidders ----------
        bidders_bin_col = None
        if _table_has_cols(cur, "bidders", "bin_number"):
            bidders_bin_col = "bin_number"
        elif _table_has_cols(cur, "bidders", "bin"):
            bidders_bin_col = "bin"
        if bidders_bin_col and _table_has_cols(cur, "bidders", "username", "timestamp"):
            try:
                cur.execute(f"""
                    SELECT LOWER(username), {bidders_bin_col}, timestamp
                    FROM bidders
                    WHERE {bidders_bin_col} IS NOT NULL
                      AND TRIM(username) <> ''
                    ORDER BY datetime(timestamp) DESC
                """)
                for u, b, _ in cur.fetchall():
                    nu = _norm_username(u)
                    if nu and b is not None and nu not in bin_map:
                        bin_map[nu] = b
            except sqlite3.Error:
                pass

        # ---------- First names (latest) ----------
        if _table_has_cols(cur, "bidders", "username", "first_name", "timestamp"):
            try:
                cur.execute("""
                    SELECT LOWER(username), first_name, timestamp
                    FROM bidders
                    WHERE first_name IS NOT NULL AND TRIM(first_name) <> ''
                    ORDER BY datetime(timestamp) DESC
                """)
                for u, first, _ in cur.fetchall():
                    nu = _norm_username(u)
                    if nu and nu not in fname_map and isinstance(first, str):
                        first = first.strip()
                        if first:
                            fname_map[nu] = first
            except sqlite3.Error:
                pass

        conn.close()
        logger.info(f"[annotate] Loaded bins={len(bin_map)}, first_names={len(fname_map)}")
    except Exception as e:
        logger.warning(f"Failed to read bidders DB: {e}")
    return bin_map, fname_map

# ------------------------------------------------------------
# Core annotator
# ------------------------------------------------------------
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
    font_size_default: int = 12
) -> list:
    """
    Read Whatnot packing labels and overlay SwiftSale Bin # and Buyer Name.
    Guarantees that every LOCAL PICKUP label gets a buyer name + bin attempt,
    even for giveaway / flash sale cases or when address parsing is incomplete.

    NEW: If a page is unassigned (no bin) and contains "Givvy" or "Giveaway",
         the placeholder will be "GIVEAWAY"; otherwise "FLASH SALE".
    Returns a list of (page_index, reason_or_username) for skipped overlays.
    """
    # Preload maps (now includes bidders-table fallback for bins)
    bin_map, fname_map = _load_bin_and_firstname_maps(bidders_db_path)

    mailing_list = MailingListManager()

    try:
        pdf_reader = PdfReader(whatnot_pdf_path)
    except Exception as e:
        raise RuntimeError(f"Failed to open input PDF: {e}")

    pdf_writer = PdfWriter()
    skipped_pages = []
    saved_usernames = set()
    label_counts = defaultdict(int)

    try:
        with pdfplumber.open(whatnot_pdf_path) as plumber_pdf:
            current_buyer = None
            current_first_name = None
            current_spent_total = 0.0
            current_address_data = None

            for page_index, (original_page, plumber_page) in enumerate(zip(pdf_reader.pages, plumber_pdf.pages)):
                try:
                    page_text = plumber_page.extract_text() or ""
                except Exception:
                    page_text = ""

                page_text_lower = page_text.lower()
                is_pickup = ("local pickup order" in page_text_lower) or ("pickup address:" in page_text_lower)
                is_packing_slip = "packing slip" in page_text_lower
                is_new_label = is_pickup or is_packing_slip

                # NEW: detect giveaway intent keywords
                is_giveaway = ("givvy" in page_text_lower) or ("giveaway" in page_text_lower)

                # Track money spent (best-effort)
                try:
                    spent = float(extract_spent_amount(page_text) or 0.0)
                except Exception:
                    spent = 0.0

                if is_new_label:
                    # Flush previous buyer to mailing list (only if we had address data)
                    if current_buyer and current_address_data:
                        mailing_entry = {
                            **current_address_data,
                            "spent": round(current_spent_total, 2),
                            "order_date": datetime.today().strftime("%Y-%m-%d"),
                            "order_id": f"PG{page_index:03}"
                        }
                        if current_buyer not in saved_usernames:
                            try:
                                mailing_list.add_or_update_entry(mailing_entry)
                                saved_usernames.add(current_buyer)
                            except Exception as e:
                                logger.warning(f"Mailing list write failed: {e}")
                        current_spent_total = 0.0

                    # Extract username + tentative first-name
                    try:
                        username, first_name_from_block = extract_username_and_pickup_firstname_from_page(plumber_page)
                        if not username:
                            username, first_name_from_block = extract_username_and_pickup_firstname(page_text)
                    except Exception:
                        username, first_name_from_block = (None, None)

                    if not username:
                        # We still can't label anything meaningfully without a username
                        skipped_pages.append((page_index, "no_username"))
                        pdf_writer.add_page(original_page)
                        continue

                    # Address is optional for pickup overlay — we won't skip a pickup just because address failed
                    address_data = parse_packing_slip_address(page_text) or {}

                    # Normalize city like "Area: Dallas"
                    city_val = address_data.get("city")
                    if city_val and isinstance(city_val, str) and city_val.lower().startswith("area:"):
                        address_data["city"] = city_val.split(":", 1)[-1].strip()

                    current_buyer = username.strip().lower()
                    nu = _norm_username(current_buyer)
                    label_counts[nu or current_buyer] += 1

                    # Name precedence: FULL NAME (from address) → extracted first name → DB → username
                    current_first_name = first_name_from_block or fname_map.get(nu or current_buyer)
                    full_name = (address_data.get("full_name") or "").strip()
                    buyer_display_name = full_name or current_first_name or (nu or current_buyer)

                    pickup_note = "PICK UP" if is_pickup else (address_data.get("address_line_2") or "")
                    current_address_data = None
                    if address_data.get("full_name") and address_data.get("address_line_1"):
                        current_address_data = {
                            "full_name": address_data["full_name"],
                            "username": nu or current_buyer,
                            "email": "",
                            "address_line_1": address_data["address_line_1"],
                            "address_line_2": pickup_note,
                            "city": address_data.get("city", ""),
                            "state": address_data.get("state", ""),
                            "zip_code": address_data.get("zip_code", "")
                        }

                    current_spent_total = spent
                else:
                    if current_buyer:
                        current_spent_total += spent
                    buyer_display_name = None  # unchanged on non-new pages
                    nu = _norm_username(current_buyer) if current_buyer else None
                    # is_giveaway is still valid for the page_text_lower of this page

                # --- overlay for this page ---
                draw_overlay = is_new_label
                bin_number = bin_map.get(nu) if nu else None

                # Debug lookup line (uncomment if needed)
                # logger.info(f"[annotate] lookup user raw='{current_buyer}' norm='{nu}' bin='{bin_number}' is_pickup={is_pickup} is_giveaway={is_giveaway}")

                if draw_overlay:
                    try:
                        packet = io.BytesIO()
                        can = canvas.Canvas(packet, pagesize=PAGE_SIZE)

                        # 1) Always print Buyer Name on LOCAL PICKUP labels
                        #    Use full name if available, else first name, else username.
                        if is_pickup:
                            name_to_print = buyer_display_name or (nu or current_buyer) or ""
                            if name_to_print:
                                can.setFont(font_name, font_size_first)
                                # Prominent name stripe
                                can.drawString(0.40 * inch, 4.72 * inch, f"****{name_to_print}****")

                        # 2) Bin stamp — show real bin or the requested placeholders
                        can.setFont(font_name, font_size_app)
                        app_label = "SwiftSale App Bin:"
                        can.drawString(stamp_x, stamp_y + font_size_first + 4, app_label)

                        label_width = can.stringWidth(app_label, font_name, font_size_app)
                        if bin_number:
                            can.setFont(font_name, font_size_bin + 16)
                            can.drawString(stamp_x + label_width + 22, stamp_y + font_size_first - 4, f"#{bin_number}")
                        else:
                            # Placeholder per new rules
                            placeholder = "GIVEAWAY" if is_giveaway else "FLASH SALE"
                            can.setFont(font_name, font_size_default)
                            can.drawString(stamp_x + label_width + 22, stamp_y + font_size_first, placeholder)
                            # keep a trace for reporting if you want
                            reason_tag = "giveaway_unassigned" if is_giveaway else "flash_unassigned"
                            skipped_pages.append((page_index, reason_tag))

                        can.save()
                        packet.seek(0)
                        overlay_pdf = PdfReader(packet)
                        overlay_page = overlay_pdf.pages[0]

                        # Merge overlay
                        try:
                            original_page.merge_page(overlay_page)  # pypdf / PyPDF2 >= 2.0
                        except AttributeError:
                            original_page.mergePage(overlay_page)   # older PyPDF2 fallback

                    except Exception as e:
                        logger.warning(f"Overlay failed on page {page_index}: {e}")

                pdf_writer.add_page(original_page)

            # Final flush to mailing list for last buyer (only if we had address data)
            if current_buyer and current_address_data and (nu or current_buyer) not in saved_usernames:
                mailing_entry = {
                    **current_address_data,
                    "spent": round(current_spent_total, 2),
                    "order_date": datetime.today().strftime("%Y-%m-%d"),
                    "order_id": f"PG{len(pdf_reader.pages):03}"
                }
                try:
                    mailing_list.add_or_update_entry(mailing_entry)
                except Exception as e:
                    logger.warning(f"Mailing list write (final) failed: {e}")

    except Exception as e:
        logger.exception("PDF processing failed")
        raise

    # Summary page for duplicates (same buyer across multiple labels)
    try:
        duplicates = {u: c for u, c in label_counts.items() if c > 1}
        if duplicates:
            packet = io.BytesIO()
            c = canvas.Canvas(packet, pagesize=PAGE_SIZE)

            def _draw_header():
                c.setFont("Helvetica-Bold", 14)
                c.drawCentredString(LABEL_WIDTH / 2, 5.60 * inch, "Multiple Labels Detected")
                c.setFont("Helvetica-Bold", 12)
                c.drawCentredString(LABEL_WIDTH / 2, 5.35 * inch, "for these Buyers / Bin Numbers")

            _draw_header()
            y = 4.90 * inch

            for username, count in sorted(duplicates.items()):
                bn = bin_map.get(_norm_username(username), "N/A")
                c.setFont("Helvetica", 14)
                c.drawString(0.50 * inch, y, f"{username} — Bin #{bn} (x{count})")
                y -= 0.30 * inch
                if y < 1.00 * inch:
                    c.showPage()
                    _draw_header()
                    y = 4.90 * inch

            c.save()
            packet.seek(0)
            summary_pdf = PdfReader(packet)
            for page in summary_pdf.pages:
                pdf_writer.add_page(page)
    except Exception as e:
        logger.warning(f"Failed to append duplicates summary: {e}")


    # Write output PDF
    try:
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
        with open(output_pdf_path, "wb") as out_f:
            pdf_writer.write(out_f)
    except Exception as e:
        raise RuntimeError(f"Failed to write output PDF: {e}")

    return skipped_pages
