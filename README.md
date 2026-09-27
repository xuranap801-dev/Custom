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

## Railway Free/Trial setup

Use the `railway-setup` branch so the Render deployment on `main` remains unchanged.

1. In Railway, create a project from the GitHub repo `xuranap801-dev/Custom` and select branch `railway-setup`.
2. Set the start command to `python bot.py` (build command: `pip install -r requirements.txt`).
3. Add a Volume to the service with mount path `/data`.
4. In the service Variables, set `BOT_TOKEN`, `MAIN_OWNER_ID`, `WEBHOOK_SECRET`, `PORT=10000`, and `DATA_DIR=/data`. Generate the webhook secret with `openssl rand -hex 32`; do not put secrets in GitHub. Railway supplies `RAILWAY_PUBLIC_DOMAIN` after you generate a domain—do not enter that value manually.
5. In Settings → Networking → Public Networking, generate a Railway domain and route it to port `10000`. Set health check path to `/` if the dashboard offers it. The bot registers its Telegram webhook automatically at `https://<RAILWAY_PUBLIC_DOMAIN>/telegram/webhook`.

**Data migration:** The Railway volume starts with an empty SQLite database. Render Free does not expose its ephemeral disk as a Railway volume, so existing users, Firebase entries, credits, and settings will not copy over automatically. Back up/export current bot data before cutover if those records must be kept.

**Cutover:** Before the Railway service first starts with `BOT_TOKEN`, suspend the old Render service. Only one host should register a webhook for the token; if Render wakes later, it could replace Railway's webhook. To roll back, stop Railway first, then resume Render. Keep the old Render service until Railway has been tested.

**Free-plan warning:** Railway's new trial provides a one-time `$5` credit for up to 30 days; afterward Free includes `$1/month` of usage credit. CPU, RAM, volume storage, and outbound network usage are metered, and the bot may stop if the available credit is exhausted. The 0.5 GB Free RAM allowance does not mean the bot uses that amount; monitor actual usage. Trial accounts may have restricted outbound networking unless Railway verifies the account through GitHub. Trial volumes are deleted 30 days after trial credits expire if the account is not upgraded. The Free volume is limited to 0.5 GB. Do not enable Serverless/sleeping for this webhook bot.

## Access control

Single-owner mode is enabled. The configured `MAIN_OWNER_ID` is the only owner; legacy extra-owner and admin IDs are discarded during data normalization, and there is no path to add another owner or administrator.
