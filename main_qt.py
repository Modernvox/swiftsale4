import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
import requests
import socket
import threading
import sqlite3
import gc
from PySide6.QtWidgets import QApplication
from dotenv import load_dotenv

from cloud_database_qt import CloudDatabaseManager
from telegram_qt import TelegramService
from bidder_manager_qt import BidderManager
from flask_server_qt import FlaskServer
from gui_qt import SwiftSaleGUI
from stripe_service_qt import StripeService
from config_qt import load_config, DEFAULT_TRIAL_EMAIL, get_or_create_install_info, save_install_info

load_dotenv()
app = QApplication.instance() or QApplication(sys.argv)
qt_dir = os.path.abspath(os.path.dirname(__file__))
user_data_dir = os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), 'SwiftSaleApp')
os.makedirs(user_data_dir, exist_ok=True)
bidders_db_path = os.path.join(user_data_dir, 'bidders_qt.db')
subs_db_path = os.path.join(user_data_dir, 'subscriptions_qt.db')
log_file = os.path.join(user_data_dir, 'swiftsale_app.log')

def custom_log(level, message):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"{timestamp} [{level}] {message}\n"
    try:
        sys.stdout.write(log_message)
    except Exception:
        pass
    try:
        with open(log_file, 'a') as f:
            f.write(log_message)
    except Exception as e:
        sys.stderr.write(f"Failed to write to log: {e}\n")

def log_info(message):
    logging.info(message)
    custom_log("INFO", message)

def log_error(message, exc_info=False):
    logging.error(message, exc_info=exc_info)
    custom_log("ERROR", message)


if getattr(sys, 'frozen', False):  # Running as PyInstaller exe
    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgres"):
        os.environ["FLASK_ENV"] = "production"
    else:
        # Don’t raise an error — fall back to local dev
        os.environ["FLASK_ENV"] = "development"
        log_info("Falling back to development mode: DATABASE_URL not found or invalid.")
else:
    os.environ["FLASK_ENV"] = "development"

file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])

def verify_sqlite_file(path):
    try:
        conn = sqlite3.connect(path)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1;")
        conn.close()
        return True
    except sqlite3.DatabaseError:
        return False

def force_close_sqlite_db(path):
    gc.collect()
    time.sleep(0.2)

def create_blank_bidders_db(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        log_error(f"Failed to delete corrupted bidders_qt.db: {e}")
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY
            );
        """)
        cursor.execute("INSERT OR IGNORE INTO schema_version (version) VALUES ('1.0');")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bidders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                username TEXT NOT NULL,
                original_username TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                weight TEXT,
                is_giveaway INTEGER NOT NULL,
                bin_number INTEGER,
                giveaway_number INTEGER,
                timestamp TEXT NOT NULL,
                last_assigned TEXT,
                first_name TEXT,
                auction_id TEXT,
                UNIQUE(username, timestamp)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bin_assignments (
                username TEXT PRIMARY KEY,
                bin_number INTEGER NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shows (
                show_id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT
            );
        """)
        conn.commit()
        log_info(f"Blank bidders_qt.db created at {path}")

def create_blank_subscriptions_db(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        log_error(f"Failed to delete corrupted subscriptions_qt.db: {e}")
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY
            );
        """)
        cursor.execute("INSERT OR IGNORE INTO schema_version (version) VALUES ('1.0');")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                email TEXT PRIMARY KEY,
                tier TEXT NOT NULL,
                license_key TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                email TEXT PRIMARY KEY,
                chat_id TEXT,
                top_buyer_text TEXT,
                giveaway_announcement_text TEXT,
                flash_sale_announcement_text TEXT,
                multi_buyer_mode BOOLEAN,
                FOREIGN KEY (email) REFERENCES subscriptions(email)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS installs (
                hashed_email TEXT PRIMARY KEY,
                install_id TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'Trial'
            );
        """)
        conn.commit()
        log_info(f"Blank subscriptions_qt.db created at {path}")

def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False

def find_open_port(start_port=8000, max_attempts=10):
    for port in range(start_port, start_port + max_attempts):
        if check_port(port):
            return port
    raise RuntimeError("No available ports found")

def wait_for_server(url, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=5).status_code == 200:
                log_info("Flask server health check passed")
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError("Flask server did not start in time")

