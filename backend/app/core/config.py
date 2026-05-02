from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    app_env: str = "development"
    app_port: int = 8000
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    tavily_api_key: str = ""
    gemini_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-2.5-flash"
    external_api_timeout_sec: float = 20.0
    youtube_api_key: str = ""
    x_bearer_token: str = ""
    x_api_base_primary: str = "https://api.x.com"
    x_api_base_fallback: str = "https://api.twitter.com"
    x_accounts_path: str = "legacy/streamlit_app/x_accounts.json"

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), str(ROOT_DIR / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


settings = Settings()
