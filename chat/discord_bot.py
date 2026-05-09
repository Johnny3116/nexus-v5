"""
Nexus Discord bot — direct Ollama, no relay.

Responds to all messages in allowed channels and DMs.
Conversation history is persisted per-channel as JSON.
"""

import json
import logging
import os
from pathlib import Path

import discord
import httpx
from dotenv import load_dotenv

# Load .env from repo root (one level up from chat/)
load_dotenv(Path(__file__).parent.parent / ".env")

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
ALLOWED_CHANNELS = set(
    c.strip()
    for c in os.environ.get("DISCORD_ALLOWED_CHANNEL_IDS", "").split(",")
    if c.strip()
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")
SOUL_PATH = Path(__file__).parent.parent / "safety" / "identity" / "soul.md"
HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)
MAX_TURNS = 20  # user+assistant pairs kept per channel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("nexus.discord")


def load_soul() -> str:
    try:
        return SOUL_PATH.read_text(encoding="utf-8")
    except Exception:
        return "You are Nexus, a helpful AI assistant."


def load_history(key: str) -> list[dict]:
    path = HISTORY_DIR / f"discord_{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_history(key: str, history: list[dict]) -> None:
    path = HISTORY_DIR / f"discord_{key}.json"
    # Trim to MAX_TURNS (each turn = 1 user + 1 assistant message)
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


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


@bot.event
async def on_ready():
    logger.info("Nexus Discord bot ready: %s | allowed channels: %s", bot.user, ALLOWED_CHANNELS)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    in_allowed = str(message.channel.id) in ALLOWED_CHANNELS

    if not (is_dm or in_allowed):
        return

    # Strip bot mention from content if present
    content = message.content
    if bot.user.mentioned_in(message):
        content = (
            content
            .replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

    if not content:
        return

    key = str(message.channel.id)
    history = load_history(key)
    history.append({"role": "user", "content": content})

    async with message.channel.typing():
        try:
            soul = load_soul()
            reply = await ask_ollama(history, soul)
        except Exception as exc:
            logger.error("Ollama error: %s", exc)
            reply = "Something went wrong connecting to my brain. Try again in a sec."

    history.append({"role": "assistant", "content": reply})
    save_history(key, history)

    # Discord message limit is 2000 chars — chunk if needed
    chunks = [reply[i : i + 1900] for i in range(0, max(len(reply), 1), 1900)]
    for chunk in chunks:
        await message.channel.send(chunk)


if __name__ == "__main__":
    bot.run(TOKEN)
