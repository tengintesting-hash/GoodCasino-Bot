from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    bot_username: str
    webapp_url: str
    admin_token: str
    postback_secret: str
    sqlite_path: str = "/data/database.db"

    class Config:
        env_prefix = ""
        case_sensitive = False


settings = Settings()
