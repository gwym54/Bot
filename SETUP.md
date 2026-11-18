# OTP Bot Setup (original documentation)

> For Railway deployment see **README.md** first.

# OTP Bot: full setup

## 1. Telegram side (5 min)
1. @BotFather -> /newbot -> copy the token -> BOT_TOKEN.
2. @userinfobot -> your numeric ID -> ADMINS (comma-separate for more admins).
3. Create 3 chats and get each ID (forward a message from it to @RawDataBot / @getidsbot; IDs look like -100xxxxxxxxxx):
   - SOURCE group: where your SMS forwarder (Teleroutex) posts incoming SMS -> SOURCE_GROUP_ID
   - OTP group: a DIFFERENT group where masked OTPs are posted -> OTP_GROUP_ID
   - Force-join channel -> CHANNEL_ID, and its invite link -> CHANNEL_LINK
4. Add the bot as ADMIN in the source group, OTP group and channel
   (the channel admin right is needed for the join check).
5. @BotFather -> /mybots -> Bot Settings -> Group Privacy -> Turn off.

## 2. Configure
Edit `.env` (used by Docker). For start.sh / start.bat, put the same values at the top of those files.
Never share or commit .env; if the token leaks, /revoke it in @BotFather.

## 3. Run (pick one)
**Docker (recommended, runs 24/7)**
    docker compose up -d --build
    docker compose logs -f          # look for "Bot started"
    docker compose down             # stop
**Linux/macOS**  `chmod +x start.sh && ./start.sh`
**Windows**      double-click `start_controller.bat` (GUI) or `start.bat`
**Python manually**
    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    set -a; source .env; set +a; python bot.py

## 4. First use
1. DM the bot /start -> ADMIN PANEL.
2. Send your .txt/.csv of full numbers with country code (e.g. 8801892345612).
3. Test: GET NUMBER -> pick service/country -> send a test SMS containing that number and a code to the source group -> the code shows in the bot and balance goes up.

## 5. Admin commands
/addnumbers N... | /ban ID | /unban ID | /addbal ID AMT | /setrate [SERVICE] AMT | /rates | /broadcast TEXT
Withdrawals arrive in your DM with Paid/Reject buttons (bKash/Nagad are paid manually).

## 6. Backups
All data lives in db.json (./data/db.json under Docker). Copy it regularly.

## Troubleshooting
- `KeyError: CHANNEL_ID` / `ADMINS is empty`: a .env value is blank.
- Bot ignores SMS: it is not admin in the source group, privacy mode is on, or SOURCE_GROUP_ID is wrong.
- Everyone sees "join channel": bot isn't admin in the channel, or CHANNEL_ID is wrong.
- Two copies running -> "Conflict: terminated by other getUpdates". Run only one instance.

## Changes made to your original
- Removed hardcoded fallback admin ID / channel / support links belonging to someone else (an empty ADMINS made a stranger the bot admin). These are now required or configurable in .env.

## Numbers per service (new)
Each service (WHATSAPP, TELEGRAM, FACEBOOK, INSTAGRAM, TIKTOK) has its own number pool.
Add numbers in any of these ways (admin only, private chat with the bot):
1. ADMIN PANEL -> tap "Add numbers: FACEBOOK" -> send your .txt/.csv file.
2. Name the file after the service, e.g. facebook.txt, and send it.
3. Send the file with the service name as the caption.
4. /addnumbers FACEBOOK 8801892345612 8801711223344
Other commands: /clearnumbers SERVICE (empty a pool), /assign SERVICE (move numbers added before this update into a service).
Users only see numbers from the service they pick under GET NUMBER.

## Numbers per request and validity (new)
Each GET NUMBER tap gives 3 numbers; each number waits 10 minutes for its OTP.
Change in start.bat / .env:  NUMBERS_PER_REQUEST=3   OTP_VALID_MINUTES=10
(Windows start.bat: add lines like  set NUMBERS_PER_REQUEST=3 )

## API mode (Teleroutex)
In start.bat:
    set SMS_SOURCE=api
    set TELEROUTEX_API_KEY=your key (paste exactly as shown in the Teleroutex panel, no quotes)
