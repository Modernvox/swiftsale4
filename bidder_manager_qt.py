import logging
import sqlite3
import os
import csv
import shutil
import sys
import threading
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Tuple
from collections import deque
from datetime import datetime
from config_qt import DEFAULT_DATA_DIR
from utils_qt import safe_default_csv_path, sanitize_filename


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class WinnerEvent:
    username: str
    lot_id: Optional[str]
    source: str
    confidence: float
    ts: int
    processed: int = 0      # 0 = queued/unprocessed, 1 = handled
    error: Optional[str] = None


class BidderManager:
    """
    Manages bidder transactions, bin assignments, and install/subscription data for SwiftSale.
    Adds winner-ingestion (from browser bridge), a Miss Queue, sticky winner tracking,
    and lightweight telemetry in bidders.db:winner_capture.
    """
    SCHEMA_VERSION = "1.1"  # bumped to run column/table migrations

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
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA foreign_keys = ON;")
            logger.info("Connected to bidders.db successfully")
            self._verify_schema(self.conn, "bidders.db")
        except sqlite3.Error as e:
            logger.error("Failed to connect to bidders.db at %s: %s", self.bidders_db_path, e)
            raise

        self._initialize_bidders_tables()
        self._migrate_bidders_schema()  # add columns/tables if missing

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
            self.sub_conn.execute("PRAGMA journal_mode=WAL;")
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
        self.bidders: Dict[str, Dict] = {}  # For in-memory transactions

        # Winner ingestion state
        self._miss_queue: deque[WinnerEvent] = deque(maxlen=200)
        self._sticky_username: Optional[str] = None
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────────────
    # Schema helpers
    # ─────────────────────────────────────────────────────────────────────────────
    def _verify_schema(self, conn, db_name):
        """Verify the database schema version, recreate if outdated."""
        try:
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (version TEXT)")
            cursor.execute("SELECT version FROM schema_version")
            row = cursor.fetchone()
            if row and row[0] != self.SCHEMA_VERSION:
                logger.warning(f"Outdated schema in {db_name}, recreating tables where needed")
                if db_name == "bidders.db":
                    # Keep data tables but we will migrate below; only reset version
                    pass
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
                    -- email column may be added by migration if missing
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
            # winner_capture (telemetry / reconciliation)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS winner_capture (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    lot_id TEXT,
                    source TEXT,
                    confidence REAL DEFAULT 0,
                    ts INTEGER,
                    processed INTEGER DEFAULT 0,
                    error TEXT
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_winner_capture_ts
                ON winner_capture (ts)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_winner_capture_username
                ON winner_capture (username)
            """)
            self.conn.commit()
            logger.info("Ensured bidders.db tables exist")
        except sqlite3.Error as e:
            logger.error("Failed to initialize bidders tables: %s", e)
            self.conn.rollback()
            raise

    def _migrate_bidders_schema(self):
        """Add missing columns / fix mismatches without dropping data."""
        try:
            cursor = self.conn.cursor()

            # Add email column to bidders if missing (your inserts use it)
            if not self._column_exists(cursor, "bidders", "email"):
                cursor.execute("ALTER TABLE bidders ADD COLUMN email TEXT")
                self.conn.commit()
                logger.info("Migrated bidders: added email TEXT column")

            # Nothing else required now; future-safe hook.
        except sqlite3.Error as e:
            logger.error("Schema migration failed: %s", e)
            self.conn.rollback()
            raise

    @staticmethod
    def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [r[1].lower() for r in cursor.fetchall()]
        return column.lower() in cols

    def _initialize_subscription_tables(self):
        """Create or verify tables in subscriptions.db: subscriptions, settings, installs."""
        try:
            cursor = self.sub_conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    email TEXT PRIMARY KEY,
                    tier  TEXT NOT NULL,
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
                    install_id   TEXT NOT NULL,
                    tier         TEXT NOT NULL DEFAULT 'Trial'
                )
            """)
            self.sub_conn.commit()
            self.log_info("Ensured subscriptions, settings, and installs tables exist")
        except sqlite3.Error as e:
            self.log_error(f"Failed to initialize subscriptions/settings/installs tables: {e}")
            self.sub_conn.rollback()
            raise


    # ─────────────────────────────────────────────────────────────────────────────
    # Public APIs used elsewhere in the app (existing)
    # ─────────────────────────────────────────────────────────────────────────────
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

    def assign_bin(self, username) -> int:
        """Return existing bin for username, or assign the next available bin."""
        if not username or not isinstance(username, str):
            raise ValueError("Username must be a non-empty string")
        try:
            cursor = self.conn.cursor()
            uname = self._normalize_username(username)

            # 1) If already assigned, return it
            cursor.execute("SELECT bin_number FROM bin_assignments WHERE username = ?", (uname,))
            row = cursor.fetchone()
            if row:
                bin_num = row[0]
                logger.info("Re-used bin %d for username %s", bin_num, uname)
                return bin_num

            # 2) Compute next bin from DB (robust across restarts)
            cursor.execute("SELECT COALESCE(MAX(bin_number), 0) FROM bin_assignments")
            max_bin = cursor.fetchone()[0] or 0
            bin_num = max_bin + 1

            # 3) Insert mapping
            cursor.execute(
                "INSERT INTO bin_assignments (username, bin_number) VALUES (?, ?)",
                (uname, bin_num)
            )
            self.conn.commit()

            logger.info("Assigned bin %d to username %s", bin_num, uname)
            return bin_num

        except sqlite3.Error as e:
            logger.error("Failed to assign bin for %s: %s", username, e)
            self.conn.rollback()
            raise

    def get_bin_for_username(self, username) -> Optional[int]:
        """Return bin number for a username if assigned."""
        if not username:
            return None
        try:
            cursor = self.conn.cursor()
            uname = self._normalize_username(username)
            cursor.execute("SELECT bin_number FROM bin_assignments WHERE username = ?", (uname,))
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error("Failed to get bin for %s: %s", username, e)
            return None

    def count_total_bins_assigned(self) -> int:
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
        """Count bins assigned to a user based on their email (legacy helper)."""
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
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            last_assigned = timestamp
            uname = self._normalize_username(username)

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

    _INVALID = r'[<>:"/\\|?*\x00-\x1F]'

    def export_csv(self, out_path: str | None = None) -> str:
        import os, csv, sqlite3

        if not out_path:
            out_path = safe_default_csv_path("bidders_export")
        else:
            dirpath = os.path.dirname(out_path) or os.getcwd()
            basename = sanitize_filename(os.path.basename(out_path), default_ext=".csv")
            out_path = os.path.join(dirpath, basename)
            os.makedirs(dirpath, exist_ok=True)

        try:
            cur = self.conn.cursor()
            cur.execute("""
                SELECT username, bin_number
                FROM bin_assignments
                ORDER BY bin_number ASC
            """)
            rows = cur.fetchall()
        except sqlite3.Error as e:
            raise RuntimeError(f"DB read failed: {e}") from e

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["username", "bin_number"])
            w.writerows(rows)

        return out_path


    def import_csv(self, file_path):
        """Import bidder data from a CSV (lenient: quantity optional, supports exported CSV)."""
        import csv, os, sqlite3
        from datetime import datetime

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        try:
            with open(file_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    logger.error("CSV file has no headers")
                    raise ValueError("CSV file must contain headers")

                # Build a lowercase header lookup
                fieldnames = reader.fieldnames
                fieldnames_lc = [h.lower() for h in fieldnames]
                idx_of = {h.lower(): i for i, h in enumerate(fieldnames)}

                # Helper to find the actual column name for any of the aliases
                def find_col(aliases):
                    for a in aliases:
                        j = idx_of.get(a.lower())
                        if j is not None:
                            return fieldnames[j]
                    return None

                # Header alias map (username required; quantity optional)
                user_col   = find_col(['username', 'user', 'name', 'handle'])
                qty_col    = find_col(['quantity', 'qty', 'count', 'q'])  # optional
                orig_col   = find_col(['original_username', 'display_name', 'original_name'])  # optional
                wt_col     = find_col(['weight', 'oz', 'ounces', 'grams', 'g'])  # optional
                bin_col    = find_col(['bin_number', 'bin', 'number'])  # optional
                gnum_col   = find_col(['giveaway_number', 'giveaway', 'gnum'])  # optional
                ts_col     = find_col(['timestamp', 'time'])  # optional
                last_col   = find_col(['last_assigned', 'last'])  # optional
                ig_col     = find_col(['is_giveaway'])  # optional

                if not user_col:
                    raise ValueError("CSV must contain a header for username (e.g., username, user, name)")

                cursor = self.conn.cursor()
                self.bidders.clear()
                self.bin_counter = 0
                self.giveaway_counter = 0

                for row_num, row in enumerate(reader, start=2):
                    try:
                        raw_user = (row.get(user_col) or "").strip()
                        uname = self._normalize_username(raw_user)
                        if not uname:
                            logger.warning("Skipping row %d: Missing username", row_num)
                            continue

                        orig_uname = (row.get(orig_col) or raw_user).strip() if orig_col else raw_user

                        # quantity defaults to 1 if missing/invalid
                        raw_qty = (row.get(qty_col) or "").strip() if qty_col else ""
                        try:
                            qty = int(raw_qty) if raw_qty else 1
                            if qty < 0:
                                logger.warning("Skipping row %d: Negative quantity (%s)", row_num, raw_qty)
                                continue
                        except ValueError:
                            logger.warning("Row %d: Invalid quantity (%s) -> using 1", row_num, raw_qty)
                            qty = 1

                        weight = (row.get(wt_col) or "").strip() if wt_col else None
                        weight = weight or None

                        # is_giveaway (optional)
                        try:
                            is_giveaway = int((row.get(ig_col) or "0").strip()) if ig_col else 0
                        except ValueError:
                            is_giveaway = 0

                        # bin_number (optional)
                        bin_num = None
                        if bin_col:
                            raw_bin = (row.get(bin_col) or "").strip()
                            if raw_bin:
                                try:
                                    bin_num = int(raw_bin)
                                except ValueError:
                                    bin_num = None

                        # giveaway_number (optional)
                        giveaway_num = None
                        if gnum_col:
                            raw_gnum = (row.get(gnum_col) or "").strip()
                            if raw_gnum:
                                try:
                                    giveaway_num = int(raw_gnum)
                                except ValueError:
                                    giveaway_num = None

                        timestamp = (row.get(ts_col) or "").strip() if ts_col else ""
                        if not timestamp:
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                        last_assigned = (row.get(last_col) or "").strip() if last_col else timestamp
                        if not last_assigned:
                            last_assigned = timestamp

                        # Maintain your existing counters/records if bin/giveaway present
                        if bin_num:
                            cursor.execute("""
                                INSERT OR REPLACE INTO bin_assignments (username, bin_number)
                                VALUES (?, ?)
                            """, (uname, bin_num))
                            self.bin_counter = max(self.bin_counter, bin_num)
                        if giveaway_num:
                            self.giveaway_counter = max(self.giveaway_counter, giveaway_num)

                        # Insert the row into bidders table (as your existing code does)
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
                            "giveaway": bool(giveaway_num),
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
        # noqa E701
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
                uname = self._normalize_username(orig_uname)
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

    # ─────────────────────────────────────────────────────────────────────────────
    # NEW: Winner ingestion, Miss Queue, Sticky Winner
    # ─────────────────────────────────────────────────────────────────────────────
    def record_winner(
        self,
        username: str,
        lot_id: Optional[str],
        source: str,
        confidence: float,
        ts: int,
        force_queue: bool = False
    ) -> Dict:
        """
        Entry point called by the Flask bridge.
        - Persists a row in winner_capture.
        - If high-confidence and not forced, auto-assigns a bin.
        - Otherwise queues for manual confirm.
        Returns a small result dict for UI.
        """
        uname = self._normalize_username(username)
        evt = WinnerEvent(username=uname, lot_id=lot_id, source=source, confidence=float(confidence or 0.0), ts=int(ts))
        action = "queued"
        bin_code: Optional[int] = None
        error: Optional[str] = None

        try:
            # Persist telemetry first
            self._insert_winner_capture(evt)

            # Sticky winner = last known good
            with self._lock:
                self._sticky_username = uname

            if not force_queue and evt.confidence >= 0.8:
                try:
                    bin_code = self.assign_bin(uname)
                    action = "auto_assigned"
                    evt.processed = 1
                except Exception as assign_ex:
                    error = f"assign_failed: {assign_ex}"
                    self.log_error(error)
                    # Fall back to queue if assignment fails
                    self._enqueue(evt)
                    self._update_winner_capture_processed(evt, processed=0, error=error)
                    return {"action": "queued", "lot_id": lot_id, "error": "assign_failed"}
                # mark processed OK
                self._update_winner_capture_processed(evt, processed=1, error=None)
            else:
                # Manual mode or low confidence
                self._enqueue(evt)
                self._update_winner_capture_processed(evt, processed=0, error=None)

            return {"action": action, "bin": bin_code, "lot_id": lot_id}
        except Exception as e:
            self.log_error(f"record_winner failed: {e}")
            try:
                # best-effort error write
                self._update_winner_capture_processed(evt, processed=0, error=str(e))
            except Exception:
                pass
            return {"action": "error", "error": str(e)}

    def list_miss_queue(self) -> List[Dict]:
        """Return a snapshot list of queued winners (oldest first)."""
        with self._lock:
            return [asdict(x) for x in list(self._miss_queue)]

    def pop_next_miss(self) -> Optional[Dict]:
        """Pop the next queued winner (FIFO)."""
        with self._lock:
            if not self._miss_queue:
                return None
            evt = self._miss_queue.popleft()
        return asdict(evt)

    def apply_sticky_to_username(self, username: Optional[str] = None) -> Optional[int]:
        """
        Assign a bin to the provided username; if not provided, use sticky winner.
        Returns bin number or None.
        """
        with self._lock:
            uname = self._normalize_username(username or self._sticky_username or "")
        if not uname:
            return None
        try:
            return self.assign_bin(uname)
        except Exception as e:
            self.log_error(f"apply_sticky_to_username failed: {e}")
            return None

    def get_sticky_username(self) -> Optional[str]:
        with self._lock:
            return self._sticky_username

    # ─────────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────────
    def _insert_winner_capture(self, evt: WinnerEvent) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT INTO winner_capture (username, lot_id, source, confidence, ts, processed, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (evt.username, evt.lot_id, evt.source, evt.confidence, evt.ts, evt.processed, evt.error))
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            raise RuntimeError(f"winner_capture insert failed: {e}")

    def _update_winner_capture_processed(self, evt: WinnerEvent, processed: int, error: Optional[str]) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute("""
                UPDATE winner_capture
                SET processed = ?, error = ?
                WHERE rowid = (SELECT MAX(rowid) FROM winner_capture WHERE username = ? AND ts = ?)
            """, (int(processed), error, evt.username, evt.ts))
            self.conn.commit()
        except sqlite3.Error as e:
            self.conn.rollback()
            # log but don't rethrow to avoid masking the primary flow
            self.log_error(f"winner_capture update failed: {e}")

    def _enqueue(self, evt: WinnerEvent) -> None:
        with self._lock:
            if len(self._miss_queue) == self._miss_queue.maxlen:
                # Drop oldest to make room
                self._miss_queue.popleft()
            self._miss_queue.append(evt)

    @staticmethod
    def _normalize_username(username: str) -> str:
        if not username:
            return ""
        u = username.strip()
        if not u:
            return ""
        # keep a single leading '@' and lower-case for keys
        if not u.startswith("@"):
            u = "@" + u
        return u.lower()
