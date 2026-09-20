# Disco-AI

<p align="center">
  <img src="assets/banner.png" alt="Disco-AI Banner" width="100%" />
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg" alt="Python Version" /></a>
  <a href="https://discordpy.readthedocs.io/"><img src="https://img.shields.io/badge/Discord.py-2.4%2B-5865F2.svg" alt="Discord.py" /></a>
  <a href="https://obsidian.md"><img src="https://img.shields.io/badge/Vault-Obsidian%20Compatible-7C3AED.svg" alt="Obsidian Compatible" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="License" /></a>
</p>

Disco-AI is a Discord bot that connects to local LLMs (LM Studio, Ollama, vLLM) or cloud APIs (OpenAI, Groq, OpenRouter). It saves user memories as plain Markdown notes inside an Obsidian vault, supports images and video keyframes, resolves Discord mentions, and lets you change the bot persona by editing a single text file.

---

## Features

- **Talk anywhere**: Chat with the bot in any channel, reply to it, ping it, or message it in DMs without channel restrictions.
- **Image and video support**: Handles pictures, animated GIFs, Discord stickers, and video frames. If your current model doesn't support vision, the bot lets you know in chat.
- **Obsidian vault memory**: Saves member notes to `vault/users/{id}.md` with YAML frontmatter, tags (`#user`, `#disco-ai/memory`), and task checkboxes. You can open the `vault/` folder directly in Obsidian to see everything in the graph view.
- **Mention and emoji cleanup**: Converts raw Discord IDs (`<@user_id>`, `<@&role_id>`, `<#channel_id>`) into readable user handles, role names, and channel names, and converts custom emojis into `:name:`.
- **User profile context**: Grabs basic profile info (account age, server join date, roles, and status/activity) so the bot knows who it is talking to.
- **Custom persona in plain text**: Change personality, tone, and rules in `prompt.txt` without editing Python code.
- **DuckDuckGo search**: The bot can look up real-time information by outputting `<search>query</search>`, with results cached for 10 minutes.
- **Terminal-only thinking**: Model reasoning blocks (`<think>...</think>`) stay in your terminal console instead of cluttering chat.
- **Slash commands**: Clean `/facts` and `/reset` commands locked to the bot owner.

---

## Quickstart

### 1. Create your Discord bot
1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. Go to the **Bot** tab and click **Reset Token** to copy your token.
3. Turn on these **Privileged Gateway Intents**:
   - Message Content Intent
   - Server Members Intent
   - Presence Intent (optional, allows reading user activity/status)
4. Go to **OAuth2 > URL Generator**, check `bot` and `applications.commands`, pick standard message permissions, and invite the bot to your server.

### 2. Configure settings
Copy the example environment file:
```bash
cp .env.example .env
```
Edit `.env` with your bot token, owner ID, and model settings:
```ini
DISCORD_BOT_TOKEN=your_discord_bot_token
BOT_OWNER_ID=your_numeric_discord_user_id
BOT_NAME=Disco

# Local LLMs (e.g. LM Studio on port 1234):
API_BASE_URL=http://127.0.0.1:1234/v1
MODEL_NAME=qwen3.5-4b
API_KEY=

# Or for vision models:
# MODEL_NAME=qwen2.5-vl-7b-instruct
```

### 3. Run the bot

#### Windows
Double-click `run.bat`. It will set up the virtual environment, install requirements, and launch the bot.

#### Linux / macOS / Terminal
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

#### Docker
```bash
docker compose up -d
```

---

## Architecture

```mermaid
flowchart TD
    subgraph Discord["Discord"]
        User["User"] <--> Bot["bot.py"]
    end

    subgraph Peripherals["Message Processing"]
        Bot <--> Media["media_utils.py (Images, GIFs, Stickers)"]
        Bot <--> Resolver["Entity Resolver (Pings, Roles, Profiles)"]
        Bot <--> Search["Web Search (DuckDuckGo)"]
        Bot <--> Prompt["prompt.txt (Bot Persona)"]
    end

    subgraph Storage["Memory"]
        Bot <--> UserMgr["user_manager.py"]
        UserMgr <--> Vault["obsidian_vault.py"]
        Vault <--> Notes["vault/users/{id}.md"]
        Vault <--> Index["vault/Index.md"]
    end

    subgraph Backend["LLM Backend"]
        Bot <--> Engine["LM Studio / Ollama / OpenAI / OpenRouter / Groq"]
    end
```

---

## Commands

| Command | What it does | Who can use it |
| :--- | :--- | :--- |
| `/facts [user]` | Shows saved Obsidian vault notes for you or a selected user | Bot Owner |
| `/reset` | Clears recent conversation memory in the current channel or DM | Bot Owner |

---

## Recommended Models

### Local
- **Qwen 3.5 4B / Qwen 2.5 7B**: Great for text chat and fast responses.
- **Qwen 2.5-VL (3B or 7B)**: Recommended if you want image and GIF understanding locally.
- **MiniCPM-V 2.6**: Strong local vision model.

### Cloud
- **Gemini 2.0 Flash**: Fast, cheap, and handles vision and text easily.
- **GPT-4o**: Reliable reasoning and multimodal support.

---

## Viewing Memories in Obsidian

Disco-AI stores memories directly as markdown notes:
1. Open the [Obsidian](https://obsidian.md) desktop app.
2. Select **Open folder as vault** and choose the `vault/` directory inside this project.
3. Open `Index.md` or check out the Graph View to see users and saved facts linked together.

---

## Documentation

Check the [Wiki](wiki/Home.md) for more details:
- [Getting Started Guide](wiki/Getting-Started.md)
- [Model Setup Guide](wiki/Model-Setup-Guide.md)
- [Customizing Personas & Memory](wiki/Customizing-Personas.md)
- [Troubleshooting & FAQ](wiki/Troubleshooting.md)

---

## License

MIT License. See [LICENSE](LICENSE) for details.
