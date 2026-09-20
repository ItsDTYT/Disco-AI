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
- In the meantime, you can use text prefix fallbacks: `!facts` and `!reset`.

---

## 4. Resetting User Memory
**Question**: How do I clear or edit memories?
- To clear a user's memory via Discord: have the owner run `/reset` in chat.
- To view or edit in plain text: open `users.md` in Notepad, make your edits, and save. The bot reads `users.md` if the database is reset.
- To completely wipe all memories: delete the `data/bot_memory.db` file while the bot is stopped.

---

## 5. OpenCV or Video Keyframe Issues on Windows
**Symptoms**: Error related to `cv2` or missing DLLs.
**Fix**:
- Make sure you have the official Microsoft Visual C++ Redistributable installed (standard for Windows gaming and media libraries).
- Run `pip install opencv-python-headless` inside your `.venv`.
