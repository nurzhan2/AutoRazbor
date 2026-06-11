import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from app.models.models import User
from app.models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def check_expiring_subscriptions():
    """Send reminders 3 days before expiry, on expiry day, and after expiry"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.is_active == True))
        users = result.scalars().all()
        now = datetime.utcnow()

        for user in users:
            if not user.telegram_id or not user.access_until:
                continue
            days_left = (user.access_until - now).days

            try:
                from bot.bot import send_message_to_user
                if days_left == 3:
                    await send_message_to_user(
                        user.telegram_id,
                        "⏰ *Напоминание*\n\nВаш доступ к обучающим материалам истекает через *3 дня*.\n\n"
                        "Чтобы не потерять доступ, продлите подписку заранее.",
                    )
                elif days_left == 0:
                    await send_message_to_user(
                        user.telegram_id,
                        "⚠️ *Сегодня истекает ваш доступ*\n\n"
                        "После полуночи вы потеряете доступ к обучающим видео.\n"
                        "Продлите подписку сейчас.",
                    )
                elif days_left < 0 and user.access_until > now - timedelta(days=1):
                    # Just expired
                    await send_message_to_user(
                        user.telegram_id,
                        "❌ *Ваш доступ истёк*\n\n"
                        "Обучающие материалы больше недоступны.\n"
                        "Нажмите /start чтобы продлить подписку.",
                    )
            except Exception as e:
                logger.warning(f"Failed to notify user {user.telegram_id}: {e}")
