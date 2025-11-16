"""
Redis-based email debouncer to prevent duplicate processing and filter trivial emails.

Implements 5-second debounce window to prevent duplicate processing of the same
email thread, and filters out trivial messages (< 10 chars, common greetings).
"""

from typing import Optional
import redis.asyncio as redis

from app.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)


class EmailDebouncer:
    """
    Redis-based debouncer for email processing.
    
    Prevents duplicate processing of emails within a 5-second window and
    filters trivial messages that don't require automated responses.
    
    Uses Redis keys with TTL for efficient debouncing without persistent storage.
    """
    
    DEBOUNCE_TTL_SECONDS = 5
    TRIVIAL_PATTERNS = {
        'hi', 'hello', 'hey', 'thanks', 'thank you', 'ok', 'okay', 
        'yes', 'no', 'yep', 'nope', '?', 'thx', 'ty'
    }
    MIN_CONTENT_LENGTH = 10
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
    
    async def connect(self, redis_url: Optional[str] = None):
        """
        Connect to Redis server.
        
        Args:
            redis_url: Redis connection string. If None, uses settings.redis_url.
            
        Raises:
            ValueError: If redis_url is not provided and settings.redis_url is not set
        """
        if self.redis_client is not None:
            return
        
        url = redis_url or settings.redis_url
        if not url:
            raise ValueError("REDIS_URL not configured in settings")
        
        self.redis_client = await redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True
        )
        
        logger.info(f"Debouncer connected to Redis at {url}")
    
    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None
            logger.info("Debouncer closed Redis connection")
    
    def _ensure_connected(self):
        """Verify Redis client is initialized."""
        if self.redis_client is None:
            raise RuntimeError(
                "Redis client not initialized. Call await debouncer.connect() first."
            )
    
    def is_trivial(self, email_body: str) -> bool:
        """
        Check if email content is trivial and should be filtered.
        
        An email is considered trivial if:
        - Content length is less than MIN_CONTENT_LENGTH characters
        - Content matches common trivial patterns (hi, hello, thanks, etc.)
        
        Args:
            email_body: Email body text to check
            
        Returns:
            True if email is trivial, False otherwise
        """
        if not email_body:
            return True
        
        cleaned = email_body.strip().lower()
        
        # Check length
        if len(cleaned) < self.MIN_CONTENT_LENGTH:
            return True
        
        # Check against trivial patterns
        if cleaned in self.TRIVIAL_PATTERNS:
            return True
        
        return False
    
    async def should_process(
        self,
        thread_id: str,
        email_body: str
    ) -> bool:
        """
        Determine if email should be processed based on debounce and trivial checks.
        
        Checks:
        1. If thread was recently processed (within 5 seconds) - prevents duplicates
        2. If email content is trivial - filters noise
        
        Args:
            thread_id: Email thread identifier
            email_body: Email body text
            
        Returns:
            True if email should be processed, False if it should be skipped
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        # Check if trivial first (no Redis call needed)
        if self.is_trivial(email_body):
            logger.debug(f"Skipping trivial email in thread {thread_id}")
            return False
        
        # Check debounce window
        debounce_key = f"debounce:{thread_id}"
        
        # Try to set key with NX (only if not exists) and EX (expiration)
        # Returns True if key was set (not in debounce window)
        # Returns False if key already exists (in debounce window)
        was_set = await self.redis_client.set(
            debounce_key,
            "1",
            nx=True,
            ex=self.DEBOUNCE_TTL_SECONDS
        )
        
        if not was_set:
            logger.debug(
                f"Thread {thread_id} in debounce window, skipping duplicate"
            )
            return False
        
        logger.debug(f"Thread {thread_id} passed debounce check, processing")
        return True
    
    async def mark_processed(self, thread_id: str) -> None:
        """
        Manually mark a thread as processed to start debounce window.
        
        Useful when you want to set the debounce window without checking it first.
        
        Args:
            thread_id: Email thread identifier
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        debounce_key = f"debounce:{thread_id}"
        await self.redis_client.setex(
            debounce_key,
            self.DEBOUNCE_TTL_SECONDS,
            "1"
        )
        logger.debug(f"Marked thread {thread_id} as processed")
    
    async def clear_debounce(self, thread_id: str) -> None:
        """
        Clear debounce window for a thread.
        
        Useful for testing or manual intervention.
        
        Args:
            thread_id: Email thread identifier
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        debounce_key = f"debounce:{thread_id}"
        await self.redis_client.delete(debounce_key)
        logger.debug(f"Cleared debounce for thread {thread_id}")


# Global debouncer instance
debouncer = EmailDebouncer()
