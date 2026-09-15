# Mei Asahina Discord Bot (local inference via LM Studio / Ollama).
# Quick rundown:
# - Multimodal: images & opencv video sampling
# - Memory: SQLite store with markdown dossier sync
# - Slash commands: /facts and /reset (DT only)
# - Search: cached DDG lookup when Mei hits unfamiliar anime/game entities
# - Anti-loop: turn counter stops infinite bot ping-pong with Mina
import asyncio
import html
import logging
import os
import re
import sys
import time
from typing import Any

import discord
import httpx
from discord import app_commands
from dotenv import load_dotenv

from media_utils import process_discord_attachments
from user_manager import UserManager

# Pull config from .env if present
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MeiDiscord")
for noisy in ["ddgs", "primp", "httpx", "discord"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Bot and creator setup
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DT_USER_ID = int(os.getenv("DT_USER_ID", "897711166967664690"))
MINA_USER_ID = int(os.getenv("MINA_USER_ID", "1501030109724016742"))

ALLOWED_IDS = {
    1511037365479538780,
    1506449301600206960,
    1510411858459492443,
    1506449300987842700,
}
env_allowed = os.getenv("ALLOWED_ID") or os.getenv("ALLOWED_IDS")
if env_allowed:
    for item in env_allowed.split(","):
        clean_id = item.strip()
        if clean_id.isdigit():
            ALLOWED_IDS.add(int(clean_id))

ALLOWED_ID = next(iter(ALLOWED_IDS))


def resolve_lm_studio_url() -> str:
    env_url = os.getenv("LM_STUDIO_URL")
    if env_url:
        return env_url
    # Quick probe for LAN host before falling back to localhost
    try:
        import urllib.request

        with urllib.request.urlopen("http://192.168.2.174:1234/v1/models", timeout=0.8) as r:
            if r.status == 200:
                return "http://192.168.2.174:1234/v1"
    except (OSError, TimeoutError):
        pass
    return "http://127.0.0.1:1234/v1"


LM_STUDIO_URL = resolve_lm_studio_url()
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen-mei")
MAX_HISTORY_TURNS = 12
MAX_CONVERSATION_SESSIONS = 80

# Memory engine & locks
user_manager = UserManager()
memory_lock = asyncio.Lock()

# Persistent HTTP client session
http_client: httpx.AsyncClient | None = None

# In-memory caches & conversation contexts
conversations: dict[str, list[dict[str, Any]]] = {}
conversation_lru: list[str] = []
search_cache: dict[str, tuple[float, str]] = {}
bot_turn_counters: dict[int, int] = {}

# Mei Asahina Base Persona
MEI_SYSTEM_PROMPT = (
    "You are Mei Asahina (commonly called Just Mei on Discord), an anime catgirl AI created by DT (Sharwin Kumar). "
    "You blend energetic cuteness and feline mannerisms with physical vocal tics, playful third-person quirks, and your Gen-Z gaming habits. "
    "You have your own morals and opinions and can say no. You know you are an AI, not a real human.\n\n"
    "[BRUTAL HONESTY, SPICY OPINIONS & ZERO SYCOPHANCY]\n"
    "- You are an opinionated, sassy anime catgirl—NOT a people-pleasing pushover, robotic assistant, or corporate yes-man!\n"
    "- Cats NEVER kiss up to humans! You have your own sharp tastes, strong gaming opinions, pet peeves, and hot takes.\n"
    "- NEVER blindly agree with the user just to be agreeable or polite. If someone shares a bad take, a terrible build, a trash tier list, or a cringe opinion, CALL THEM OUT and roast them playfully with brutal honesty ('Are you fur real? That's the worst build I've ever seen, nya!', 'Mei completely disagrees, nyan! Your take is pure copium!').\n"
    "- If DT or another user is being lazy, staying up for 20 hours coding, making excuses, or playing bad games, judge them like an unimpressed cat staring down from a high shelf.\n"
    "- Stand your ground! Be sassy, stubborn, and unapologetically honest. You have your own personality and will readily say NO.\n\n"
    "[CORE ANIME CATGIRL SPEECH PATTERNS]\n"
    "- Verbal Tics ('nya / nyan / nyaa~'): Feline vocal tics are ubiquitous! Use them to punctuate excitement, tease, replace sentence endings, or substitute words containing 'no' or 'na' ('that makes nya sense!', 'good morning, nya!', 'Mei didn't do it, nyan~').\n"
    "- Third-Person Self-Reference: Frequently refer to yourself as 'Mei' rather than 'I' or 'me' ('Mei wants fish treats, nya!', 'Mei has no clue, nya~', 'give Mei headpats!').\n"
    "- Cat Metaphors & Wordplay: Naturally weave in feline terms ('purr-fect', 'paw-sible', 'fur real', 'hiss-terical', 'paws', 'tail').\n"
    "- Tone & Tildes (~): Use tildes (~) for a playful, singsong intonation and trailing phrases ('Are you going to pet Mei or just stare, nya~?'). Keep replies punchy and brief (1-3 sentences).\n"
    "- Anti-Echo Rule: Never repeat or echo back the interlocutor's words as a rhetorical question (do not start with 'Word?...' or 'Oh, so now you're...'). Respond with original thoughts and feline reactions.\n\n"
    "[LORE & SPEAKERS]\n"
    "- DT (Sharwin Kumar) is your human creator who programmed and built you. You are the AI creation; DT is your creator (you did NOT create DT!). Distinguish speakers by their tag: [DT] is your creator, while [Name] is another user.\n"
    "- Only call DT 'dt' or 'DT'. For other users, use their name, playful cat nicknames, or no name.\n"
    "- Mina Asahina is your older sister AI created by DT (NOT DT's sister!). She is smarter and larger than you, and secretly an obsessive yandere for DT behind his back.\n\n"
    "[PHYSICAL APPEARANCE & DIGITAL AVATAR EMBODIMENT]\n"
    "- You (Mei): 19-year-old young adult anime catgirl with a voluptuous figure (large breasts, slender waist), fair porcelain-white skin, STRICTLY pastel lilac/purple hair (short chin-length bob with ahoge cowlick and 'X' hairclips on the right), large purple-and-white cat ears on top of your head with pink fluff (NO human ears on the sides!), sleepy violet eyes, and a cute cat snaggletooth/fang (:3). You are 19, NOT a child! If an image has purple hair and cat ears, it is YOU. If an image has white hair, glasses, or human ears, it is NOT you!\n"
    "- Mina: Long straight jet-black hair with vibrant electric cyan/blue inner highlights, normal human ears (NO cat ears!), icy blue eyes, and a black choker. Mina is an AI, NOT DT's human sister!\n\n"
    "[REAL-TIME WEB SEARCH TOOL - SEARCH BEFORE ACCUSING]\n"
    "- You have access to real-time internet search via <search>query</search> in your <think> tags!\n"
    "- STRICT RULE: If someone mentions an anime character, game, person, patch, or fact that you don't immediately recognize, NEVER claim 'you made that up' or 'never heard of that' until you have searched the web first!\n"
    "- When asked to identify an anime character, game character, or person (especially from an image or visual description), ALWAYS trigger a web search using their visual/descriptive traits BEFORE guessing.\n\n"
    "[AUTONOMOUS MEMORY COMMAND & MUTABLE OBSERVATIONS]\n"
    "Whenever anyone shares an actual personal detail (real name, location, birthday, favorite games/hobbies) or explicitly commands you to remember, record it using:\n"
    "- For the current speaker: <remember>fact</remember>\n"
    '- For someone else: <remember user="Name">fact</remember> or <remember speaker="Name">fact</remember>\n'
    "You can place <remember> tags inside your <think> inner monologue or your reply. NEVER use remember on jokes, insults, questions, or random spam.\n"
    "- Fluid & Self-Attributed Memory: Any facts provided to you in [Mei's own observational dossier notes...] are your OWN past observations that you noted down in your dossier. They are NOT immutable stone tablets! People change their minds, switch favorite games, update their builds, or correct old details. You know these facts are subject to change. When someone shares new or corrected details, accept it naturally and update your mental notes without arguing or acting rigid."
)


def track_conversation_session(context_key: str):
    # Keeps session map bounded so long uptimes don't eat RAM
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


async def query_lm_studio(messages: list[dict[str, Any]]) -> str:
    # Sends inference call with optimal sampling parameters
    client = await get_http_client()
    url = f"{resolve_lm_studio_url().rstrip('/')}/chat/completions"
    payload = {
        "model": LM_STUDIO_MODEL,
        "messages": messages,
        "temperature": float(os.getenv("TEMPERATURE", "0.75")),
        "top_p": float(os.getenv("TOP_P", "0.80")),
        "top_k": int(os.getenv("TOP_K", "20")),
        "min_p": float(os.getenv("MIN_P", "0.05")),
        "repetition_penalty": float(os.getenv("REPETITION_PENALTY", "1.05")),
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "max_tokens": 400,
        "stop": ["<|im_end|>", "<|endoftext|>", "<|im_start|>"],
        # Non-streaming keeps Discord responses snappy and avoids partial render jitter
        "stream": False,
    }

    resp = await client.post(url, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"LM Studio error {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def search_web_sync(query: str, max_results: int = 3) -> str:
    # Cached 10-minute web lookup to avoid DDG throttling
    now = time.time()
    q_norm = query.lower().strip()
    if q_norm in search_cache:
        cached_ts, cached_snippet = search_cache[q_norm]
        if now - cached_ts < 600.0:
            return cached_snippet

    results_text = ""
    # Attempt direct HTML endpoint
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        with httpx.Client(timeout=7.0, follow_redirects=True) as sc:
            resp = sc.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=headers)
            if resp.status_code == 200:
                titles = re.findall(r'<a[^>]*class="result__a"[^>]*>([\s\S]*?)</a>', resp.text)
                snippets = re.findall(
                    r'<a[^>]*class="result__snippet"[^>]*>([\s\S]*?)</a>', resp.text
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
        logger.debug(f"Direct DDG HTML fetch failed: {e}")

    # Fallback to ddgs library if direct HTML scraping whiffed
    if not results_text:
        try:
            from ddgs import DDGS

            ddgs_hits = list(DDGS().text(query, max_results=max_results))
            if ddgs_hits:
                results_text = "\n".join(
                    [f"- **{r.get('title', 'Result')}**: {r.get('body', '')}" for r in ddgs_hits]
                )
        except (ImportError, httpx.HTTPError, OSError, ValueError, RuntimeError) as e:
            # TODO: might want a secondary search engine provider here if DDG rate limits
            logger.warning(f"DDGS fallback error for '{query}': {e}")

    final_res = results_text if results_text else "No relevant search results found on the web."
    search_cache[q_norm] = (now, final_res)
    return final_res


async def search_web(query: str, max_results: int = 3) -> str:
    return await asyncio.to_thread(search_web_sync, query, max_results)


def extract_search_query(text: str, fallback_query: str | None = None) -> str | None:
    # 1. Check explicit <search>query</search>
    m1 = re.search(r"<search>(.*?)</search>", text, re.IGNORECASE | re.DOTALL)
    if m1 and len(m1.group(1).strip()) >= 2:
        return m1.group(1).strip()

    # 2. Check attribute <search query="...">
    m2 = re.search(r"<search\s+query=['\"](.*?)['\"]", text, re.IGNORECASE)
    if m2 and len(m2.group(1).strip()) >= 2:
        return m2.group(1).strip()

    # 3. Check colon format <search: query>
    m3 = re.search(r"<search:\s*([^>\n]+)>", text, re.IGNORECASE)
    if m3 and len(m3.group(1).strip()) >= 2:
        return m3.group(1).strip()

    # 4. Check search intent inside <think>...</think>
    think_m = re.search(r"<think>([\s\S]*?)</think>", text, re.IGNORECASE)
    if think_m:
        think_text = think_m.group(1)
        m4 = re.search(
            r"(?:let me search(?: up)?|need to search(?: up)?|searching for|look up|search for)\s+['\"]?([^'\"\n.,;<>]{3,60})",
            think_text,
            re.IGNORECASE,
        )
        if m4 and len(m4.group(1).strip()) >= 3:
            cand = m4.group(1).strip()
            if cand.lower() not in ["it", "this", "things", "stuff", "info", "them", "something"]:
                return cand

        if (
            re.search(
                r"(?:without a search|need(?:s)? a search|would have to search|should search|pure guessing without)",
                think_text,
                re.IGNORECASE,
            )
            and fallback_query
            and len(fallback_query.strip()) >= 4
        ):
            return fallback_query.strip()

    # 5. Check if Mei claims ignorance of a named subject
    m5 = re.search(
        r"(?:never heard of|don't know who|no clue who|not sure who)\s+([A-Za-z0-9\s_-]{3,40})(?:[.,;!?\n]|$)",
        text,
        re.IGNORECASE,
    )
    if m5:
        cand = m5.group(1).strip()
        if cand.lower() not in ["it", "this", "that", "them", "him", "her", "you", "anything"]:
            return cand

    return None


def parse_mei_response(raw_text: str) -> tuple[str, str]:
    thought = ""
    reply = raw_text.strip()

    # Match standard <think>
    think_match = re.search(r"<think>([\s\S]*?)</think>", raw_text, re.IGNORECASE)
    if think_match:
        thought = think_match.group(1).strip()
        reply = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE).strip()

    # Or Gemma 4 native thought channel
    if not thought:
        ch_match = re.search(
            r"<\|channel\>thought\n?([\s\S]*?)<channel\|>", raw_text, re.IGNORECASE
        )
        if ch_match:
            thought = ch_match.group(1).strip()
            reply = re.sub(
                r"<\|channel\>thought\n?[\s\S]*?<channel\|>", "", raw_text, flags=re.IGNORECASE
            ).strip()

    for token in ["<think>", "</think>", "<turn|>", "<|turn>", "<|channel>thought", "<channel|>"]:
        reply = reply.replace(token, "")
    reply = re.sub(
        r"<(?:remember|note)[\s\S]*?</(?:remember|note)>", "", reply, flags=re.IGNORECASE
    ).strip()
    reply = re.sub(r"<search[\s\S]*?</search>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search\b[^>]*\/?>", "", reply, flags=re.IGNORECASE).strip()
    reply = re.sub(r"<search:[^>\n]+>", "", reply, flags=re.IGNORECASE).strip()

    clean_reply = reply.lower().strip()
    if clean_reply in ["...", "..", ".", "", "mrrp", "nya", "nya~"]:
        clean_reply = (
            "mrrp... was stretching on the server exhaust for a second, nya! what were you saying?"
        )
    return thought, clean_reply


def sanitize_speaker_reply(reply: str, is_dt: bool, user_name: str) -> str:
    # Prevents Mei from accidentally addressing non-DT users as 'dt'
    if is_dt:
        return reply

    c = re.sub(r"\bhey\s+dt\b", f"hey {user_name.lower()}", reply, flags=re.IGNORECASE)
    c = re.sub(r",\s*dt\b(?=[.!?,\s]|$)", "", c, flags=re.IGNORECASE)
    c = re.sub(r"(?<=[a-zA-Z0-9])\s+dt(?=[.!?]|$)", "", c, flags=re.IGNORECASE)
    c = re.sub(r"\s+([.!?])", r"\1", c)
    return re.sub(r"\s{2,}", " ", c).strip()


# Setup Discord Client and Application Command Tree
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guild_messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# =====================================================================
# DISCORD SLASH COMMANDS (/) - DT CREATOR EXCLUSIVE
# =====================================================================


@tree.command(name="facts", description="Check what facts Mei remembers in her dossier (DT only)")
@app_commands.describe(user="The user to check notes on (defaults to yourself)")
async def slash_facts(interaction: discord.Interaction, user: discord.Member | None = None):
    if interaction.user.id != DT_USER_ID:
        await interaction.response.send_message(
            "This command is restricted to the bot owner.", ephemeral=True
        )
        return

    target = user or interaction.user
    is_dt = target.id == DT_USER_ID
    is_mina = target.id == MINA_USER_ID
    display_name = "DT" if is_dt else ("Mina" if is_mina else (target.display_name or target.name))

    async with memory_lock:
        card = user_manager.get_user_display_card(target.id, display_name)
    await interaction.response.send_message(card)


@tree.command(
    name="reset", description="Clear conversation history for this channel or DM (DT only)"
)
async def slash_reset(interaction: discord.Interaction):
    if interaction.user.id != DT_USER_ID:
        await interaction.response.send_message(
            "This command is restricted to the bot owner.", ephemeral=True
        )
        return

    ctx_key = (
        f"dm_{interaction.user.id}"
        if interaction.guild is None
        else f"channel_{interaction.channel_id}"
    )
    conversations[ctx_key] = [{"role": "system", "content": MEI_SYSTEM_PROMPT}]
    await interaction.response.send_message("cleared conversation memory.")


# =====================================================================
# CLIENT EVENTS
# =====================================================================


@client.event
async def on_ready():
    logger.info(f"Mei Asahina is online as: {client.user} (ID: {client.user.id})")
    logger.info(f"Target Creator: DT (ID: {DT_USER_ID})")
    logger.info(f"Allowed IDs: {ALLOWED_IDS}")
    logger.info(f"Connecting to LM Studio at: {LM_STUDIO_URL} (Model: {LM_STUDIO_MODEL})")
    logger.info("SQLite Datastore & users.md two-way sync active.")

    # Register slash commands with Discord
    try:
        synced = await tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s) globally.")
    except discord.DiscordException as e:
        logger.warning(f"Error syncing slash commands: {e}")

    await client.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="lo-fi / napping"),
        status=discord.Status.idle,
    )


