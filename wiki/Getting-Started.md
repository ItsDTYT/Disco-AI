# Getting Started with Disco-AI

This guide walks you through setting up Disco-AI from scratch. No programming experience is required.

---

## 1. Create Your Discord Bot Application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and log in with your Discord account.
2. Click the **New Application** button in the top right.
3. Give your bot a name (e.g. `Disco`) and accept the Developer Terms.
4. In the left sidebar, click **Bot**:
   - Under **Build-A-Bot**, click **Reset Token** (and enter your 2FA code if prompted). Copy this token. This is your `DISCORD_BOT_TOKEN`.
   - Scroll down to **Privileged Gateway Intents** and enable both:
     - **Message Content Intent** (required so the bot can read messages and respond)
     - **Server Members Intent** (required to identify users)
   - Click **Save Changes**.

---

## 2. Invite the Bot to Your Server

1. In the Developer Portal sidebar, navigate to **OAuth2 > URL Generator**.
2. Under **Scopes**, check:
   - `bot`
   - `applications.commands`
3. Under **Bot Permissions**, select:
   - Send Messages
   - Read Message History
   - Attach Files
   - Embed Links
   - Use Slash Commands
4. Copy the generated URL at the bottom of the page, open it in your browser, select your server, and click **Authorize**.

---

## 3. Find Your User ID (Owner Admin Access)

To restrict admin commands (`/facts`, `/reset`) to yourself:
1. Open Discord settings > **Advanced** > enable **Developer Mode**.
2. Right-click your own profile in Discord and click **Copy User ID**.
3. This number is your `BOT_OWNER_ID`.

---

## 4. Configure `.env`

Copy the provided template:
```bash
cp .env.example .env
```
Open `.env` in Notepad or your preferred text editor and paste your credentials:
```ini
DISCORD_BOT_TOKEN=your_token_here
BOT_OWNER_ID=your_numeric_user_id
BOT_NAME=Disco
```

Choose either a local engine or a cloud API (see [Model Setup Guide](Model-Setup-Guide.md)).

---

## 5. Launch the Bot

### Windows (Recommended)
Double-click `run.bat`.
- The script checks if Python is installed.
- It automatically creates an isolated virtual environment (`.venv`) and installs required packages.
- It starts your bot immediately.

### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 bot.py
```
