from pydantic import BaseModel, Field


class TelegramAuthRequest(BaseModel):
    initData: str


class TelegramAuthResponse(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    balance_pro: int
    is_deposit: bool
    banned: bool


class WithdrawRequest(BaseModel):
    amount_pro: int = Field(gt=0)
    details: str


class PostbackRequest(BaseModel):
    sub1: str
    status: str
    offer_id: str
    signature: str


class BroadcastRequest(BaseModel):
    type: str
    text: str | None = None
    media_url: str | None = None
    media_file_id: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    audience: str


class BanRequest(BaseModel):
    banned: bool


class BalanceAdjustRequest(BaseModel):
    delta_pro: int
    reason: str


class OfferCreateRequest(BaseModel):
    title: str
    reward_pro: int
    link: str
    is_active: bool = True
    is_limited: bool = False


class OfferUpdateRequest(BaseModel):
    title: str
    reward_pro: int
    link: str
    is_active: bool = True
    is_limited: bool = False


class ChannelCreateRequest(BaseModel):
    channel_id: str
    link: str
    title: str
    is_required: bool = True


class ChannelUpdateRequest(BaseModel):
    channel_id: str
    link: str
    title: str
    is_required: bool = True