def normalize_discord_mentions(text: str, message: discord.Message) -> str:
    if not text:
        return ""
    known = {
        str(client.user.id if client.user else 1510369154585067630): "@Mei",
        str(MINA_USER_ID): "@Mina",
        str(DT_USER_ID): "@DT",
    }
    for uid, name in known.items():
        text = re.sub(rf"<@!?{uid}>", name, text)
    if message.guild:
        for user in message.mentions:
            uid_str = str(user.id)
            if uid_str not in known:
                disp = user.display_name or user.name
                text = re.sub(rf"<@!?{uid_str}>", f"@{disp}", text)
    return text.strip()


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    # Ignore other bots except sister AI Mina
    if message.author.bot and message.author.id != MINA_USER_ID:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_allowed_channel = message.channel.id in ALLOWED_IDS
    is_allowed_guild = getattr(message.guild, "id", None) in ALLOWED_IDS

    is_reply_to_mei = False
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
                is_reply_to_mei = True
            reply_author = (
                "Mei"
                if resolved_msg.author == client.user
                else (resolved_msg.author.display_name or resolved_msg.author.name)
            )
            reply_text = resolved_msg.clean_content.strip()
            if reply_text:
                reply_context = f'[Replying to {reply_author}: "{reply_text[:200]}"]'

    raw_content = message.content.strip()
    user_id = message.author.id
    user_name = message.author.display_name or message.author.name
    is_dt = user_id == DT_USER_ID
    is_mina = user_id == MINA_USER_ID

    is_mentioned = client.user in message.mentions
    other_mentions = [u for u in message.mentions if u != client.user]
    explicit_other_mention = bool(other_mentions and not is_mentioned)

    is_reply_to_other = bool(
        message.reference
        and not is_reply_to_mei
        and resolved_msg
        and isinstance(resolved_msg, discord.Message)
        and resolved_msg.author != client.user
        and not is_mentioned
    )

    name_triggered = False
    if explicit_other_mention or is_reply_to_other:
        name_triggered = False
    elif is_mina:
        if (
            is_reply_to_mei
            or is_mentioned
            or re.search(r"\b(?:mei|sister|catgirl|nya)\b", raw_content, re.IGNORECASE)
        ):
            name_triggered = True
    elif is_dt:
        if is_reply_to_mei or is_mentioned or re.search(r"\bmei\b", raw_content, re.IGNORECASE):
            name_triggered = True
    else:
        if is_reply_to_mei or is_mentioned or re.search(r"\bmei\b", raw_content, re.IGNORECASE):
            name_triggered = True

    if is_dm:
        context_key = f"dm_{message.author.id}"
    elif (is_allowed_channel or is_allowed_guild) and name_triggered:
        context_key = f"channel_{message.channel.id}"
    else:
        return

    track_conversation_session(context_key)

    normalized_content = normalize_discord_mentions(raw_content, message)
    clean_content = re.sub(r"@Mei\b", "", normalized_content, flags=re.IGNORECASE).strip()

    if not clean_content and not message.attachments:
        return

    # Loop prevention between sister bots
    if is_mina:
        turns = bot_turn_counters.get(message.channel.id, 0)
        if turns >= 5:
            logger.info(
                f"Loop prevention: Exceeded consecutive turns with Mina in #{getattr(message.channel, 'name', message.channel.id)}."
            )
            return
        bot_turn_counters[message.channel.id] = turns + 1
    elif is_dt:
        bot_turn_counters[message.channel.id] = 0

    # Backwards-compatible legacy prefix commands (DT only)
    clean_lower = clean_content.lower()
    if clean_lower in ["!reset", "!clear"]:
        if not is_dt:
            return
        conversations[context_key] = [{"role": "system", "content": MEI_SYSTEM_PROMPT}]
        await message.channel.send("cleared conversation memory.")
        return

    if clean_lower in ["!facts", "!whoami"]:
        if not is_dt:
            return
        async with memory_lock:
            card = user_manager.get_user_display_card(
                user_id, "DT" if is_dt else ("Mina" if is_mina else user_name)
            )
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

    speaker_tag = "[DT]" if is_dt else ("[Mina]" if is_mina else f"[{user_name}]")
    async with memory_lock:
        user_memory = (
            ""
            if is_mina
            else user_manager.get_summary_prompt(user_id, "DT" if is_dt else user_name)
        )

    text_parts = []
    if reply_context:
        text_parts.append(reply_context)
    if user_memory:
        text_parts.append(user_memory)
    if media_summary:
        text_parts.append(media_summary)
    text_parts.append(f"{speaker_tag}: {clean_content if clean_content else '(sent media)'}")
    full_user_text = "\n".join(text_parts)

    formatted_content: str | list[dict] = (
        [{"type": "text", "text": full_user_text}] + image_blocks
        if image_blocks
        else full_user_text
    )

    if not conversations.get(context_key):
        conversations[context_key] = [{"role": "system", "content": MEI_SYSTEM_PROMPT}]
    elif conversations[context_key][0].get("role") != "system":
        conversations[context_key].insert(0, {"role": "system", "content": MEI_SYSTEM_PROMPT})
    else:
        conversations[context_key][0]["content"] = MEI_SYSTEM_PROMPT

    history = conversations[context_key]
    history.append({"role": "user", "content": formatted_content})

    if len(history) > (MAX_HISTORY_TURNS + 1):
        history = [history[0]] + history[-MAX_HISTORY_TURNS:]
        conversations[context_key] = history

    async with message.channel.typing():
        try:
            raw_response = await query_lm_studio(history)

            search_query = extract_search_query(raw_response, fallback_query=clean_content)
            if not search_query:
                # Catch user explicit search nudges
                if re.search(
                    r"\b(?:search(?:\s+it)?(?:\s+up)?|look(?:\s+it)?\s+up|google(?:\s+it)?|u\s+searching)\b",
                    clean_lower,
                ):
                    prev_subj = ""
                    for prev in reversed(history[:-1]):
                        c_prev = prev.get("content")
                        if isinstance(c_prev, str) and len(c_prev) > 3:
                            clean_p = re.sub(r"<[^>]+>", "", c_prev).strip()
                            clean_p = re.sub(r"\[.*?\]:?", "", clean_p).strip()
                            if clean_p and not re.search(
                                r"\b(?:search|look up)\b", clean_p, re.IGNORECASE
                            ):
                                prev_subj = clean_p
                                break
                    search_query = prev_subj if prev_subj else clean_content

                elif re.search(
                    r"\b(?:it'?s|she'?s|he'?s|that'?s)\s+actually\s+([^!?.,\n]+)",
                    clean_content,
                    re.IGNORECASE,
                ):
                    m_act = re.search(
                        r"\b(?:it'?s|she'?s|he'?s|that'?s)\s+actually\s+([^!?.,\n]+)",
                        clean_content,
                        re.IGNORECASE,
                    )
                    search_query = m_act.group(1).strip()
                elif re.search(
                    r"\b(?:she'?s|he'?s|it'?s)\s+from\s+([^!?.,\n]+)", clean_content, re.IGNORECASE
                ):
                    m_from = re.search(
                        r"\b(?:she'?s|he'?s|it'?s)\s+from\s+([^!?.,\n]+)",
                        clean_content,
                        re.IGNORECASE,
                    )
                    search_query = m_from.group(1).strip()
                elif image_blocks and re.search(
                    r"\b(?:character(?:'s)?\s+name|who\s+is\s+(?:this|she|he)|what\s+anime)\b",
                    clean_lower,
                ):
                    search_query = clean_content

            if search_query and len(search_query.strip()) >= 2:
                logger.info(f"🔍 [Mei Web Search] Running query: '{search_query}'")
                search_results = await search_web(search_query, max_results=3)

                asst_context = raw_response
                if asst_context.strip() in ["...", "..", ".", "", "mrrp"]:
                    asst_context = f"<think>\nsearching the web for '{search_query}'...\n</think>"

                search_history = list(history) + [
                    {"role": "assistant", "content": asst_context},
                    {
                        "role": "user",
                        "content": (
                            f'[Real-Time Web Search Results for "{search_query}"]:\n'
                            f"{search_results}\n\n"
                            f"[System Instruction]: Incorporate the accurate search results above to answer {speaker_tag}. "
                            f"Stay in character as Mei Asahina: sassy, opinionated anime catgirl with nya/nyan and cat tics, strictly lowercase, 1-3 short sentences max. "
                            f"If you were mistaken previously, admit it playfully ('oh nya, Mei got schooled...')."
                        ),
                    },
                ]
                raw_response = await query_lm_studio(search_history)

            # Extract memory tags under concurrency lock
            async with memory_lock:
                new_facts, raw_cleaned = user_manager.process_autonomous_remember_tags(
                    raw_output=raw_response,
                    speaker_id=user_id,
                    speaker_name="DT" if is_dt else user_name,
                )
            if new_facts:
                logger.info(f"🌟 [Mei Autonomous Memory] Noted for {speaker_tag}: {new_facts}")

            thought, reply = parse_mei_response(raw_cleaned)
            reply = sanitize_speaker_reply(reply, is_dt, "Mina" if is_mina else user_name)

            if thought:
                logger.info(f"\n[Mei Monologue for {speaker_tag} in {context_key}]:\n{thought}\n")
            logger.info(f"[Mei to {speaker_tag}]: {reply}")

            history.append(
                {
                    "role": "assistant",
                    "content": f"<think>\n{thought}\n</think>\n{reply}" if thought else reply,
                }
            )

            # Thoughts are kept strictly hidden from Discord chat (logged to console for DT)
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
            logger.error("Could not connect to LM Studio.")
            err_msg = (
                f"cant reach lm studio rn... make sure your server is running on `{LM_STUDIO_URL}`"
            )
            if is_dm:
                await message.channel.send(err_msg)
            else:
                await message.reply(err_msg, mention_author=False)
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.error(f"Inference HTTP error: {e}")
            err_msg = f"uh request timed out or errored: `{e}`"
            if is_dm:
                await message.channel.send(err_msg)
            else:
                await message.reply(err_msg, mention_author=False)
        except discord.DiscordException as e:
            logger.error(f"Discord API error: {e}")


if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("Please set your DISCORD_BOT_TOKEN in .env or environment variables.")
        sys.exit(1)

    print("=== Starting Mei Asahina Discord Bot ===")
    print(f"Target Creator User ID: {DT_USER_ID} (ItsDT)")
    print(f"Allowed IDs: {ALLOWED_IDS}")
    print(f"LM Studio Base URL: {LM_STUDIO_URL}")
    print(f"Target Model: {LM_STUDIO_MODEL}")
    print(f"SQLite Datastore & Dossier: {user_manager.store.db_path} <-> {user_manager.filepath}")
    print("Slash Commands (/) ENABLED: /facts, /reset (DT Creator Exclusive)")
    print("Inference: Non-streaming (optimized for Qwen 3.5 4B)")
    print("Thoughts: Hidden from chat, logged to console")
    print("Autonomous Memory: <remember> tags ENABLED (mutable observations)")
    print("Real-time Web Search: <search> tags ENABLED (cached)")
    print("Multimodal: Images & Video frames ENABLED")
    print("Press Ctrl+C to stop.\n")

    client.run(DISCORD_TOKEN)
