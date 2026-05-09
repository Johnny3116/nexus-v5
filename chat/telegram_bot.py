"""
Nexus Telegram bot — direct Ollama, no relay.

Responds to messages from the configured chat ID.
Conversation history is persisted per-chat as JSON.
"""

import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# Load .env from repo root (one level up from chat/)
load_dotenv(Path(__file__).parent.parent / ".env")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
SOUL_PATH = Path(__file__).parent.parent / "safety" / "identity" / "soul.md"
HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)
MAX_TURNS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("nexus.telegram")


def load_soul() -> str:
    try:
        return SOUL_PATH.read_text(encoding="utf-8")
    except Exception:
        return "You are Nexus, a helpful AI assistant."


def load_history(chat_id: str) -> list[dict]:
    path = HISTORY_DIR / f"telegram_{chat_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_history(chat_id: str, history: list[dict]) -> None:
    path = HISTORY_DIR / f"telegram_{chat_id}.json"
    if len(history) > MAX_TURNS * 2:
        history = history[-(MAX_TURNS * 2):]
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


async def ask_ollama(history: list[dict], system: str) -> str:
    messages = [{"role": "system", "content": system}] + history
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 512},
                "keep_alive": -1,
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id

    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        logger.warning("Message from unauthorized chat %d — ignored", chat_id)
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    key = str(chat_id)
    history = load_history(key)
    history.append({"role": "user", "content": text})

    await update.message.chat.send_action("typing")

    try:
        soul = load_soul()
        reply = await ask_ollama(history, soul)
    except Exception as exc:
        logger.error("Ollama error: %s", exc)
        reply = "Something went wrong connecting to my brain. Try again in a sec."

    history.append({"role": "assistant", "content": reply})
    save_history(key, history)

    # Telegram limit is 4096 chars
    chunks = [reply[i : i + 4000] for i in range(0, max(len(reply), 1), 4000)]
    for chunk in chunks:
        await update.message.reply_text(chunk)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Nexus Telegram bot starting (allowed chat: %d)...", ALLOWED_CHAT_ID)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
