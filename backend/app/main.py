import json
import hmac
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import BroadcastLog, Channel, Offer, ReferralEvent, Transaction, User
from .schemas import (
    BalanceAdjustRequest,
    BanRequest,
    BroadcastRequest,
    ChannelCreateRequest,
    ChannelUpdateRequest,
    OfferCreateRequest,
    OfferUpdateRequest,
    PostbackRequest,
    TelegramAuthRequest,
    TelegramAuthResponse,
    WithdrawRequest,
)
from .settings import settings
from .utils.telegram import validate_init_data

INVITE_REWARD = 1000
DEPOSIT_REWARD = 5000
GAME_REWARD = 50000
RATE_PRO_TO_USD = 10000

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def get_current_user(
    db: Session = Depends(get_db),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Відсутній користувач")
    user = db.get(User, int(x_user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    if user.banned:
        raise HTTPException(status_code=403, detail="Ваш акаунт заблоковано.")
    return user


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Недійсний токен адміністратора")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/auth/telegram", response_model=TelegramAuthResponse)
def auth_telegram(payload: TelegramAuthRequest, db: Session = Depends(get_db)) -> Any:
    try:
        parsed = validate_init_data(payload.initData, settings.bot_token)
    except ValueError:
        raise HTTPException(status_code=403, detail="Недійсні дані Telegram")
    if "user" not in parsed:
        raise HTTPException(status_code=400, detail="Немає даних користувача")
    user_data = json.loads(parsed["user"])
    telegram_id = int(user_data["id"])
    username = user_data.get("username")

    user = db.execute(select(User).where(User.telegram_id == telegram_id)).scalar_one_or_none()
    now = datetime.utcnow()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.username = username
        user.last_login_at = now
        db.commit()

    return TelegramAuthResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        username=user.username,
        balance_pro=user.balance_pro,
        is_deposit=user.is_deposit,
        banned=user.banned,
    )


@app.get("/api/offers")
def get_offers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    offers = db.execute(select(Offer).where(Offer.is_active.is_(True))).scalars().all()
    return [
        {
            "id": offer.id,
            "title": offer.title,
            "reward_pro": offer.reward_pro,
            "link": offer.link,
            "is_limited": offer.is_limited,
        }
        for offer in offers
    ]


@app.get("/api/referrals")
def get_referrals(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    total_referrals = db.execute(
        select(func.count()).select_from(User).where(User.referrer_id == user.id)
    ).scalar_one()
    referrals_with_deposit = db.execute(
        select(func.count())
        .select_from(User)
        .where(User.referrer_id == user.id, User.is_deposit.is_(True))
    ).scalar_one()
    return {
        "total_referrals": total_referrals,
        "referrals_with_deposit": referrals_with_deposit,
        "invite_reward_pro": INVITE_REWARD,
        "deposit_reward_pro": DEPOSIT_REWARD,
    }


@app.post("/api/game/play")
def play_game(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if not user.is_deposit:
        raise HTTPException(status_code=403, detail="Гра доступна після депозиту")
    user.balance_pro += GAME_REWARD
    transaction = Transaction(
        user_id=user.id,
        type="game_bonus",
        amount_pro=GAME_REWARD,
        status="ok",
        meta=None,
    )
    db.add(transaction)
    db.commit()
    db.refresh(user)
    return {"ok": True, "added_pro": GAME_REWARD, "balance_pro": user.balance_pro}


@app.get("/api/wallet")
def get_wallet(user: User = Depends(get_current_user)) -> dict[str, Any]:
    balance_usd = round(user.balance_pro / RATE_PRO_TO_USD, 2)
    return {"balance_pro": user.balance_pro, "balance_usd": balance_usd, "rate": RATE_PRO_TO_USD}


@app.post("/api/withdraw")
def withdraw_funds(
    payload: WithdrawRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if payload.amount_pro > user.balance_pro:
        raise HTTPException(status_code=400, detail="Недостатньо PRO#")
    user.balance_pro -= payload.amount_pro
    transaction = Transaction(
        user_id=user.id,
        type="withdraw_request",
        amount_pro=payload.amount_pro,
        status="pending",
        meta=json.dumps({"details": payload.details}),
    )
    db.add(transaction)
    db.commit()
    return {"ok": True, "status": "pending"}


@app.post("/admin/broadcast")
def admin_broadcast(
    payload: BroadcastRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    if payload.type not in {"text", "photo", "video"}:
        raise HTTPException(status_code=400, detail="Недійсний тип розсилки")
    if payload.type in {"photo", "video"} and not (payload.media_url or payload.media_file_id):
        raise HTTPException(status_code=400, detail="Потрібне медіа для розсилки")
    if payload.audience not in {"all", "deposit_only"}:
        raise HTTPException(status_code=400, detail="Недійсна аудиторія")

    user_query = select(User).where(User.banned.is_(False))
    if payload.audience == "deposit_only":
        user_query = user_query.where(User.is_deposit.is_(True))
    total_users = db.execute(select(func.count()).select_from(user_query.subquery())).scalar_one()

    log = BroadcastLog(
        type=payload.type,
        text=payload.text,
        media_file_id=payload.media_file_id,
        media_url=payload.media_url,
        button_text=payload.button_text,
        button_url=payload.button_url,
        audience=payload.audience,
        total_users=total_users,
        sent_ok=0,
        sent_fail=0,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return {"queued": True, "broadcast_id": log.id, "total_users": total_users}


@app.get("/admin/users")
def admin_users(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    users = db.execute(select(User)).scalars().all()
    return [
        {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "balance_pro": user.balance_pro,
            "is_deposit": user.is_deposit,
            "banned": user.banned,
        }
        for user in users
    ]


@app.post("/admin/users/{user_id}/ban")
def admin_ban_user(
    user_id: int,
    payload: BanRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    user.banned = payload.banned
    db.commit()
    return {"ok": True}


@app.post("/admin/users/{user_id}/balance")
def admin_balance_adjust(
    user_id: int,
    payload: BalanceAdjustRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    user.balance_pro += payload.delta_pro
    transaction = Transaction(
        user_id=user.id,
        type="admin_adjust",
        amount_pro=payload.delta_pro,
        status="ok",
        meta=json.dumps({"reason": payload.reason}),
    )
    db.add(transaction)
    db.commit()
    return {"ok": True, "balance_pro": user.balance_pro}


@app.get("/admin/offers")
def admin_offers(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    offers = db.execute(select(Offer)).scalars().all()
    return [
        {
            "id": offer.id,
            "title": offer.title,
            "reward_pro": offer.reward_pro,
            "link": offer.link,
            "is_active": offer.is_active,
            "is_limited": offer.is_limited,
        }
        for offer in offers
    ]


@app.post("/admin/offers")
def admin_create_offer(
    payload: OfferCreateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    offer = Offer(
        title=payload.title,
        reward_pro=payload.reward_pro,
        link=payload.link,
        is_active=payload.is_active,
        is_limited=payload.is_limited,
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return {"id": offer.id}


@app.put("/admin/offers/{offer_id}")
def admin_update_offer(
    offer_id: int,
    payload: OfferUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    offer = db.get(Offer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Офер не знайдено")
    offer.title = payload.title
    offer.reward_pro = payload.reward_pro
    offer.link = payload.link
    offer.is_active = payload.is_active
    offer.is_limited = payload.is_limited
    db.commit()
    return {"ok": True}


@app.delete("/admin/offers/{offer_id}")
def admin_delete_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    offer = db.get(Offer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Офер не знайдено")
    db.delete(offer)
    db.commit()
    return {"ok": True}


@app.get("/admin/channels")
def admin_channels(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    channels = db.execute(select(Channel)).scalars().all()
    return [
        {
            "id": channel.id,
            "channel_id": channel.channel_id,
            "link": channel.link,
            "title": channel.title,
            "is_required": channel.is_required,
        }
        for channel in channels
    ]


@app.post("/admin/channels")
def admin_create_channel(
    payload: ChannelCreateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    channel = Channel(
        channel_id=payload.channel_id,
        link=payload.link,
        title=payload.title,
        is_required=payload.is_required,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return {"id": channel.id}


@app.put("/admin/channels/{channel_id}")
def admin_update_channel(
    channel_id: int,
    payload: ChannelUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    channel = db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Канал не знайдено")
    channel.channel_id = payload.channel_id
    channel.link = payload.link
    channel.title = payload.title
    channel.is_required = payload.is_required
    db.commit()
    return {"ok": True}


@app.delete("/admin/channels/{channel_id}")
def admin_delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    channel = db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Канал не знайдено")
    db.delete(channel)
    db.commit()
    return {"ok": True}


@app.get("/admin/transactions")
def admin_transactions(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    transactions = db.execute(select(Transaction).order_by(Transaction.created_at.desc())).scalars().all()
    return [
        {
            "id": tx.id,
            "user_id": tx.user_id,
            "type": tx.type,
            "amount_pro": tx.amount_pro,
            "status": tx.status,
            "meta": tx.meta,
            "created_at": tx.created_at.isoformat(),
        }
        for tx in transactions
    ]


@app.post("/postback")
def postback(payload: PostbackRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    expected = hmac_sha256(settings.postback_secret, f"{payload.sub1}:{payload.status}:{payload.offer_id}")
    if expected != payload.signature:
        raise HTTPException(status_code=403, detail="Недійсний підпис")
    if payload.status != "deposit":
        return {"ok": True}
    user = db.execute(select(User).where(User.telegram_id == int(payload.sub1))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
    offer = db.get(Offer, int(payload.offer_id))
    if not offer:
        raise HTTPException(status_code=404, detail="Офер не знайдено")

    is_first_deposit = not user.is_deposit
    user.is_deposit = True
    if is_first_deposit:
        user.deposited_at = datetime.utcnow()

    user.balance_pro += offer.reward_pro
    transaction = Transaction(
        user_id=user.id,
        type="offer_reward",
        amount_pro=offer.reward_pro,
        status="ok",
        meta=json.dumps({"offer_id": offer.id}),
    )
    db.add(transaction)

    if user.referrer_id:
        existing = db.execute(
            select(ReferralEvent).where(
                ReferralEvent.referrer_id == user.referrer_id,
                ReferralEvent.referral_id == user.id,
                ReferralEvent.event_type == "deposit",
            )
        ).scalar_one_or_none()
        if not existing:
            referrer = db.get(User, user.referrer_id)
            if referrer:
                referrer.balance_pro += DEPOSIT_REWARD
                referral_event = ReferralEvent(
                    referrer_id=user.referrer_id,
                    referral_id=user.id,
                    event_type="deposit",
                    reward_pro=DEPOSIT_REWARD,
                )
                db.add(referral_event)
                db.add(
                    Transaction(
                        user_id=referrer.id,
                        type="deposit_reward",
                        amount_pro=DEPOSIT_REWARD,
                        status="ok",
                        meta=json.dumps({"referral_id": user.id}),
                    )
                )

    db.commit()
    return {"ok": True}


def hmac_sha256(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), "sha256").hexdigest()
