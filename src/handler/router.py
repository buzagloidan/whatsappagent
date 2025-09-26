import logging
from sqlmodel.ext.asyncio.session import AsyncSession
from voyageai.client_async import AsyncClient

from handler.knowledge_base_answers import KnowledgeBaseAnswers
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
        embedding_client: AsyncClient,
        admin_phone: str = "972542607800",
        secret_word: str = "banana",
        scheduler=None
    ):
        self.ask_knowledge_base = KnowledgeBaseAnswers(
            session, whatsapp, embedding_client
        )
        self.admin_phone = normalize_jid(admin_phone) if admin_phone else None
        self.secret_word = secret_word.lower()
        self.scheduler = scheduler
        super().__init__(session, whatsapp, embedding_client)

    async def __call__(self, message: Message):
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

        # Send immediate emoji reaction to acknowledge message receipt
        try:
            await self.whatsapp.react_to_message(
                message_id=message.message_id,
                phone=message.chat_jid,
                emoji="💬"
            )
            logger.info(f"Sent immediate reaction 💬 for message {message.message_id}")
        except Exception as e:
            logger.warning(f"Failed to send immediate reaction: {e}")

        # Route all intents to LLM knowledge base for intelligent responses
        await self.ask_knowledge_base(message)


