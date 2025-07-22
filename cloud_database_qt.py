import os
import sys
import psycopg2
from psycopg2 import OperationalError, pool
from psycopg2.extras import RealDictCursor
import logging
from datetime import datetime, timezone
import time
from config_qt import get_config_value

class CloudDatabaseManager:
    def __init__(self, log_info=None, log_error=None):
        self.log_info = log_info or logging.info
        self.log_error = log_error or logging.error

        env = os.getenv("ENV", "development")

        # DO NOT force prod mode just because app is frozen
        # This lets you test a frozen .exe locally without hitting Render
        if env != "production":
            self.log_info("Cloud sync skipped (non-production environment).")
            return

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
                connect_timeout=5
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
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        email VARCHAR(255) PRIMARY KEY,
                        tier VARCHAR(50) NOT NULL,
                        license_key VARCHAR(255),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # Create dev_codes table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dev_codes (
                        code VARCHAR(255) PRIMARY KEY,
                        email VARCHAR(255),
                        expires_at TIMESTAMP,
                        used BOOLEAN DEFAULT FALSE,
                        assigned_to VARCHAR(255),
                        device_id VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # Create installs table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS installs (
                        hashed_email VARCHAR(64) PRIMARY KEY,
                        install_id VARCHAR(7) UNIQUE NOT NULL,
                        tier VARCHAR(20) NOT NULL DEFAULT 'free',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
                self.log_info("Verified/created database schema for subscriptions, dev_codes, and installs")
        except Exception as e:
            self.log_error(f"Failed to ensure database schema: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                self._put_connection(conn)

    def get_install_by_hashed_email(self, hashed_email):
        """Fetch install record by hashed email."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT install_id, tier FROM installs WHERE hashed_email = %s",
                    (hashed_email,)
                )
                row = cur.fetchone()
                if row:
                    self.log_info(f"Found install for hashed_email={hashed_email}: install_id={row['install_id']}, tier={row['tier']}")
                    return {"install_id": row['install_id'], "tier": row['tier']}
                self.log_info(f"No install found for hashed_email={hashed_email}")
                return None
        except Exception as e:
            self.log_error(f"Error fetching install for hashed_email={hashed_email}: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def get_last_install(self):
        """Fetch the last install record by install_id."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT install_id FROM installs ORDER BY install_id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    self.log_info(f"Found last install: install_id={row['install_id']}")
                    return {"install_id": row['install_id']}
                self.log_info("No installs found")
                return None
        except Exception as e:
            self.log_error(f"Error fetching last install: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def save_install(self, install_data):
        """Save a new install record."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO installs (hashed_email, install_id, tier, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        install_data['hashed_email'],
                        install_data['install_id'],
                        install_data['tier'],
                        datetime.now(timezone.utc)
                    )
                )
                conn.commit()
                self.log_info(f"Saved install: hashed_email={install_data['hashed_email']}, install_id={install_data['install_id']}, tier={install_data['tier']}")
        except Exception as e:
            self.log_error(f"Error saving install: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def update_install_tier(self, hashed_email, tier):
        """Update tier for an install record."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE installs SET tier = %s, updated_at = %s
                    WHERE hashed_email = %s
                    """,
                    (tier, datetime.now(timezone.utc), hashed_email)
                )
                conn.commit()
                self.log_info(f"Updated install tier to {tier} for hashed_email={hashed_email}")
        except Exception as e:
            self.log_error(f"Error updating install tier for hashed_email={hashed_email}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def update_subscription(self, user_email, tier, license_key):
        """Update or insert a subscription record."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO subscriptions (email, tier, license_key, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        tier = EXCLUDED.tier,
                        license_key = EXCLUDED.license_key,
                        updated_at = EXCLUDED.updated_at
                """, (user_email, tier, license_key, datetime.now(timezone.utc)))
                conn.commit()
                self.log_info(f"Updated subscription for {user_email}: tier={tier}, license_key={license_key}")
        except Exception as e:
            self.log_error(f"Failed to update subscription for {user_email}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def load_subscription_by_id(self, license_key):
        """Retrieve subscription by license key."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT email, tier, license_key FROM subscriptions WHERE license_key = %s", (license_key,))
                row = cur.fetchone()
                if row:
                    self.log_info(f"Loaded subscription for license_key={license_key}: {row['email']}, {row['tier']}")
                    return (row['email'], row['tier'], row['license_key'])
                self.log_info(f"No subscription found for license_key={license_key}")
                return (None, None, None)
        except Exception as e:
            self.log_error(f"Failed to load subscription by license_key={license_key}: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def load_subscription_by_email(self, user_email):
        """Retrieve subscription by user email."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT email, tier, license_key FROM subscriptions WHERE email = %s", (user_email,))
                row = cur.fetchone()
                if row:
                    self.log_info(f"Loaded subscription for {user_email}: tier={row['tier']}, license_key={row['license_key']}")
                    return (row['email'], row['tier'], row['license_key'])
                self.log_info(f"No subscription found for {user_email}")
                raise RuntimeError("No subscription found. Launching app in free trial mode.")
        except Exception as e:
            self.log_error(f"Failed to load subscription for {user_email}: {e}", exc_info=True)
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def delete_subscription(self, user_email):
        """Delete a subscription by user email."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subscriptions WHERE email = %s", (user_email,))
                conn.commit()
                self.log_info(f"Deleted subscription for {user_email}")
        except Exception as e:
            self.log_error(f"Failed to delete subscription for {user_email}: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                self._put_connection(conn)

    def validate_dev_code(self, code, user_email, device_id):
        """Validate a developer code and assign it if valid."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT email, expires_at, used, assigned_to, device_id, tier, license_key
                    FROM dev_codes
                    WHERE code = %s
                """, (code,))
                row = cur.fetchone()
                if not row:
                    self.log_info(f"Dev code {code} not found")
                    raise RuntimeError("Invalid or expired developer code. Try again or contact support.")

                email, expires_at, used, assigned_to, bound_device, tier, license_key = (
                    row['email'], row['expires_at'], row['used'],
                    row['assigned_to'], row['device_id'],
                    row.get('tier') or 'Gold',
                    row.get('license_key') or 'DEV_MODE'
                )

                now = datetime.now(timezone.utc)

                # Ensure expires_at is timezone-aware to avoid comparison errors
                if expires_at and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if expires_at and now > expires_at:
                    self.log_info(f"Dev code {code} expired on {expires_at}")
                    raise RuntimeError("Developer code expired. Try again or contact support.")

                if used:
                    if assigned_to != user_email or bound_device != device_id:
                        self.log_info(f"Dev code {code} rejected: bound to {assigned_to}/{bound_device}")
                        raise RuntimeError("Developer code already in use on another device or email.")
                else:
                    from datetime import timedelta
                    expires = None if code.lower() == "brandi9933" else now + timedelta(hours=48)
                    cur.execute("""
                        UPDATE dev_codes
                        SET used = TRUE, assigned_to = %s, device_id = %s, expires_at = %s
                        WHERE code = %s
                    """, (user_email, device_id, expires, code))
                    conn.commit()
                    self.log_info(f"Assigned dev code {code} to {user_email}/{device_id}")

                return {
                    "tier": tier,
                    "license_key": license_key
                }

        except RuntimeError:
            raise
        except Exception as e:
            self.log_error(f"Failed to validate dev code {code}: {e}", exc_info=True)
            raise RuntimeError("An unexpected error occurred while validating your developer code.")
        finally:
            if conn:
                self._put_connection(conn)

    def sync_with_local(self, bidder_manager, user_email):
        """Sync cloud subscription and install data with local BidderManager."""
        try:
            # Sync subscription
            email, tier, license_key = self.load_subscription_by_email(user_email)
            if email:
                bidder_manager.update_subscription(user_email, tier, license_key)
                self.log_info(f"Synced cloud subscription for {user_email}: tier={tier}, license_key={license_key}")
            else:
                self.log_info(f"No cloud subscription found for {user_email}")

            # Sync install (optional, if needed by BidderManager)
            import hashlib
            hashed_email = hashlib.sha256(user_email.encode()).hexdigest()
            install = self.get_install_by_hashed_email(hashed_email)
            if install:
                bidder_manager.update_install(hashed_email, install['install_id'], install['tier'])
                self.log_info(f"Synced install for {user_email}: install_id={install['install_id']}, tier={install['tier']}")
            else:
                self.log_info(f"No install found for {user_email}")
        except Exception as e:
            self.log_error(f"Failed to sync for {user_email}: {e}", exc_info=True)
            raise

    def close(self):
        """Close the connection pool."""
        if self.pool:
            self.pool.closeall()
            self.log_info("Closed PostgreSQL connection pool")