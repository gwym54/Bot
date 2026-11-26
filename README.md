# RoutexSMS OTP Bot — Version 2.0

A Telegram number / OTP bot for Railway (python-telegram-bot v20+).
It reads received SMS from **two panels at the same time** — **Teleroutex** and **IMS SMS** —
gives numbers to users, forwards each OTP to the user who holds the number, pays the user,
and posts it in a public OTP group.

---

## How it works

1. A user taps **GET NUMBER** (or **Search Number**), picks a service and gets numbers.
2. The user uses the number on WhatsApp / Facebook / Uber etc.
3. The SMS arrives in the Teleroutex or IMS SMS panel.
4. The bot checks both panels every **5 seconds**.
5. The user who holds the number gets the message with a green **copy button** with the OTP.
   An SMS with no code shows the button **N/A**.
6. The user is **paid for every SMS** received on the held number. There is no number timer.
7. The same SMS is posted in the **public OTP group**: the number is masked, the OTP code is visible,
   and two buttons are added: **Number Bot** and **Method** (your channel).

No source group is needed. A number is never given to two users at the same time.

---

## Railway variables

Add these in Railway → your service → **Variables**. Never put them in GitHub.

| Variable | Required | What it is |
|---|---|---|
| `BOT_TOKEN` | Yes | Bot token from @BotFather |
| `ADMINS` | Yes | Admin Telegram user IDs, separated by commas |
| `CHANNEL_ID` | Yes | Your channel ID (`-100...`) used for force join |
| `CHANNEL_LINK` | Yes | Your channel link (`https://t.me/...`), used for force join and the **Method** button |
| `TELEROUTEX_API_KEY` | Yes | API key from the Teleroutex panel |
| `DB_FILE` | Yes | `/app/data/db.json` (must match the volume mount path) |
| `IMS_API_TOKEN` | No | API token from the IMS SMS panel (REST API page). Leave it out to use Teleroutex only |
| `OTP_GROUP_ID` | No | Public OTP group ID. Default is set in the code; `/setotpgroup` can change it |
| `SUPPORT_LINK`, `DEVELOPER_LINK` | No | Links for the Support buttons |
| `BACKUP_HOURS` | No | Send `db.json` to admins every N hours (default `6`, `0` = off) |
| `NUMBERS_PER_REQUEST` | No | Numbers given per GET NUMBER tap (default `3`) |
| `TIMEZONE_HOURS` | No | Time zone shown in messages (default `6`) |

Other optional settings: `OTP_GROUP_LINK`, `OTP_RATE`, `TRAFFIC_MINUTES`, `MESSAGES_URL`.
`SMS_SOURCE` defaults to `api` and should stay that way.

---

## Railway deploy

1. Push this folder to a **private** GitHub repo (`bot.py`, `requirements.txt`, `Dockerfile` / `start.sh`).
2. Railway → New Project → **Deploy from GitHub**.
3. **Add a Volume** to the service with mount path **`/app/data`**, then press **Deploy**.
   Without the volume, your data is lost on every redeploy.
4. Add the variables above, then press **Deploy**.
5. Set **Replicas = 1**. Two copies of the bot cause a `Conflict: terminated by other getUpdates` error.
6. Open **Deploy Logs** and check for:
   - `=== NEW BOT CODE LOADED - VERSION 2.0 ===`
   - `API mode: dual-panel ready → Teleroutex + IMS SMS`
   - `IMS SMS connected: N recent SMS in the panel (not forwarded)`

A new GitHub commit starts a new deployment by itself. The **Redeploy** button only re-runs the old commit.

> The Railway trial credit ($5) is one-time and runs out after 30 days. Upgrade to the Hobby plan
> before it ends, or the bot stops and the volume is deleted later.

---

## The two panels

- **Teleroutex** — read with `TELEROUTEX_API_KEY`.
- **IMS SMS** — read from `https://imssms.org/api/v1/messages` with `IMS_API_TOKEN` in a header.
  Rate limit: 1 request per second, 40 per minute. The bot makes about 12 per minute.
- If one panel is down, the other keeps working. Each panel remembers its own old SMS.
- When the bot starts, old SMS are only remembered, never forwarded.

---

## Features

**For users**
- GET NUMBER and **Search Number** (send 3–9 digits to find a number)
- Copy-number buttons, Change Number, View OTP, number format with or without country code
- Leaderboard with tabs: **24h / 7 Days / All Time**
- Profile, Refer, Support, Language (English / বাংলা), Traffic
- Withdrawal (bKash / Nagad) with a payment photo from the admin
- Force join: users must be in your **channel** and the **public OTP group**

**For admins** (Admin Panel)
- Add numbers by sending a `.txt` / `.csv` file, then give a **batch name** (Togo 1, Togo 2 ...)
- New service (emoji allowed, for example `Facebook🔥🔥`), **Rename service** (keeps all data), Remove service
- Edit rates, pools, users, broadcast, ban / unban
- **Withdraw ON / OFF** switch
- **✏️ Edit texts & buttons**: change the welcome message and any text in English or Bangla, no redeploy
- Pending withdrawals: **Paid** asks for a payment photo that the user sees in the bot, or **Reject** to refund

---

## Admin commands

| Command | Use |
|---|---|
| `/backup` | Send `db.json` to you now |
| `/addnumbers SERVICE n1 n2 ...` | Add numbers by text |
| `/setotpgroup` | Send it inside the public OTP group to set it |
| `/testgroup` | Post a test message in the public OTP group |
| `/setemoji KEY EMOJI_ID` | Premium emoji icon on a button (needs Telegram Premium) |
| `/setrate`, `/rates` | Rates per service |
| `/addbal`, `/ban`, `/unban`, `/broadcast` | User tools |
| `/addservice`, `/delservice`, `/delnumbers`, `/delcountry`, `/clearnumbers`, `/assign` | Services and numbers |
| `/language` | Language choice (also for users) |

---

## Backup and restore

- The bot sends `db.json` to every admin every **6 hours**, and `/backup` sends it at once.
- Restore: send a backup `.json` file to the bot in a private chat as admin. When it says
  **Backup restored**, **restart the bot straight away**, before pressing anything else.
- Keep the latest backup file. It contains user data, so keep it private.

---

## Local test

```bash
pip install "python-telegram-bot>=20" httpx pyotp
export BOT_TOKEN="..."
export ADMINS="123456789"
export CHANNEL_ID="-100..."
export CHANNEL_LINK="https://t.me/yourchannel"
export TELEROUTEX_API_KEY="..."
export IMS_API_TOKEN="..."        # optional
python bot.py
```

---

## Notes

- Keep `BOT_TOKEN`, `TELEROUTEX_API_KEY` and `IMS_API_TOKEN` secret. Never upload `db.json` to GitHub.
- The bot must be **admin** in the public OTP group, and in the channel for force join.
- Numbers are paid for as long as the user holds them. A number is released when the user cancels it
  or an admin removes it.
