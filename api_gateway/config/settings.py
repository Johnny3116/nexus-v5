"""nexus-gateway — configuration loader.

Ported from V4 `nexus_core/config/settings.py`. Changes:
  - Remove `@lru_cache` on the getter (the 2026-03-27 bug). Module-level
    singleton pattern: one instance per process, `.env` reloads on process
    restart with no cache semantics to fight.
  - Drop dead V4 ports (`CHAT_PORT`, `VTUBE_PORT`, `TOOLS_PORT`, `CODING_PORT`).
  - Drop V4 split-service URL properties.
  - `ollama_url` is the new canonical name (was `ollama_host`).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic.fields import AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

# api_gateway/config/settings.py → repo root is 2 levels up
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Typed env configuration for the api_gateway service."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase ------------------------------------------------------
    supabase_url: str = ""
    supabase_service_key: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_service_key", "supabase_key"),
    )
    supabase_anon_key: str = ""

    # --- LLM: Anthropic (direct, for Claude Sonnet 4.6) ---------------
    anthropic_api_key: str = ""
    anthropic_oauth_token: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_oauth_token", "claude_web_api_key"),
    )

    # --- LLM: Nexus-Agent gateway (OpenClaw, for Codex) ---------------
    nexus_agent_url: str = "wss://nexusserver.tail344870.ts.net:18789"
    nexus_agent_token: str = "nexus2026"
    nexus_agent_model: str = "openai-codex/gpt-5.4"
    # SSH transport for codex.py (token auth = read-only, SSH gives full operator)
    openclaw_ssh_user: str = "nexus"
    openclaw_cwd: str = r"C:\Users\Nexus\openclaw"

    # --- LLM: Ollama (local Qwen) -------------------------------------
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    # --- BrainPool model names (overridable per provider) -------------
    claude_model: str = "claude-sonnet-4-6"
    codex_model: str = "openai-codex/gpt-5.4"
    qwen_model: str = "qwen2.5-coder:7b"

    # --- Gateway service binding --------------------------------------
    gateway_host: str = "0.0.0.0"     # overridden in ecosystem.config.js to Tailscale IP
    gateway_port: int = 8000

    # --- Tailscale IPs ------------------------------------------------
    nexus_body_ip: str = ""
    nexus_server_ip: str = ""
    workstation_prime_ip: str = ""

    # --- Security -----------------------------------------------------
    inter_service_secret: str = ""

    # --- Budgets ------------------------------------------------------
    claude_daily_budget_usd: float = 5.0
    claude_monthly_budget_usd: float = 100.0

    # --- Identity -----------------------------------------------------
    nexus_owner_identity: str = "john"

    # --- Discord ----------------------------------------------------------
    discord_webhook_url: str = ""
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    discord_owner_id: str = ""
    discord_channel_general: str = ""
    discord_channel_tech_news: str = ""
    discord_channel_game_news: str = ""
    discord_channel_ai_drops: str = ""
    discord_channel_anime: str = ""
    discord_channel_dev_feed: str = ""

    # --- Telegram ---------------------------------------------------------
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_alerts_chat_id: str = ""

    # --- YouTube Data API v3 ---------------------------------------------
    youtube_api_key: str = ""

    # --- GitHub (Phase 8 Scout) ------------------------------------------
    github_token: str = ""

    # --- Convenience --------------------------------------------------
    @property
    def nexus_agent_http_url(self) -> str:
        """`ws://` and `wss://` rewritten to http(s) for non-streaming calls."""
        url = self.nexus_agent_url
        if url.startswith("ws://"):
            return "http://" + url[5:]
        if url.startswith("wss://"):
            return "https://" + url[6:]
        return url

    def is_configured(self) -> bool:
        """Minimum viable config for the gateway to start."""
        return bool(self.supabase_url and self.supabase_service_key)


# --- Module-level singleton (NOT @lru_cache — see 2026-03-27 lesson) ------
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide Settings singleton.

    First call constructs it from .env; subsequent calls return the same
    instance. .env changes require a process restart to take effect — but
    restart actually works (lru_cache variant silently kept stale values).
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
