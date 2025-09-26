import logging
import httpx

from sqlmodel.ext.asyncio.session import AsyncSession

from handler.router import Router
from models import (
    WhatsAppWebhookPayload,
)
from whatsapp import WhatsAppClient
from .base_handler import BaseHandler

logger = logging.getLogger(__name__)


class MessageHandler(BaseHandler):
    def __init__(
        self,
        session: AsyncSession,
        whatsapp: WhatsAppClient,
        scheduler=None,
        settings=None,
    ):
        if not settings:
            raise ValueError("Settings are required - admin_phone_number and summary_secret_word must be set")

        self.router = Router(
            session,
            whatsapp,
            admin_phone=settings.admin_phone_number,
            secret_word=settings.summary_secret_word,
            scheduler=scheduler
        )
        super().__init__(session, whatsapp)

    async def __call__(self, payload: WhatsAppWebhookPayload):
        message = await self.store_message(payload)

        # Only process messages with text content
        if not message or not message.text:
            logger.info("Ignoring message without text content")
            return

        from whatsapp.jid import parse_jid
        chat_jid = parse_jid(message.chat_jid)

        if chat_jid.is_group():
            logger.info(f"Processing group message from {message.chat_jid}")
            # For group messages, we still store them but only process if mentioned or from admin
            await self.router(message)
        else:
            logger.info(f"Processing private message from {message.sender_jid}: {message.text[:100]}...")
            # Process all private messages
            await self.router(message)