The bot checks the API once every 5 seconds for all waiting numbers. SOURCE_GROUP_ID is not used (leave 0).
Console logs no longer show the bot token or API key.

## Several OTPs per number, hidden public code
A user keeps a number for OTP_VALID_MINUTES (default 10). Every OTP that arrives on it is forwarded to that user
(the first replaces the "waiting" message, later ones come as new replies).
PAY_EVERY_OTP=1 pays each OTP, 0 pays only the first.
The public OTP group shows the masked number and a hidden code (••••••). OTP_PUBLIC_VISIBLE_DIGITS=2 would show the first 2 digits.
Numbers in the bot must be the same full numbers (with country code) that appear in your Teleroutex panel under My Numbers.

## View OTP button
Each number message has a "View OTP" button next to "Change Number". It checks Teleroutex immediately
(at most once every 3 seconds per number) and shows a popup: the OTP, or "No OTP yet".
After the first OTP the message keeps only the View OTP button until the number's time is up.

## View OTP opens the public OTP group
Set OTP_GROUP_LINK (invite link of the public OTP group, e.g. https://t.me/+abc123) in start.bat.
Then the View OTP button opens that group directly. Without OTP_GROUP_LINK it shows the OTP in a popup instead.

## Change Number gives 3 new numbers
"Change Number" releases every number of the same batch that has not got an OTP yet and gives 3 fresh numbers.
The existing 3 messages are updated in place; a number that already received an OTP stays as it is.

## Add / remove services (folders) from the admin panel
ADMIN PANEL -> "🆕 New service" -> send a name (e.g. AGODA, IMO). It appears in GET NUMBER and in "➕ Add numbers" at once.
"🗑 Remove service" deletes a service and its numbers (asks for confirmation).
Commands: /addservice NAME   /delservice NAME
The list is saved in db.json, so it survives restarts.

## Remove numbers
ADMIN PANEL -> "🗑 Remove numbers" -> choose a service -> "🧹 Clear all" (asks to confirm) or "✏️ Remove specific numbers"
(send the numbers as text, one per line or separated by spaces, or as a .txt/.csv file).
Commands: /delnumbers SERVICE N1 N2 ...   /clearnumbers SERVICE
Only numbers still in the pool are removed; numbers already given to users are not affected.

## Remove one country
ADMIN PANEL -> "🗑 Remove numbers" -> service -> "🌍 Remove a country" -> pick the country (shows how many numbers) -> confirm.
Command: /delcountry SERVICE CODE   e.g. /delcountry FACEBOOK 880

## Public OTP group
Every OTP is posted there with the service, country, masked number, sender (API mode) and a HIDDEN code.
Requirements: OTP_GROUP_ID = the group's ID (-100...), the bot is ADMIN in it, and it differs from SOURCE_GROUP_ID.
Test it: send /testgroup to the bot (admin). If posting fails the bot tells you why, and the console shows
"public OTP group post FAILED". On start the console prints "Public OTP group: <name>" when the bot can reach it.

## Set the public OTP group from Telegram (no file editing)
1. Create the group, add the bot as ADMIN (allow "invite users" so it can make the link).
2. As admin, send /setotpgroup INSIDE that group.
3. The bot saves the group and its invite link, posts a test notice, and from then on posts every OTP there automatically (code hidden).
   The View OTP button uses the saved link.
From a private chat you can also use /setotpgroup -100xxxxxxxxxx (needed for channels).
The group saved this way is kept in db.json and overrides OTP_GROUP_ID in start.bat. Change it any time by running /setotpgroup in another group.

## Old numbers keep delivering after Change Number (no time limit)
When a user presses Change Number, the previous numbers stay reserved for that user and keep delivering OTPs with NO time limit
(KEEP_OLD_MINUTES=0). An OTP on an old number arrives as a normal OTP message (new message), is paid, and is posted to the
public group. These numbers are saved in db.json, so they still work after a restart (an OTP is never delivered twice).
Set KEEP_OLD_MINUTES=30 (or any minutes) in start.bat if you prefer a limit. Cancel and timeout still drop a number.
Note: the bot checks Teleroutex every 5 seconds as long as any number is held.
