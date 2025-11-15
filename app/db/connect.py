"""
Async PostgreSQL connection and CRUD operations using asyncpg.

Provides connection pooling and basic database operations for email threads
and follow-up history with built-in idempotency.

All methods assume connect() has been called. Raises RuntimeError if pool is not initialized.
"""

import os
from typing import Optional, Dict, List
from datetime import datetime
import asyncpg


class DatabaseNotConnectedError(RuntimeError):
    """Raised when database operations are attempted without an active connection pool."""
    pass


class Database:
    """Async PostgreSQL database connection manager with connection pooling."""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self, database_url: Optional[str] = None):
        """
        Create connection pool to PostgreSQL database.
        
        Args:
            database_url: PostgreSQL connection string. If None, reads from DATABASE_URL env var.
            
        Raises:
            ValueError: If database_url is not provided and DATABASE_URL env var is not set
        """
        if self.pool is not None:
            return
        
        url = database_url or os.getenv('DATABASE_URL')
        if not url:
            raise ValueError("DATABASE_URL environment variable not set")
        
        self.pool = await asyncpg.create_pool(
            url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
    
    async def close(self):
        """Close the connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
    
    def _ensure_connected(self):
        """Verify pool is initialized. Raises DatabaseNotConnectedError if not."""
        if self.pool is None:
            raise DatabaseNotConnectedError(
                "Database pool not initialized. Call await db.connect() first."
            )
    
    async def insert_thread(
        self,
        message_id: str,
        thread_id: str,
        account_email: str,
        creator_email: str,
        subject: str,
        received_at: datetime,
        intent: Optional[str] = None,
        has_contact: bool = False,
        status: str = 'PROCESSING'
    ) -> Optional[int]:
        """
        Insert new email thread with idempotency.
        
        Uses ON CONFLICT (message_id) DO NOTHING to prevent duplicate inserts.
        
        Args:
            message_id: Unique Gmail message ID
            thread_id: Gmail thread ID
            account_email: Which account received the email
            creator_email: Creator's email address
            subject: Email subject line
            received_at: When email was received
            intent: Classified intent (optional)
            has_contact: Whether contact details were found
            status: Thread status (default: PROCESSING)
            
        Returns:
            Thread ID (int) if successfully inserted.
            None if message_id already exists (conflict).
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            INSERT INTO email_threads (
                message_id, thread_id, account_email, creator_email,
                subject, received_at, intent, has_contact, status, processed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING id
        """
        
        async with self.pool.acquire() as conn:
            # fetchval returns None on conflict (no row returned)
            result = await conn.fetchval(
                query,
                message_id, thread_id, account_email, creator_email,
                subject, received_at, intent, has_contact, status, datetime.now()
            )
            return result  # int if inserted, None if conflict
    
    async def get_thread(self, message_id: str) -> Optional[Dict]:
        """
        Fetch email thread by message ID.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            Thread record as dict, or None if not found
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            SELECT * FROM email_threads WHERE message_id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, message_id)
            return dict(row) if row else None
    
    async def get_thread_by_id(self, thread_id: int) -> Optional[Dict]:
        """
        Fetch email thread by internal ID.
        
        Args:
            thread_id: Internal database ID
            
        Returns:
            Thread record as dict, or None if not found
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            SELECT * FROM email_threads WHERE id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, thread_id)
            return dict(row) if row else None
    
    async def update_thread(
        self,
        message_id: str,
        **kwargs
    ) -> bool:
        """
        Update email thread fields.
        
        Args:
            message_id: Unique Gmail message ID
            **kwargs: Fields to update (intent, has_contact, current_stage, status, etc.)
            
        Returns:
            True if row was updated, False if not found or no fields provided
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        if not kwargs:
            return False
        
        set_clauses = []
        values = []
        param_num = 1
        
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ${param_num}")
            values.append(value)
            param_num += 1
        
        values.append(message_id)
        
        query = f"""
            UPDATE email_threads
            SET {', '.join(set_clauses)}
            WHERE message_id = ${param_num}
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *values)
            return result != 'UPDATE 0'

    async def increment_failed_sends(self, message_id: str) -> Optional[int]:
        """
        Increment failed_sends counter for a thread.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            New failed_sends count (int), or None if message_id not found
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            UPDATE email_threads
            SET failed_sends = failed_sends + 1
            WHERE message_id = $1
            RETURNING failed_sends
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, message_id)
            return result  # int or None
    
    async def increment_followups_sent(self, message_id: str) -> Optional[int]:
        """
        Increment followups_sent counter for a thread.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            New followups_sent count (int), or None if message_id not found
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            UPDATE email_threads
            SET followups_sent = followups_sent + 1
            WHERE message_id = $1
            RETURNING followups_sent
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, message_id)
            return result  # int or None
    
    async def insert_followup_history(
        self,
        email_thread_id: int,
        stage: int,
        sent_at: datetime,
        template_used: str
    ) -> int:
        """
        Record a follow-up action in history.
        
        Args:
            email_thread_id: Internal thread ID
            stage: Follow-up stage (1, 2, or 3)
            sent_at: When follow-up was sent
            template_used: Template text that was used
            
        Returns:
            History record ID (int)
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            INSERT INTO followup_history (email_thread_id, stage, sent_at, template_used)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, email_thread_id, stage, sent_at, template_used)
            return result
    
    async def get_followup_history(self, email_thread_id: int) -> List[Dict]:
        """
        Get all follow-up history for a thread.
        
        Args:
            email_thread_id: Internal thread ID
            
        Returns:
            List of history records as dicts (empty list if none found)
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            SELECT * FROM followup_history
            WHERE email_thread_id = $1
            ORDER BY sent_at ASC
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, email_thread_id)
            return [dict(row) for row in rows]
    
    async def get_threads_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """
        Get threads by status.
        
        Args:
            status: Thread status to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of thread records as dicts (empty list if none found)
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            SELECT * FROM email_threads
            WHERE status = $1
            ORDER BY received_at DESC
            LIMIT $2
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, status, limit)
            return [dict(row) for row in rows]
    
    async def get_threads_needing_followup(
        self,
        current_time: datetime,
        stage: int
    ) -> List[Dict]:
        """
        Get threads that need follow-up at specified stage.
        
        Filters for threads where:
        - Status is FOLLOWUP_ACTIVE
        - Current stage matches requested stage
        - Number of followups sent is less than the stage (idempotency check)
        - No stop reason set
        - Failed sends < 3
        - Last followup was sent before current_time (ready to send)
        
        Args:
            current_time: Current timestamp to check against last_followup_sent_at
            stage: Stage to check for (1, 2, or 3)
            
        Returns:
            List of thread records needing follow-up (empty list if none)
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        query = """
            SELECT * FROM email_threads
            WHERE status = 'FOLLOWUP_ACTIVE'
            AND current_stage = $1
            AND followups_sent < $2
            AND stop_reason IS NULL
            AND failed_sends < 3
            AND (last_followup_sent_at IS NULL OR last_followup_sent_at <= $3)
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, stage, stage, current_time)
            return [dict(row) for row in rows]
    
    async def record_followup_sent(
        self,
        message_id: str,
        stage: int,
        sent_at: datetime,
        template_used: str
    ) -> bool:
        """
        Atomically record a successful follow-up send.
        
        Updates thread counters and inserts history record in a single transaction
        to prevent race conditions.
        
        Args:
            message_id: Unique Gmail message ID
            stage: Follow-up stage that was sent (1, 2, or 3)
            sent_at: When follow-up was sent
            template_used: Template text that was used
            
        Returns:
            True if recorded successfully, False if message_id not found
            
        Raises:
            DatabaseNotConnectedError: If connect() hasn't been called
        """
        self._ensure_connected()
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Update thread counters and timestamp
                update_query = """
                    UPDATE email_threads
                    SET followups_sent = followups_sent + 1,
                        last_followup_sent_at = $2
                    WHERE message_id = $1
                    RETURNING id
                """
                thread_id = await conn.fetchval(update_query, message_id, sent_at)
                
                if thread_id is None:
                    return False
                
                # Insert history record
                history_query = """
                    INSERT INTO followup_history (email_thread_id, stage, sent_at, template_used)
                    VALUES ($1, $2, $3, $4)
                """
                await conn.execute(history_query, thread_id, stage, sent_at, template_used)
                
                return True


# Global database instance
db = Database()
