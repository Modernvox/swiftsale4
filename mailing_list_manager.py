import os
import sqlite3
from datetime import datetime

MAILING_DB_PATH = os.path.join(os.getenv("LOCALAPPDATA"), "SwiftSale", "mailing_list.db")

class MailingListManager:
    def __init__(self, db_path=MAILING_DB_PATH):
        self.db_path = db_path
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Create base table (initial definition — spent added directly)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mailing_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT,
                    username TEXT,
                    email TEXT,
                    address_line_1 TEXT,
                    address_line_2 TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,
                    order_date TEXT,
                    order_id TEXT,
                    num_orders INTEGER DEFAULT 1,
                    spent REAL DEFAULT 0.0
                )
            """)

            # Check for existing columns to apply non-breaking upgrades
            cursor.execute("PRAGMA table_info(mailing_list);")
            existing_columns = [col[1] for col in cursor.fetchall()]

            if "email" not in existing_columns:
                cursor.execute("ALTER TABLE mailing_list ADD COLUMN email TEXT;")

            if "spent" not in existing_columns:
                cursor.execute("ALTER TABLE mailing_list ADD COLUMN spent REAL DEFAULT 0.0;")

            conn.commit()


    def add_or_update_entry(self, entry):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Match only on full_name and username (relaxed address match)
            cursor.execute("""
                SELECT id, num_orders, spent FROM mailing_list
                WHERE full_name = ? AND username = ?
            """, (
                entry["full_name"],
                entry.get("username", "")
            ))
            row = cursor.fetchone()

            if row:
                new_count = row[1] + 1
                new_spent = row[2] + entry.get("spent", 0.0)
                cursor.execute("""
                    UPDATE mailing_list
                    SET num_orders = ?, order_date = ?, order_id = ?, email = ?, spent = ?,
                        address_line_1 = ?, address_line_2 = ?, city = ?, state = ?, zip_code = ?
                    WHERE id = ?
                """, (
                    new_count,
                    entry["order_date"],
                    entry.get("order_id", ""),
                    entry.get("email", ""),
                    new_spent,
                    entry["address_line_1"],
                    entry.get("address_line_2", ""),
                    entry["city"],
                    entry["state"],
                    entry["zip_code"],
                    row[0]
                ))
            else:
                cursor.execute("""
                    INSERT INTO mailing_list (
                        full_name, username, email, address_line_1, address_line_2,
                        city, state, zip_code, order_date, order_id, num_orders, spent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    entry["full_name"],
                    entry.get("username", ""),
                    entry.get("email", ""),
                    entry["address_line_1"],
                    entry.get("address_line_2", ""),
                    entry["city"],
                    entry["state"],
                    entry["zip_code"],
                    entry["order_date"],
                    entry.get("order_id", ""),
                    entry.get("spent", 0.0)
                ))

            conn.commit()

    def search_entries(self, filters=None, sort_by_spent=False):
        query = "SELECT * FROM mailing_list WHERE 1=1"
        params = []

        if filters:
            if "name" in filters:
                query += " AND full_name LIKE ?"
                params.append(f"%{filters['name']}%")
            if "city" in filters:
                query += " AND city LIKE ?"
                params.append(f"%{filters['city']}%")
            if "state" in filters:
                query += " AND state LIKE ?"
                params.append(f"%{filters['state']}%")
            if "date" in filters:
                query += " AND order_date = ?"
                params.append(filters["date"])

        # Append sort condition
        if sort_by_spent:
            query += " ORDER BY spent DESC"
        else:
            query += " ORDER BY full_name COLLATE NOCASE ASC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def get_all_entries(self, sort_by_spent=False):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            order_clause = "ORDER BY spent DESC" if sort_by_spent else "ORDER BY full_name COLLATE NOCASE ASC"
            cursor.execute(f"SELECT * FROM mailing_list {order_clause}")
            return cursor.fetchall()

    def bulk_import_emails_from_csv(self, csv_path):
        """
        Parses a CSV file with columns: full_name, email, and optionally address_line_1, city, state, zip_code,
        order_id, order_date. Tries to match each row to an existing contact and update their email.
        """
        import csv
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        updated = 0
        added = 0
        skipped = 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)

                all_headers = set(reader.fieldnames or [])
                required_headers = {"full_name", "email"}
                optional_headers = {
                    "address_line_1", "city", "state", "zip_code",
                    "order_id", "order_date"
                }

                missing_required = required_headers - all_headers
                missing_optional = optional_headers - all_headers

                if missing_required:
                    raise ValueError(f"Missing required CSV headers: {', '.join(missing_required)}")
                if missing_optional:
                    print(f"Warning: Optional headers missing: {', '.join(missing_optional)}")

                for row in reader:
                    full_name = row.get("full_name", "").strip()
                    email = row.get("email", "").strip()
                    address_line_1 = row.get("address_line_1", "").strip()
                    city = row.get("city", "").strip()
                    state = row.get("state", "").strip()
                    zip_code = row.get("zip_code", "").strip()
                    order_id = row.get("order_id", "").strip()
                    order_date = row.get("order_date", "").strip()

                    if not full_name or not email:
                        skipped += 1
                        continue

                    # Match existing
                    cursor.execute("""
                        SELECT id FROM mailing_list
                        WHERE full_name = ? AND address_line_1 = ? AND city = ? AND state = ? AND zip_code = ?
                    """, (full_name, address_line_1, city, state, zip_code))
                    match = cursor.fetchone()

                    if match:
                        cursor.execute("UPDATE mailing_list SET email = ? WHERE id = ?", (email, match[0]))
                        updated += 1
                    else:
                        cursor.execute("""
                            INSERT INTO mailing_list (
                                full_name, username, email, address_line_1, address_line_2,
                                city, state, zip_code, order_date, order_id, num_orders
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """, (
                            full_name, '', email, address_line_1, '',
                            city, state, zip_code, order_date, order_id
                        ))
                        added += 1

            conn.commit()

        return {"updated": updated, "added": added, "skipped": skipped}

    def clear_all_entries(self):
        """Permanently deletes all entries from the mailing list database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mailing_list")
            conn.commit()
