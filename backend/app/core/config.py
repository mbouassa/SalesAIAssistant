"""
Application configuration.
Loads settings from environment variables.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "AI Demo Agent"
    debug: bool = False
    
    # Daily.co
    daily_api_key: str = ""
    daily_api_url: str = "https://api.daily.co/v1"
    #
    # Deepgram (Speech-to-Text)
    deepgram_api_key: str = ""
    
    # OpenAI (LLM)
    openai_api_key: str = ""
    
    # ElevenLabs (TTS)
    elevenlabs_api_key: str = ""
    
    # Browserbase (Browser automation)
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""
    
    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
