# Disco-AI: Beginner-friendly Discord AI bot powered by Local LLMs or Cloud APIs.
# Supports images, video keyframes, SQLite persistent memory, and real-time web search.
import asyncio
import html
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import discord
import httpx
from discord import app_commands
from dotenv import load_dotenv

from media_utils import process_discord_attachments
from user_manager import UserManager

# Load configuration from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DiscoBot")
for noisy in ["ddgs", "primp", "httpx", "discord"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Discord Credentials & Admin IDs
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
BOT_NAME = os.getenv("BOT_NAME", "Disco").strip()
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

# Allowed Channel/Guild IDs (leave empty to allow all channels where bot is present)
raw_allowed = os.getenv("ALLOWED_CHANNEL_IDS", "").strip()
ALLOWED_IDS = {int(x.strip()) for x in raw_allowed.split(",") if x.strip().isdigit()}

# LLM Backend Settings (Local or Cloud API)
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
API_KEY = os.getenv("API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.5-4b").strip()

# Sampling Parameters
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.75"))
TOP_P = float(os.getenv("TOP_P", "0.80"))
TOP_K = int(os.getenv("TOP_K", "20"))
MIN_P = float(os.getenv("MIN_P", "0.05"))
REPETITION_PENALTY = float(os.getenv("REPETITION_PENALTY", "1.05"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))

# Memory and User Management
PROMPT_FILE = Path(__file__).resolve().parent / "prompt.txt"
user_manager = UserManager()
memory_lock = asyncio.Lock()


def load_system_prompt() -> str:
    # Loads custom character persona from prompt.txt if available
    if PROMPT_FILE.exists():
        try:
            content = PROMPT_FILE.read_text(encoding="utf-8").strip()
            # Filter out top comment headers starting with '#'
            lines = [l for l in content.splitlines() if not l.startswith("#")]
            cleaned = "\n".join(lines).strip()
            if cleaned:
                return cleaned
        except OSError as e:
            logger.warning(f"Could not read prompt.txt: {e}")

    # Fallback default prompt
    return (
        f"You are {BOT_NAME}, a friendly, intelligent, and relaxed companion on Discord. "
        "Keep your replies concise and conversational (1-3 sentences typically). "
        "Match the casual tone of Discord chat, avoiding stiff corporate or assistant clichés. "
        "You maintain internal memory notes on users using <remember>fact</remember>. "
        "If you encounter unfamiliar recent facts or media, trigger a search via <search>query</search>."
    )


SYSTEM_PROMPT = load_system_prompt()

# Runtime conversation caches
conversations: dict[str, list[dict[str, Any]]] = {}
conversation_lru: list[str] = []
MAX_CONVERSATION_SESSIONS = 50
MAX_HISTORY_TURNS = 12
search_cache: dict[str, tuple[float, str]] = {}
http_client: httpx.AsyncClient | None = None


def track_conversation_session(context_key: str):
    if context_key in conversation_lru:
        conversation_lru.remove(context_key)
    conversation_lru.append(context_key)

    if len(conversation_lru) > MAX_CONVERSATION_SESSIONS:
        evicted = conversation_lru.pop(0)
        conversations.pop(evicted, None)


async def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None or http_client.is_closed:
        http_client = httpx.AsyncClient(timeout=180.0)
    return http_client


async def query_llm(messages: list[dict[str, Any]]) -> str:
    # Supports both Local LLMs and Cloud APIs using standard OpenAI format
    client = await get_http_client()
    url = f"{API_BASE_URL}/chat/completions"

    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "top_k": TOP_K,
        "min_p": MIN_P,
        "repetition_penalty": REPETITION_PENALTY,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    resp = await client.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error ({resp.status_code}): {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def search_web_sync(query: str, max_results: int = 3) -> str:
    # 10-minute caching avoids throttling search engines
    now = time.time()
    q_norm = query.lower().strip()
    if q_norm in search_cache:
        cached_ts, cached_snippet = search_cache[q_norm]
        if now - cached_ts < 600.0:
            return cached_snippet

    results_text = ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = client.get("https://html.duckduckgo.com/html/", params={"q": query})
            if resp.status_code == 200:
                titles = re.findall(
                    r'<a[^>]+class="result__snippet[^>]*>(.*?)</a>', resp.text, re.IGNORECASE
                )
                snippets = re.findall(
                    r'<a[^>]+class="result__url[^>]*>(.*?)</a>', resp.text, re.IGNORECASE
                )
                found = []
                for t, s in zip(titles[:max_results], snippets[:max_results]):
                    ct = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
                    cs = html.unescape(re.sub(r"<[^>]+>", "", s)).strip()
                    if ct or cs:
                        found.append(f"- **{ct}**: {cs}")
                if found:
                    results_text = "\n".join(found)
    except (httpx.HTTPError, OSError) as e:
        logger.debug(f"Direct HTML search failed: {e}")

    if not results_text:
        try:
            from ddgs import DDGS

            hits = list(DDGS().text(query, max_results=max_results))
            if hits:
                results_text = "\n".join(
                    [f"- **{r.get('title', 'Result')}**: {r.get('body', '')}" for r in hits]
                )
        except (ImportError, httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
            logger.warning(f"DDGS fallback error for '{query}': {e}")

    final_res = results_text if results_text else "No relevant search results found on the web."
    search_cache[q_norm] = (now, final_res)
    return final_res


async def search_web(query: str, max_results: int = 3) -> str:
    return await asyncio.to_thread(search_web_sync, query, max_results)


def extract_search_query(text: str, fallback_query: str | None = None) -> str | None:
    # Check explicit <search>query</search> tags
    m = re.search(r"<search>(.*?)</search>", text, re.IGNORECASE | re.DOTALL)
    if m and len(m.group(1).strip()) >= 2:
        return m.group(1).strip()

    m_attr = re.search(r"<search\s+query=['\"](.*?)['\"]", text, re.IGNORECASE)
    if m_attr and len(m_attr.group(1).strip()) >= 2:
        return m_attr.group(1).strip()

    # Search hints inside thinking traces
    think_match = re.search(r"<think>([\s\S]*?)</think>", text, re.IGNORECASE)
    if think_match:
        think_text = think_match.group(1)
        m_intent = re.search(
            r"(?:let me search|need to search|searching for|look up|search for)\s+['\"]?([^'\"\n.,;<>]{3,60})",
            think_text,
            re.IGNORECASE,
        )
        if m_intent and len(m_intent.group(1).strip()) >= 3:
            cand = m_intent.group(1).strip()
            if cand.lower() not in ["it", "this", "things", "stuff", "info", "them", "something"]:
                return cand

        if (
            re.search(
                r"(?:without a search|need a search|would have to search|should search)",
                think_text,
                re.IGNORECASE,
            )
            and fallback_query
            and len(fallback_query.strip()) >= 4
        ):
            return fallback_query.strip()

    return None


def parse_bot_response(raw_text: str) -> tuple[str, str]:
    thought = ""
    reply = raw_text.strip()

    # Extract <think> reasoning trace
    think_match = re.search(r"<think>([\s\S]*?)</think>", raw_text, re.IGNORECASE)
    if think_match:
        thought = think_match.group(1).strip()
        reply = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE).strip()

    for token in ["<think>", "</think>", "<turn|>", "<|turn>"]:
        reply = reply.replace(token, "")

    reply = re.sub(
        r"<(?:remember|note)[\s\S]*?</(?:remember|note)>", "", reply, flags=re.IGNORECASE
    ).strip()
    reply = re.sub(r"<search[\s\S]*?</search>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search\b[^>]*\/?>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search:[^>\n]+>", "", reply, flags=re.IGNORECASE).strip()

    clean_reply = reply.strip()
    if clean_reply in ["...", "..", ".", ""]:
        clean_reply = "Thinking over what you said..."
    return thought, clean_reply


# Setup Discord Client and Application Command Tree
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guild_messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =====================================================================
# SLASH COMMANDS (/) - ADMIN & OWNER RESTRICTED
# =====================================================================


@tree.command(name="facts", description="Check what facts the bot remembers about a user")
@app_commands.describe(user="The user to check notes on (defaults to yourself)")
async def slash_facts(interaction: discord.Interaction, user: discord.Member | None = None):
    if BOT_OWNER_ID and interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message(
            "This command is restricted to the bot owner.", ephemeral=True
        )
        return

    target = user or interaction.user
    display_name = target.display_name or target.name

    async with memory_lock:
        card = user_manager.get_user_display_card(target.id, display_name)
    await interaction.response.send_message(card)


@tree.command(name="reset", description="Clear conversation context memory for this channel or DM")
async def slash_reset(interaction: discord.Interaction):
    if BOT_OWNER_ID and interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message(
            "This command is restricted to the bot owner.", ephemeral=True
        )
        return

    ctx_key = (
        f"dm_{interaction.user.id}"
        if interaction.guild is None
        else f"channel_{interaction.channel_id}"
    )
    conversations[ctx_key] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await interaction.response.send_message("Cleared conversation context.")


# =====================================================================
# CLIENT EVENTS
# =====================================================================


@client.event
async def on_ready():
    logger.info(f"{BOT_NAME} is online as: {client.user} (ID: {client.user.id})")
    logger.info(f"Bot Owner ID: {BOT_OWNER_ID}")
    logger.info(f"Inference Backend: {API_BASE_URL} (Model: {MODEL_NAME})")
    logger.info("SQLite Datastore and Markdown dossier active.")

    try:
        synced = await tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s) with Discord.")
    except discord.DiscordException as e:
        logger.warning(f"Error syncing slash commands: {e}")

    await client.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="your messages"),
        status=discord.Status.online,
    )


