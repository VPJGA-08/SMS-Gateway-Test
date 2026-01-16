"""
Configuration management using environment variables
"""
import os
import secrets
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # API Settings
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "production"  # production, development, testing
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Security
    API_KEY: str = os.getenv("API_KEY", "")  # MUST be set in production
    API_KEY_HEADER: str = "X-API-Key"
    ALLOWED_IPS: Optional[str] = None  # Comma-separated IPs, None = allow all
    
    # Rate Limiting (per IP)
    RATE_LIMIT_PER_MINUTE: str = "30/minute"  # 30 requests per minute
    RATE_LIMIT_PER_HOUR: str = "500/hour"     # 500 requests per hour
    
    # Execution Settings
    MAX_CONCURRENT_EXECUTIONS: int = 3
    DEFAULT_TIMEOUT: int = 30  # seconds
    MAX_TIMEOUT: int = 120     # seconds
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    SCRIPTS_DIR: Path = BASE_DIR  # Where whitelisted scripts are located
    LOG_DIR: Path = BASE_DIR / "logs"
    
    # Logging
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    LOG_FILE: str = "api_gateway.log"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Ensure log directory exists
        self.LOG_DIR.mkdir(exist_ok=True)
        
        # Generate API key if not set (warn in production)
        if not self.API_KEY:
            if self.ENVIRONMENT == "production":
                raise ValueError(
                    "API_KEY must be set in production! "
                    "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
                )
            else:
                # Generate a temporary key for dev/testing
                self.API_KEY = secrets.token_urlsafe(32)
                print(f"⚠️  Using temporary API key: {self.API_KEY}")
    
    def get_allowed_ips(self) -> list[str]:
        """Parse allowed IPs from comma-separated string"""
        if not self.ALLOWED_IPS:
            return []
        return [ip.strip() for ip in self.ALLOWED_IPS.split(",")]

# Global settings instance
settings = Settings()
