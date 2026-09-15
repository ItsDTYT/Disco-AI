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

Project Mei links Discord to an OpenAI-compatible local server. Mei speaks as a sarcastic companion with cat ears. The backend runs on your machine, keeping chat history, notes, and media on your own hardware.

### Model Notes

- **Recommended Setup**: Qwen 3.5 4B and Qwen 2.5 (3B or 7B) fit this project well. A 4B model takes 6 GB to 8 GB of VRAM, responds fast, and keeps XML tags intact.
- **Custom Fine-Tune**: I built Mei around a private fine-tune for her voice. This repository includes prompts and sampling settings tuned for stock open-weight models, though tone will differ from the private checkpoint.

---

## Features

- **Image & Video Vision**: Encodes PNG, JPG, and WEBP attachments for vision models. Pulls keyframes from MP4, MOV, and WEBM clips using OpenCV.
- **Persistent Memory (SQLite + Markdown)**: Writes facts to SQLite (`data/mei_memory.db`) in WAL mode. Exports plain text summaries to `users.md`. The model marks details to save with `<remember>` tags, and you can update entries by correcting her in chat.
- **DuckDuckGo Search**: Triggers `<search>query</search>` tags when the prompt needs external facts, release dates, or names. Caches results for 10 minutes to stay clear of rate limits.
- **Terminal-Only Thinking**: Strips `<think>` blocks from Discord messages and prints reasoning traces to the terminal. Posts finished replies to prevent chat jitter.
- **Admin Commands**: Restricts `/facts` and `/reset` to `DT_USER_ID`.

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
