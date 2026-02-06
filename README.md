# GoodCasino Telegram Web App

Повністю готовий стек для Telegram Web App казино: FastAPI backend, aiogram 3 бот, статичний фронтенд (React/Vite), Nginx проксі та SQLite.

## Швидкий старт (локально)

1. Скопіюйте `.env.example` у `.env` та заповніть значення:

```bash
cp .env.example .env
```

2. Запустіть проєкт:

```bash
docker compose up -d --build
```

3. Перевірка стану:

```bash
curl http://localhost/health
```

## Продакшен нотатки

- Вкажіть `DOMAIN` та `CERTBOT_EMAIL` у `.env` якщо плануєте додати certbot (шаблон залишено для майбутніх сценаріїв).
- Всі сервіси працюють через Nginx. Статичний фронтенд доступний за `/`, API за `/api/*`, адмінка за `/admin/*`.
- База даних SQLite зберігається у volume `db_data` за шляхом `/data/database.db`.

## Основні сервіси

- `backend` — FastAPI API.
- `bot` — Telegram бот (aiogram 3).
- `frontend` — збірка Vite та копіювання `dist` у спільний volume.
- `nginx` — віддає `/` та проксі `/api`, `/admin`, `/postback`, `/health`.

## Ключові API

### Аутентифікація WebApp
`POST /api/auth/telegram` з `initData` з Telegram WebApp.

### Публічні ендпоінти
- `GET /api/offers`
- `GET /api/referrals`
- `POST /api/game/play`
- `GET /api/wallet`
- `POST /api/withdraw`

### Адмін API (заголовок `X-Admin-Token`)
- `GET /admin/users`
- `POST /admin/users/{id}/ban`
- `POST /admin/users/{id}/balance`
- `GET /admin/offers`
- `POST /admin/offers`
- `PUT /admin/offers/{id}`
- `DELETE /admin/offers/{id}`
- `GET /admin/channels`
- `POST /admin/channels`
- `PUT /admin/channels/{id}`
- `DELETE /admin/channels/{id}`
- `GET /admin/transactions`
- `POST /admin/broadcast`

### Постбек
`POST /postback` з підписом `HMAC_SHA256(POSTBACK_SECRET, sub1:status:offer_id)`.

## Telegram бот

- `/start` перевіряє підписку на required-канали та показує кнопку WebApp.
- `/ref` повертає реферальне посилання.
- Автоматично підтверджує заявки на вступ у канали.
- Розсилка відбувається асинхронно через опитування таблиці broadcast_logs.

## Налаштування середовища

Файл `.env` має містити:

```
BOT_TOKEN=
BOT_USERNAME=
WEBAPP_URL=
ADMIN_TOKEN=
POSTBACK_SECRET=
DOMAIN=
CERTBOT_EMAIL=
SQLITE_PATH=/data/database.db
ADMIN_ID=
```
