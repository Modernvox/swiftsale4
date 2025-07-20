import logging
import sqlite3
import os
import csv
import shutil
import sys
from datetime import datetime
from config_qt import DEFAULT_DATA_DIR

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BidderManager:
    """
    Manages bidder transactions, bin assignments, and install data for SwiftSale,
    using bidders.db for transactions and subscriptions.db for subscriptions and installs.
    """
    SCHEMA_VERSION = "1.0"

    def __init__(self, bidders_db_path, subs_db_path, log_info=None, log_error=None):
        if not bidders_db_path or not subs_db_path:
            raise ValueError("bidders_db_path and subs_db_path must be provided")

        self.log_info = log_info if log_info else logger.info
        self.log_error = log_error if log_error else logger.error

        # ─── bidders.db ──────────────────────────────────────────────────────────
        self.bidders_db_path = bidders_db_path
        logger.info("Using bidders database path: %s", self.bidders_db_path)
        os.makedirs(os.path.dirname(self.bidders_db_path), exist_ok=True)

        if not os.path.exists(self.bidders_db_path):
            exe_dir = os.path.dirname(sys.executable)
            bundled = os.path.join(exe_dir, 'bidders.db')
            if os.path.isfile(bundled):
                try:
                    shutil.copy(bundled, self.bidders_db_path)
                    logger.info("Copied bundled bidders.db from %s to %s", bundled, self.bidders_db_path)
                except Exception as e:
                    logger.error("Failed to copy bundled bidders.db: %s", e)
            else:
                logger.info("No bundled bidders.db found; will create fresh schema on connect.")

        try:
            self.conn = sqlite3.connect(self.bidders_db_path, check_same_thread=False)
            logger.info("Connected to bidders.db successfully")
            self._verify_schema(self.conn, "bidders.db")
        except sqlite3.Error as e:
            logger.error("Failed to connect to bidders.db at %s: %s", self.bidders_db_path, e)
            raise

        self._initialize_bidders_tables()

        # ─── subscriptions.db ─────────────────────────────────────────────────────
        self.subs_db_path = subs_db_path
        logger.info("Using subscriptions database path: %s", self.subs_db_path)
        os.makedirs(os.path.dirname(self.subs_db_path), exist_ok=True)

        if not os.path.exists(self.subs_db_path):
            exe_dir = os.path.dirname(sys.executable)
            bundled = os.path.join(exe_dir, 'subscriptions.db')
            if os.path.isfile(bundled):
                try:
                    shutil.copy(bundled, self.subs_db_path)
                    logger.info("Copied bundled subscriptions.db from %s to %s", bundled, self.subs_db_path)
                except Exception as e:
                    logger.error("Failed to copy bundled subscriptions.db: %s", e)
            else:
                logger.info("No bundled subscriptions.db found; will create fresh schema on connect.")

        try:
            self.sub_conn = sqlite3.connect(self.subs_db_path, check_same_thread=False)
            self.sub_conn.execute("PRAGMA foreign_keys = ON;")
            logger.info("Connected to subscriptions.db successfully")
            self._verify_schema(self.sub_conn, "subscriptions.db")
        except sqlite3.Error as e:
            logger.error("Failed to connect to subscriptions.db at %s: %s", self.subs_db_path, e)
            raise

        self._initialize_subscription_tables()

        # In-memory counters and cache
        self.bin_counter = 0
        self.giveaway_counter = 0
        self.show_start_time = None
        self.bidders = {}  # For in-memory transactions

    def _verify_schema(self, conn, db_name):
        """Verify the database schema version, recreate if outdated."""
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (version TEXT)")
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            if row and row[0] != self.SCHEMA_VERSION:
                logger.warning(f"Outdated schema in {db_name}, recreating tables")
                if db_name == "bidders.db":
                    cursor.execute("DROP TABLE IF EXISTS bidders")
                    cursor.execute("DROP TABLE IF EXISTS bin_assignments")
                else:
                    cursor.execute("DROP TABLE IF EXISTS subscriptions")
                    cursor.execute("DROP TABLE IF EXISTS settings")
                    cursor.execute("DROP TABLE IF EXISTS installs")
                conn.commit()
                cursor.execute("DELETE FROM schema_version")
                cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (self.SCHEMA_VERSION,))
                conn.commit()
            elif not row:
                cursor.execute("INSERT INTO schema_version (version) VALUES (?)", (self.SCHEMA_VERSION,))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to verify schema for {db_name}: {e}")
            raise

    def _initialize_bidders_tables(self):
        """Create or verify tables in bidders.db."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bidders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    original_username TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    weight TEXT,
                    is_giveaway INTEGER NOT NULL,
                    bin_number INTEGER,
                    giveaway_number INTEGER,
                    timestamp TEXT NOT NULL,
                    last_assigned TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bin_assignments (
                    username TEXT PRIMARY KEY,
                    bin_number INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bin_assignments_username 
                ON bin_assignments (username)
            """)
            self.conn.commit()
            logger.info("Ensured bidders.db tables exist")
        except sqlite3.Error as e:
            logger.error("Failed to initialize bidders tables: %s", e)
            self.conn.rollback()
            raise

    def _initialize_subscription_tables(self):
        """Create or verify tables in subscriptions.db: subscriptions, settings, installs."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    email TEXT PRIMARY KEY,
                    tier TEXT NOT NULL,
                    license_key TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    email TEXT PRIMARY KEY,
                    chat_id TEXT,
                    top_buyer_text TEXT,
                    giveaway_announcement_text TEXT,
                    flash_sale_announcement_text TEXT,
                    multi_buyer_mode BOOLEAN
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS installs (
                    hashed_email TEXT PRIMARY KEY,
                    install_id TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'Trial'
                )
            """)
            self.sub_conn.commit()
            logger.info("Ensured subscriptions, settings, and installs tables exist")
        except sqlite3.Error as e:
            logger.error("Failed to initialize subscriptions/settings/installs tables: %s", e)
            self.sub_conn.rollback()
            raise

    def update_install(self, hashed_email, install_id, tier):
        """Update or insert an install record in subscriptions.db."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO installs (hashed_email, install_id, tier)
                VALUES (?, ?, ?)
            """, (hashed_email, install_id, tier))
            self.sub_conn.commit()
            logger.info(f"Updated install: hashed_email={hashed_email}, install_id={install_id}, tier={tier}")
        except sqlite3.Error as e:
            logger.error(f"Failed to update install for hashed_email={hashed_email}: {e}")
            self.sub_conn.rollback()
            raise

    def get_install(self, hashed_email):
        """Fetch install record by hashed_email from subscriptions.db."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute(
                "SELECT install_id, tier FROM installs WHERE hashed_email = ?",
                (hashed_email,)
            )
            row = cursor.fetchone()
            if row:
                logger.info(f"Found install for hashed_email={hashed_email}: install_id={row[0]}, tier={row[1]}")
                return {"install_id": row[0], "tier": row[1]}
            logger.info(f"No install found for hashed_email={hashed_email}")
            return None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch install for hashed_email={hashed_email}: {e}")
            raise

    def assign_bin(self, username):
        """Assign a bin to username in bidders.db."""
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")

        try:
            cursor = self.conn.cursor()
            uname = username.strip().lower()
            cursor.execute("SELECT bin_number FROM bin_assignments WHERE username = ?", (uname,))
            bin_result = cursor.fetchone()
            if bin_result:
                bin_num = bin_result[0]
            else:
                self.bin_counter += 1
                bin_num = self.bin_counter
                cursor.execute("""
                    INSERT INTO bin_assignments (username, bin_number)
                    VALUES (?, ?)
                """, (uname, bin_num))
                self.conn.commit()
            logger.info("Assigned bin %d to username %s", bin_num, uname)
            return bin_num
        except sqlite3.Error as e:
            logger.error("Failed to assign bin for %s: %s", username, e)
            self.conn.rollback()
            raise

    def count_user_bins(self) -> int:
        """Count distinct usernames that have a bin assigned."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(DISTINCT username) FROM bidders WHERE bin_number IS NOT NULL")
            count = cursor.fetchone()[0] or 0
            logger.debug(f"Total bins assigned (distinct usernames): {count}")
            return count
        except sqlite3.Error as e:
            logger.error(f"Failed to count bins: {e}")
            return 0

    def count_bins_by_email(self, user_email):
        """Count bins assigned to a user based on their email."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT COUNT(DISTINCT bin_number)
                FROM bin_assignments
                WHERE username IN (
                    SELECT LOWER(original_username)
                    FROM bidders
                    WHERE LOWER(original_username) = LOWER(?)
                )
            """, (user_email,))
            count = cursor.fetchone()[0] or 0
            logger.debug(f"Retrieved bin count for {user_email}: {count}")
            return count
        except sqlite3.Error as e:
            logger.error(f"Failed to count bins for {user_email}: {e}")
            return 0

    def add_transaction(self, username, original_username, qty, weight, is_giveaway, email="trial@swiftsaleapp.com"):
        """Add a bidder transaction to bidders."""
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")
        if not original_username or not isinstance(original_username, str):
            raise ValueError("Original username must be a non-empty string")
        if not isinstance(qty, int) or qty < 0:
            raise ValueError("Quantity must be non-negative")
        if qty == 0 and not is_giveaway:
            raise ValueError("Quantity must be positive for non-giveaway bids")
        if weight is not None and not isinstance(weight, str):
            raise ValueError("Weight must be a string or None")
        if not email:
            email = "trial@swiftsaleapp.com"

        try:
            bin_num = None
            giveaway_num = None
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            last_assigned = timestamp
            uname = username.strip().lower()

            if is_giveaway:
                self.giveaway_counter += 1
                giveaway_num = self.giveaway_counter
            else:
                bin_num = self.assign_bin(uname)

            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO bidders (email, username, original_username, quantity, weight, is_giveaway,
                                     bin_number, giveaway_number, timestamp, last_assigned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (email, uname, original_username, qty, weight, int(is_giveaway),
                  bin_num, giveaway_num, timestamp, last_assigned))
            self.conn.commit()

            if uname not in self.bidders:
                self.bidders[uname] = {
                    "original_username": original_username,
                    "bin": bin_num,
                    "transactions": []
                }
            self.bidders[uname]["transactions"].append({
                "qty": qty,
                "weight": weight,
                "giveaway": is_giveaway,
                "giveaway_num": giveaway_num,
                "timestamp": timestamp,
                "last_assigned": last_assigned
            })

            logger.info(
                "Added transaction: %s, qty=%s, giveaway=%s, bin=%s, giveaway_num=%s, timestamp=%s, email=%s",
                original_username, qty, is_giveaway, bin_num, giveaway_num, timestamp, email
            )
            return bin_num, giveaway_num
        except (ValueError, sqlite3.Error) as e:
            self.conn.rollback()
            logger.error("Failed to add transaction for %s: %s", original_username, e)
            raise


    def add_bidder(self, username, original_username=None, qty=1, weight=None, is_giveaway=False):
        """Wrapper for add_transaction."""
        if not original_username:
            original_username = username
        return self.add_transaction(username, original_username, qty, weight, is_giveaway)

    def get_latest_bidder(self):
        """Return the most recent bidder."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT username, bin_number
                FROM bidders
                WHERE timestamp IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                return {'username': row[0], 'bin_number': row[1]}
            return None
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve latest bidder: {e}")
            return None

    def export_csv(self):
        """Export all transactions to a CSV file."""
        headers = [
            'username', 'original_username', 'quantity', 'weight', 'is_giveaway',
            'bin_number', 'giveaway_number', 'timestamp', 'last_assigned'
        ]
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = os.path.join(os.path.dirname(self.bidders_db_path), f"bidders_export_{timestamp}.csv")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT username, original_username, quantity, weight, is_giveaway, bin_number, giveaway_number, timestamp, last_assigned
                FROM bidders
            """)
            rows = cursor.fetchall()
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(zip(headers, row)))
            logger.info("Exported bidders CSV to: %s", file_path)
            return file_path
        except (sqlite3.Error, OSError) as e:
            logger.error("CSV export failed: %s", e)
            raise

    def import_csv(self, file_path):
        """Import bidder data from a CSV."""
        try:
            with open(file_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    logger.error("CSV file has no headers")
                    raise ValueError("CSV file must contain headers")
                header_map = {
                    'username': ['username', 'user', 'name'],
                    'original_username': ['original_username', 'display_name', 'original_name'],
                    'quantity': ['quantity', 'qty', 'count']
                }
                field_mapping = {}
                fieldnames_lower = [f.lower() for f in reader.fieldnames]
                for standard, aliases in header_map.items():
                    for alias in aliases:
                        if alias.lower() in fieldnames_lower:
                            idx = fieldnames_lower.index(alias.lower())
                            field_mapping[standard] = reader.fieldnames[idx]
                            break
                    if standard == 'username' and standard not in field_mapping:
                        raise ValueError(f"CSV must contain a header for username (e.g., {', '.join(aliases)})")
                    if standard == 'quantity' and standard not in field_mapping:
                        raise ValueError(f"CSV must contain a header for quantity (e.g., {', '.join(aliases)})")
                    if standard == 'original_username' and standard not in field_mapping:
                        field_mapping['original_username'] = field_mapping.get('username', 'username')

                cursor = self.conn.cursor()
                self.bidders.clear()
                self.bin_counter = 0
                self.giveaway_counter = 0
                for row_num, row in enumerate(reader, start=2):
                    try:
                        uname = row[field_mapping['username']].strip().lower()
                        if not uname:
                            logger.warning("Skipping row %d: Missing username", row_num)
                            continue
                        orig_uname = row.get(field_mapping['original_username'], uname).strip()
                        try:
                            qty = int(row[field_mapping['quantity']])
                            if qty < 0:
                                logger.warning("Skipping row %d: Negative quantity (%s)", row_num, row[field_mapping['quantity']])
                                continue
                        except ValueError:
                            logger.warning("Skipping row %d: Invalid quantity (%s)", row_num, row[field_mapping['quantity']])
                            continue
                        weight = row.get('weight', None)
                        try:
                            is_giveaway = int(row.get('is_giveaway', 0))
                        except ValueError:
                            is_giveaway = 0
                        try:
                            bin_num = int(row['bin_number']) if 'bin_number' in row and row['bin_number'] else None
                        except ValueError:
                            bin_num = None
                        try:
                            giveaway_num = int(row['giveaway_number']) if row.get('giveaway_number') else None
                        except ValueError:
                            giveaway_num = None
                        timestamp = row.get('timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        last_assigned = row.get('last_assigned', timestamp)
                        if bin_num:
                            cursor.execute("""
                                INSERT OR REPLACE INTO bin_assignments (username, bin_number)
                                VALUES (?, ?)
                            """, (uname, bin_num))
                            self.bin_counter = max(self.bin_counter, bin_num)
                        if giveaway_num:
                            self.giveaway_counter = max(self.giveaway_counter, giveaway_num)
                        cursor.execute("""
                            INSERT INTO bidders (username, original_username, quantity, weight, is_giveaway, bin_number, giveaway_number, timestamp, last_assigned)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (uname, orig_uname, qty, weight, is_giveaway, bin_num, giveaway_num, timestamp, last_assigned))
                        if uname not in self.bidders:
                            self.bidders[uname] = {
                                "original_username": orig_uname,
                                "bin": bin_num,
                                "transactions": []
                            }
                        self.bidders[uname]["transactions"].append({
                            "qty": qty,
                            "weight": weight,
                            "giveaway": bool(is_giveaway),
                            "giveaway_num": giveaway_num,
                            "timestamp": timestamp,
                            "last_assigned": last_assigned
                        })
                    except Exception as e:
                        logger.error("Failed to process row %d: %s", row_num, e)
                        continue
                self.conn.commit()
                logger.info("Imported CSV to bidders.db successfully: %s", file_path)
        except (OSError, ValueError, sqlite3.Error) as e:
            self.conn.rollback()
            logger.error("CSV import failed: %s", e)
            raise

    def start_show(self):
        """Mark the show start time."""
        try:
            self.show_start_time = datetime.now()
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1;")
            self.conn.commit()
            logger.info("Show started at %s", self.show_start_time)
        except sqlite3.Error as e:
            logger.error("Failed to start show: %s", e)
            self.conn.rollback()
            raise

    def get_avg_sell_rate(self):
        """Compute sell rate from bidders."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT MIN(timestamp), MAX(timestamp), SUM(quantity)
                FROM bidders
                WHERE is_giveaway = 0
            """)
            min_ts, max_ts, total_items = cursor.fetchone()
            if not total_items or total_items == 0:
                logger.debug("No transactions for sell rate calculation")
                return 0, 0, 0, 0, 0
            try:
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        min_time = datetime.strptime(min_ts, fmt)
                        max_time = datetime.strptime(max_ts, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    logger.error("Invalid timestamp format in database")
                    return 0, 0, 0, 0, 0
            except (ValueError, TypeError) as e:
                logger.error("Invalid timestamp format: %s", e)
                return 0, 0, 0, 0, 0
            seconds_elapsed = (max_time - min_time).total_seconds()
            if seconds_elapsed <= 0:
                logger.debug("Insufficient time elapsed for sell rate calculation")
                return 0, 0, 0, 0, 0
            hours_elapsed = seconds_elapsed / 3600
            minutes_elapsed = seconds_elapsed / 60
            items_per_hour = total_items / hours_elapsed
            items_per_minute = total_items / minutes_elapsed
            projected_2h = round(items_per_minute * (2 * 60))
            projected_3h = round(items_per_minute * (3 * 60))
            projected_4h = round(items_per_minute * (4 * 60))
            logger.debug("Sell rate: %.2f items/hour, %.2f items/minute", items_per_hour, items_per_minute)
            return items_per_hour, items_per_minute, projected_2h, projected_3h, projected_4h
        except sqlite3.Error as e:
            logger.error("Failed to calculate sell rate: %s", e)
            return 0, 0, 0, 0, 0

    def clear_all_bidders(self):
        """Clear all bidder and bin assignment records."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM bidders")
            cursor.execute("DELETE FROM bin_assignments")
            self.conn.commit()
            self.bidders.clear()
            self.bin_counter = 0
            self.giveaway_counter = 0
            logger.info("Cleared all bidders and bin assignments")
        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error("Failed to clear bidders: %s", e)
            raise

    def get_top_buyers(self):
        """Return top 5 buyers (username, total_quantity)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT LOWER(original_username), SUM(quantity) as total_quantity
                FROM bidders
                WHERE is_giveaway = 0
                GROUP BY LOWER(original_username)
                ORDER BY total_quantity DESC
                LIMIT 5
            """)
            top_buyers = cursor.fetchall()
            logger.debug("Retrieved top buyers: %s", top_buyers)
            return top_buyers
        except sqlite3.Error as e:
            logger.error("Failed to get top buyers: %s", e)
            return []

    def print_bidders(self):
        """Fetch bidder data and update self.bidders in memory."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT original_username, quantity, bin_number, giveaway_number, weight, timestamp, last_assigned
                FROM bidders
                ORDER BY timestamp DESC
            """)
            transactions = cursor.fetchall()
            self.bidders.clear()
            for trans in transactions:
                orig_uname, qty, bin_num, giveaway_num, weight, timestamp, last_assigned = trans
                uname = orig_uname.lower()
                if uname not in self.bidders:
                    self.bidders[uname] = {
                        "original_username": orig_uname,
                        "bin": bin_num,
                        "transactions": []
                    }
                self.bidders[uname]["transactions"].append({
                    "qty": qty,
                    "weight": weight,
                    "giveaway": bool(giveaway_num),
                    "giveaway_num": giveaway_num,
                    "timestamp": timestamp,
                    "last_assigned": last_assigned
                })
            return self.bidders
        except sqlite3.Error as e:
            logger.error("Failed to retrieve transactions: %s", e)
            return {}

    def get_user_tier(self, user_email):
        """Fetch the current tier for user_email."""
        if not user_email:
            return None
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute(
                "SELECT tier FROM subscriptions WHERE email = ?", (user_email,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error("Failed to fetch tier for %s: %s", user_email, e)
            return None

    def get_user_license_key(self, user_email):
        """Return the license_key for user_email."""
        if not user_email:
            return None
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute(
                "SELECT license_key FROM subscriptions WHERE email = ?", (user_email,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error("Failed to fetch license_key for %s: %s", user_email, e)
            return None

    def update_subscription(self, user_email, tier, license_key):
        """Update or insert a subscription record."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO subscriptions (email, tier, license_key)
                VALUES (?, ?, ?)
            """, (user_email, tier, license_key))
            self.sub_conn.commit()
            logger.info(f"Updated subscription for {user_email}: tier={tier}, license_key={license_key}")
        except sqlite3.Error as e:
            logger.error(f"Failed to update subscription for {user_email}: {e}")
            self.sub_conn.rollback()
            raise

    def update_user_tier(self, user_email, new_tier):
        """Update the user's tier in the subscriptions table."""
        if not user_email or not new_tier:
            return
        try:
            with self.sub_conn:
                self.sub_conn.execute(
                    "UPDATE subscriptions SET tier = ? WHERE email = ?",
                    (new_tier, user_email)
                )
        except Exception as e:
           self.log_error(f"Failed to update tier for {user_email}: {e}")
                                    
    def save_settings(self, email, chat_id, top_buyer_text, giveaway_text, flash_sale_text, multi_buyer_mode):
        """Save user settings to subscriptions.db."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO settings (
                    email, chat_id, top_buyer_text, giveaway_announcement_text,
                    flash_sale_announcement_text, multi_buyer_mode
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (email, chat_id, top_buyer_text, giveaway_text, flash_sale_text, int(multi_buyer_mode)))
            self.sub_conn.commit()
            logger.info(f"Saved settings for {email}")
        except sqlite3.Error as e:
            logger.error(f"Failed to save settings for {email}: {e}")
            self.sub_conn.rollback()
            raise

    def get_settings(self, email):
        """Fetch user settings from subscriptions.db."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                SELECT chat_id, top_buyer_text, giveaway_announcement_text,
                       flash_sale_announcement_text, multi_buyer_mode
                FROM settings WHERE email = ?
            """, (email,))
            row = cursor.fetchone()
            if row:
                return {
                    "chat_id": row[0] or "",
                    "top_buyer_text": row[1] or "",
                    "giveaway_announcement_text": row[2] or "",
                    "flash_sale_announcement_text": row[3] or "",
                    "multi_buyer_mode": bool(row[4])
                }
            return {}
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch settings for {email}: {e}")
            raise

    def close(self):
        """Close both SQLite connections."""
        try:
            if self.conn:
                self.conn.close()
                logger.info("bidders.db connection closed")
            if self.sub_conn:
                self.sub_conn.close()
                logger.info("subscriptions.db connection closed")
        except sqlite3.Error as e:
            logger.error("Error closing databases: %s", e)
            raise