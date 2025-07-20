import os
import sqlite3
import logging
import shutil
from datetime import datetime
from config import load_config, DEFAULT_DATA_DIR

class DatabaseManager:
    def __init__(self, db_path=None):
        config = load_config()
        env = os.getenv("ENV", "development")

        if env == "production" and "DATABASE_URL" in os.environ:
            # Use PostgreSQL for Render.com
            try:
                self.conn = psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=DictCursor)
                self.db_path = None
                logging.info("Connected to PostgreSQL database via DATABASE_URL")
            except psycopg2.Error as e:
                logging.error(f"Database connection failed: {e}")
                raise
        else:
            # Fallback to SQLite for development
            if db_path is None:
                user_data_dir = os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), 'SwiftSaleApp')
                os.makedirs(user_data_dir, exist_ok=True)
                db_path = os.path.join(user_data_dir, 'subscriptions_qt.db')

            if not os.path.exists(db_path):
                install_dir = os.path.dirname(os.path.abspath(__file__))
                src_db = os.path.join(install_dir, 'subscriptions.db')
                if os.path.exists(src_db):
                    shutil.copy(src_db, db_path)
                    logging.info(f"Copied database from {src_db} to {db_path}")
                else:
                    logging.info(f"Source database not found at {src_db}, creating new database")

            try:
                self.conn = sqlite3.connect(db_path, check_same_thread=False)
                self.db_path = db_path
                logging.info(f"Connected to SQLite database: {db_path}")
                self._initialize_database()
                self._migrate_database()

            except sqlite3.Error as e:
                logging.error(f"Database connection failed for {db_path}: {e}")
                raise

    def _initialize_database(self):
        cursor = self.conn.cursor()
        # Existing tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                email TEXT PRIMARY KEY,
                tier TEXT NOT NULL,
                license_key TEXT
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            CREATE TABLE IF NOT EXISTS bin_assignments (
                username TEXT PRIMARY KEY,
                bin_number INTEGER NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                expires_at TEXT,
                tier TEXT,
                hours_valid INTEGER
            )
        """)
        # New installs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS installs (
                hashed_email TEXT PRIMARY KEY,
                install_id TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free'
            )
        """)
        self.conn.commit()
        logging.info("Database tables initialized successfully")

    def _migrate_database(self):
        cursor = self.conn.cursor()
        # Existing migration for settings table
        cursor.execute("PRAGMA table_info(settings)")
        columns = [col[1] for col in cursor.fetchall()]
        if "multi_buyer_mode" not in columns:
            logging.info("Migrating settings table to add multi_buyer_mode column")
            cursor.execute("""
                CREATE TABLE settings_new (
                    email TEXT PRIMARY KEY,
                    chat_id TEXT,
                    top_buyer_text TEXT,
                    giveaway_announcement_text TEXT,
                    flash_sale_announcement_text TEXT,
                    multi_buyer_mode BOOLEAN
                )
            """)
            cursor.execute("""
                INSERT INTO settings_new (email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text)
                SELECT email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text
                FROM settings
            """)
            cursor.execute("DROP TABLE settings")
            cursor.execute("ALTER TABLE settings_new RENAME TO settings")
            self.conn.commit()
            logging.info("Migration completed: added multi_buyer_mode column")

        # Check if installs table exists (for backward compatibility)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='installs'")
        if not cursor.fetchone():
            logging.info("Creating installs table during migration")
            cursor.execute("""
                CREATE TABLE installs (
                    hashed_email TEXT PRIMARY KEY,
                    install_id TEXT UNIQUE NOT NULL,
                    tier TEXT NOT NULL DEFAULT 'free'
                )
            """)
            self.conn.commit()
            logging.info("Migration completed: created installs table")

    def save_subscription(self, email, tier, license_key):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO subscriptions (email, tier, license_key, updated_at) VALUES (?, ?, ?, ?)",
            (email, tier, license_key, datetime.utcnow().isoformat())
        )
        self.conn.commit()
        logging.info(f"Saved subscription for {email}: tier={tier}, license_key={license_key}")

    def get_subscription(self, email):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT email, tier, license_key FROM subscriptions WHERE email = ?", (email,)
        )
        result = cursor.fetchone()
        if result:
            return {"email": result[0], "tier": result[1], "license_key": result[2]}
        return None

    def get_settings(self, email):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, multi_buyer_mode FROM settings WHERE email = ?",
            (email,)
        )
        result = cursor.fetchone()
        if result:
            return {
                "email": result[0],
                "chat_id": result[1],
                "top_buyer_text": result[2],
                "giveaway_announcement_text": result[3],
                "flash_sale_announcement_text": result[4],
                "multi_buyer_mode": bool(result[5])
            }
        return None

    def save_settings(self, email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, multi_buyer_mode):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (
                email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, multi_buyer_mode
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (email, chat_id, top_buyer_text, giveaway_announcement_text, flash_sale_announcement_text, int(multi_buyer_mode)))
        self.conn.commit()
        logging.info(f"Saved settings for {email}")

    def update_subscription(self, email, tier, license_key):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT email FROM subscriptions WHERE email = ?", (email,)
        )
        if cursor.fetchone():
            cursor.execute(
                "UPDATE subscriptions SET tier = ?, license_key = ? WHERE email = ?", (tier, license_key, email)
            )
        else:
            cursor.execute(
                "INSERT OR REPLACE INTO subscriptions (email, tier, license_key, updated_at) VALUES (?, ?, ?, ?)",
                (email, tier, license_key, datetime.utcnow().isoformat())
            )
        self.conn.commit()
        logging.info(f"Updated subscription for {email}: tier={tier}, license_key={license_key}")

    def load_subscription(self, email):
        sub = self.get_subscription(email)
        return (sub["email"], sub["tier"], sub["license_key"]) if sub else (None, None, None)

    def load_subscription_by_id(self, license_key):
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT email, tier, license_key FROM subscriptions WHERE license_key = ?",
            (license_key,)
        )
        result = cursor.fetchone()
        return (result[0], result[1], result[2]) if result else (None, None, None)

    def count_user_bins(self, user_email: str) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM bin_assignments WHERE username = ?",
                (user_email,)
            )
            result = cursor.fetchone()
            return result[0] if result else 0
        except sqlite3.Error as e:
            logging.error(f"Failed to count bins for {user_email}: {e}", exc_info=True)
            return 0

    def get_setting(self, key):
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logging.error(f"Error retrieving setting for key {key}: {e}")
            return None

    def save_setting(self, key, value):
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()
            logging.info(f"Saved setting: {key} = {value}")
        except sqlite3.Error as e:
            logging.error(f"Error saving setting {key}: {e}")

    def is_promo_code_valid(self, code):
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    expires_at TEXT,
                    tier TEXT,
                    hours_valid INTEGER
                )
            """)
            cursor.execute("SELECT expires_at, tier, hours_valid FROM promo_codes WHERE code = ?", (code,))
            row = cursor.fetchone()
            if not row:
                return None
            expires_at, tier, hours_valid = row
            if datetime.utcnow() > datetime.fromisoformat(expires_at):
                return None
            return {"tier": tier, "hours_valid": hours_valid}
        except Exception as e:
            logging.error(f"Error validating promo code: {e}", exc_info=True)
            return None

    def save_promo_code(self, code, tier, hours_valid, expires_at):
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    code TEXT PRIMARY KEY,
                    expires_at TEXT,
                    tier TEXT,
                    hours_valid INTEGER
                )
            """)
            cursor.execute("""
                INSERT OR REPLACE INTO promo_codes (code, expires_at, tier, hours_valid)
                VALUES (?, ?, ?, ?)
            """, (code, expires_at.isoformat(), tier, hours_valid))
            self.conn.commit()
            logging.info(f"Saved promo code: {code}")
        except Exception as e:
            logging.error(f"Error saving promo code {code}: {e}")

    def get_install_by_hashed_email(self, hashed_email):
        """Fetch install record by hashed email."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT install_id, tier FROM installs WHERE hashed_email = ?",
                (hashed_email,)
            )
            result = cursor.fetchone()
            if result:
                return {"install_id": result[0], "tier": result[1]}
            return None
        except sqlite3.Error as e:
            logging.error(f"Error fetching install for hashed email {hashed_email}: {e}", exc_info=True)
            return None

    def get_last_install(self):
        """Fetch the last install record by install_id."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT install_id FROM installs ORDER BY install_id DESC LIMIT 1"
            )
            result = cursor.fetchone()
            return {"install_id": result[0]} if result else None
        except sqlite3.Error as e:
            logging.error(f"Error fetching last install: {e}", exc_info=True)
            return None

    def save_install(self, install_data):
        """Save a new install record."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO installs (hashed_email, install_id, tier)
                VALUES (?, ?, ?)
                """,
                (install_data['hashed_email'], install_data['install_id'], install_data['tier'])
            )
            self.conn.commit()
            logging.info(f"Saved install: hashed_email={install_data['hashed_email']}, install_id={install_data['install_id']}, tier={install_data['tier']}")
        except sqlite3.Error as e:
            logging.error(f"Error saving install: {e}", exc_info=True)
            raise

    def update_install_tier(self, hashed_email, tier):
        """Update tier for an install record."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE installs SET tier = ? WHERE hashed_email = ?",
                (tier, hashed_email)
            )
            self.conn.commit()
            logging.info(f"Updated install tier to {tier} for hashed email {hashed_email}")
        except sqlite3.Error as e:
            logging.error(f"Error updating install tier for hashed email {hashed_email}: {e}", exc_info=True)
            raise

    def close(self):
        if self.conn:
            self.conn.close()
            logging.info("Database connection closed")