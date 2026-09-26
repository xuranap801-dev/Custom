# Telegram bot

## Render setup

Create a **Background Worker** from this repository.

- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Environment: set `BOT_TOKEN` (new token from BotFather), `MAIN_OWNER_ID`, and any optional settings used by the bot.
- Storage: attach a persistent disk mounted at `/var/data`, then set `DATA_DIR=/var/data`.

Do not commit `.env`, bot tokens, or runtime database files. This bot uses Telegram long polling and should run as a single worker instance. Background workers and persistent disks require a paid Render service plan; a free web service is not a reliable always-on host for this polling process.
## Access control

Single-owner mode is enabled. The configured `MAIN_OWNER_ID` is the only owner; legacy extra-owner and admin IDs are discarded during data normalization, and there is no path to add another owner or administrator.
