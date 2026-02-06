import asyncio
import json
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from sqlalchemy import select

from db import Base, BroadcastLog, Channel, ReferralEvent, SessionLocal, Transaction, User, engine
from settings import settings

INVITE_REWARD = 1000
BROADCAST_DELAY = 0.05
BROADCAST_POLL_INTERVAL = 5


bot = Bot(token=settings.bot_token)
dp = Dispatcher()


def build_webapp_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎮 Відкрити WebApp", web_app=WebAppInfo(url=settings.webapp_url))]],
        resize_keyboard=True,
    )


async def check_required_channels(user_id: int) -> list[Channel]:
    with SessionLocal() as db:
        channels = db.execute(select(Channel).where(Channel.is_required.is_(True))).scalars().all()
    missing = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel.channel_id, user_id)
            if member.status not in {"member", "administrator", "creator"}:
                missing.append(channel)
        except Exception:
            missing.append(channel)
    return missing


def build_channels_keyboard(channels: list[Channel]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=channel.title, url=channel.link)] for channel in channels
    ]
    buttons.append([
        InlineKeyboardButton(text="✅ Я підписався(лась), перевірити", callback_data="recheck_subs")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def ensure_user(message: Message, referrer_telegram_id: int | None) -> User:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.telegram_id == message.from_user.id)).scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                created_at=datetime.utcnow(),
                last_login_at=datetime.utcnow(),
            )
            if referrer_telegram_id and referrer_telegram_id != message.from_user.id:
                referrer = db.execute(
                    select(User).where(User.telegram_id == referrer_telegram_id)
                ).scalar_one_or_none()
                if referrer:
                    user.referrer_id = referrer.id
            db.add(user)
            db.commit()
            db.refresh(user)

            if user.referrer_id:
                existing = db.execute(
                    select(ReferralEvent).where(
                        ReferralEvent.referrer_id == user.referrer_id,
                        ReferralEvent.referral_id == user.id,
                        ReferralEvent.event_type == "invite",
                    )
                ).scalar_one_or_none()
                if not existing:
                    referrer = db.get(User, user.referrer_id)
                    if referrer:
                        referrer.balance_pro += INVITE_REWARD
                        db.add(
                            ReferralEvent(
                                referrer_id=user.referrer_id,
                                referral_id=user.id,
                                event_type="invite",
                                reward_pro=INVITE_REWARD,
                            )
                        )
                        db.add(
                            Transaction(
                                user_id=referrer.id,
                                type="invite_reward",
                                amount_pro=INVITE_REWARD,
                                status="ok",
                                meta=json.dumps({"referral_id": user.id}),
                            )
                        )
                        db.commit()
        else:
            user.username = message.from_user.username
            user.last_login_at = datetime.utcnow()
            db.commit()
        return user


@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    args = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            args = parts[1]
    referrer_id = None
    if args and args.startswith("ref_"):
        try:
            referrer_id = int(args.replace("ref_", ""))
        except ValueError:
            referrer_id = None

    user = await ensure_user(message, referrer_id)
    if user.banned:
        await message.answer("Ваш акаунт заблоковано.")
        return

    missing = await check_required_channels(message.from_user.id)
    if missing:
        await message.answer(
            "Потрібно підписатися на канали нижче:",
            reply_markup=build_channels_keyboard(missing),
        )
        return

    await message.answer(
        "Вітаємо! Натисніть кнопку нижче, щоб відкрити WebApp.",
        reply_markup=build_webapp_keyboard(),
    )
    await message.answer(
        "Ваше реферальне посилання доступне командою /ref.",
        reply_markup=build_webapp_keyboard(),
    )


@dp.message(Command("ref"))
async def cmd_ref(message: Message) -> None:
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.telegram_id == message.from_user.id)).scalar_one_or_none()
        if not user:
            await message.answer("Спочатку використайте /start.")
            return
        if user.banned:
            await message.answer("Ваш акаунт заблоковано.")
            return
    link = f"https://t.me/{settings.bot_username}?start=ref_{message.from_user.id}"
    await message.answer(f"Ваше реферальне посилання:\n{link}")


@dp.callback_query(F.data == "recheck_subs")
async def recheck_subs(callback: CallbackQuery) -> None:
    missing = await check_required_channels(callback.from_user.id)
    if missing:
        await callback.message.answer(
            "Підписка ще не підтверджена. Перевірте знову після підписки.",
            reply_markup=build_channels_keyboard(missing),
        )
    else:
        await callback.message.answer(
            "Підписку підтверджено! Відкрийте WebApp.",
            reply_markup=build_webapp_keyboard(),
        )
    await callback.answer()


@dp.chat_join_request()
async def join_request_handler(request: ChatJoinRequest) -> None:
    await bot.approve_chat_join_request(chat_id=request.chat.id, user_id=request.from_user.id)
    await bot.send_message(request.from_user.id, "✅ Заявку прийнято. Дякуємо за підписку!")


async def broadcast_worker() -> None:
    while True:
        await asyncio.sleep(BROADCAST_POLL_INTERVAL)
        with SessionLocal() as db:
            pending_logs = db.execute(
                select(BroadcastLog).where((BroadcastLog.sent_ok + BroadcastLog.sent_fail) < BroadcastLog.total_users)
            ).scalars().all()
            for log in pending_logs:
                user_query = select(User).where(User.banned.is_(False))
                if log.audience == "deposit_only":
                    user_query = user_query.where(User.is_deposit.is_(True))
                users = db.execute(user_query).scalars().all()

                sent_ok = 0
                sent_fail = 0
                keyboard = None
                if log.button_text and log.button_url:
                    keyboard = InlineKeyboardMarkup(
                        inline_keyboard=[[InlineKeyboardButton(text=log.button_text, url=log.button_url)]]
                    )
                for user in users:
                    try:
                        if log.type == "text":
                            await bot.send_message(user.telegram_id, log.text or "", reply_markup=keyboard)
                        elif log.type == "photo":
                            media = log.media_file_id or log.media_url
                            await bot.send_photo(user.telegram_id, media, caption=log.text, reply_markup=keyboard)
                        elif log.type == "video":
                            media = log.media_file_id or log.media_url
                            await bot.send_video(user.telegram_id, media, caption=log.text, reply_markup=keyboard)
                        sent_ok += 1
                    except Exception:
                        sent_fail += 1
                    await asyncio.sleep(BROADCAST_DELAY)

                log.sent_ok = sent_ok
                log.sent_fail = sent_fail
                db.commit()


async def main() -> None:
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(broadcast_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
