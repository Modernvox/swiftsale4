# -*- coding: utf-8 -*-
import os
import json
import sqlite3
import logging
import shutil
from datetime import datetime
from typing import Optional, Dict, Any

from config_qt import load_config, DEFAULT_DATA_DIR

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Local settings/subscription/install manager (SQLite only).

    Why SQLite only?
      - The desktop app should NOT ship live DB credentials or talk directly to Postgres.
      - Cloud sync should flow through your API / CloudDatabaseManager.
    """

    def __init__(self, db_path: Optional[str] = None):
        config = load_config() or {}
        try:
            if not db_path:
                os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)
                db_path = os.path.join(DEFAULT_DATA_DIR, "subscriptions_qt.db")

            # Bootstrap from bundled template if needed
            if not os.path.exists(db_path):
                try:
                    install_dir = os.path.dirname(os.path.abspath(__file__))
                    src_db = os.path.join(install_dir, "subscriptions.db")
                    if os.path.exists(src_db):
                        shutil.copy(src_db, db_path)
                        logger.info("Copied bundled DB %s -> %s", src_db, db_path)
                except Exception as e:
                    logger.warning("No bundled DB copy performed: %s", e)

            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.conn.execute("PRAGMA journal_mode = WAL;")
            self.db_path = db_path
            logger.info("Connected to SQLite database: %s", db_path)

            self._initialize_database()
            self._migrate_database()
        except sqlite3.Error as e:
            logger.error("Database connection/init failed for %s: %s", db_path, e, exc_info=True)
            raise

    # -------------------------------------------------------------------------
    # Schema
    # -------------------------------------------------------------------------
    def _initialize_database(self) -> None:
        cur = self.conn.cursor()

        # subscriptions
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                email TEXT PRIMARY KEY,
                tier TEXT NOT NULL,
                license_key TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # user settings
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                email TEXT PRIMARY KEY,
                chat_id TEXT,
                top_buyer_text TEXT,
                giveaway_announcement_text TEXT,
                flash_sale_announcement_text TEXT,
                multi_buyer_mode INTEGER
            )
            """
        )

        # app settings (key/value)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        # promo codes (local cache / offline)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                expires_at TEXT,
                tier TEXT,
                hours_valid INTEGER
            )
            """
        )

        # installs (hashed email -> install id/tier)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS installs (
                hashed_email TEXT PRIMARY KEY,
                install_id TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL DEFAULT 'free'
            )
            """
        )

        # kept for legacy helpers; not authoritative for bins (bidders.db owns that)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bin_assignments (
                username TEXT PRIMARY KEY,
                bin_number INTEGER NOT NULL
            )
            """
        )

        self.conn.commit()
        logger.info("Database tables initialized successfully")

    def _migrate_database(self) -> None:
        """Lightweight migrations to keep older DBs compatible."""
        cur = self.conn.cursor()

        # Ensure settings table has multi_buyer_mode column
        try:
            cur.execute("PRAGMA table_info(settings)")
            cols = [c[1] for c in cur.fetchall()]
            if "multi_buyer_mode" not in cols:
                logger.info("Migrating: adding settings.multi_buyer_mode")
                cur.execute("ALTER TABLE settings ADD COLUMN multi_buyer_mode INTEGER")
                self.conn.commit()
        except sqlite3.Error as e:
            logger.warning("Settings migration (multi_buyer_mode) skipped: %s", e)

        # Ensure installs table exists (older builds may lack it)
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='installs'")
            if not cur.fetchone():
                logger.info("Migrating: creating installs table")
                cur.execute(
                    """
                    CREATE TABLE installs (
                        hashed_email TEXT PRIMARY KEY,
                        install_id TEXT UNIQUE NOT NULL,
                        tier TEXT NOT NULL DEFAULT 'free'
                    )
                    """
                )
                self.conn.commit()
        except sqlite3.Error as e:
            logger.warning("Installs migration skipped: %s", e)

    # -------------------------------------------------------------------------
    # Subscriptions
    # -------------------------------------------------------------------------
    def save_subscription(self, email: str, tier: str, license_key: Optional[str]) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO subscriptions (email, tier, license_key, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, tier, license_key, datetime.utcnow().isoformat(timespec="seconds")),
        )
        self.conn.commit()
        logger.info("Saved subscription for %s: tier=%s", email, tier)

    def get_subscription(self, email: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT email, tier, license_key FROM subscriptions WHERE email = ?", (email,))
        row = cur.fetchone()
        if row:
            return {"email": row[0], "tier": row[1], "license_key": row[2]}
        return None

    def update_subscription(self, email: str, tier: str, license_key: Optional[str]) -> None:
        # upsert
        self.save_subscription(email, tier, license_key)

    def load_subscription(self, email: str):
        sub = self.get_subscription(email)
        return (sub["email"], sub["tier"], sub["license_key"]) if sub else (None, None, None)

    def load_subscription_by_id(self, license_key: str):
        cur = self.conn.cursor()
        cur.execute("SELECT email, tier, license_key FROM subscriptions WHERE license_key = ?", (license_key,))
        row = cur.fetchone()
        return (row[0], row[1], row[2]) if row else (None, None, None)

    # -------------------------------------------------------------------------
    # User settings (per email)
    # -------------------------------------------------------------------------
    def get_settings(self, email: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT email, chat_id, top_buyer_text, giveaway_announcement_text,
                   flash_sale_announcement_text, multi_buyer_mode
            FROM settings WHERE email = ?
            """,
            (email,),
        )
        row = cur.fetchone()
        if row:
            return {
                "email": row[0],
                "chat_id": row[1] or "",
                "top_buyer_text": row[2] or "",
                "giveaway_announcement_text": row[3] or "",
                "flash_sale_announcement_text": row[4] or "",
                "multi_buyer_mode": bool(row[5]),
            }
        return None

    def save_settings(
        self,
        email: str,
        chat_id: str,
        top_buyer_text: str,
        giveaway_announcement_text: str,
        flash_sale_announcement_text: str,
        multi_buyer_mode: bool,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO settings (
                email, chat_id, top_buyer_text, giveaway_announcement_text,
                flash_sale_announcement_text, multi_buyer_mode
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                email,
                chat_id,
                top_buyer_text,
                giveaway_announcement_text,
                flash_sale_announcement_text,
                int(bool(multi_buyer_mode)),
            ),
        )
        self.conn.commit()
        logger.info("Saved settings for %s", email)

    # -------------------------------------------------------------------------
    # App-level settings (key/value)
    # -------------------------------------------------------------------------
    def get_setting(self, key: str) -> Optional[str]:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.error("Error retrieving app setting '%s': %s", key, e)
            return None

    def save_setting(self, key: str, value: str) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
            self.conn.commit()
            logger.info("Saved app setting: %s", key)
        except sqlite3.Error as e:
            logger.error("Error saving app setting '%s': %s", key, e, exc_info=True)

    # -------------------------------------------------------------------------
    # Promo codes (local cache)
    # -------------------------------------------------------------------------
    def is_promo_code_valid(self, code: str) -> Optional[Dict[str, Any]]:
        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT expires_at, tier, hours_valid FROM promo_codes WHERE code = ?",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            expires_at, tier, hours_valid = row
            try:
                if datetime.utcnow() > datetime.fromisoformat(expires_at):
                    return None
            except Exception:
                # If expires_at invalid, consider it invalid
                return None
            return {"tier": tier, "hours_valid": hours_valid}
        except Exception as e:
            logger.error("Error validating promo code '%s': %s", code, e, exc_info=True)
            return None

    def save_promo_code(self, code: str, tier: str, hours_valid: int, expires_at: datetime) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO promo_codes (code, expires_at, tier, hours_valid)
                VALUES (?, ?, ?, ?)
                """,
                (code, expires_at.isoformat(timespec="seconds"), tier, hours_valid),
            )
            self.conn.commit()
            logger.info("Saved promo code: %s", code)
        except Exception as e:
            logger.error("Error saving promo code '%s': %s", code, e, exc_info=True)

    # -------------------------------------------------------------------------
    # Installs
    # -------------------------------------------------------------------------
    def get_install_by_hashed_email(self, hashed_email: str) -> Optional[Dict[str, Any]]:
        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT install_id, tier FROM installs WHERE hashed_email = ?",
                (hashed_email,),
            )
            row = cur.fetchone()
            if row:
                return {"install_id": row[0], "tier": row[1]}
            return None
        except sqlite3.Error as e:
            logger.error("Error fetching install for hashed email %s: %s", hashed_email, e, exc_info=True)
            return None

    def get_last_install(self) -> Optional[Dict[str, Any]]:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT install_id FROM installs ORDER BY install_id DESC LIMIT 1")
            row = cur.fetchone()
            return {"install_id": row[0]} if row else None
        except sqlite3.Error as e:
            logger.error("Error fetching last install: %s", e, exc_info=True)
            return None

    def save_install(self, install_data: Dict[str, Any]) -> None:
        """
        install_data requires:
          - hashed_email: str
          - install_id: str
          - tier: str
        """
        try:
            cur = self.conn.cursor()
            cur.execute(
                """
                INSERT INTO installs (hashed_email, install_id, tier)
                VALUES (?, ?, ?)
                """,
                (install_data["hashed_email"], install_data["install_id"], install_data["tier"]),
            )
            self.conn.commit()
            logger.info(
                "Saved install: hashed_email=%s, install_id=%s, tier=%s",
                install_data["hashed_email"], install_data["install_id"], install_data["tier"]
            )
        except sqlite3.IntegrityError as e:
            # If record exists, convert to update for idempotency
            logger.info("Install already exists, updating tier: %s", e)
            self.update_install_tier(install_data["hashed_email"], install_data["tier"])
        except sqlite3.Error as e:
            logger.error("Error saving install: %s", e, exc_info=True)
            raise

    def update_install_tier(self, hashed_email: str, tier: str) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE installs SET tier = ? WHERE hashed_email = ?",
                (tier, hashed_email),
            )
            self.conn.commit()
            logger.info("Updated install tier to %s for %s", tier, hashed_email)
        except sqlite3.Error as e:
            logger.error("Error updating install tier for %s: %s", hashed_email, e, exc_info=True)
            raise

    # -------------------------------------------------------------------------
    # Legacy helper (rarely used)
    # -------------------------------------------------------------------------
    def count_user_bins(self, user_email: str) -> int:
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM bin_assignments WHERE username = ?", (user_email,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error as e:
            logger.error("Failed to count bins for %s: %s", user_email, e, exc_info=True)
            return 0

    # -------------------------------------------------------------------------
    def close(self) -> None:
        try:
            if getattr(self, "conn", None):
                self.conn.close()
                logger.info("Database connection closed")
        except Exception as e:
            logger.error("Error closing database: %s", e)
