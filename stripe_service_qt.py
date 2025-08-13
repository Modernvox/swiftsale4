import logging
import hashlib
from config_qt import PRICE_MAP, REVERSE_PRICE_MAP, TIER_LIMITS

class StripeService:
    def __init__(self, db_manager, api_token, env="development"):
        self.db_manager = db_manager
        self.api_token = api_token
        self.env = env
        self.price_map = PRICE_MAP
        self.reverse_price_map = REVERSE_PRICE_MAP
        logging.info("StripeService initialized (payment link mode) env: %s", env)

    def hash_email(self, email):
        return hashlib.sha256(email.lower().encode()).hexdigest()

    def upgrade_subscription(self, user_email, new_tier, license_key):
        if license_key == "DEV_MODE":
            self.db_manager.update_subscription(user_email, new_tier, "DEV_MODE")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, new_tier)
                logging.info(f"(dev) Install upgraded to {new_tier} for {user_email}")
            return True
        return False

    def cancel_subscription(self, user_email, license_key):
        if license_key == "DEV_MODE":
            self.db_manager.update_subscription(user_email, "Trial", "")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, "free")
                logging.info(f"(dev) Subscription cancelled for {user_email}")
            return True
        return False