def normalize_discord_mentions(text: str, message: discord.Message) -> str:
    if not text:
        return ""
    if client.user:
        text = re.sub(rf"<@!?{client.user.id}>", f"@{BOT_NAME}", text)
    if message.guild:
        for user in message.mentions:
            uid_str = str(user.id)
            disp = user.display_name or user.name
            text = re.sub(rf"<@!?{uid_str}>", f"@{disp}", text)
    return text.strip()


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    # Ignore other bots to prevent infinite response loops
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_allowed = (
        not ALLOWED_IDS
        or message.channel.id in ALLOWED_IDS
        or getattr(message.guild, "id", None) in ALLOWED_IDS
    )

    is_reply_to_bot = False
    reply_context = ""
    resolved_msg = None
    if message.reference:
        resolved_msg = message.reference.resolved
        if not resolved_msg and message.reference.message_id:
            try:
                resolved_msg = await message.channel.fetch_message(message.reference.message_id)
            except discord.DiscordException:
                resolved_msg = None

        if isinstance(resolved_msg, discord.Message):
            if resolved_msg.author == client.user:
                is_reply_to_bot = True
            author_name = (
                BOT_NAME
                if resolved_msg.author == client.user
                else (resolved_msg.author.display_name or resolved_msg.author.name)
            )
            clean_ref = resolved_msg.clean_content.strip()
            if clean_ref:
                reply_context = f'[Replying to {author_name}: "{clean_ref[:200]}"]'

    raw_content = message.content.strip()
    user_id = message.author.id
    user_name = message.author.display_name or message.author.name
    is_owner = user_id == BOT_OWNER_ID

    is_mentioned = bool(client.user and client.user in message.mentions)
    name_in_content = bool(re.search(rf"\b{re.escape(BOT_NAME)}\b", raw_content, re.IGNORECASE))

    # Respond in DMs, on mentions, when replied to, or when called by name
    should_respond = is_dm or is_reply_to_bot or is_mentioned or name_in_content
    if not should_respond or not is_allowed:
        return

    context_key = f"dm_{message.author.id}" if is_dm else f"channel_{message.channel.id}"
    track_conversation_session(context_key)

    normalized_content = normalize_discord_mentions(raw_content, message)
    clean_content = re.sub(
        rf"@{re.escape(BOT_NAME)}\b", "", normalized_content, flags=re.IGNORECASE
    ).strip()

    if not clean_content and not message.attachments:
        return

    # Backwards-compatible legacy prefix commands
    clean_lower = clean_content.lower()
    if clean_lower in ["!reset", "!clear"]:
        if BOT_OWNER_ID and not is_owner:
            return
        conversations[context_key] = [{"role": "system", "content": SYSTEM_PROMPT}]
        await message.channel.send("Cleared conversation context.")
        return

    if clean_lower in ["!facts", "!whoami"]:
        if BOT_OWNER_ID and not is_owner:
            return
        async with memory_lock:
            card = user_manager.get_user_display_card(user_id, user_name)
        await message.channel.send(card)
        return

    # Process media attachments (images and video keyframes)
    image_blocks = []
    media_summary = ""
    if message.attachments:
        image_blocks, media_summary = await process_discord_attachments(message.attachments)
        if image_blocks:
            logger.info(
                f"Processed {len(image_blocks)} visual block(s) from {len(message.attachments)} attachment(s)."
            )

    role_label = "Bot Owner" if is_owner else "Server Member"
    async with memory_lock:
        user_memory = user_manager.get_summary_prompt(user_id, user_name)

    text_parts = []
    if reply_context:
        text_parts.append(reply_context)
    if user_memory:
        text_parts.append(user_memory)
    if media_summary:
        text_parts.append(media_summary)
    text_parts.append(
        f"[{user_name} ({role_label})]: {clean_content if clean_content else '(sent media)'}"
    )
    full_user_text = "\n".join(text_parts)

    formatted_content: str | list[dict] = (
        [{"type": "text", "text": full_user_text}] + image_blocks
        if image_blocks
        else full_user_text
    )

    if not conversations.get(context_key):
        conversations[context_key] = [{"role": "system", "content": SYSTEM_PROMPT}]
    elif conversations[context_key][0].get("role") != "system":
        conversations[context_key].insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    else:
        conversations[context_key][0]["content"] = SYSTEM_PROMPT

    history = conversations[context_key]
    history.append({"role": "user", "content": formatted_content})

    if len(history) > (MAX_HISTORY_TURNS + 1):
        history = [history[0]] + history[-MAX_HISTORY_TURNS:]
        conversations[context_key] = history

    async with message.channel.typing():
        try:
            raw_response = await query_llm(history)

            search_query = extract_search_query(raw_response, fallback_query=clean_content)
            if search_query and len(search_query.strip()) >= 2:
                logger.info(f"Searching the web for: '{search_query}'")
                search_results = await search_web(search_query, max_results=3)

                asst_context = raw_response
                if asst_context.strip() in ["...", "..", ".", ""]:
                    asst_context = f"<think>\nSearching web for '{search_query}'...\n</think>"

                search_history = list(history) + [
                    {"role": "assistant", "content": asst_context},
                    {
                        "role": "user",
                        "content": (
                            f'[Real-Time Web Search Results for "{search_query}"]:\n'
                            f"{search_results}\n\n"
                            f"[System Instruction]: Use the web search results above to accurately answer {user_name}. "
                            "Stay in character, keep the tone natural, and answer concisely."
                        ),
                    },
                ]
                raw_response = await query_llm(search_history)

            # Extract memory tags under concurrency lock
            async with memory_lock:
                new_facts, raw_cleaned = user_manager.process_autonomous_remember_tags(
                    raw_output=raw_response,
                    speaker_id=user_id,
                    speaker_name=user_name,
                )
            if new_facts:
                logger.info(f"Memory recorded for {user_name}: {new_facts}")

            thought, reply = parse_bot_response(raw_cleaned)

            # Output reasoning trace strictly to console (never in Discord chat)
            if thought:
                logger.info(f"\n[{BOT_NAME} Internal Reasoning for {user_name}]:\n{thought}\n")
            logger.info(f"[{BOT_NAME} to {user_name}]: {reply}")

            history.append(
                {
                    "role": "assistant",
                    "content": f"<think>\n{thought}\n</think>\n{reply}" if thought else reply,
                }
            )

            discord_output = reply if reply else "..."

            if not is_dm:
                if len(discord_output) <= 2000:
                    await message.reply(discord_output, mention_author=False)
                else:
                    for i in range(0, len(discord_output), 1950):
                        await message.channel.send(discord_output[i : i + 1950])
            else:
                if len(discord_output) <= 2000:
                    await message.channel.send(discord_output)
                else:
                    for i in range(0, len(discord_output), 1950):
                        await message.channel.send(discord_output[i : i + 1950])

        except httpx.ConnectError:
            logger.error("Could not connect to LLM backend.")
            err_msg = f"Cannot reach the AI backend at `{API_BASE_URL}`. Make sure your local server is running or your API endpoint is reachable."
            await (
                message.channel.send(err_msg)
                if is_dm
                else message.reply(err_msg, mention_author=False)
            )
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.error(f"Inference HTTP error: {e}")
            err_msg = f"Request timed out or returned an error: `{e}`"
            await (
                message.channel.send(err_msg)
                if is_dm
                else message.reply(err_msg, mention_author=False)
            )
        except discord.DiscordException as e:
            logger.error(f"Discord API error: {e}")


if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_discord_bot_token_here":
        print("\n[!] Please set your DISCORD_BOT_TOKEN in .env before running.")
        sys.exit(1)

    print("========================================")
    print(f"       Starting {BOT_NAME} AI Bot        ")
    print("========================================")
    print(f"Bot Name: {BOT_NAME}")
    print(f"Owner ID: {BOT_OWNER_ID or '(not set)'}")
    print(f"API Backend: {API_BASE_URL}")
    print(f"Model: {MODEL_NAME}")
    print(f"Prompt File: {PROMPT_FILE.name}")
    print("Commands: /facts, /reset (Owner restricted)")
    print("Press Ctrl+C to stop.\n")

    client.run(DISCORD_TOKEN)
