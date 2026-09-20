# Troubleshooting & Frequently Asked Questions

Common issues and solutions when running Disco-AI.

---

## 1. "Privileged Intents" Error on Startup
**Symptoms**: The bot crashes on startup with `discord.errors.PrivilegedIntentsRequired`.
**Fix**:
1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Select your application > click **Bot** in the left menu.
3. Scroll down to **Privileged Gateway Intents**.
4. Turn on both **Message Content Intent** and **Server Members Intent**.
5. Click **Save Changes** and restart `run.bat`.

---

## 2. "Cannot reach AI backend at http://127.0.0.1:1234"
**Symptoms**: Bot is online in Discord, but when you chat with it, it says it cannot reach the AI backend.
**Fix**:
1. If using **LM Studio**: Make sure you clicked the **Local Server** tab and hit **Start Server**. Check that the port matches `1234` in `.env`.
2. If using **Ollama**: Make sure Ollama is running in your taskbar or terminal (`ollama serve`). Default port is `11434`.
3. If using a **Cloud API**: Check that `API_KEY` in `.env` is valid and has active credits or quota.

---

## 3. Slash Commands (`/facts`, `/reset`) Do Not Appear
**Symptoms**: Typing `/` in Discord does not show the bot's commands.
**Fix**:
- Discord can take up to a few minutes to register global slash commands for newly invited bots.
- Ensure you invited the bot with both `bot` and `applications.commands` checked in the URL Generator.

---

## 4. Resetting or Editing User Memory (Obsidian Vault)
**Question**: How do I clear or edit memories?
- To clear conversation memory for a channel or DM: have the owner run `/reset` in chat.
- To view or edit user memories directly: open `vault/users/{user_id}.md` in Obsidian or any text editor, edit or delete facts, and save. The bot reads changes immediately.
- To completely wipe all memories: delete the `vault/` directory while the bot is stopped.

---

## 5. "Vision Model Required" Warning in Discord
**Symptoms**: When you send an image, GIF, or sticker, the bot replies: *"The currently loaded model cannot process images because it lacks multimodal vision support."*
**Fix**:
- You are running a text-only language model (e.g. `qwen3.5-4b`, `gemma4:e4b`).
- Switch your backend model to a multimodal vision model:
  - Local (LM Studio / Ollama): `Qwen2.5-VL-7B-Instruct`, `Llama-3.2-11B-Vision`, or `MiniCPM-V-2_6`.
  - Cloud API: `gpt-4o` or `gemini-2.0-flash`.

---

## 5. OpenCV or Video Keyframe Issues on Windows
**Symptoms**: Error related to `cv2` or missing DLLs.
**Fix**:
- Make sure you have the official Microsoft Visual C++ Redistributable installed (standard for Windows gaming and media libraries).
- Run `pip install opencv-python-headless` inside your `.venv`.
