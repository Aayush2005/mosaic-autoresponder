"""
Redis synchronization module for follow-up scheduling.

PostgreSQL is the source of truth for when follow-ups should be sent.
Redis is used as a temporary cache that syncs from PostgreSQL every 15 minutes.
This ensures the system continues working even if Redis goes down.

Architecture:
- PostgreSQL stores next_followup_at timestamp for each thread
- Redis stores a sorted set of threads by their next_followup_at
- Sync job runs every 15 minutes to update Redis from PostgreSQL
- Scheduler checks Redis for due follow-ups every minute
- If Redis is down, scheduler falls back to PostgreSQL directly
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import redis.asyncio as redis

from app.db.prisma_client import db
from app.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)


class RedisSync:
    """
    Synchronizes follow-up schedules from PostgreSQL to Redis.
    
    Redis stores a sorted set where:
    - Key: "followup_schedule"
    - Score: Unix timestamp of next_followup_at
    - Member: message_id
    
    This allows efficient retrieval of threads due for follow-up.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis sync.
        
        Args:
            redis_url: Redis connection URL (default: from settings)
        """
        self.redis_url = redis_url or settings.redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.sync_interval = 900  # 15 minutes in seconds
        self.running = False
    
    async def connect(self):
        """Connect to Redis."""
        try:
            # redis.from_url() is NOT awaitable - it returns client directly
            self.redis_client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Connected to Redis for follow-up scheduling")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
    
    async def close(self):
        """Close Redis connection and connection pool."""
        if self.redis_client:
            await self.redis_client.connection_pool.disconnect()
            self.redis_client = None
            logger.info("Closed Redis connection")
    
    async def sync_from_postgres(self) -> int:
        """
        Sync follow-up schedules from PostgreSQL to Redis.
        
        Fetches all threads with scheduled follow-ups from PostgreSQL
        and updates Redis sorted set atomically using temp key + rename.
        
        Returns:
            Number of threads synced
        """
        if not self.redis_client:
            logger.warning("Redis not connected, skipping sync")
            return 0
        
        try:
            # Get all threads with scheduled follow-ups
            threads = await db.get_threads_for_redis_sync()
            
            if not threads:
                logger.info("No threads to sync to Redis")
                # Clear Redis if no threads
                await self.redis_client.delete("followup_schedule")
                return 0
            
            # Use atomic swap to avoid data gaps during sync
            temp_key = "followup_schedule_tmp"
            pipeline = self.redis_client.pipeline()
            
            # Clear temp key
            pipeline.delete(temp_key)
            
            # Add threads to temp sorted set
            for thread in threads:
                next_followup_at = thread['next_followup_at']
                message_id = thread['message_id']
                
                # Convert to Unix timestamp for Redis score
                score = next_followup_at.timestamp()
                
                # Store as sorted set member
                pipeline.zadd(temp_key, {message_id: score})
            
            # Atomic swap: rename temp to production key
            pipeline.rename(temp_key, "followup_schedule")
            
            await pipeline.execute()
            
            logger.info(f"Synced {len(threads)} threads to Redis (atomic swap)")
            return len(threads)
            
        except Exception as e:
            logger.error(f"Error syncing to Redis: {e}", exc_info=True)
            return 0
    
    async def get_due_followups(self, current_time: Optional[datetime] = None) -> List[str]:
        """
        Get message IDs of threads due for follow-up from Redis.
        
        Args:
            current_time: Current time (default: now)
            
        Returns:
            List of message IDs due for follow-up
        """
        if not self.redis_client:
            logger.warning("Redis not connected, cannot get due followups")
            return []
        
        try:
            if current_time is None:
                current_time = datetime.now()
            
            # Get all threads with score <= current timestamp
            max_score = current_time.timestamp()
            
            # Use "-inf" instead of 0 to handle any valid timestamp
            message_ids = await self.redis_client.zrangebyscore(
                "followup_schedule",
                min="-inf",
                max=max_score
            )
            
            return message_ids
            
        except Exception as e:
            logger.error(f"Error getting due followups from Redis: {e}", exc_info=True)
            return []
    
    async def remove_from_schedule(self, message_id: str) -> bool:
        """
        Remove a thread from Redis schedule (when sent or stopped).
        
        Args:
            message_id: Thread's message ID
            
        Returns:
            True if removed, False otherwise
        """
        if not self.redis_client:
            return False
        
        try:
            result = await self.redis_client.zrem("followup_schedule", message_id)
            return result > 0
        except Exception as e:
            logger.error(f"Error removing {message_id} from Redis: {e}")
            return False
    
    async def add_to_schedule(
        self,
        message_id: str,
        next_followup_at: datetime
    ) -> bool:
        """
        Add a thread to Redis schedule.
        
        Args:
            message_id: Thread's message ID
            next_followup_at: When to send follow-up
            
        Returns:
            True if added, False otherwise
        """
        if not self.redis_client:
            return False
        
        try:
            score = next_followup_at.timestamp()
            await self.redis_client.zadd("followup_schedule", {message_id: score})
            return True
        except Exception as e:
            logger.error(f"Error adding {message_id} to Redis: {e}")
            return False
    
    async def get_schedule_count(self) -> int:
        """
        Get count of scheduled follow-ups in Redis.
        
        Returns:
            Number of threads in schedule
        """
        if not self.redis_client:
            return 0
        
        try:
            return await self.redis_client.zcard("followup_schedule")
        except Exception as e:
            logger.error(f"Error getting schedule count: {e}")
            return 0
    
    async def acquire_sync_lock(self, ttl: int = 840) -> bool:
        """
        Acquire distributed lock for sync operation.
        
        Prevents multiple workers from syncing simultaneously.
        
        Args:
            ttl: Lock TTL in seconds (default: 14 minutes, less than sync interval)
            
        Returns:
            True if lock acquired, False otherwise
        """
        if not self.redis_client:
            return False
        
        try:
            # SET NX (only if not exists) with expiration
            result = await self.redis_client.set(
                "redis_sync_lock",
                "locked",
                nx=True,
                ex=ttl
            )
            return result is not None
        except Exception as e:
            logger.error(f"Error acquiring sync lock: {e}")
            return False
    
    async def release_sync_lock(self):
        """Release distributed sync lock."""
        if not self.redis_client:
            return
        
        try:
            await self.redis_client.delete("redis_sync_lock")
        except Exception as e:
            logger.error(f"Error releasing sync lock: {e}")
    
    async def start_sync_loop(self):
        """
        Start the sync loop that runs every 15 minutes.
        
        Continuously syncs from PostgreSQL to Redis.
        Uses distributed lock to prevent multiple workers from syncing.
        """
        self.running = True
        logger.info(f"Starting Redis sync loop (every {self.sync_interval}s)")
        
        while self.running:
            try:
                # Try to acquire lock (prevents multiple workers from syncing)
                lock_acquired = await self.acquire_sync_lock(ttl=self.sync_interval - 60)
                
                if not lock_acquired:
                    logger.debug("Another worker is syncing, skipping this cycle")
                    await asyncio.sleep(self.sync_interval)
                    continue
                
                try:
                    # Sync from PostgreSQL
                    count = await self.sync_from_postgres()
                    
                    if count > 0:
                        logger.info(f"Redis sync complete: {count} threads scheduled")
                finally:
                    # Always release lock
                    await self.release_sync_lock()
                
                # Wait for next sync
                await asyncio.sleep(self.sync_interval)
                
            except Exception as e:
                logger.error(f"Error in sync loop: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    async def stop_sync_loop(self):
        """Stop the sync loop."""
        self.running = False
        logger.info("Stopping Redis sync loop")
    
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self.redis_client is not None


# Global Redis sync instance
redis_sync = RedisSync()


async def get_due_followups_with_fallback(
    current_time: Optional[datetime] = None
) -> List[Dict]:
    """
    Get threads due for follow-up with Redis fallback to PostgreSQL.
    
    Tries Redis first for performance. If Redis is down or returns nothing,
    falls back to querying PostgreSQL directly.
    
    Args:
        current_time: Current time (default: now)
        
    Returns:
        List of thread records due for follow-up
    """
    if current_time is None:
        current_time = datetime.now()
    
    # Try Redis first
    if redis_sync.is_connected():
        try:
            message_ids = await redis_sync.get_due_followups(current_time)
            
            if message_ids:
                # Fetch full thread records from PostgreSQL
                threads = []
                for message_id in message_ids:
                    thread = await db.get_thread(message_id)
                    if thread:
                        threads.append(thread)
                
                logger.info(f"Got {len(threads)} due followups from Redis")
                return threads
        except Exception as e:
            logger.warning(f"Redis query failed, falling back to PostgreSQL: {e}")
    
    # Fallback to PostgreSQL
    logger.info("Using PostgreSQL for due followups (Redis unavailable)")
    threads = await db.get_threads_needing_followup(current_time)
    return threads
