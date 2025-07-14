import logging
import asyncio
from datetime import datetime, timezone
from telegram import Bot
from telegram.error import TelegramError

class TelegramService:
    def __init__(self, bot_token, chat_id=None, log_info=None, log_error=None, loop=None):
        """
        Initialize TelegramService with a bot token and optional asyncio loop.
        
        Args:
            bot_token (str): Telegram bot token from environment.
            chat_id (str, optional): Default Telegram chat ID.
            log_info (callable, optional): Logging function for info messages.
            log_error (callable, optional): Logging function for error messages.
            loop (asyncio.AbstractEventLoop, optional): Asyncio event loop.
        """
        self.bot = None
        self.chat_id = chat_id
        self.log_info = log_info or logging.info
        self.log_error = log_error or logging.error
        self.loop = loop or asyncio.new_event_loop()  # Create new loop if none provided
        self.error_shown = set()  # Track specific errors to avoid spamming

        if not bot_token:
            self.log_warning("Telegram bot token not found. Telegram features disabled.")
            return

        try:
            self.bot = Bot(token=bot_token)
            self.log_info("Telegram bot initialized successfully")
        except TelegramError as e:
            self.log_error(f"Failed to initialize Telegram bot: {e}", exc_info=True)
            self.error_shown.add(str(e))

    async def send_bin_number(self, chat_id, username, bin_number, auction_id=None):
        """
        Send a bin number notification to the specified Telegram chat.
        
        Args:
            chat_id (str): Telegram chat ID (e.g., '@ChannelName' or numeric ID).
            username (str): Username of the bidder.
            bin_number (int): Assigned bin number.
            auction_id (str, optional): Auction ID for context.
            
        Returns:
            bool: True if message sent successfully, False otherwise.
        """
        if not self.bot:
            self.log_warning("Cannot send Telegram message: Bot not initialized")
            return False
        target_chat_id = chat_id or self.chat_id
        if not target_chat_id:
            self.log_warning("Cannot send Telegram message: Chat ID missing")
            return False

        try:
            message = f"Username: {username} | Bin: {bin_number}"
            if auction_id:
                message += f" | Auction: {auction_id}"
            message += f" | Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            await self.bot.send_message(chat_id=target_chat_id, text=message)
            self.log_info(f"Sent Telegram message: {message}")
            self.error_shown.discard("send_message_failure")  # Reset error suppression
            return True
        except TelegramError as e:
            error_key = "send_message_failure"
            if error_key not in self.error_shown:
                self.log_error(f"Failed to send Telegram message: {e}", exc_info=True)
                self.error_shown.add(error_key)
            return False
        except Exception as e:
            error_key = f"unexpected_{str(e)[:50]}"
            if error_key not in self.error_shown:
                self.log_error(f"Unexpected error sending Telegram message: {e}", exc_info=True)
                self.error_shown.add(error_key)
            return False

    def run_async(self, coro):
        """
        Run an async coroutine in the provided event loop.
        
        Args:
            coro: Coroutine to execute (e.g., send_bin_number).
            
        Returns:
            asyncio.Future: Future object for the coroutine, or None if loop unavailable.
        """
        try:
            if self.loop.is_closed():
                self.loop = asyncio.new_event_loop()
                self.log_info("Created new asyncio event loop for TelegramService")
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception as e:
            self.log_error(f"Failed to run async coroutine: {e}", exc_info=True)
            return None

    def close(self):
        """
        Close the asyncio event loop.
        """
        if self.loop and not self.loop.is_closed():
            self.loop.close()
            self.log_info("Closed TelegramService asyncio event loop")