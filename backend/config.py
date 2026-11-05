"""ROBIN global configuration (loaded from .env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "database"
DATA_DIR.mkdir(exist_ok=True)
(DATA_DIR / "files").mkdir(exist_ok=True)
(DATA_DIR / "audio").mkdir(exist_ok=True)
(DATA_DIR / "backups").mkdir(exist_ok=True)
(DATA_DIR / "recordings").mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    APP_NAME: str = "ROBIN"
    VERSION: str = "1.0.0"
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    SECRET_KEY: str = "change-me-to-a-long-random-string"
    ACCESS_TOKEN_MINUTES: int = 60 * 24 * 7
    # Auto-deploy: GitHub webhook → git pull → pip install → restart (see deploy/README.md)
    DEPLOY_WEBHOOK_SECRET: str = ""
    DEPLOY_BRANCH: str = "main"
    DEPLOY_RESTART: bool = False      # True on the hosting server (systemd/docker restarts the process)
    DEPLOY_REQUIREMENTS: str = "requirements.txt"   # server: requirements-server.txt
    # PythonAnywhere: after `git pull` the site is reloaded through the PA API (Account → API token)
    PA_API_TOKEN: str = ""
    PA_USERNAME: str = ""
    PA_DOMAIN: str = ""               # default <username>.pythonanywhere.com
    PA_HOST: str = "www.pythonanywhere.com"   # EU accounts: eu.pythonanywhere.com

    DATABASE_URL: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'robin.db').as_posix()}"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-5-5"
    ANTHROPIC_FAST_MODEL: str = "claude-haiku-5-5"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_FAST_MODEL: str = "gemini-3.5-flash-lite"
    PRIMARY_PROVIDER: str = "anthropic"
    # Free / OpenAI-compatible providers (keys can also be entered in Dashboard → Brain)
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    CEREBRAS_API_KEY: str = ""
    GITHUB_API_KEY: str = ""        # GitHub personal access token (models:read)
    CLOUDFLARE_API_KEY: str = ""    # "ACCOUNT_ID:API_TOKEN"
    HUGGINGFACE_API_KEY: str = ""
    GROQ_MODEL: str = ""
    OPENROUTER_MODEL: str = ""
    MISTRAL_MODEL: str = ""
    CEREBRAS_MODEL: str = ""
    GITHUB_MODEL: str = ""
    CLOUDFLARE_MODEL: str = ""
    HUGGINGFACE_MODEL: str = ""

    LOCAL_EXECUTION: bool = True
    ALLOWED_ROOTS: str = ""

    TELEGRAM_BOT_TOKEN: str = ""

    TRADING_MODE: str = "paper"
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_TESTNET: bool = True
    MAX_DAILY_LOSS_PCT: float = 3.0
    MAX_POSITION_PCT: float = 10.0
    MAX_RISK_PER_TRADE_PCT: float = 1.0

    MAX_PARALLEL_TASKS: int = 3
    MAX_AGENT_STEPS: int = 25

    @property
    def allowed_roots(self) -> list[Path]:
        if self.ALLOWED_ROOTS.strip():
            return [Path(p).expanduser().resolve() for p in self.ALLOWED_ROOTS.split(";") if p.strip()]
        return [Path.home().resolve()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
