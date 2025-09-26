import logging
from typing import List
from sqlmodel.ext.asyncio.session import AsyncSession

from models import Message
from whatsapp import WhatsAppClient
from whatsapp.jid import normalize_jid
from .base_handler import BaseHandler

# Creating an object
logger = logging.getLogger(__name__)


class Router(BaseHandler):
    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        admin_phone: str = "972542607800",
        secret_word: str = "banana",
        scheduler=None,
        allowed_numbers: List[str] = None
    ):
        self.admin_phone = normalize_jid(admin_phone) if admin_phone else None
        self.secret_word = secret_word.lower()
        self.scheduler = scheduler
        self.allowed_numbers = [normalize_jid(num) for num in (allowed_numbers or ["972542607800"])]
        super().__init__(session, whatsapp)

    async def __call__(self, message: Message):
        from whatsapp.jid import parse_jid
        chat_jid = parse_jid(message.chat_jid)

        # If this is a group message, just store it and don't respond
        if chat_jid.is_group():
            logger.info(f"Stored group message from {message.sender_jid} in {message.chat_jid}")
            return  # Already stored by MessageHandler, no response needed

        # For private messages, check if sender is allowed
        if message.sender_jid not in self.allowed_numbers:
            logger.info(f"Ignoring message from unauthorized number: {message.sender_jid}")
            return

        logger.info(f"Processing private message from authorized number: {message.sender_jid}")

        # Check if this is a secret word trigger from admin
        if (self.admin_phone and
            message.sender_jid == self.admin_phone and
            message.text and
            self.secret_word in message.text.lower()):

            logger.info(f"Secret word '{self.secret_word}' detected from admin {self.admin_phone}")

            try:
                # Send immediate acknowledgment
                await self.whatsapp.react_to_message(
                    message_id=message.message_id,
                    phone=message.chat_jid,
                    emoji="📊"
                )

                # Trigger instant summary
                if self.scheduler:
                    await self.scheduler.send_instant_summary()
                else:
                    logger.warning("Scheduler not available for instant summary")

                return  # Don't process further

            except Exception as e:
                logger.error(f"Failed to handle secret word trigger: {e}")

        # For other messages from allowed numbers, just acknowledge
        try:
            await self.whatsapp.react_to_message(
                message_id=message.message_id,
                phone=message.chat_jid,
                emoji="👍"
            )
            logger.info(f"Acknowledged message from authorized number {message.sender_jid}")
        except Exception as e:
            logger.warning(f"Failed to send acknowledgment reaction: {e}")


