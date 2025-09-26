import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from models import Message
from whatsapp import WhatsAppClient
from whatsapp.models import SendMessageRequest

logger = logging.getLogger(__name__)


class GroupSummaryService:
    def __init__(self, session: AsyncSession, whatsapp: WhatsAppClient):
        self.session = session
        self.whatsapp = whatsapp
        self.summary_agent = Agent(
            model=GoogleModel("gemini-1.5-flash"),
            system_prompt="""You are a WhatsApp group activity summarizer.
            Analyze the provided group messages and create a concise, engaging summary.

            Focus on:
            - Key topics discussed
            - Important decisions or announcements
            - Active participants
            - Notable conversations or highlights

            Format your response as a friendly, informative summary in Hebrew or English
            (based on the language used in the messages).
            Keep it under 200 words and make it engaging to read."""
        )

    async def get_groups_from_messages(self) -> List[str]:
        """Get all unique group chat JIDs from recent messages."""
        statement = select(Message.chat_jid).distinct().where(
            Message.chat_jid.contains("@g.us")  # WhatsApp group format
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_group_messages_since(
        self, group_jid: str, since: datetime
    ) -> List[Message]:
        """Get all messages from a group since a specific time."""
        statement = select(Message).where(
            and_(
                Message.chat_jid == group_jid,
                Message.timestamp >= since
            )
        ).order_by(Message.timestamp)

        result = await self.session.exec(statement)
        return list(result.all())

    async def generate_group_summary(
        self, group_jid: str, messages: List[Message]
    ) -> Optional[str]:
        """Generate a summary for a group's messages."""
        if not messages:
            return None

        # Format messages for AI analysis
        messages_text = []
        for msg in messages:
            sender_name = msg.sender.name if msg.sender else "Unknown"
            timestamp_str = msg.timestamp.strftime("%H:%M")
            message_content = msg.text or "[Media]"
            messages_text.append(f"[{timestamp_str}] {sender_name}: {message_content}")

        if not messages_text:
            return None

        # Get group name from first message (simplified approach)
        group_name = group_jid.split("@")[0] if "@" in group_jid else "Group"

        try:
            summary_input = f"""Group: {group_name}
Time period: {messages[0].timestamp.strftime('%Y-%m-%d %H:%M')} to {messages[-1].timestamp.strftime('%Y-%m-%d %H:%M')}
Total messages: {len(messages)}

Messages:
{chr(10).join(messages_text)}"""

            result = await self.summary_agent.run(summary_input)
            return result.data

        except Exception as e:
            logger.error(f"Failed to generate summary for group {group_jid}: {e}")
            return f"Summary for {group_name}: {len(messages)} messages in the last 24 hours"

    async def get_daily_summaries(self) -> List[tuple[str, str]]:
        """Get summaries for all groups from the last 24 hours."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        groups = await self.get_groups_from_messages()

        summaries = []
        for group_jid in groups:
            messages = await self.get_group_messages_since(group_jid, since)
            if messages:  # Only summarize groups with activity
                summary = await self.generate_group_summary(group_jid, messages)
                if summary:
                    summaries.append((group_jid, summary))

        return summaries

    async def send_summary_to_admin(self, admin_phone: str, summaries: List[tuple[str, str]]):
        """Send combined summaries to admin phone number."""
        if not summaries:
            summary_text = "📊 Daily Group Summary\n\nNo group activity in the last 24 hours."
        else:
            summary_parts = ["📊 Daily Group Summary\n"]
            for group_jid, summary in summaries:
                group_name = group_jid.split("@")[0] if "@" in group_jid else "Group"
                summary_parts.append(f"🔹 **{group_name}**")
                summary_parts.append(summary)
                summary_parts.append("")  # Empty line

            summary_text = "\n".join(summary_parts)

        try:
            await self.whatsapp.send_message(
                SendMessageRequest(
                    phone=admin_phone,
                    message=summary_text
                )
            )
            logger.info(f"Sent daily summary to admin {admin_phone}")
        except Exception as e:
            logger.error(f"Failed to send summary to admin {admin_phone}: {e}")