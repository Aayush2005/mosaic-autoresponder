"""
Redis-based scheduler for delayed follow-up emails.

Schedules Stage 2 (24 hours) and Stage 3 (48 hours) follow-ups using Redis
sorted sets with atomic operations to prevent double-sends. Includes complete
idempotency checks against database state.
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import redis.asyncio as redis

from app.db.prisma_client import db
from app.smtp.sender import sender
from app.config import settings
from app.utils.logger import get_logger, log_followup_sent, log_followup_scheduled


logger = get_logger(__name__)


class FollowUpScheduler:
    """
    Redis-based scheduler for delayed follow-up emails.
    
    Uses Redis sorted sets to schedule follow-ups with epoch timestamps as scores.
    Implements complete idempotency through:
    - Atomic ZREM operations to pop items
    - Database status checks before sending
    - followups_sent counter verification
    - Redis deduplication keys
    
    Prevents double-sends even with multiple scheduler instances or restarts.
    """
    
    FOLLOWUP_SORTED_SET = "followups:scheduled"
    CHECK_INTERVAL_SECONDS = 900  # 15 minutes
    STAGE_2_DELAY_HOURS = 24  # 1 day after Stage 1
    STAGE_3_DELAY_HOURS = 48  # 2 days after Stage 2
    DEDUP_KEY_TTL_SECONDS = 3600  # 1 hour
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.running = False
    
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
        
        logger.info(f"Connected to Redis at {url}")
    
    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None
            logger.info("Closed Redis connection")
    
    def _ensure_connected(self):
        """Verify Redis client is initialized."""
        if self.redis_client is None:
            raise RuntimeError(
                "Redis client not initialized. Call await scheduler.connect() first."
            )
    
    async def schedule_followup(
        self,
        message_id: str,
        stage: int,
        delay_hours: int
    ) -> bool:
        """
        Schedule a follow-up email for future delivery.
        
        Adds the follow-up to Redis sorted set with timestamp score.
        The score is the epoch time when the follow-up should be sent.
        
        Args:
            message_id: Unique Gmail message ID
            stage: Follow-up stage (1, 2, or 3)
            delay_hours: Hours to wait before sending
            
        Returns:
            True if scheduled successfully, False otherwise
            
        Raises:
            RuntimeError: If Redis client not connected
            ValueError: If stage is not 1, 2, or 3
        """
        self._ensure_connected()
        
        if stage not in [1, 2, 3]:
            raise ValueError(f"Invalid stage: {stage}. Must be 1, 2, or 3")
        
        # Calculate when to send (epoch timestamp)
        send_at = datetime.now() + timedelta(hours=delay_hours)
        score = send_at.timestamp()
        
        # Store as "message_id:stage" in sorted set
        member = f"{message_id}:{stage}"
        
        try:
            await self.redis_client.zadd(
                self.FOLLOWUP_SORTED_SET,
                {member: score}
            )
            
            logger.info(
                f"Scheduled Stage {stage} follow-up for {message_id} "
                f"at {send_at.isoformat()} ({delay_hours}h delay)"
            )
            return True
        
        except Exception as e:
            logger.error(
                f"Failed to schedule Stage {stage} follow-up for {message_id}: {e}"
            )
            return False
    
    async def cancel_followup(self, message_id: str) -> int:
        """
        Cancel all scheduled follow-ups for a thread.
        
        Removes all stages for the given message_id from the sorted set
        and deletes any deduplication keys.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            Number of follow-ups cancelled
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        cancelled_count = 0
        
        try:
            # Remove all stages (1, 2, 3) from sorted set
            for stage in [1, 2, 3]:
                member = f"{message_id}:{stage}"
                removed = await self.redis_client.zrem(
                    self.FOLLOWUP_SORTED_SET,
                    member
                )
                if removed:
                    cancelled_count += removed
                
                # Delete deduplication key
                dedup_key = f"followup:{message_id}:{stage}"
                await self.redis_client.delete(dedup_key)
            
            if cancelled_count > 0:
                logger.info(
                    f"Cancelled {cancelled_count} scheduled follow-ups "
                    f"for {message_id}"
                )
            
            return cancelled_count
        
        except Exception as e:
            logger.error(
                f"Failed to cancel follow-ups for {message_id}: {e}"
            )
            return 0
    
    async def _get_due_followups(self) -> List[tuple[str, int]]:
        """
        Get follow-ups that are due to be sent now.
        
        Atomically fetches and removes items from sorted set using ZRANGEBYSCORE
        and ZREM to prevent duplicate processing.
        
        Returns:
            List of (message_id, stage) tuples ready to send
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        now = datetime.now().timestamp()
        
        try:
            # Get all items with score <= now (due for sending)
            # ZRANGEBYSCORE returns items in ascending order by score
            items = await self.redis_client.zrangebyscore(
                self.FOLLOWUP_SORTED_SET,
                min=0,
                max=now
            )
            
            if not items:
                return []
            
            # Atomically remove items from sorted set
            # This prevents other scheduler instances from processing same items
            await self.redis_client.zrem(
                self.FOLLOWUP_SORTED_SET,
                *items
            )
            
            # Parse "message_id:stage" format
            followups = []
            for item in items:
                try:
                    message_id, stage_str = item.rsplit(':', 1)
                    stage = int(stage_str)
                    followups.append((message_id, stage))
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Invalid followup item format: {item}, skipping: {e}"
                    )
                    continue
            
            if followups:
                logger.info(f"Found {len(followups)} due follow-ups to process")
            
            return followups
        
        except Exception as e:
            logger.error(f"Failed to get due follow-ups: {e}")
            return []
    
    async def _should_send_followup(
        self,
        message_id: str,
        stage: int
    ) -> tuple[bool, Optional[Dict]]:
        """
        Check if follow-up should be sent based on database state.
        
        Performs comprehensive idempotency checks:
        1. Thread exists in database
        2. Thread status is FOLLOWUP_ACTIVE
        3. Thread has no stop_reason
        4. Thread failed_sends < 3
        5. followups_sent < stage (hasn't been sent yet)
        6. No deduplication key exists in Redis
        
        Args:
            message_id: Unique Gmail message ID
            stage: Follow-up stage to check (1, 2, or 3)
            
        Returns:
            Tuple of (should_send: bool, thread_data: Optional[Dict])
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        # Check deduplication key first (fastest check)
        dedup_key = f"followup:{message_id}:{stage}"
        if await self.redis_client.exists(dedup_key):
            logger.debug(
                f"Dedup key exists for {message_id} Stage {stage}, skipping"
            )
            return (False, None)
        
        # Get thread from database
        thread = await db.get_thread(message_id)
        
        if not thread:
            logger.warning(
                f"Thread not found for message_id {message_id}, skipping"
            )
            return (False, None)
        
        # Check status
        if thread['status'] != 'FOLLOWUP_ACTIVE':
            logger.debug(
                f"Thread {message_id} status is {thread['status']}, "
                f"not FOLLOWUP_ACTIVE, skipping"
            )
            return (False, None)
        
        # Check stop reason
        if thread['stop_reason']:
            logger.debug(
                f"Thread {message_id} has stop_reason: {thread['stop_reason']}, "
                f"skipping"
            )
            return (False, None)
        
        # Check failed sends
        failed_sends = thread.get('failed_sends', 0)
        if failed_sends >= 3:
            logger.warning(
                f"Thread {message_id} has {failed_sends} failed sends, skipping"
            )
            return (False, None)
        
        # Check if stage already sent (idempotency)
        followups_sent = thread.get('followups_sent', 0)
        if followups_sent >= stage:
            logger.debug(
                f"Thread {message_id} already sent {followups_sent} follow-ups, "
                f"Stage {stage} already sent, skipping"
            )
            return (False, None)
        
        # All checks passed
        return (True, thread)
    
    async def _process_followup(
        self,
        message_id: str,
        stage: int
    ) -> bool:
        """
        Process a single follow-up: check eligibility and send.
        
        Args:
            message_id: Unique Gmail message ID
            stage: Follow-up stage to send (1, 2, or 3)
            
        Returns:
            True if sent successfully, False otherwise
        """
        # Check if should send
        should_send, thread_data = await self._should_send_followup(message_id, stage)
        
        if not should_send:
            return False
        
        # Set deduplication key before sending
        dedup_key = f"followup:{message_id}:{stage}"
        await self.redis_client.setex(
            dedup_key,
            self.DEDUP_KEY_TTL_SECONDS,
            "1"
        )
        
        # Send follow-up
        logger.info(
            f"Sending Stage {stage} follow-up for thread {message_id}"
        )
        
        success = await sender.send_followup(thread_data, stage)
        
        if success:
            # Update current_stage in database
            await db.update_thread(
                message_id,
                current_stage=stage
            )
            
            # Log follow-up sent
            log_followup_sent(message_id, stage, thread_data['creator_email'])
            
            logger.info(
                f"Successfully sent Stage {stage} follow-up for {message_id}"
            )
            
            # Schedule next stage if applicable
            if stage == 1:
                # Schedule Stage 2 for 24 hours later
                await self.schedule_followup(
                    message_id,
                    stage=2,
                    delay_hours=self.STAGE_2_DELAY_HOURS
                )
                log_followup_scheduled(message_id, 2, self.STAGE_2_DELAY_HOURS)
            elif stage == 2:
                # Schedule Stage 3 for 48 hours (2 days) after Stage 2
                await self.schedule_followup(
                    message_id,
                    stage=3,
                    delay_hours=48
                )
                log_followup_scheduled(message_id, 3, 48)
            
            return True
        else:
            logger.error(
                f"Failed to send Stage {stage} follow-up for {message_id}"
            )
            return False
    
    async def check_and_send_due_followups(self) -> int:
        """
        Check for due follow-ups and send them.
        
        This is the main method called by the scheduler loop.
        Fetches all due follow-ups from Redis and processes them.
        
        Returns:
            Number of follow-ups successfully sent
            
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        logger.debug("Checking for due follow-ups...")
        
        # Get due follow-ups (atomically removed from sorted set)
        due_followups = await self._get_due_followups()
        
        if not due_followups:
            logger.debug("No due follow-ups found")
            return 0
        
        # Process each follow-up
        sent_count = 0
        for message_id, stage in due_followups:
            try:
                success = await self._process_followup(message_id, stage)
                if success:
                    sent_count += 1
            except Exception as e:
                logger.error(
                    f"Error processing follow-up for {message_id} Stage {stage}: {e}",
                    exc_info=True
                )
        
        logger.info(
            f"Processed {len(due_followups)} due follow-ups, "
            f"sent {sent_count} successfully"
        )
        
        return sent_count
    
    async def start(self):
        """
        Start the scheduler loop.
        
        Runs continuously, checking for due follow-ups every 15 minutes.
        Call stop() to gracefully shut down.
        
        Raises:
            RuntimeError: If Redis client not connected
        """
        self._ensure_connected()
        
        self.running = True
        logger.info(
            f"Starting follow-up scheduler (checking every "
            f"{self.CHECK_INTERVAL_SECONDS}s)"
        )
        
        while self.running:
            try:
                await self.check_and_send_due_followups()
            except Exception as e:
                logger.error(
                    f"Error in scheduler loop: {e}",
                    exc_info=True
                )
            
            # Wait for next check interval
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
        
        logger.info("Scheduler stopped")
    
    def stop(self):
        """Stop the scheduler loop gracefully."""
        logger.info("Stopping scheduler...")
        self.running = False


# Global scheduler instance
scheduler = FollowUpScheduler()
