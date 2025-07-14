import os
import sys
import json
import logging
from cryptography.fernet import Fernet

# ─── LOGGING SETUP ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── STRIPE PRICE IDS ──────────────────────────────────────
PRICE_MAP = {
    "Bronze": "price_1RLcP4J7WrcpTNl6a8aHdSgv",
    "Silver": "price_1RLcKcJ7WrcpTNl6jT7sLvmU",
    "Gold":   "price_1RQefvJ7WrcpTNl68QwN2zEj",
}
REVERSE_PRICE_MAP = {v: k for k, v in PRICE_MAP.items()}

# ─── LOCAL FILE PATHS ──────────────────────────────
DEFAULT_DATA_DIR = os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), "SwiftSaleApp")
REMEMBER_ME_PATH = os.path.join(DEFAULT_DATA_DIR, "remember_me.json")
CONFIG_PATH = os.path.join(DEFAULT_DATA_DIR, "config.json")
NGROK_PATH = os.getenv("NGROK_PATH", os.path.join(USER_DATA_DIR, "ngrok.exe"))


# ─── BIN LIMITS PER TIER ──────────────────────────
TIER_LIMITS = {
    "Trial":  {"bins": 20},
    "Bronze": {"bins": 50},
    "Silver": {"bins": 150},
    "Gold":   {"bins": 300},
}

# ─── PATH UTIL ─────────────────────────────────────

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def ensure_data_dir():
    os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)
    logger.debug(f"Ensured data directory exists: {DEFAULT_DATA_DIR}")

# ─── REMEMBER ME EMAIL STORAGE ───────────────────────────

def save_email(email: str):
    try:
        ensure_data_dir()
        config = load_config()
        config['USER_EMAIL'] = email
        save_config(config)
        logger.info(f"Saved email to {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to save email: {e}")

def load_email() -> str:
    try:
        config = load_config()
        return config.get('USER_EMAIL', '')
    except Exception as e:
        logger.error(f"Failed to load email: {e}")
        return ''

def clear_saved_email():
    try:
        config = load_config()
        config['USER_EMAIL'] = ''
        save_config(config)
        logger.info(f"Cleared saved email in {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to clear saved email: {e}")

# ─── INSTALL ID AND TIER STORAGE ───────────────────────────

def save_install_info(email: str, install_id: str, tier: str):
    """Save email, install_id, and tier to config.json."""
    try:
        ensure_data_dir()
        config = load_config()
        config['USER_EMAIL'] = email
        config['INSTALL_ID'] = install_id
        config['TIER'] = tier
        save_config(config)
        logger.info(f"Saved install info: email={email}, install_id={install_id}, tier={tier}")
    except Exception as e:
        logger.error(f"Failed to save install info: {e}")
        raise

def load_install_info():
    """Load email, install_id, and tier from config.json."""
    try:
        config = load_config()
        return {
            'email': config.get('USER_EMAIL', ''),
            'install_id': config.get('INSTALL_ID', ''),
            'tier': config.get('TIER', 'Trial')
        }
    except Exception as e:
        logger.error(f"Failed to load install info: {e}")
        return {'email': '', 'install_id': '', 'tier': 'Trial'}

# ─── MAIN CONFIG LOADER ───────────────────────────

def load_config():
    """Load local-only config with zero production risk."""
    ensure_data_dir()

    # Default config
    config = {
        "API_TOKEN": os.getenv("API_TOKEN", "dev-api-token"),
        "USER_EMAIL": "",
        "INSTALL_ID": "",
        "TIER": "Trial",
        "APP_BASE_URL": os.getenv("APP_BASE_URL", "http://localhost:5000"),
        "PORT": os.getenv("PORT", "5000"),
        "DATABASE_URL": f"sqlite:///{os.path.join(DEFAULT_DATA_DIR, 'subscriptions_qt.db')}",
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "dummy-bot-token"),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", "123456"),
        "DEV_UNLOCK_CODE": os.getenv("DEV_UNLOCK_CODE", "letmein"),
        "SECRET_KEY": os.urandom(24).hex(),
        "SUCCESS_URL": os.getenv("SUCCESS_URL", "http://localhost:5000/success"),
        "CANCEL_URL": os.getenv("CANCEL_URL", "http://localhost:5000/cancel"),
        "FLASK_ENV": os.getenv("FLASK_ENV", "development"),
    }

    # Override with values from config.json if it exists
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                file_config = json.load(f)
            config.update(file_config)
            logger.info(f"Loaded config from {CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Failed to load config from {CONFIG_PATH}: {e}")

    # Stripe secrets (decrypt if FERNET_KEY is available)
    fernet_key = os.getenv("FERNET_KEY")
    enc_secret = os.getenv("ENCRYPTED_STRIPE_SECRET_KEY", "")
    enc_webhook = os.getenv("ENCRYPTED_STRIPE_WEBHOOK_SECRET", "")

    if fernet_key:
        try:
            fernet = Fernet(fernet_key.encode())
            config["STRIPE_SECRET_KEY"] = fernet.decrypt(enc_secret.encode()).decode() if enc_secret else "sk_test_dummy"
            config["STRIPE_WEBHOOK_SECRET"] = fernet.decrypt(enc_webhook.encode()).decode() if enc_webhook else "whsec_dummy"
        except Exception as e:
            logger.error(f"Failed to decrypt Stripe config: {e}")
            config["STRIPE_SECRET_KEY"] = "sk_test_dummy"
            config["STRIPE_WEBHOOK_SECRET"] = "whsec_dummy"
    else:
        config["STRIPE_SECRET_KEY"] = os.getenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        config["STRIPE_WEBHOOK_SECRET"] = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_dummy")

    config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY", "pk_test_dummy")

    # Override APP_BASE_URL for production (Render.com)
    if config["FLASK_ENV"] == "production":
        config["APP_BASE_URL"] = os.getenv("APP_BASE_URL", "https://yourapp.onrender.com")
        config["SUCCESS_URL"] = f"{config['APP_BASE_URL']}/success"
        config["CANCEL_URL"] = f"{config['APP_BASE_URL']}/cancel"

    return config

def save_config(config_dict):
    """Save the provided dictionary to the config.json file."""
    try:
        ensure_data_dir()
        with open(CONFIG_PATH, "w") as f:
            json.dump(config_dict, f, indent=4)
        logger.info(f"Config saved to {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise