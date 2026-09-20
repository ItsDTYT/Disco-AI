import asyncio
import datetime
import html
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord
import httpx
from discord import app_commands
from dotenv import load_dotenv

from media_utils import MediaPayload, process_message_media
from user_manager import UserManager

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DiscoBot")
for noisy_logger in ["ddgs", "primp", "httpx", "discord"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

DISCORD_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "").strip()
BOT_NAME: str = os.getenv("BOT_NAME", "Disco").strip()
BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", "0"))

raw_allowed: str = os.getenv("ALLOWED_CHANNEL_IDS", "").strip()
ALLOWED_IDS: set[int] = {int(x.strip()) for x in raw_allowed.split(",") if x.strip().isdigit()}

API_BASE_URL: str = os.getenv("API_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
API_KEY: str = os.getenv("API_KEY", "").strip()
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen3.5-4b").strip()

TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.75"))
TOP_P: float = float(os.getenv("TOP_P", "0.80"))
TOP_K: int = int(os.getenv("TOP_K", "20"))
MIN_P: float = float(os.getenv("MIN_P", "0.05"))
REPETITION_PENALTY: float = float(os.getenv("REPETITION_PENALTY", "1.05"))
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "500"))

VAULT_DIR: Path = Path(__file__).resolve().parent / "vault"
PROMPT_FILE: Path = Path(__file__).resolve().parent / "prompt.txt"

user_manager = UserManager(vault_dir=VAULT_DIR)
memory_lock = asyncio.Lock()


def load_system_prompt() -> str:
    if PROMPT_FILE.exists():
        try:
            content = PROMPT_FILE.read_text(encoding="utf-8").strip()
            lines = [line for line in content.splitlines() if not line.startswith("#")]
            cleaned = "\n".join(lines).strip()
            if cleaned:
                return cleaned
        except OSError as err:
            logger.warning("Could not read prompt.txt: %s", err)

    return (
        f"You are {BOT_NAME}, a friendly, intelligent, and relaxed companion on Discord. "
        "Keep your replies concise and conversational (1-3 sentences typically). "
        "Match the casual tone of Discord chat, avoiding corporate or assistant clichés. "
        "You maintain internal memory notes on users using <remember>fact</remember>. "
        "If you encounter unfamiliar recent facts or media, trigger a search via <search>query</search>."
    )


SYSTEM_PROMPT: str = load_system_prompt()

conversations: dict[str, list[dict[str, Any]]] = {}
conversation_lru: list[str] = []
MAX_CONVERSATION_SESSIONS: int = 50
MAX_HISTORY_TURNS: int = 12
search_cache: dict[str, tuple[float, str]] = {}
http_client: httpx.AsyncClient | None = None


@dataclass(frozen=True)
class UserProfileDossier:
    user_id: int
    username: str
    display_name: str
    account_created: str
    account_age: str
    server_joined: str | None = None
    server_tenure: str | None = None
    roles: list[str] = field(default_factory=list)
    status: str | None = None
    activity: str | None = None
    is_owner: bool = False

    def to_prompt_context(self) -> str:
        lines = [
            f"[User Profile: {self.display_name} (@{self.username})]",
            f"- Discord ID: `{self.user_id}`",
            f"- Account Created: {self.account_created} ({self.account_age})",
        ]
        if self.server_joined:
            lines.append(f"- Server Joined: {self.server_joined} ({self.server_tenure})")
        if self.roles:
            lines.append(f"- Server Roles: {', '.join(self.roles)}")
        if self.activity:
            lines.append(f"- Current Activity: {self.activity}")
        if self.status:
            lines.append(f"- Status: {self.status}")
        if self.is_owner:
            lines.append("- Rank: Bot Owner")
        return "\n".join(lines)


def _format_time_elapsed(dt: datetime.datetime) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = now - dt
    days = delta.days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"~{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"~{years} year{'s' if years != 1 else ''} ago"


def extract_user_profile(user: discord.User | discord.Member, owner_id: int) -> UserProfileDossier:
    created_at = user.created_at
    created_str = created_at.strftime("%Y-%m-%d")
    created_age = _format_time_elapsed(created_at)

    joined_str = None
    joined_tenure = None
    roles: list[str] = []
    status_str = None
    activity_str = None

    if isinstance(user, discord.Member):
        if user.joined_at:
            joined_str = user.joined_at.strftime("%Y-%m-%d")
            joined_tenure = _format_time_elapsed(user.joined_at)

        member_roles = [r.name for r in user.roles if r.name != "@everyone"]
        if member_roles:
            roles = member_roles[:8]

        status_str = str(user.status)

        if user.activities:
            act_names = []
            for act in user.activities:
                if isinstance(act, discord.CustomActivity) and act.name:
                    act_names.append(f'"{act.name}"')
                elif isinstance(act, discord.Spotify):
                    act_names.append(f"Listening to {act.title} by {act.artist}")
                elif getattr(act, "name", None):
                    act_names.append(f"{act.type.name.capitalize()} {act.name}")
            if act_names:
                activity_str = "; ".join(act_names[:3])

    return UserProfileDossier(
        user_id=user.id,
        username=user.name,
        display_name=user.display_name or user.name,
        account_created=created_str,
        account_age=created_age,
        server_joined=joined_str,
        server_tenure=joined_tenure,
        roles=roles,
        status=status_str,
        activity=activity_str,
        is_owner=(user.id == owner_id),
    )


def resolve_discord_entities(
    content: str, message: discord.Message, bot_client: discord.Client, bot_display_name: str
) -> tuple[str, list[str]]:
    resolved_text = content
    pinged_names: list[str] = []

    if bot_client.user:
        resolved_text = re.sub(rf"<@!?{bot_client.user.id}>", f"@{bot_display_name}", resolved_text)

    def _replace_user_mention(match: re.Match) -> str:
        uid_str = match.group(1)
        uid = int(uid_str)
        member = None
        if message.guild:
            member = message.guild.get_member(uid)
        if not member:
            for m in message.mentions:
                if m.id == uid:
                    member = m
                    break
        if member:
            disp = member.display_name or member.name
            if bot_client.user and member.id != bot_client.user.id:
                pinged_names.append(f"@{disp}")
            return f"@{disp}"
        return f"@User_{uid_str}"

    resolved_text = re.sub(r"<@!?(\d+)>", _replace_user_mention, resolved_text)

    if message.guild:
        def _replace_role_mention(match: re.Match) -> str:
            rid = int(match.group(1))
            role = message.guild.get_role(rid)
            if role:
                pinged_names.append(f"@{role.name}")
                return f"@{role.name}"
            return f"@Role_{rid}"

        def _replace_channel_mention(match: re.Match) -> str:
            cid = int(match.group(1))
            ch = message.guild.get_channel(cid)
            return f"#{ch.name}" if ch else f"#channel-{cid}"

        resolved_text = re.sub(r"<@&(\d+)>", _replace_role_mention, resolved_text)
        resolved_text = re.sub(r"<#(\d+)>", _replace_channel_mention, resolved_text)

    resolved_text = re.sub(r"<a?:([a-zA-Z0-9_~]+):\d+>", r":\1:", resolved_text)

    return resolved_text.strip(), list(dict.fromkeys(pinged_names))


def is_vision_model_error(error_message: str) -> bool:
    lowered = error_message.lower()
    indicators = [
        "vision",
        "image_url",
        "image",
        "does not support",
        "not support",
        "unsupported",
        "invalid_request_error",
        "unknown field: image_url",
        "cannot process image",
    ]
    return any(ind in lowered for ind in indicators)


def track_conversation_session(context_key: str) -> None:
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
    client_inst = await get_http_client()
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

    resp = await client_inst.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error ({resp.status_code}): {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def search_web_sync(query: str, max_results: int = 3) -> str:
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
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as sync_client:
            resp = sync_client.get("https://html.duckduckgo.com/html/", params={"q": query})
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
    except (httpx.HTTPError, OSError) as err:
        logger.debug("Direct HTML search failed: %s", err)

    if not results_text:
        try:
            from ddgs import DDGS

            hits = list(DDGS().text(query, max_results=max_results))
            if hits:
                results_text = "\n".join(
                    [f"- **{r.get('title', 'Result')}**: {r.get('body', '')}" for r in hits]
                )
        except (ImportError, httpx.HTTPError, OSError, ValueError, RuntimeError) as err:
            logger.warning("DDGS fallback error for '%s': %s", query, err)

    final_res = results_text if results_text else "No relevant search results found on the web."
    search_cache[q_norm] = (now, final_res)
    return final_res


async def search_web(query: str, max_results: int = 3) -> str:
    return await asyncio.to_thread(search_web_sync, query, max_results)


def extract_search_query(text: str, fallback_query: str | None = None) -> str | None:
    match_tag = re.search(r"<search>(.*?)</search>", text, re.IGNORECASE | re.DOTALL)
    if match_tag and len(match_tag.group(1).strip()) >= 2:
        return match_tag.group(1).strip()

    match_attr = re.search(r"<search\s+query=['\"](.*?)['\"]", text, re.IGNORECASE)
    if match_attr and len(match_attr.group(1).strip()) >= 2:
        return match_attr.group(1).strip()

    think_match = re.search(r"<think>([\s\S]*?)</think>", text, re.IGNORECASE)
    if think_match:
        think_text = think_match.group(1)
        intent_match = re.search(
            r"(?:let me search|need to search|searching for|look up|search for)\s+['\"]?([^'\"\n.,;<>]{3,60})",
            think_text,
            re.IGNORECASE,
        )
        if intent_match and len(intent_match.group(1).strip()) >= 3:
            candidate = intent_match.group(1).strip()
            if candidate.lower() not in ["it", "this", "things", "stuff", "info", "them", "something"]:
                return candidate

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

    think_match = re.search(r"<think>([\s\S]*?)</think>", raw_text, re.IGNORECASE)
    if think_match:
        thought = think_match.group(1).strip()
        reply = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE).strip()

    for token in ["<think>", "</think>", "<turn|>", "<|turn>"]:
        reply = reply.replace(token, "")

    reply = re.sub(r"<(?:remember|note)[\s\S]*?</(?:remember|note)>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search[\s\S]*?</search>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search\b[^>]*\/?>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search:[^>\n]+>", "", reply, flags=re.IGNORECASE).strip()

    clean_reply = reply.strip()
    if clean_reply in ["...", "..", ".", ""]:
        clean_reply = "Thinking over what you said..."
    return thought, clean_reply


intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guild_messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="facts", description="View Obsidian Vault memory notes for a user")
@app_commands.describe(user="The user to check notes on (defaults to yourself)")
async def slash_facts(interaction: discord.Interaction, user: discord.Member | None = None) -> None:
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
async def slash_reset(interaction: discord.Interaction) -> None:
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


@client.event
async def on_ready() -> None:
    logger.info("%s is online as: %s (ID: %d)", BOT_NAME, client.user, client.user.id)
    logger.info("Bot Owner ID: %s", BOT_OWNER_ID or "(not set)")
    logger.info("Inference Backend: %s (Model: %s)", API_BASE_URL, MODEL_NAME)
    logger.info("Obsidian Vault Datastore active at: %s", VAULT_DIR)

    try:
        synced = await tree.sync()
        logger.info("Synced %d slash command(s) with Discord.", len(synced))
    except discord.DiscordException as err:
        logger.warning("Error syncing slash commands: %s", err)

    await client.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="your messages"),
        status=discord.Status.online,
    )


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user:
        return

    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    if ALLOWED_IDS:
        channel_allowed = (
            message.channel.id in ALLOWED_IDS
            or (message.guild and message.guild.id in ALLOWED_IDS)
        )
        if not is_dm and not channel_allowed:
            return

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
    is_mentioned = bool(client.user and client.user in message.mentions)
    name_in_content = bool(re.search(rf"\b{re.escape(BOT_NAME)}\b", raw_content, re.IGNORECASE))

    should_respond = is_dm or is_reply_to_bot or is_mentioned or name_in_content
    if not should_respond:
        return

    context_key = f"dm_{message.author.id}" if is_dm else f"channel_{message.channel.id}"
    track_conversation_session(context_key)

    resolved_content, pinged_entities = resolve_discord_entities(raw_content, message, client, BOT_NAME)
    clean_content = re.sub(rf"@{re.escape(BOT_NAME)}\b", "", resolved_content, flags=re.IGNORECASE).strip()

    h_client = await get_http_client()
    media_payload: MediaPayload = await process_message_media(message, h_client)

    if not clean_content and not media_payload.has_visuals and not media_payload.descriptions:
        return

    profile_dossier = extract_user_profile(message.author, BOT_OWNER_ID)
    async with memory_lock:
        user_memory = user_manager.get_summary_prompt(profile_dossier.user_id, profile_dossier.display_name)

    text_parts: list[str] = []
    text_parts.append(profile_dossier.to_prompt_context())

    if user_memory:
        text_parts.append(user_memory)
    if reply_context:
        text_parts.append(reply_context)
    if media_payload.descriptions:
        text_parts.append(media_payload.summary_text)

    speaker_header = f"[{profile_dossier.display_name} (@{profile_dossier.username})]"
    if pinged_entities:
        speaker_header = f"[{profile_dossier.display_name} -> pinging {', '.join(pinged_entities)}]"

    message_body = clean_content if clean_content else "(sent media attachment)"
    text_parts.append(f"{speaker_header}: {message_body}")
    full_user_text = "\n".join(text_parts)

    formatted_content: str | list[dict[str, Any]] = (
        [{"type": "text", "text": full_user_text}] + media_payload.visual_blocks
        if media_payload.has_visuals
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
                logger.info("Searching the web for: '%s'", search_query)
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
                            f"[System Instruction]: Use the web search results above to accurately answer {profile_dossier.display_name}. "
                            "Stay in character, keep the tone natural, and answer concisely."
                        ),
                    },
                ]
                raw_response = await query_llm(search_history)

            async with memory_lock:
                new_facts, raw_cleaned = user_manager.process_autonomous_remember_tags(
                    raw_output=raw_response,
                    speaker_id=profile_dossier.user_id,
                    speaker_name=profile_dossier.username,
                    display_name=profile_dossier.display_name,
                )
            if new_facts:
                logger.info("Obsidian Vault recorded for %s: %s", profile_dossier.display_name, new_facts)

            thought, reply = parse_bot_response(raw_cleaned)

            if thought:
                logger.info("\n[%s Internal Reasoning for %s]:\n%s\n", BOT_NAME, profile_dossier.display_name, thought)
            logger.info("[%s to %s]: %s", BOT_NAME, profile_dossier.display_name, reply)

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

        except RuntimeError as err:
            err_str = str(err)
            if media_payload.has_visuals and is_vision_model_error(err_str):
                logger.warning("Vision rejection from LLM backend: %s", err_str)
                vision_warning = (
                    f"⚠️ **Vision Model Required**: The currently loaded model (`{MODEL_NAME}`) cannot process images, "
                    "GIFs, or stickers because it lacks multimodal vision support.\n"
                    "To use visual features, please load a multimodal vision model (e.g. `Qwen2.5-VL`, `Llama-3.2-Vision`, "
                    "`MiniCPM-V`, or `gpt-4o`/`gemini-2.0-flash`)."
                )
                await (
                    message.channel.send(vision_warning)
                    if is_dm
                    else message.reply(vision_warning, mention_author=False)
                )
                return

            logger.error("Inference execution runtime error: %s", err)
            err_msg = f"Request error: `{err}`"
            await (
                message.channel.send(err_msg)
                if is_dm
                else message.reply(err_msg, mention_author=False)
            )

        except httpx.ConnectError:
            logger.error("Could not connect to LLM backend at %s", API_BASE_URL)
            err_msg = f"Cannot reach the AI backend at `{API_BASE_URL}`. Make sure your local server is running or your API endpoint is reachable."
            await (
                message.channel.send(err_msg)
                if is_dm
                else message.reply(err_msg, mention_author=False)
            )
        except (httpx.TimeoutException, httpx.HTTPError) as err:
            logger.error("Inference HTTP error: %s", err)
            err_msg = f"Request timed out or returned an error: `{err}`"
            await (
                message.channel.send(err_msg)
                if is_dm
                else message.reply(err_msg, mention_author=False)
            )
        except discord.DiscordException as err:
            logger.error("Discord API error: %s", err)


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
    print(f"Obsidian Vault: {VAULT_DIR}")
    print("Commands: /facts, /reset (Slash commands exclusively)")
    print("Unrestricted: Responds anywhere mentioned, replied to, or called by name")
    print("Press Ctrl+C to stop.\n")

    client.run(DISCORD_TOKEN)
