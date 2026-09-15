# Project Mei

<p align="center">
  <img src="assets/mei_avatar.png" alt="Mei Asahina" width="250" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="assets/mei_peace.png" alt="Mei Asahina Rooftop" width="250" />
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue.svg" alt="Python Version" /></a>
  <a href="https://discordpy.readthedocs.io/"><img src="https://img.shields.io/badge/Discord.py-2.4%2B-5865F2.svg" alt="Discord.py" /></a>
  <a href="https://huggingface.co/Qwen/Qwen3.5-4B"><img src="https://img.shields.io/badge/Model-Qwen3.5--4B%20Recommended-brightgreen.svg" alt="Recommended Model" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="License" /></a>
</p>

A Discord companion bot powered by local LLM backends (LM Studio, Ollama, or vLLM). Mei keeps track of user details in SQLite, processes images and video clips, pulls live web context through DuckDuckGo, and speaks with a sharp, casual catgirl personality.

---

## Overview

Project Mei connects Discord to a local OpenAI-compatible inference server. Instead of acting like a bland assistant, Mei talks like a sarcastic friend who happens to have cat ears. Because the model runs locally, your chat logs, user notes, and media stay on your own hardware.

### Model Notes

- **Recommended Setup**: Small models like **Qwen 3.5 4B** (or Qwen 2.5 3B / 7B) work best. A 4B model uses 6 GB to 8 GB of VRAM, answers single Discord messages with low latency, and handles structured XML tags without breaking syntax.
- **Custom Fine-Tune Note**: I originally made Mei using a private fine-tune built for her character voice. The system prompt and sampling settings in this repo work well on stock open-weight models, but expect minor voice differences compared to the private checkpoint.

---

## Features

- **Image & Video Vision**:
  - Resizes and base64-encodes `.png`, `.jpg`, and `.webp` attachments for vision models.
  - Extracts keyframes across `.mp4`, `.mov`, and `.webm` clips with OpenCV so vision models can see actions in video.
- **Persistent Memory (SQLite + Markdown)**:
  - Stores user facts in SQLite (`data/mei_memory.db`) using WAL mode.
  - Exports an up-to-date summary to `users.md` so you can read or edit what she knows in plain text.
  - Mei decides what to save during chat using `<remember>` tags.
  - Treats saved notes as observations rather than immutable rules. If you correct her or change your mind, she updates the entry.
- **DuckDuckGo Search**:
  - Emits `<search>query</search>` tags when she hits unfamiliar media, release dates, or names.
  - Caches search queries for 10 minutes to avoid rate limits.
- **Terminal-Only Thinking**:
  - Strips `<think>` blocks before sending replies to Discord and logs the full reasoning trace to your terminal.
  - Posts finished replies instead of streaming edits to prevent Discord chat jitter.
- **Admin Commands**:
  - Locks `/facts` and `/reset` to your user ID (`DT_USER_ID`). Other users get an in-character brush-off.

---

## Architecture

```mermaid
flowchart TD
    subgraph Discord["Discord Client"]
        User["User / Owner"] <--> Bot["discord_mei.py"]
    end

    subgraph Peripherals["Peripherals & Tools"]
        Bot <--> Media["media_utils.py<br/>(PIL + OpenCV Keyframes)"]
        Bot <--> Search["Web Search<br/>(DuckDuckGo + Cache)"]
    end

    subgraph Storage["Persistence Layer"]
        Bot <--> UserMgr["user_manager.py"]
        UserMgr <--> DataStore["datastore.py<br/>(SQLite WAL Engine)"]
        DataStore <--> DB[("data/mei_memory.db")]
        DataStore <--> Dossier[("users.md")]
    end

    subgraph Backend["Inference Server"]
        Bot <-->|POST /v1/chat/completions| Engine["LM Studio / Ollama / vLLM<br/>(Qwen 3.5 4B)"]
    end
```

---

## Quickstart

### 1. Requirements
- Python 3.11 or higher (or [uv](https://github.com/astral-sh/uv))
- A local OpenAI-compatible inference server running on port 1234 or your configured URL (LM Studio, Ollama, or vLLM)
- A Discord bot token with Message Content and Server Members intents enabled

### 2. Setup
Clone the repo:
```bash
git clone https://github.com/ItsDTYT/Project-Mei.git
cd Project-Mei
```

Create your configuration file from the template:
```bash
cp .env.example .env
```

Set your configuration values in `.env`:
```ini
DISCORD_BOT_TOKEN=your_discord_bot_token
DT_USER_ID=your_discord_numeric_id
LM_STUDIO_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=qwen3.5-4b
```

### 3. Running

#### Option A: Windows Script
Double-click `run_discord_mei.bat`. If no virtual environment exists, the script creates one using `uv` and installs dependencies.

#### Option B: Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python discord_mei.py
```

#### Option C: Docker
```bash
docker compose up -d
```

---

## Memory System

When a user mentions facts or preferences, Mei saves them with inline XML tags:

```xml
<remember user="DT" cat="gaming">favorite game is the binding of isaac</remember>
```

The bot writes these entries to SQLite and updates `users.md`:

```markdown
## User: ItsDT (ID: 897711166967664690)
- **Role/Relationship**: Creator (DT)
- **Known Facts**:
  - favorite game is the binding of isaac
```

> **Privacy Note**: `.env`, `data/mei_memory.db`, and `users.md` stay in `.gitignore` by default so your credentials and personal notes never get pushed to git.

---

## Commands

Slash commands (`/`) are restricted to the owner ID specified in your `.env`:

| Command | Description | Access |
| :--- | :--- | :--- |
| `/facts [user]` | Shows dossier notes for yourself or another user. | Owner Only |
| `/reset` | Clears recent conversation history in the current channel or DM. | Owner Only |

Prefix fallbacks (`!facts`, `!reset`) are also available for the bot owner.

---

## Sampling Settings (Qwen 3.5 4B)

The default parameters in `discord_mei.py` and `.env.example` target Qwen 3.5 4B:

```ini
TEMPERATURE=0.75
TOP_P=0.80
TOP_K=20
MIN_P=0.05
REPETITION_PENALTY=1.05
```

- **Top-K (20)**: Keeps Qwen focused and stops responses from drifting off-topic.
- **Repetition Penalty (1.05)**: Cuts down repetitive phrasing without making common words sound stiff.
- **Min-P (0.05)**: Removes low-confidence tail tokens based on the top token score.

---

## License

Distributed under the [MIT License](LICENSE).
