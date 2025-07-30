"""
Corrected version of the CloudDatabaseManager module.

This file provides a clean implementation of ``CloudDatabaseManager``
without the syntax errors that appeared in your patched ``cloud_database_qt.py``.
It is based on the earlier ``cloud_database_qt_fixed.py`` but is
ready to be imported directly as ``CloudDatabaseManager`` by your
application.  The original ``cloud_database_qt.py`` remains
read‑only in this environment, so to use this implementation, either
rename this file to ``cloud_database_qt.py`` in your own project or
change your import to point here.
"""

import os
import psycopg2
from psycopg2 import OperationalError, pool
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime, timezone
from config_qt import get_config_value


class CloudDatabaseManager:
    def __init__(self, log_info=None, log_error=None):
        self.log_info = log_info or logging.info
        self.log_error = log_error or logging.error

        env = os.getenv("ENV", "development")

        # DO NOT force prod mode just because app is frozen
        # This lets you test a frozen .exe locally without hitting Render
        if env != "production" or not os.getenv("DATABASE_URL", "").startswith("postgres"):
            raise RuntimeError(
                "CloudDatabaseManager is disabled or misconfigured (missing DATABASE_URL)"
            )

        self.pool = None
        self._initialize_connection_pool()
        self._ensure_schema()

    def _initialize_connection_pool(self):
        """Initialize a thread-safe connection pool."""
        database_url = get_config_value("DATABASE_URL")
        if not database_url or not database_url.startswith("postgres"):
            raise RuntimeError("DATABASE_URL not set or invalid.")

        try:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=database_url,
                connect_timeout=5,
            )
            self.log_info("Initialized PostgreSQL connection pool")
        except OperationalError as e:
            self.log_error(f"Could not initialize connection pool: {e}", exc_info=True)
            raise RuntimeError("Could not connect to PostgreSQL") from e

    def _get_connection(self):
        """Retrieve a connection from the pool."""
        try:
            conn = self.pool.getconn()
            conn.cursor_factory = RealDictCursor
            return conn
        except OperationalError as e:
            self.log_error(f"Failed to get connection from pool: {e}", exc_info=True)
            raise

    def _put_connection(self, conn, close=False):
        """Return connection to the pool or close it."""
        if close:
            try:
                conn.close()
            except Exception as e:
                self.log_error(f"Error closing connection: {e}", exc_info=True)
        else:
            self.pool.putconn(conn)

    def _ensure_schema(self):
        """Ensure required database tables exist."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                # Create subscriptions table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        email VARCHAR(255) PRIMARY KEY,
                        tier VARCHAR(50) NOT NULL,
                        license_key VARCHAR(255),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                # Create dev_codes table (includes frozen + tier + license_key)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dev_codes (
                        code VARCHAR(255) PRIMARY KEY,
                        email VARCHAR(255),
                        expires_at TIMESTAMP,
                        used BOOLEAN DEFAULT FALSE,
                        assigned_to VARCHAR(255),
                        device_id VARCHAR(255),
                        frozen BOOLEAN DEFAULT FALSE,
                        tier VARCHAR(50),
                        license_key VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                # Create installs table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS installs (
                        hashed_email VARCHAR(64) PRIMARY KEY,
                        install_id VARCHAR(7) UNIQUE NOT NULL,
                        tier VARCHAR(20) NOT NULL DEFAULT 'free',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                conn.commit()
                self.log_info(
                    "Verified/created database schema for subscriptions, dev_codes, and installs"
                )
        except Exception as e:
            self.log_error(f"Failed to ensure database schema: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                self._put_connection(conn)

    def validate_dev_code(self, code: str) -> dict:
        """Validate a developer unlock code.

        This method queries the ``dev_codes`` table for a given code and
        performs several checks:

        * The code must exist in the table.
        * It must not be marked as ``used``.
        * It must not be ``frozen``.
        * If an ``expires_at`` timestamp is set, it must not be in the past.

        A dictionary is returned containing the ``tier``, ``license_key`` and
        optional ``email`` associated with the code.  Defaults are provided
        when the stored values are ``NULL``.

        Parameters
        ----------
        code : str
            The developer code to validate.

        Returns
        -------
        dict
            Mapping with keys ``tier``, ``license_key``, and ``email``.

        Raises
        ------
        ValueError
            If the code is invalid, already used, frozen, or expired.
        RuntimeError
            If no connection pool is configured.
        """
        if not self.pool:
            raise RuntimeError("Database connection pool not initialized")

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                        SELECT code, email, used, expires_at, tier, license_key, frozen, assigned_to
                        FROM dev_codes
                        WHERE code = %s
                    """,
                    (code,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError("Invalid or unreachable developer code.")

                # When RealDictCursor is in effect, row is a dict; otherwise it's a tuple
                def get_field(idx_or_key):
                    if isinstance(row, dict):
                        return row[idx_or_key]
                    return row[idx_or_key]

                used_value = get_field("used") if isinstance(row, dict) else row[2]
                if used_value:
                    raise ValueError("Developer code already used.")

                frozen_value = get_field("frozen") if isinstance(row, dict) else row[6]
                if frozen_value:
                    raise ValueError("Developer code is frozen.")

                expires_at = get_field("expires_at") if isinstance(row, dict) else row[3]
                if expires_at and expires_at < datetime.utcnow():
                    raise ValueError("Developer code expired.")

                tier = get_field("tier") if isinstance(row, dict) else row[4]
                license_key = get_field("license_key") if isinstance(row, dict) else row[5]
                email = get_field("email") if isinstance(row, dict) else row[1]
                return {
                    "tier": tier or "Gold",
                    "license_key": license_key or "DEV_MODE",
                    "email": email or "dev@swiftsaleapp.com",
                }
        finally:
            if conn:
                self._put_connection(conn)