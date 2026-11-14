# The app has a settings card. On my laptop 
# it says 'use the small notebook'; on the server it says 'use the big filing cabinet'. 
# The code is identical; only the card changes
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Order Management API"
    database_url: str = "sqlite:///./orders.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()