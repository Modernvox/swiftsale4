import stripe
import logging
import hashlib
from flask import request, jsonify
from tenacity import retry, stop_after_attempt, wait_exponential
from config_qt import PRICE_MAP, REVERSE_PRICE_MAP, TIER_LIMITS
import datetime

class StripeService:
    def __init__(self, stripe_secret_key, webhook_secret, db_manager, api_token, env="development"):
        stripe.api_key = stripe_secret_key
        self.webhook_secret = webhook_secret
        self.db_manager = db_manager
        self.api_token = api_token
        self.env = env
        self.price_map = PRICE_MAP
        self.reverse_price_map = REVERSE_PRICE_MAP
        logging.info("StripeService initialized with env: %s, db_manager: %s", env, type(db_manager).__name__)

    def hash_email(self, email):
        """Hash email using SHA256."""
        return hashlib.sha256(email.lower().encode()).hexdigest()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_email_from_customer(self, customer_id):
        """
        Fetch email from Stripe customer by ID. Returns email or None.
        """
        try:
            customer = stripe.Customer.retrieve(customer_id)
            return customer.get("email")
        except stripe.error.StripeError as e:
            logging.error(f"Failed to fetch email for customer {customer_id}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Unexpected error fetching email for customer {customer_id}: {e}", exc_info=True)
            return None
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_checkout_session(self, tier, user_email, request_url_root):
        """
        Create a Stripe Checkout link for the specified tier and user email.
        Returns (response_dict, status_code).
        """
        if not user_email:
            logging.info("User on free trial (no email), skipping checkout creation.")
            return {"error": "No email provided—user is still on free trial."}, 400

        if "@" not in user_email:
            logging.error(f"Invalid email: {user_email}")
            return {"error": "Invalid email address."}, 400

        if tier not in TIER_LIMITS:
            logging.error(f"Unknown tier requested: '{tier}'")
            return {"error": f"Invalid tier '{tier}'."}, 400

        try:
            # Check for active subscription
            customers = stripe.Customer.list(email=user_email, limit=1)
            if customers.data:
                customer_id = customers.data[0].id
                subscriptions = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
                if subscriptions.data:
                    logging.info(f"User {user_email} already has an active subscription: {subscriptions.data[0].id}")
                    return {"error": "User already has an active subscription."}, 400

            current_count = self.db_manager.count_user_bins(user_email)
            max_bins = TIER_LIMITS[tier]["bins"]
            if current_count >= max_bins:
                logging.info(f"User {user_email} has {current_count} bins; max for {tier} is {max_bins}.")
                return {"error": f"Bin limit reached for tier '{tier}' ({max_bins} bins)."}, 400

            price_id = self.price_map.get(tier)
            if not price_id:
                logging.error(f"No price ID configured for tier: {tier}")
                return {"error": f"No price found for tier '{tier}'"}, 400

            session = stripe.checkout.Session.create(
                success_url=request_url_root + 'success',
                cancel_url=request_url_root + 'cancel',
                payment_method_types=["card"],
                mode="subscription",
                customer_email=user_email,
                line_items=[{"price": price_id, "quantity": 1}],
                metadata={"user_email": user_email},
            )

            logging.info(f"Created Stripe Checkout Session for {user_email}, Tier: {tier}, Session ID: {session.id}")
            return {"url": session.url}, 200

        except stripe.error.StripeError as e:
            logging.error(f"Stripe error creating checkout session for {user_email}: {e}", exc_info=True)
            return {"error": f"Stripe error: {str(e)}"}, 500
        except Exception as e:
            logging.error(f"Unexpected error creating checkout session for {user_email}: {e}", exc_info=True)
            return {"error": "Internal server error"}, 500

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def verify_subscription(self, user_email, tier, license_key):
        """
        Verify the subscription status for a user. Returns (tier, license_key).
        """
        if not user_email or not license_key:
            logging.info("No active subscription to verify for %s; reverting to Trial.", user_email or "unknown")
            self.db_manager.update_subscription(user_email, "Trial", "")
            return "Trial", ""

        try:
            subscription = stripe.Subscription.retrieve(license_key)
            status = subscription.get("status", "")
            if status not in ("active", "trialing"):
                logging.info(
                    f"Subscription {license_key} for {user_email} is not active or trialing: status={status}. Reverting to Trial."
                )
                self.db_manager.update_subscription(user_email, "Trial", "")
                return "Trial", ""

            items = subscription.get("items", {}).get("data", [])
            if not items or not isinstance(items, list) or "price" not in items[0]:
                logging.error(f"Malformed subscription data: {subscription}")
                self.db_manager.update_subscription(user_email, "Trial", "")
                return "Trial", ""
            price_id = items[0]["price"]["id"]

            new_tier = self.reverse_price_map.get(price_id, "Trial")
            if new_tier != tier:
                logging.info(f"Updating tier from {tier} to {new_tier} for {user_email}")
                self.db_manager.update_subscription(user_email, new_tier, license_key)
                # Update installs table
                hashed_email = self.hash_email(user_email)
                install = self.db_manager.get_install_by_hashed_email(hashed_email)
                if install:
                    self.db_manager.update_install_tier(hashed_email, new_tier)
                    logging.info(f"Updated install tier to {new_tier} for hashed email {hashed_email}")

            return new_tier, license_key

        except stripe.error.StripeError as e:
            logging.error(f"Stripe error verifying subscription for {user_email}: {e}", exc_info=True)
            self.db_manager.update_subscription(user_email, "Trial", "")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, "free")
                logging.info(f"Reverted install tier to free for hashed email {hashed_email}")
            return "Trial", ""
        except Exception as e:
            logging.error(f"Unexpected error verifying subscription for {user_email}: {e}", exc_info=True)
            self.db_manager.update_subscription(user_email, "Trial", "")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, "free")
                logging.info(f"Reverted install tier to free for hashed email {hashed_email}")
            return "Trial", ""

    def handle_webhook(self, payload, signature):
        """
        Handle Stripe webhooks to update subscription status in the database.
        Returns (status_code, response).
        """
        logging.info("Stripe webhook received")
        try:
            event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)

            # Ignore test webhooks in production
            if self.env == "production" and not event["livemode"]:
                logging.info(f"Ignoring test webhook in production: {event['type']}")
                return 200, {"status": "ignored_test_webhook"}

            if event["type"] == "checkout.session.completed":
                session = event["data"]["object"]
                sub_id = session.get("subscription")
                user_email = session.get("customer_email") or self.get_email_from_customer(session.get("customer"))

                if sub_id and user_email:
                    subscription = stripe.Subscription.retrieve(
                        sub_id, expand=["items.data.price"]
                    )
                    price_id = subscription["items"]["data"][0]["price"]["id"]
                    new_tier = self.reverse_price_map.get(price_id, "Trial")
                    hashed_email = self.hash_email(user_email)
                    install = self.db_manager.get_install_by_hashed_email(hashed_email)
                    if install:
                        self.db_manager.update_install_tier(hashed_email, new_tier)
                        logging.info(f"Updated install tier to {new_tier} for hashed email {hashed_email}")
                    logging.info(f"Webhook: Updating subscription to {new_tier} for {user_email}")
                    self.db_manager.update_subscription(user_email, new_tier, sub_id)

            elif event["type"] == "customer.subscription.updated":
                subscription = event["data"]["object"]
                sub_id = subscription.get("id")
                price_id = subscription["items"]["data"][0]["price"]["id"]
                new_tier = self.reverse_price_map.get(price_id, "Trial")
                result = self.db_manager.load_subscription_by_id(sub_id)
                if result:
                    user_email = result[0]
                    hashed_email = self.hash_email(user_email)
                    install = self.db_manager.get_install_by_hashed_email(hashed_email)
                    if install:
                        self.db_manager.update_install_tier(hashed_email, new_tier)
                        logging.info(f"Updated install tier to {new_tier} for hashed email {hashed_email}")
                    logging.info(f"Webhook: Subscription updated to {new_tier} for {user_email}")
                    self.db_manager.update_subscription(user_email, new_tier, sub_id)
                else:
                    user_email = self.get_email_from_customer(subscription.get("customer"))
                    if user_email:
                        hashed_email = self.hash_email(user_email)
                        install = self.db_manager.get_install_by_hashed_email(hashed_email)
                        if install:
                            self.db_manager.update_install_tier(hashed_email, new_tier)
                            logging.info(f"Updated install tier to {new_tier} for hashed email {hashed_email}")
                        logging.info(f"Webhook: Subscription updated to {new_tier} for {user_email} (fetched from Stripe)")
                        self.db_manager.update_subscription(user_email, new_tier, sub_id)

            elif event["type"] == "customer.subscription.deleted":
                subscription = event["data"]["object"]
                sub_id = subscription.get("id")
                result = self.db_manager.load_subscription_by_id(sub_id)
                if result:
                    user_email = result[0]
                    hashed_email = self.hash_email(user_email)
                    install = self.db_manager.get_install_by_hashed_email(hashed_email)
                    if install:
                        self.db_manager.update_install_tier(hashed_email, "free")
                        logging.info(f"Reverted install tier to free for hashed email {hashed_email}")
                    logging.info(f"Webhook: Subscription canceled for {user_email}. Reverting to Trial.")
                    self.db_manager.update_subscription(user_email, "Trial", "")
                else:
                    user_email = self.get_email_from_customer(subscription.get("customer"))
                    if user_email:
                        hashed_email = self.hash_email(user_email)
                        install = self.db_manager.get_install_by_hashed_email(hashed_email)
                        if install:
                            self.db_manager.update_install_tier(hashed_email, "free")
                            logging.info(f"Reverted install tier to free for hashed email {hashed_email}")
                        logging.info(f"Webhook: Subscription canceled for {user_email} (fetched from Stripe). Reverting to Trial.")
                        self.db_manager.update_subscription(user_email, "Trial", "")

            elif event["type"] == "invoice.payment_failed":
                logging.info("Webhook: Payment failed for subscription")
                return 200, {"warning": "Payment failed"}

            else:
                logging.info(f"Ignoring unrecognized webhook event type: {event['type']}")
                return 200, {"status": "ignored_unrecognized_event"}

            return 200, {"status": "success"}

        except stripe.error.SignatureVerificationError as e:
            logging.error(f"Webhook signature verification failed: {e}", exc_info=True)
            return 400, {"error": "Invalid signature"}
        except Exception as e:
            logging.error(f"Webhook error: {e}", exc_info=True)
            return 500, {"error": "Internal server error"}

    # @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def upgrade_subscription(self, user_email, new_tier, license_key):
        """
        Upgrade a user's subscription plan. Returns True on success, False on error.
        """
        try:
            if license_key == "DEV_MODE":
                if new_tier == current_tier:
                    logging.info(f"(dev) No-op upgrade; already on {new_tier} for {user_email}")
                    return False
                self.db_manager.update_subscription(user_email, new_tier, "DEV_MODE")
                hashed_email = self.hash_email(user_email)
                install = self.db_manager.get_install_by_hashed_email(hashed_email)
                if install:
                    self.db_manager.update_install_tier(hashed_email, new_tier)
                    logging.info(f"(dev) Updated install tier to {new_tier} for hashed email {hashed_email}")
                logging.info(f"(dev) Upgraded to {new_tier} for {user_email}")
                return True

            if not license_key or not user_email:
                logging.warning("Upgrade attempt: Missing license key or user email.")
                return False

            subscription = stripe.Subscription.retrieve(license_key)
            items = subscription.get("items", {}).get("data", [])

            logging.info(f"Stripe subscription retrieved: {subscription}")
            logging.info(f"Subscription items: {items}")

            if not items or not isinstance(items, list) or not items[0] or "id" not in items[0]:
                logging.error(f"Malformed subscription items for {user_email}: {subscription}")
                return False

            price_id = self.price_map.get(new_tier)
            if not price_id:
                logging.error(f"Invalid tier: {new_tier}")
                return False

            stripe.Subscription.modify(
                license_key,
                items=[{"id": items[0]["id"], "price": price_id}],
            )

            self.db_manager.update_subscription(user_email, new_tier, license_key)
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, new_tier)
                logging.info(f"Upgraded install tier to {new_tier} for hashed email {hashed_email}")

            logging.info(f"Upgrade complete: {user_email} moved to {new_tier}")
            return True

        except Exception as e:
            import traceback
            logging.error(f"🔥 Exception in upgrade_subscription:\n{traceback.format_exc()}")
            raise


    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def downgrade_subscription(self, user_email, current_tier, new_tier, license_key):
        """
        Downgrade or cancel a subscription. Returns True on success, False if no action taken or on error.
        """
        if license_key == "DEV_MODE":
            if new_tier == current_tier:
                logging.info(f"(dev) No-op downgrade; already on {new_tier} for {user_email}")
                return False
            db_tier = "Trial" if new_tier == "Trial" else new_tier
            self.db_manager.update_subscription(user_email, db_tier, "DEV_MODE")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                install_tier = "free" if db_tier == "Trial" else db_tier
                self.db_manager.update_install_tier(hashed_email, install_tier)
                logging.info(f"(dev) Updated install tier to {install_tier} for hashed email {hashed_email}")
            logging.info(f"(dev) Downgraded to {db_tier} for {user_email}")
            return True

        if not license_key or not user_email:
            logging.info("Downgrade attempt: No active subscription for %s—already on Trial.", user_email or "unknown")
            return False

        if new_tier == "Trial":
            return self.cancel_subscription(user_email, license_key)

        try:
            subscription = stripe.Subscription.retrieve(license_key)
            price_id = self.price_map.get(new_tier)
            if not price_id:
                logging.error(f"Invalid tier: {new_tier}")
                return False

            stripe.Subscription.modify(
                license_key,
                items=[{"id": subscription["items"]["data"][0]["id"], "price": price_id}],
            )
            self.db_manager.update_subscription(user_email, new_tier, license_key)
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, new_tier)
                logging.info(f"Updated install tier to {new_tier} for hashed email {hashed_email}")
            logging.info(f"Downgraded to {new_tier} for {user_email}")
            return True

        except stripe.error.StripeError as e:
            logging.error(f"Downgrade failed for {user_email}: {e}", exc_info=True)
            return False
        except Exception as e:
            logging.error(f"Unexpected error in downgrade for {user_email}: {e}", exc_info=True)
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def cancel_subscription(self, user_email, license_key):
        """
        Cancel a subscription in Stripe and update the database. Returns True on success, False on error.
        """
        if license_key == "DEV_MODE":
            self.db_manager.update_subscription(user_email, "Trial", "")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, "free")
                logging.info(f"(dev) Reverted install tier to free for hashed email {hashed_email}")
            logging.info(f"(dev) Subscription cancelled for {user_email}")
            return True

        if not license_key or not user_email:
            logging.info("Cancel attempt: No active subscription for %s—already on Trial.", user_email or "unknown")
            return False

        try:
            stripe.Subscription.delete(license_key)
            self.db_manager.update_subscription(user_email, "Trial", "")
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, "free")
                logging.info(f"Reverted install tier to free for hashed email {hashed_email}")
            logging.info(f"Subscription canceled for {user_email}")
            return True

        except stripe.error.StripeError as e:
            logging.error(f"Cancellation failed for {user_email}: {e}", exc_info=True)
            return False
        except Exception as e:
            logging.error(f"Unexpected error in cancel for {user_email}: {e}", exc_info=True)
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_subscription_status(self, license_key):
        """
        Return (status, next_billing_date) for a given license_key.
        """
        if license_key == "DEV_MODE":
            return "Active", "N/A"

        if not license_key:
            logging.info("No subscription ID provided for status check")
            return "N/A", "N/A"

        try:
            sub = stripe.Subscription.retrieve(license_key)
            status = sub.get("status", "").capitalize()
            ts = sub.get("trial_end") if status == "Trialing" else sub.get("current_period_end")
            if ts:
                next_billing_date = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            else:
                next_billing_date = "N/A"

            logging.info(
                f"Subscription status for {license_key}: status={status}, next_billing={next_billing_date}"
            )
            return status, next_billing_date

        except stripe.error.InvalidRequestError as e:
            logging.error(f"Invalid subscription ID {license_key}: {e}", exc_info=True)
            return "N/A", "N/A"
        except stripe.error.StripeError as e:
            logging.error(f"Stripe API error for subscription {license_key}: {e}", exc_info=True)
            return "Error", "N/A"
        except Exception as e:
            logging.error(
                f"Unexpected error fetching subscription status for {license_key}: {e}",
                exc_info=True,
            )
            return "Error", "N/A"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def create_test_subscription(self, user_email, tier):
        """
        Create a 7-day trial subscription for testing. Returns subscription ID or None.
        """
        if not user_email:
            logging.error(f"Invalid email: {user_email} (cannot create test subscription)")
            return None

        price_id = self.price_map.get(tier)
        if not price_id:
            logging.error(f"Invalid tier: {tier}")
            return None

        try:
            customers = stripe.Customer.list(email=user_email, limit=1)
            if customers.data:
                customer_id = customers.data[0].id
            else:
                customer = stripe.Customer.create(email=user_email, metadata={"user_email": user_email})
                customer_id = customer.id

            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                payment_behavior="error_if_incomplete",
                trial_period_days=7,
                expand=["items.data.price"],
            )
            logging.info(f"Created test subscription for {user_email}: {subscription.id}")
            self.db_manager.update_subscription(user_email, tier, subscription.id)
            hashed_email = self.hash_email(user_email)
            install = self.db_manager.get_install_by_hashed_email(hashed_email)
            if install:
                self.db_manager.update_install_tier(hashed_email, tier)
                logging.info(f"Updated install tier to {tier} for hashed email {hashed_email}")
            return subscription.id

        except stripe.error.StripeError as e:
            logging.error(f"Failed to create test subscription for {user_email}: {e}", exc_info=True)
            return None
        except Exception as e:
            logging.error(f"Unexpected error in test subscription for {user_email}: {e}", exc_info=True)
            return None