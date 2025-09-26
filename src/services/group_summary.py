import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import os

from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
import google.generativeai as genai

from models import Message
from whatsapp import WhatsAppClient
from whatsapp.models import SendMessageRequest

logger = logging.getLogger(__name__)


class GroupSummaryService:
    def __init__(self, session: AsyncSession, whatsapp: WhatsAppClient):
        self.session = session
        self.whatsapp = whatsapp
        
        # Configure Google Generative AI
        api_key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.warning("No Google API key found. Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable.")
        else:
            genai.configure(api_key=api_key)
            
        self.model = genai.GenerativeModel("gemini-2.5-flash")
        
        self.system_prompt = """You are a WhatsApp group activity summarizer.
        Analyze the provided group messages and create a concise, engaging summary.

        Focus on:
        - Key topics discussed
        - Important decisions or announcements
        - Active participants
        - Notable conversations or highlights

        Format your response as a friendly, informative summary in Hebrew or English
        (based on the language used in the messages).
        Keep it under 200 words and make it engaging to read."""

    async def get_groups_from_messages(self) -> List[str]:
        """Get all unique group chat JIDs from recent messages."""
        statement = select(Message.chat_jid).distinct().where(
            Message.chat_jid.contains("@g.us")  # WhatsApp group format
        )
        result = await self.session.exec(statement)
        return list(result.all())

    async def get_group_messages_for_date(
        self, group_jid: str, date: datetime
    ) -> List[Message]:
        """Get all messages from a group for a specific date (00:00 to 23:59)."""
        from datetime import time

        start_of_day = datetime.combine(date.date(), time.min, tzinfo=date.tzinfo)
        end_of_day = datetime.combine(date.date(), time.max, tzinfo=date.tzinfo)

        statement = select(Message).where(
            and_(
                Message.chat_jid == group_jid,
                Message.timestamp >= start_of_day,
                Message.timestamp <= end_of_day
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
            sender_name = msg.sender.push_name if msg.sender and msg.sender.push_name else "Unknown"
            timestamp_str = msg.timestamp.strftime("%H:%M")
            message_content = msg.text or "[Media]"
            messages_text.append(f"[{timestamp_str}] {sender_name}: {message_content}")

        if not messages_text:
            return None

        # Get group name from first message (simplified approach)
        group_name = group_jid.split("@")[0] if "@" in group_jid else "Group"

        try:
            # Get unique participants
            participants = set()
            for msg in messages:
                if msg.sender and msg.sender.push_name:
                    participants.add(msg.sender.push_name)

            summary_input = f"""Group: {group_name}
Date: {messages[0].timestamp.strftime('%Y-%m-%d')}
Time period: {messages[0].timestamp.strftime('%H:%M')} to {messages[-1].timestamp.strftime('%H:%M')}
Total messages: {len(messages)}
Active participants: {', '.join(participants) if participants else 'Unknown'}

Messages chronologically:
{chr(10).join(messages_text)}

Please provide a comprehensive summary that includes:
- Main topics discussed
- Key decisions or important information shared
- Notable conversations or events
- Most active participants
- Any important announcements or updates

Make it informative and well-structured."""

            # Combine system prompt with the input
            full_prompt = f"{self.system_prompt}\n\n{summary_input}"
            
            # Generate response using Google Generative AI directly
            response = await self.model.generate_content_async(full_prompt)
            return response.text

        except Exception as e:
            logger.error(f"Failed to generate summary for group {group_jid}: {e}")
            return f"Summary for {group_name}: {len(messages)} messages on {messages[0].timestamp.strftime('%Y-%m-%d')}"

    async def get_daily_summaries(self, target_date: datetime = None) -> List[tuple[str, str]]:
        """Get summaries for all groups for a specific date (defaults to today)."""
        if target_date is None:
            target_date = datetime.now(timezone.utc)

        groups = await self.get_groups_from_messages()

        summaries = []
        for group_jid in groups:
            messages = await self.get_group_messages_for_date(group_jid, target_date)
            if messages:  # Only summarize groups with activity
                summary = await self.generate_group_summary(group_jid, messages)
                if summary:
                    summaries.append((group_jid, summary))

        return summaries

    async def send_summary_to_admin(self, admin_phone: str, summaries: List[tuple[str, str]], is_instant: bool = False):
        """Send combined summaries to admin phone number."""
        header = "🚨 Instant Group Summary (Last 24h)" if is_instant else "📊 Daily Group Summary"

        if not summaries:
            summary_text = f"{header}\n\nNo group activity in the last 24 hours."
        else:
            summary_parts = [f"{header}\n"]
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