def main():
    log_info("Starting SwiftSale GUI")
    install_info = get_or_create_install_info()
    user_email = install_info.get("email", "trial@swiftsaleapp.com")
    device_id = install_info.get("install_id")

    # Prompt for real email if still using default trial email
    if user_email == "trial@swiftsaleapp.com":
        from PySide6.QtWidgets import QInputDialog
        email, ok = QInputDialog.getText(None, "Enter Your Email", "Please enter your SwiftSale email:")
        if ok and email:
            user_email = email.strip().lower()
            install_info["email"] = user_email
            save_install_info(user_email, install_info.get("install_id"), install_info.get("tier"))
            log_info(f"User email set to: {user_email}")

            # Auto-update installs table with hashed_email -> tier mapping
            try:
                # Enforce 2-device limit
                if os.getenv("FLASK_ENV") == "production":
                    import hashlib
                    from PySide6.QtWidgets import QMessageBox
                    from cloud_database_qt import CloudDatabaseManager

                    hashed_email = hashlib.sha256(user_email.strip().lower().encode()).hexdigest()
                    cloud_db_tmp = CloudDatabaseManager(log_info=log_info, log_error=log_error)

                    with cloud_db_tmp.pool.connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                SELECT 1 FROM install_devices
                                WHERE hashed_email = %s AND device_id = %s
                            """, (hashed_email, device_id))
                            if cur.fetchone():
                                log_info(f"Device {device_id} already registered for {user_email}")
                            else:
                                cur.execute("""
                                    SELECT COUNT(*) FROM install_devices
                                    WHERE hashed_email = %s
                                """, (hashed_email,))
                                count = cur.fetchone()[0]
                                if count < 2:
                                    cur.execute("""
                                        INSERT INTO install_devices (raw_email, hashed_email, device_id)
                                        VALUES (%s, %s, %s)
                                    """, (user_email, hashed_email, device_id))
                                    log_info(f"Registered device {device_id} for {user_email}")
                                else:
                                    QMessageBox.critical(None, "Access Denied", f"{user_email} is already signed in on 2 devices.")
                                    sys.exit(1)
                    cloud_db_tmp.close()
            except Exception as e:
                QMessageBox.critical(None, "Database Error", f"Device limit check failed:\n{e}")
                sys.exit(1)

            
    config = load_config()
    redacted = {k: ("<REDACTED>" if any(x in k for x in ["KEY", "TOKEN", "SECRET"]) else v) for k, v in config.items()}
    log_info(f"Loaded config: {redacted}")

    port = find_open_port(int(config.get("PORT", 8000)))
    config["PORT"] = str(port)
    config["APP_BASE_URL"] = f"http://localhost:{port}"

    # Initialize database paths
    if not os.path.exists(bidders_db_path) or not verify_sqlite_file(bidders_db_path):
        force_close_sqlite_db(bidders_db_path)
        create_blank_bidders_db(bidders_db_path)
    if not os.path.exists(subs_db_path) or not verify_sqlite_file(subs_db_path):
        force_close_sqlite_db(subs_db_path)
        create_blank_subscriptions_db(subs_db_path)

    bidder_manager = BidderManager(
        bidders_db_path=bidders_db_path,
        subs_db_path=subs_db_path,
        log_info=log_info,
        log_error=log_error,
    )

    stripe_service = StripeService(
        stripe_secret_key=config["STRIPE_SECRET_KEY"],
        webhook_secret=config["STRIPE_WEBHOOK_SECRET"],
        api_token=config["API_TOKEN"],
        db_manager=bidder_manager 
    )

    telegram_service = TelegramService(
        bot_token=config["TELEGRAM_BOT_TOKEN"],
        chat_id=config["TELEGRAM_CHAT_ID"],
        log_info=log_info,
        log_error=log_error
    )

    def latest_bin_callback(bin_info):
        log_info(f"Latest bin callback received: {bin_info}")

    cloud_db = None
    if os.getenv("FLASK_ENV", "development") == "production":
        try:
            cloud_db = CloudDatabaseManager(log_info=log_info, log_error=log_error)
        except Exception as e:
            log_error(f"Failed to initialize CloudDatabaseManager: {e}", exc_info=True)

    flask_server = FlaskServer(
        port=port,
        stripe_service=stripe_service,
        api_token=config["API_TOKEN"],
        latest_bin_assignment_callback=latest_bin_callback,
        secret_key=config["SECRET_KEY"],
        log_info=log_info,
        log_error=log_error,
        user_data_dir=user_data_dir,
        bidder_manager=bidder_manager,
        telegram_service=telegram_service
    )
    threading.Thread(target=flask_server.start, daemon=True).start()
    wait_for_server(f"http://localhost:{port}/health")
 
    gui = SwiftSaleGUI(
        stripe_service=stripe_service,  # Pass stripe_service instead of None
        api_token=config["API_TOKEN"],
        user_email=user_email,
        base_url=config["APP_BASE_URL"],
        dev_unlock_code = config.get("DEV_UNLOCK_CODE", ""),
        telegram_bot_token=config.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=config.get("TELEGRAM_CHAT_ID", ""),
        dev_access_granted=False,
        log_info=log_info,
        log_error=log_error,
        bidder_manager=bidder_manager,
        bidders_db_path=bidders_db_path,
        subs_db_path=subs_db_path
    )

    gui.cloud_db = cloud_db
    gui.telegram_service = telegram_service

    # Sync cloud install info (tier/license) into local
    if cloud_db and user_email:
        try:
            cloud_db.sync_with_local(bidder_manager, user_email)
            tier = bidder_manager.get_tier_for_user(user_email)
            install_info["tier"] = tier
            save_install_info(user_email, install_info.get("install_id"), tier)
            log_info(f"[SYNC] Synced and saved cloud tier '{tier}' for {user_email}")
            gui.show_toast(f"✔ License Verified – {tier} Tier")
        except Exception as e:
            log_error(f"Cloud sync failed for {user_email}: {e}")

    gui.show()

    def on_closing():
        try:
            if cloud_db:
                cloud_db.close()
            telegram_service.close()
            flask_server.shutdown()
            bidder_manager.close()
        except Exception as e:
            log_error(f"Error during shutdown: {e}")
        app.quit()

    gui.closeEvent = lambda event: [on_closing(), event.accept()]
    sys.exit(app.exec())

if __name__ == "__main__":
    main()