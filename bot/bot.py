import os
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@Senya_Razbor")
SITE_URL = os.getenv("SITE_URL", "https://eurorazbor.online")
ACCESS_PRICE = os.getenv("ACCESS_PRICE", "1990")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


def main_menu(has_access: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if has_access:
        buttons.append([InlineKeyboardButton(text="🔄 Продлить доступ", callback_data="pay")])
        if not SITE_URL.startswith("http://localhost"):
            buttons.append([InlineKeyboardButton(text="🌐 Перейти на сайт", url=SITE_URL + "/dashboard")])
    else:
        buttons.append([InlineKeyboardButton(text="💳 Оплатить доступ", callback_data="pay")])
    buttons.append([InlineKeyboardButton(text="📚 Описание обучения", callback_data="about")])
    buttons.append([InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(CommandStart())
async def cmd_start(message: Message):
    from app.models.database import AsyncSessionLocal
    from app.services.auth import get_user_by_telegram_id

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, str(message.from_user.id))

    has_access = user is not None and user.has_active_subscription

    if user and has_access:
        until = user.access_until.strftime("%d.%m.%Y")
        text = (
            f"👋 С возвращением, <b>{message.from_user.first_name}</b>!\n\n"
            f"✅ Ваш доступ активен до <b>{until}</b>.\n\n"
            f"Перейдите на сайт для просмотра обучения и каталога запчастей."
        )
    elif user and not has_access:
        text = (
            f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
            f"❌ Ваш доступ истёк.\n"
            f"Оплатите подписку, чтобы снова получить доступ к обучению."
        )
    else:
        text = (
            f"👋 Добро пожаловать в <b>ЕвроРазбор</b>, {message.from_user.first_name}!\n\n"
            "Здесь вы можете получить доступ к обучающим материалам "
            "для оптовиков автозапчастей.\n\n"
            "📦 Каталог оптовых автозапчастей\n"
            "🎓 3 обучающих видео для оптовиков\n"
            "⏱ Доступ на <b>30 дней</b>\n\n"
            f"💰 Стоимость: <b>{ACCESS_PRICE} ₽</b>"
        )

    await message.answer(text, reply_markup=main_menu(has_access), parse_mode="HTML")


@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    text = (
        "📚 <b>Обучение для оптовиков автозапчастей</b>\n\n"
        "В программе обучения:\n"
        "• Видеоурок 1\n"
        "• Видеоурок 2\n"
        "• Видеоурок 3\n\n"
        "После оплаты вы получаете:\n"
        "✅ Доступ к 3 обучающим видео\n"
        "✅ Доступ к каталогу оптовых автозапчастей\n"
        "✅ Личный кабинет на сайте eurorazbor.online\n\n"
        f"Срок доступа: <b>30 дней</b>\n"
        f"Стоимость: <b>{ACCESS_PRICE} ₽</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", callback_data="pay")],
            [InlineKeyboardButton(text="← Назад", callback_data="back")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    text = (
        "🆘 <b>Поддержка ЕвроРазбор</b>\n\n"
        f"По вопросам оплаты и доступа напишите: {SUPPORT_USERNAME}\n\n"
        "Мы ответим в ближайшее время."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data="back")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "back")
async def cb_back(callback: CallbackQuery):
    from app.models.database import AsyncSessionLocal
    from app.services.auth import get_user_by_telegram_id
    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, str(callback.from_user.id))
    has_access = user is not None and user.has_active_subscription
    await callback.message.edit_text(
        "Главное меню",
        reply_markup=main_menu(has_access)
    )
    await callback.answer()


@router.callback_query(F.data == "pay")
async def cb_pay(callback: CallbackQuery):
    text = (
        "💳 <b>Оплата доступа — ЕвроРазбор</b>\n\n"
        f"Стоимость: <b>{ACCESS_PRICE} ₽</b> на 30 дней\n\n"
        "⚠️ <i>Оплата в тестовом режиме.\n"
        "Нажмите «Тестовая оплата» для проверки системы.</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Тестовая оплата", callback_data="pay_stub")],
            [InlineKeyboardButton(text="← Назад", callback_data="back")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "pay_stub")
async def cb_pay_stub(callback: CallbackQuery):
    telegram_id = str(callback.from_user.id)
    await process_successful_payment(callback.message, telegram_id)
    await callback.answer()


async def process_successful_payment(message: Message, telegram_id: str):
    from app.models.database import AsyncSessionLocal
    from app.services.auth import get_user_by_telegram_id, create_user_for_telegram, extend_user_access
    from app.models.models import Payment

    async with AsyncSessionLocal() as db:
        user = await get_user_by_telegram_id(db, telegram_id)

        if user:
            user = await extend_user_access(db, user)
            plain_password = None
            is_new = False
        else:
            user, plain_password = await create_user_for_telegram(db, telegram_id)
            is_new = True

        payment = Payment(
            user_id=user.id,
            amount=float(ACCESS_PRICE),
            status="success",
            payment_system="stub",
            paid_at=datetime.utcnow(),
        )
        db.add(payment)
        await db.commit()

    until = user.access_until.strftime("%d.%m.%Y")

    if is_new:
        text = (
            "✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Доступ активирован на <b>30 дней</b> (до {until}).\n\n"
            f"🔑 <b>Логин:</b> <code>{user.login}</code>\n"
            f"🔑 <b>Пароль:</b> <code>{plain_password}</code>\n\n"
            f"🌐 <b>Сайт:</b> {SITE_URL}/login\n\n"
            "⚠️ Сохраните логин и пароль!"
        )
    else:
        text = (
            "✅ <b>Доступ продлён!</b>\n\n"
            f"Активен до <b>{until}</b>.\n\n"
            f"🌐 {SITE_URL}/login\n"
            f"🔑 Логин: <code>{user.login}</code>"
        )

    keyboard = None
    if not SITE_URL.startswith("http://localhost"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Перейти на сайт", url=SITE_URL + "/login")],
        ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

    await notify_admin_new_payment(user.login, telegram_id, is_new)


async def notify_admin_new_payment(login: str, telegram_id: str, is_new: bool):
    if not ADMIN_TELEGRAM_ID:
        return
    try:
        action = "🆕 Новый пользователь" if is_new else "🔄 Продление"
        await bot.send_message(
            ADMIN_TELEGRAM_ID,
            f"{action}\n👤 {login}\n📱 TG: {telegram_id}\n💰 {ACCESS_PRICE} ₽",
        )
    except Exception as e:
        logger.warning(f"Admin notify failed: {e}")


async def send_admin_message(text: str):
    if not ADMIN_TELEGRAM_ID:
        return
    try:
        await bot.send_message(ADMIN_TELEGRAM_ID, text)
    except Exception as e:
        logger.warning(f"Admin notify failed: {e}")


async def send_message_to_user(telegram_id: str, text: str):
    try:
        await bot.send_message(telegram_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Failed to send to {telegram_id}: {e}")


async def start_bot():
    await dp.start_polling(bot, skip_updates=True)
