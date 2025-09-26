#!/usr/bin/env python3
"""
Dashboard API for visualizing group messages and activity
"""
import logging
from typing import Annotated, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, desc, func
from datetime import datetime, timedelta, timezone

from models import Message, Sender
from .deps import get_db_async_session

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/dashboard/messages")
async def get_messages(
    session: Annotated[AsyncSession, Depends(get_db_async_session)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    group_jid: str = Query(default=None, description="Filter by group JID")
) -> Dict[str, Any]:
    """Get recent group messages for dashboard visualization."""
    try:
        # Build query for group messages only
        query = select(Message).where(Message.chat_jid.contains("@g.us")).order_by(desc(Message.timestamp))

        # Apply group filter if provided
        if group_jid:
            query = query.where(Message.chat_jid == group_jid)

        # Apply pagination
        query = query.offset(offset).limit(limit)

        # Get total count for pagination
        count_query = select(func.count(Message.message_id)).where(Message.chat_jid.contains("@g.us"))
        if group_jid:
            count_query = count_query.where(Message.chat_jid == group_jid)

        # Execute queries
        result = await session.exec(query)
        messages = result.all()

        count_result = await session.exec(count_query)
        total_count = count_result.first()

        # Get available groups for filtering
        groups_query = select(Message.chat_jid).where(Message.chat_jid.contains("@g.us")).distinct()
        groups_result = await session.exec(groups_query)
        available_groups = [group for group in groups_result.all() if group]

        return {
            "messages": [
                {
                    "id": msg.message_id,
                    "text": msg.text[:100] + "..." if msg.text and len(msg.text) > 100 else msg.text,
                    "chat_jid": msg.chat_jid,
                    "sender_jid": msg.sender_jid,
                    "timestamp": msg.timestamp.isoformat(),
                    "sender_name": msg.sender.push_name if msg.sender else "Unknown",
                }
                for msg in messages
            ],
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total_count
            },
            "available_groups": available_groups
        }

    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch messages")

@router.get("/dashboard/stats")
async def get_stats(
    session: Annotated[AsyncSession, Depends(get_db_async_session)]
) -> Dict[str, Any]:
    """Get overall statistics for the dashboard."""
    try:
        # Total messages
        total_query = select(func.count(Message.message_id))
        total_result = await session.exec(total_query)
        total_messages = total_result.first()

        # Messages by group
        group_query = select(Message.chat_jid, func.count(Message.message_id)).where(
            Message.chat_jid.contains("@g.us")
        ).group_by(Message.chat_jid)
        group_result = await session.exec(group_query)
        group_stats = [(group, count) for group, count in group_result.all()]

        # Recent activity (last 24 hours)
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_query = select(func.count(Message.message_id)).where(
            Message.timestamp >= yesterday
        )
        recent_result = await session.exec(recent_query)
        recent_messages = recent_result.first()

        return {
            "total_messages": total_messages,
            "recent_messages_24h": recent_messages,
            "group_stats": [{"group": group, "message_count": count} for group, count in group_stats],
            "total_groups": len(group_stats)
        }

    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch statistics")