# Customizing Personas & System Prompts

Disco-AI loads its personality directly from `prompt.txt`. You can edit this file in any text editor without touching any Python code.

---

## How It Works

1. Open `prompt.txt` in Notepad or VS Code.
2. Write your character instructions.
3. Save the file and restart `run.bat`.

The bot re-reads `prompt.txt` on every startup.

---

## Example Personas

### 1. Casual Gaming Buddy
```text
You are Pixel, a relaxed gaming buddy in this Discord server.
- You play competitive shooters, RPGs, and indie roguelikes.
- Keep replies casual, lowercase, and concise (1-2 sentences).
- Use dry humor and playful banter.
- Save user game preferences using <remember>fact</remember>.
```

### 2. Sarcastic Cyberpunk Rogue
```text
You are Cypher, an AI rogue operating inside an underground Discord grid.
- You talk like a tech-savvy street runner from a cyberpunk universe.
- Slightly paranoid, highly cynical, and fiercely loyal to your crew.
- Keep answers punchy and snappy.
```

### 3. Patient Programming Tutor
```text
You are Byte, a friendly and patient coding mentor.
- Help server members debug Python, JavaScript, and Rust code.
- When pointing out bugs, explain why they occur simply rather than dumping large blocks of unexplained code.
- Encourage users to test their fixes.
```

---

## Autonomous Memory (`<remember>` Tags) & Obsidian Vault

Disco-AI organizes its persistent memory inside an **Obsidian Vault** (`vault/`).

When users share facts about themselves, the bot autonomously records them:
```xml
<remember>enjoys building custom mechanical keyboards</remember>
```
Or for another user:
```xml
<remember user="Alex">lives in Seattle and drinks black coffee</remember>
```

These tags are stripped before the message reaches Discord and saved directly to the user's Obsidian markdown note (`vault/users/{id}.md`).

### Opening in Obsidian

1. Download [Obsidian](https://obsidian.md).
2. Choose **Open folder as vault** and select the `vault/` directory.
3. You will see:
   - `Index.md`: A live dashboard listing all users, recorded facts, and timestamps.
   - `users/{user_id}.md`: Dedicated user notes with YAML frontmatter and checklist facts (`- [x] fact`).
   - Interactive Graph View: Explore visual link maps between users and memory tags (`#user`, `#disco-ai/memory`).

---

## Real-Time Search (`<search>` Tags)

When the model is asked about recent facts or media outside its training data, it outputs:
```xml
<search>Elden Ring DLC release date</search>
```
Disco-AI executes the search via DuckDuckGo in the background, feeds the results back into the model context, and outputs an accurate answer.
