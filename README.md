# OTP Bot – API Mode (Railway Ready)

This version is set for **API mode only**.
The bot gets SMS/OTP from **Teleroutex API** (not from a Telegram group).

## Required variables (Railway)

| Variable | Required | Example |
|----------|----------|---------|
| `BOT_TOKEN` | Yes | `7123...:AAH...` from @BotFather |
| `ADMINS` | Yes | Your Telegram user ID |
| `CHANNEL_ID` | Yes | `-1001234567890` |
| `CHANNEL_LINK` | Yes | `https://t.me/yourchannel` |
| `TELEROUTEX_API_KEY` | Yes | Key from Teleroutex panel |
| `SMS_SOURCE` | No | Already defaults to `api` |

Optional: `OTP_GROUP_ID`, `SUPPORT_LINK`, `DEVELOPER_LINK`

## Railway deploy (short)

1. Push this folder to a **private** GitHub repo
2. Railway → New Project → Deploy from GitHub
3. Add **Volume** mount path: `/app/data`
4. Add the Variables above
5. Set **Replicas = 1**
6. Deploy → check Logs for `Bot started` and `API mode: checking Teleroutex every 5s`

## How OTP works in API mode

1. User gets a number from the bot
2. User uses that number on WhatsApp / Facebook etc.
3. SMS arrives in your Teleroutex account
4. Bot polls Teleroutex API every 5 seconds
5. When OTP is found → bot sends it to the user and adds balance

No Source Group needed.

## Local test

```bash
cp .env.example .env
# fill BOT_TOKEN, ADMINS, CHANNEL_*, TELEROUTEX_API_KEY
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
python bot.py
```
