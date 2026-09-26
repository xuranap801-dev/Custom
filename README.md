# Telegram bot

## Render Free Web Service setup

Create a **Web Service** from this repository (not a Background Worker).

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Health check path: `/`
- Add `BOT_TOKEN` (new token from BotFather), `MAIN_OWNER_ID`, and a random `WEBHOOK_SECRET` made only of letters, digits, `_` or `-` (generate one with `openssl rand -hex 32`).
- Render automatically supplies `RENDER_EXTERNAL_URL` and `PORT`; do not set these manually. Optional variables include `BOT_USERNAME`, `OWNER_NAME`, and `OWNER_LINK`.
- No persistent disk is available on the free plan. Do not set `DATA_DIR`; the SQLite database and JSON backup use the default working directory.

The bot receives Telegram updates through an HTTPS webhook at `/telegram/webhook`; the application validates Telegram's secret-token header. `requirements.txt` includes aiogram 3.25+ (which supports Telegram button styles) and aiohttp (already required by the bot; no extra package is needed for the web server).

Stop any existing polling instance using this bot token before starting the webhook service; Telegram does not allow polling and a webhook to be active at the same time.

## Free plan limitations

Render may spin a free web service down after 15 minutes without inbound traffic. Telegram updates can wake it, but startup can delay or interrupt delivery; test the bot after deployment. The local SQLite database, in-memory user conversation states, and background scanner cache are not durable on the free filesystem and may reset after a restart, spin-down, or redeploy. Back up important data regularly. A persistent disk requires a paid plan.

Do not commit `.env`, bot tokens, or runtime database files.

## Access control

Single-owner mode is enabled. The configured `MAIN_OWNER_ID` is the only owner; legacy extra-owner and admin IDs are discarded during data normalization, and there is no path to add another owner or administrator.
