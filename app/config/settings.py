"""
Application configuration using Pydantic Settings.

Loads all environment variables from .env file with validation and type safety.
"""

from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GmailAccount(BaseSettings):
    """Configuration for a single Gmail account."""
    
    email: str
    password: str
    rate_limit_per_day: int = 500
    
    model_config = SettingsConfigDict(extra='ignore')


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Automatically loads from .env file in project root.
    """
    
    # Gmail Account 1
    gmail_account_1_email: str = Field(..., alias='GMAIL_ACCOUNT_1_EMAIL')
    gmail_account_1_password: str = Field(..., alias='GMAIL_ACCOUNT_1_PASSWORD')
    gmail_account_1_rate_limit_per_day: int = Field(500, alias='GMAIL_ACCOUNT_1_RATE_LIMIT_PER_DAY')
    
    # Gmail Account 2
    gmail_account_2_email: str = Field(..., alias='GMAIL_ACCOUNT_2_EMAIL')
    gmail_account_2_password: str = Field(..., alias='GMAIL_ACCOUNT_2_PASSWORD')
    gmail_account_2_rate_limit_per_day: int = Field(500, alias='GMAIL_ACCOUNT_2_RATE_LIMIT_PER_DAY')
    
    # Gmail Account 3
    gmail_account_3_email: str = Field(..., alias='GMAIL_ACCOUNT_3_EMAIL')
    gmail_account_3_password: str = Field(..., alias='GMAIL_ACCOUNT_3_PASSWORD')
    gmail_account_3_rate_limit_per_day: int = Field(500, alias='GMAIL_ACCOUNT_3_RATE_LIMIT_PER_DAY')
    
    # IMAP Configuration
    imap_server: str = Field('imap.gmail.com', alias='IMAP_SERVER')
    imap_port: int = Field(993, alias='IMAP_PORT')
    
    # SMTP Configuration
    smtp_server: str = Field('smtp.gmail.com', alias='SMTP_SERVER')
    smtp_port: int = Field(587, alias='SMTP_PORT')
    
    # Groq API Configuration
    groq_api_key: str = Field(..., alias='GROQ_API_KEY')
    
    # Database Configuration
    database_url: str = Field(..., alias='DATABASE_URL')
    
    # Redis Configuration
    redis_url: str = Field('redis://localhost:6379/0', alias='REDIS_URL')
    
    # System Configuration
    polling_interval: int = Field(60, alias='POLLING_INTERVAL')
    max_concurrent_workers: int = Field(10, alias='MAX_CONCURRENT_WORKERS')
    log_level: str = Field('INFO', alias='LOG_LEVEL')
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    def get_account_password(self, account_email: str) -> Optional[str]:
        """
        Get password for a Gmail account by email address.
        
        Args:
            account_email: Email address of the account
            
        Returns:
            Password string, or None if account not found
        """
        if account_email == self.gmail_account_1_email:
            return self.gmail_account_1_password
        elif account_email == self.gmail_account_2_email:
            return self.gmail_account_2_password
        elif account_email == self.gmail_account_3_email:
            return self.gmail_account_3_password
        return None
    
    def get_account_rate_limit(self, account_email: str) -> Optional[int]:
        """
        Get rate limit for a Gmail account by email address.
        
        Args:
            account_email: Email address of the account
            
        Returns:
            Rate limit per day, or None if account not found
        """
        if account_email == self.gmail_account_1_email:
            return self.gmail_account_1_rate_limit_per_day
        elif account_email == self.gmail_account_2_email:
            return self.gmail_account_2_rate_limit_per_day
        elif account_email == self.gmail_account_3_email:
            return self.gmail_account_3_rate_limit_per_day
        return None
    
    @property
    def all_account_emails(self) -> list[str]:
        """Get list of all configured Gmail account emails."""
        return [
            self.gmail_account_1_email,
            self.gmail_account_2_email,
            self.gmail_account_3_email
        ]


# Global settings instance
settings = Settings()
