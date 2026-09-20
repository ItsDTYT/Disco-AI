# Model Setup Guide: Local & Cloud Options

Disco-AI supports any OpenAI-compatible Chat Completions endpoint. This means you can run lightweight local models on your GPU with zero subscription costs, or connect to cloud API keys.

---

## Recommended Models

### Local Models (Consumer Hardware)
1. **Qwen 3.5 4B** (Top Recommendation)
   - **Why**: Lightweight, ultra-fast response latency, fits easily on 6 GB–8 GB consumer GPUs, and strictly adheres to tool tags (`<remember>`, `<search>`).
2. **Gemma 4 E4B**
   - **Why**: Google's lightweight open model architecture. Delivers strong natural conversational flow with low memory overhead.

### Cloud Models (API Providers)
1. **Gemini 3.8 Flash**
   - **Why**: Extreme generation speed, massive context window, and very low cost per million tokens.
2. **ChatGPT 5.6 (Luna / Terra)**
   - **Why**: Deep creative nuance, complex roleplay capabilities, and reliable instruction following.

---

## Setting Up Local Models

### Option 1: LM Studio (Easiest GUI)
1. Download and install [LM Studio](https://lmstudio.ai/).
2. Search for and download **Qwen 3.5 4B** (or **Gemma 4 E4B**).
3. Click the **Developer / Local Server** tab (icon with `<->` on the left).
4. Select your downloaded model from the top dropdown.
5. Click **Start Server** (default port is `1234`).
6. In your `.env`:
   ```ini
   API_BASE_URL=http://127.0.0.1:1234/v1
   MODEL_NAME=qwen3.5-4b
   API_KEY=
   ```

### Option 2: Ollama (CLI / Background Service)
1. Download and install [Ollama](https://ollama.com/).
2. Open terminal and run:
   ```bash
   ollama run qwen2.5:7b
   ```
3. In your `.env`:
   ```ini
   API_BASE_URL=http://127.0.0.1:11434/v1
   MODEL_NAME=qwen2.5:7b
   API_KEY=
   ```

---

## Setting Up Cloud APIs

### Option 1: Google Gemini (Gemini 3.8 Flash)
Google AI Studio provides an OpenAI-compatible endpoint for Gemini models:
1. Get a free API key from [Google AI Studio](https://aistudio.google.com/).
2. In your `.env`:
   ```ini
   API_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   MODEL_NAME=gemini-2.0-flash
   API_KEY=your_google_api_key_here
   ```

### Option 2: OpenAI (ChatGPT 5.6 Luna / Terra / GPT-4o)
1. Get an API key from [platform.openai.com](https://platform.openai.com/).
2. In your `.env`:
   ```ini
   API_BASE_URL=https://api.openai.com/v1
   MODEL_NAME=gpt-4o-mini
   API_KEY=sk-your_openai_api_key_here
   ```

### Option 3: OpenRouter (All Models in One Key)
OpenRouter provides access to models from Anthropic, Meta, Mistral, Google, and open-source fine-tunes:
1. Create an account at [openrouter.ai](https://openrouter.ai/) and generate a key.
2. In your `.env`:
   ```ini
   API_BASE_URL=https://openrouter.ai/api/v1
   MODEL_NAME=meta-llama/llama-3.3-70b-instruct
   API_KEY=sk-or-v1-your_key_here
   ```

### Option 4: Groq (Ultra-Fast LPU Cloud)
1. Get a free API key from [console.groq.com](https://console.groq.com/).
2. In your `.env`:
   ```ini
   API_BASE_URL=https://api.groq.com/openai/v1
   MODEL_NAME=llama-3.3-70b-versatile
   API_KEY=gsk_your_groq_key_here
   ```
