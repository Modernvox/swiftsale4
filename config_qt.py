import os
import sys
import json
import logging
import uuid
from cryptography.fernet import Fernet

INSTALL_INFO_PATH = os.path.join(
    os.getenv("LOCALAPPDATA", os.path.expanduser("~")),
    "SwiftSaleApp",
    "install_info.json"
)

def load_install_info():
    if not os.path.exists(INSTALL_INFO_PATH):
        return {}
    try:
        with open(INSTALL_INFO_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_install_info(email, install_id, tier):
    try:
        os.makedirs(os.path.dirname(INSTALL_INFO_PATH), exist_ok=True)
        data = {
            "email": email,
            "install_id": install_id,
            "tier": tier
        }
        with open(INSTALL_INFO_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save install info: {e}")

def get_or_create_install_info():
    """Ensure install_info.json exists and has install_id, email, and tier."""
    if not os.path.exists(INSTALL_INFO_PATH):
        os.makedirs(os.path.dirname(INSTALL_INFO_PATH), exist_ok=True)
        install_id = str(uuid.uuid4())[:8]  # short UUID
        info = {
            "email": "trial@swiftsaleapp.com",
            "install_id": install_id,
            "tier": "Trial"
        }
        with open(INSTALL_INFO_PATH, "w") as f:
            json.dump(info, f, indent=2)
        return info

    # Patch older versions if needed
    info = load_install_info()
    changed = False
    if not info.get("install_id"):
        info["install_id"] = str(uuid.uuid4())[:8]
        changed = True
    if not info.get("email"):
        info["email"] = "trial@swiftsaleapp.com"
        changed = True
    if not info.get("tier"):
        info["tier"] = "Trial"
        changed = True

    if changed:
        save_install_info(info["email"], info["install_id"], info["tier"])

    return info

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
CONFIG_PATH = os.path.join(DEFAULT_DATA_DIR, "config.json")
NGROK_PATH = os.getenv("NGROK_PATH", os.path.join(DEFAULT_DATA_DIR, "ngrok.exe"))
DEFAULT_TRIAL_EMAIL = "trial@swiftsaleapp.com"


# ─── BIN LIMITS PER TIER ──────────────────────────
TIER_LIMITS = {
    "Trial":  {"bins": 20},
    "Bronze": {"bins": 50},
    "Silver": {"bins": 150},
    "Gold":   {"bins": 600},
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

# ─── CONFIG LOADING ───────────────────────────────
def load_config():
    """Load all critical app settings, enforce strict secret validation in production."""
    ensure_data_dir()

    logger = logging.getLogger("config_qt_debug")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())

    env = os.getenv("FLASK_ENV", "development").lower()
    logger.debug(f"Running in environment: {env}")


    config = {
        "FLASK_ENV": env,
        "PORT": os.getenv("PORT", "5000"),
        "APP_BASE_URL": os.getenv("APP_BASE_URL", "http://localhost:5000"),
        "DATABASE_URL": os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(DEFAULT_DATA_DIR, 'subscriptions_qt.db')}"),
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
        "API_TOKEN": os.getenv("API_TOKEN", ""),
        "DEV_UNLOCK_CODE": os.getenv("DEV_UNLOCK_CODE", "letmein"),
        "SECRET_KEY": os.getenv("SECRET_KEY"),
        "USER_EMAIL": "",
        "INSTALL_ID": "",
        "TIER": "Trial",
    }

    # Load Stripe secrets (required in production)
    fernet_key = os.getenv("FERNET_KEY")
    enc_secret = os.getenv("ENCRYPTED_STRIPE_SECRET_KEY", "")
    enc_webhook = os.getenv("ENCRYPTED_STRIPE_WEBHOOK_SECRET", "")

    logger = logging.getLogger("config_qt_debug")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())

    logger.debug(f"FERNET_KEY: {bool(fernet_key)}")
    logger.debug(f"ENCRYPTED_STRIPE_SECRET_KEY: {bool(enc_secret)}")
    logger.debug(f"ENCRYPTED_STRIPE_WEBHOOK_SECRET: {bool(enc_webhook)}")

    if fernet_key:
        try:
            fernet = Fernet(fernet_key.encode())
            config["STRIPE_SECRET_KEY"] = fernet.decrypt(enc_secret.encode()).decode()
            config["STRIPE_WEBHOOK_SECRET"] = fernet.decrypt(enc_webhook.encode()).decode()
        except Exception as e:
            logger.critical(f"Fernet decryption failed: {e}")
            raise RuntimeError(" Critical: Unable to decrypt Stripe keys.")
    else:
        config["STRIPE_SECRET_KEY"] = os.getenv("STRIPE_SECRET_KEY")
        config["STRIPE_WEBHOOK_SECRET"] = os.getenv("STRIPE_WEBHOOK_SECRET")

    config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # Validate secrets in production
    if env == "production":
        required = [
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PUBLIC_KEY",
            "SECRET_KEY", "APP_BASE_URL", "DATABASE_URL"
        ]
        for key in required:
            if not config.get(key):
                raise RuntimeError(f" Missing required env var in production: {key}")

    # Success/cancel URL for Stripe
    config["SUCCESS_URL"] = f"{config['APP_BASE_URL']}/success"
    config["CANCEL_URL"] = f"{config['APP_BASE_URL']}/cancel"

    # Load overrides from config.json if available (safe only for local)
    if os.path.exists(CONFIG_PATH) and env != "production":
        try:
            with open(CONFIG_PATH, 'r') as f:
                file_config = json.load(f)
            config.update(file_config)
            logger.info(f"Loaded config overrides from {CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"Failed to load config.json overrides: {e}")

    return config

def save_config(config_dict):
    try:
        ensure_data_dir()
        with open(CONFIG_PATH, "w") as f:
            json.dump(config_dict, f, indent=4)
        logger.info(f"Saved config to {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise

# ─── HELPER TO GET SINGLE CONFIG VALUE ────────────────
_app_config_cache = None

_app_config_cache = None

def get_config_value(key):
    """Always prioritize live environment variables for critical keys."""
    if key in os.environ:
        return os.environ[key]

    global _app_config_cache
    if _app_config_cache is None:
        _app_config_cache = load_config()
    return _app_config_cache.get(key)

def reload_config_cache():
    """Force a fresh reload of app config."""
    global _app_config_cache
    _app_config_cache = load_config()
