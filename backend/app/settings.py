from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    bot_token: str | None = None
    checker_interval_seconds: int = 60


settings = Settings()