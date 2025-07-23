import stripe
import logging
import hashlib
from config_qt import PRICE_MAP, REVERSE_PRICE_MAP, TIER_LIMITS

class StripeService:
    def __init__(self, stripe_secret_key, webhook_secret, db_manager, api_token, env="development"):
        stripe.api_key = stripe_secret_key
        self.webhook_secret = webhook_secret
        self.db_manager = db_manager
        self.api_token = api_token
        self.env = env
        self.price_map = PRICE_MAP
        self.reverse_price_map = REVERSE_PRICE_MAP
        logging.info("StripeService initialized with env: %s", env)

    def hash_email(self, email):
        return hashlib.sha256(email.lower().encode()).hexdigest()

    def create_checkout_session(self, tier, user_email, request_url_root):
        if not user_email or "@" not in user_email:
            logging.error(f"Invalid email: {user_email}")
            return {"error": "Invalid email address."}, 400

        if tier not in TIER_LIMITS:
            logging.error(f"Unknown tier: {tier}")
            return {"error": f"Invalid tier '{tier}'."}, 400

        try:
            price_id = self.price_map.get(tier)
            if not price_id:
                return {"error": f"No price configured for tier '{tier}'"}, 400

            session = stripe.checkout.Session.create(
                success_url=request_url_root + 'success',
                cancel_url=request_url_root + 'cancel',
                payment_method_types=["card"],
                mode="subscription",
                customer_email=user_email,
                line_items=[{"price": price_id, "quantity": 1}],
                metadata={"user_email": user_email},
            )
            logging.info(f"Stripe Checkout session created for {user_email} -> {tier}")
            return {"url": session.url}, 200

        except Exception as e:
            logging.error(f"Stripe Checkout error: {e}", exc_info=True)
            return {"error": "Failed to create checkout session."}, 500

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
