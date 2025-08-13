"""
CloudDatabaseManager

Production-only PostgreSQL access for SwiftSaleApp running on Render.
Provides a small, safe API used by StripeService and server endpoints.

Key features:
- Threaded connection pool (psycopg2)
- Schema bootstrap for subscriptions, dev_codes, installs
- Helpers: get/set subscription, validate dev code, mark code used
- Minimal, explicit error handling and logging
"""

from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Optional, Tuple

# psycopg2 is intentionally NOT imported at module load to keep desktop builds safe.
# We lazy-import inside methods when actually needed.

from config_qt import get_config_value


def _is_prod_runtime() -> bool:
    """
    Consider 'production' when running on Render or when APP_ENV/FLASK_ENV is production.
    DATABASE_URL must be postgres://... too.
    """
    render = os.getenv("RENDER", "").lower() == "true"
    app_env = (get_config_value("APP_ENV") or os.getenv("APP_ENV") or os.getenv("FLASK_ENV", "development")).lower()
    db_url = (get_config_value("DATABASE_URL") or os.getenv("DATABASE_URL") or "")
    is_pg = db_url.startswith("postgres")
    return (render or app_env == "production") and is_pg


class CloudDatabaseManager:
    # ------------------------------
    # Init & pool
    # ------------------------------
    def __init__(self, log_info=None, log_error=None):
        self.log_info = log_info or logging.info
        self.log_error = log_error or logging.error

        if not _is_prod_runtime():
            raise RuntimeError(
                "CloudDatabaseManager disabled (non-production or DATABASE_URL not postgres)."
            )

        self.pool = None  # type: ignore[assignment]
        self._initialize_connection_pool()
        self._ensure_schema()

    def _pg(self):
        """Lazy import psycopg2 modules. Raises cleanly if not available."""
        try:
            import psycopg2  # type: ignore
            from psycopg2 import OperationalError, pool  # type: ignore
            from psycopg2.extras import RealDictCursor  # type: ignore
            return psycopg2, OperationalError, pool, RealDictCursor
        except Exception as e:
            self.log_error("PostgreSQL driver not available", exc_info=True)
            raise RuntimeError("PostgreSQL driver not available") from e

    def _initialize_connection_pool(self):
        """Initialize a thread-safe connection pool."""
        db_url = get_config_value("DATABASE_URL") or os.getenv("DATABASE_URL")
        if not db_url or not db_url.startswith("postgres"):
            raise RuntimeError("DATABASE_URL not set or invalid.")

        psycopg2, OperationalError, pool_mod, _ = self._pg()
        try:
            self.pool = pool_mod.ThreadedConnectionPool(
                minconn=1,
                maxconn=int(os.getenv("PG_POOL_MAX", "10")),
                dsn=db_url,
                connect_timeout=5,
            )
            self.log_info("Initialized PostgreSQL connection pool")
        except OperationalError as e:
            self.log_error("Could not initialize connection pool", exc_info=True)
            raise RuntimeError("Could not connect to PostgreSQL") from e

    def _get_connection(self):
        """Retrieve a connection from the pool."""
        if not self.pool:
            raise RuntimeError("Database connection pool not initialized")
        try:
            return self.pool.getconn()  # type: ignore[no-any-return]
        except Exception:
            self.log_error("Failed to get connection from pool", exc_info=True)
            raise

    def _put_connection(self, conn, close: bool = False):
        """Return connection to the pool or close it."""
        if not conn:
            return
        if close or not self.pool:
            try:
                conn.close()
            except Exception:
                self.log_error("Error closing connection", exc_info=True)
        else:
            try:
                self.pool.putconn(conn)  # type: ignore[arg-type]
            except Exception:
                self.log_error("Error returning connection to pool", exc_info=True)

    # ------------------------------
    # Schema
    # ------------------------------
    def _ensure_schema(self):
        """Ensure required database tables exist."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                # subscriptions
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
                # dev_codes (add missing updated_at)
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                # installs
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
                self.log_info("Verified/created schema: subscriptions, dev_codes, installs")
        except Exception:
            if conn:
                conn.rollback()
            self.log_error("Failed to ensure database schema", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    # ------------------------------
    # Subscriptions
    # ------------------------------
    def get_user_tier(self, email: str) -> Optional[str]:
        """Return user's tier from subscriptions (or None)."""
        conn = None
        try:
            conn = self._get_connection()
            _, _, _, RealDictCursor = self._pg()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT tier FROM subscriptions WHERE email = %s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                return (row and row.get("tier")) or None
        except Exception:
            self.log_error("get_user_tier failed", exc_info=True)
            return None
        finally:
            if conn:
                self._put_connection(conn)

    def get_user_license_key(self, email: str) -> Optional[str]:
        """Return user's license_key from subscriptions (or None)."""
        conn = None
        try:
            conn = self._get_connection()
            _, _, _, RealDictCursor = self._pg()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT license_key FROM subscriptions WHERE email = %s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                return (row and row.get("license_key")) or None
        except Exception:
            self.log_error("get_user_license_key failed", exc_info=True)
            return None
        finally:
            if conn:
                self._put_connection(conn)

    def set_user_subscription(self, email: str, tier: str, license_key: Optional[str]):
        """Upsert subscription (email, tier, license_key)."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO subscriptions (email, tier, license_key, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (email)
                    DO UPDATE SET tier = EXCLUDED.tier,
                                  license_key = EXCLUDED.license_key,
                                  updated_at = CURRENT_TIMESTAMP
                    """,
                    (email, tier, license_key),
                )
                conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            self.log_error("set_user_subscription failed", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    # ------------------------------
    # Dev codes
    # ------------------------------
    def validate_dev_code(self, code: str) -> dict:
        """
        Validate a developer unlock code.
        Returns dict with keys: tier, license_key, email.
        Raises ValueError on invalid/used/frozen/expired.
        """
        conn = None
        try:
            conn = self._get_connection()
            _, _, _, RealDictCursor = self._pg()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
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

                if row.get("used"):
                    raise ValueError("Developer code already used.")
                if row.get("frozen"):
                    raise ValueError("Developer code is frozen.")

                expires_at = row.get("expires_at")
                if expires_at and expires_at < datetime.utcnow():
                    raise ValueError("Developer code expired.")

                tier = row.get("tier") or "Gold"
                license_key = row.get("license_key") or "DEV_MODE"
                email = row.get("email") or "dev@swiftsaleapp.com"
                return {"tier": tier, "license_key": license_key, "email": email}
        finally:
            if conn:
                self._put_connection(conn)

    def mark_dev_code_used(
        self,
        code: str,
        assigned_to: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> None:
        """Mark a dev code as used and (optionally) bind it to a user/device."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dev_codes
                    SET used = TRUE,
                        assigned_to = COALESCE(%s, assigned_to),
                        device_id = COALESCE(%s, device_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE code = %s
                    """,
                    (assigned_to, device_id, code),
                )
                conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            self.log_error("mark_dev_code_used failed", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    # ------------------------------
    # Installs
    # ------------------------------
    def get_install(self, hashed_email: str) -> Optional[Tuple[str, str]]:
        """Return (install_id, tier) for hashed_email, or None."""
        conn = None
        try:
            conn = self._get_connection()
            _, _, _, RealDictCursor = self._pg()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT install_id, tier
                    FROM installs
                    WHERE hashed_email = %s
                    LIMIT 1
                    """,
                    (hashed_email,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return (row.get("install_id"), row.get("tier"))
        except Exception:
            self.log_error("get_install failed", exc_info=True)
            return None
        finally:
            if conn:
                self._put_connection(conn)

    def upsert_install(self, hashed_email: str, install_id: str, tier: str = "free"):
        """Create or update install row for hashed_email."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO installs (hashed_email, install_id, tier, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (hashed_email)
                    DO UPDATE SET install_id = EXCLUDED.install_id,
                                  tier = EXCLUDED.tier,
                                  updated_at = CURRENT_TIMESTAMP
                    """,
                    (hashed_email, install_id, tier),
                )
                conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            self.log_error("upsert_install failed", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def update_install_tier(self, hashed_email: str, tier: str):
        """Update tier for an existing install."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE installs
                    SET tier = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE hashed_email = %s
                    """,
                    (tier, hashed_email),
                )
                conn.commit()
        except Exception:
            if conn:
                conn.rollback()
            self.log_error("update_install_tier failed", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    # ------------------------------
    # Shutdown
    # ------------------------------
    def close(self):
        """Close the pool (on app shutdown)."""
        try:
            if self.pool:
                self.pool.closeall()  # type: ignore[union-attr]
                self.pool = None
        except Exception:
            self.log_error("Error closing pool", exc_info=True)
