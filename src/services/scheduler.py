import asyncio
import logging
from datetime import datetime, time, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel.ext.asyncio.session import AsyncSession

from whatsapp import WhatsAppClient
from .group_summary import GroupSummaryService

logger = logging.getLogger(__name__)


class SummaryScheduler:
    def __init__(
        self,
        session_factory,
        whatsapp: WhatsAppClient,
        admin_phone: str,
        timezone_str: str = "Asia/Jerusalem"
    ):
        self.session_factory = session_factory
        self.whatsapp = whatsapp
        self.admin_phone = admin_phone
        self.timezone_str = timezone_str
        self.scheduler: Optional[AsyncIOScheduler] = None

    async def start(self):
        """Start the scheduler."""
        if self.scheduler and self.scheduler.running:
            logger.warning("Scheduler is already running")
            return

        self.scheduler = AsyncIOScheduler(timezone=self.timezone_str)

        # Schedule daily summary at 22:00 (10 PM)
        self.scheduler.add_job(
            self._send_daily_summary,
            CronTrigger(hour=22, minute=0, timezone=self.timezone_str),
            id="daily_summary",
            name="Daily Group Summary",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(f"Scheduler started - Daily summaries will be sent to {self.admin_phone} at 22:00 {self.timezone_str}")

    async def stop(self):
        """Stop the scheduler."""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")

    async def _send_daily_summary(self):
        """Send daily summary to admin (scheduled job)."""
        try:
            async with self.session_factory() as session:
                summary_service = GroupSummaryService(session, self.whatsapp)
                summaries = await summary_service.get_daily_summaries()
                await summary_service.send_summary_to_admin(self.admin_phone, summaries, is_instant=False)

        except Exception as e:
            logger.error(f"Failed to send scheduled daily summary: {e}")

    async def send_instant_summary(self):
        """Send instant summary to admin (triggered by secret word)."""
        try:
            async with self.session_factory() as session:
                summary_service = GroupSummaryService(session, self.whatsapp)
                summaries = await summary_service.get_daily_summaries()

                # Add instant indicator to message
                if summaries:
                    # Create instant version by modifying the combined summary
                    modified_summaries = []
                    for group_jid, summary in summaries:
                        modified_summaries.append((group_jid, summary))
                    # We'll let the send_summary_to_admin handle formatting, just pass it through
                    summaries = modified_summaries

                await summary_service.send_summary_to_admin(self.admin_phone, summaries, is_instant=True)
                logger.info(f"Sent instant summary to admin {self.admin_phone}")

        except Exception as e:
            logger.error(f"Failed to send instant summary: {e}")

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self.scheduler is not None and self.scheduler.running