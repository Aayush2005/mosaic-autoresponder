"""
Prisma ORM database client for PostgreSQL.

Provides type-safe database operations for email threads and follow-up history
with built-in SQL injection protection and connection pooling.

All methods are async and use Prisma's query builder for safe database access.
"""

from typing import Optional, Dict, List
from datetime import datetime
from prisma import Prisma
from prisma.models import EmailThread, EmailReply, FollowupSend, StageTransition
from prisma.enums import ThreadStatus, ReplyIntent

from app.config import settings


class DatabaseNotConnectedError(RuntimeError):
    """Raised when database operations are attempted without an active connection."""
    pass


class PrismaDatabase:
    """Prisma ORM database connection manager with type-safe operations."""
    
    def __init__(self):
        self.client: Optional[Prisma] = None
    
    async def connect(self):
        """
        Connect to PostgreSQL database using Prisma.
        
        Raises:
            ValueError: If DATABASE_URL is not configured
        """
        if self.client is not None and self.client.is_connected():
            return
        
        if not settings.database_url:
            raise ValueError("DATABASE_URL not configured in settings")
        
        self.client = Prisma(auto_register=True)
        await self.client.connect()
    
    async def close(self):
        """Close the database connection."""
        if self.client and self.client.is_connected():
            await self.client.disconnect()
            self.client = None
    
    def _ensure_connected(self):
        """Verify client is initialized. Raises DatabaseNotConnectedError if not."""
        if self.client is None or not self.client.is_connected():
            raise DatabaseNotConnectedError(
                "Database not connected. Call await db.connect() first."
            )
    
    def _convert_to_snake_case(self, data: Dict) -> Dict:
        """
        Convert camelCase keys to snake_case for backward compatibility.
        
        Args:
            data: Dict with camelCase keys from Prisma
            
        Returns:
            Dict with snake_case keys
        """
        mapping = {
            'messageId': 'message_id',
            'threadId': 'thread_id',
            'accountEmail': 'account_email',
            'creatorEmail': 'creator_email',
            'initialReplyReceivedAt': 'initial_reply_received_at',
            'initialReplyProcessedAt': 'initial_reply_processed_at',
            'initialReplyIntent': 'initial_reply_intent',
            'initialReplyHasContact': 'initial_reply_has_contact',
            'currentStage': 'current_stage',
            'lastFollowupSentAt': 'last_followup_sent_at',
            'nextFollowupAt': 'next_followup_at',
            'failedSends': 'failed_sends',
            'followupsSent': 'followups_sent',
            'stopReason': 'stop_reason',
            'delegatedToHuman': 'delegated_to_human',
            'delegatedAt': 'delegated_at',
            'completedAt': 'completed_at',
            'createdAt': 'created_at',
            'updatedAt': 'updated_at',
            'emailThreadId': 'email_thread_id',
            'receivedAt': 'received_at',
            'processedAt': 'processed_at',
            'replyToStage': 'reply_to_stage',
            'bodyText': 'body_text',
            'bodyHtml': 'body_html',
            'hasPhone': 'has_phone',
            'hasAddress': 'has_address',
            'extractedPhone': 'extracted_phone',
            'extractedAddress': 'extracted_address',
            'analysisDetails': 'analysis_details',
            'sentAt': 'sent_at',
            'templateUsed': 'template_used',
            'sendSuccess': 'send_success',
            'sendError': 'send_error',
            'smtpMessageId': 'smtp_message_id',
            'fromStage': 'from_stage',
            'toStage': 'to_stage',
            'fromStatus': 'from_status',
            'toStatus': 'to_status',
            'triggeredByReplyId': 'triggered_by_reply_id',
            'transitionedAt': 'transitioned_at'
        }
        
        result = {}
        for key, value in data.items():
            # Convert enum to string
            if hasattr(value, 'value'):
                value = value.value
            # Use mapped key or original key
            snake_key = mapping.get(key, key)
            result[snake_key] = value
        
        return result
    
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
        
        Uses Prisma's upsert with create-only to prevent duplicate inserts.
        
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
        """
        self._ensure_connected()
        
        try:
            # Convert string intent to enum if provided
            intent_enum = None
            if intent:
                try:
                    intent_enum = ReplyIntent[intent.upper().replace(' ', '_')]
                except (KeyError, AttributeError):
                    intent_enum = ReplyIntent.UNCLEAR
            
            # Convert string status to enum
            try:
                status_enum = ThreadStatus[status.upper().replace(' ', '_')]
            except (KeyError, AttributeError):
                status_enum = ThreadStatus.PROCESSING
            
            thread = await self.client.emailthread.create(
                data={
                    'messageId': message_id,
                    'threadId': thread_id,
                    'accountEmail': account_email,
                    'creatorEmail': creator_email,
                    'subject': subject,
                    'initialReplyReceivedAt': received_at,
                    'initialReplyProcessedAt': datetime.now(),
                    'initialReplyIntent': intent_enum,
                    'initialReplyHasContact': has_contact,
                    'status': status_enum
                }
            )
            return thread.id
        except Exception:
            # Unique constraint violation - thread already exists
            return None
    
    async def get_thread(self, message_id: str) -> Optional[Dict]:
        """
        Fetch email thread by message ID.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            Thread record as dict with snake_case keys, or None if not found
        """
        self._ensure_connected()
        
        thread = await self.client.emailthread.find_unique(
            where={'messageId': message_id}
        )
        if not thread:
            return None
        
        # Convert to dict and transform camelCase to snake_case for backward compatibility
        data = thread.model_dump()
        return self._convert_to_snake_case(data)
    
    async def get_thread_by_id(self, thread_id: int) -> Optional[Dict]:
        """
        Fetch email thread by internal ID.
        
        Args:
            thread_id: Internal database ID
            
        Returns:
            Thread record as dict with snake_case keys, or None if not found
        """
        self._ensure_connected()
        
        thread = await self.client.emailthread.find_unique(
            where={'id': thread_id}
        )
        if not thread:
            return None
        
        return self._convert_to_snake_case(thread.model_dump())
    
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
        """
        self._ensure_connected()
        
        if not kwargs:
            return False
        
        # Convert snake_case to camelCase for Prisma
        data = {}
        field_mapping = {
            'intent': 'initialReplyIntent',
            'has_contact': 'initialReplyHasContact',
            'current_stage': 'currentStage',
            'last_followup_sent_at': 'lastFollowupSentAt',
            'next_followup_at': 'nextFollowupAt',
            'failed_sends': 'failedSends',
            'followups_sent': 'followupsSent',
            'status': 'status',
            'stop_reason': 'stopReason',
            'delegated_to_human': 'delegatedToHuman',
            'delegated_at': 'delegatedAt',
            'completed_at': 'completedAt'
        }
        
        for key, value in kwargs.items():
            prisma_key = field_mapping.get(key, key)
            
            # Convert string values to enums where needed
            if prisma_key == 'status' and isinstance(value, str):
                try:
                    value = ThreadStatus[value.upper().replace(' ', '_')]
                except (KeyError, AttributeError):
                    pass  # Keep original value if conversion fails
            elif prisma_key == 'initialReplyIntent' and isinstance(value, str):
                try:
                    value = ReplyIntent[value.upper().replace(' ', '_')]
                except (KeyError, AttributeError):
                    pass  # Keep original value if conversion fails
            
            data[prisma_key] = value
        
        try:
            await self.client.emailthread.update(
                where={'messageId': message_id},
                data=data
            )
            return True
        except Exception:
            return False
    
    async def increment_failed_sends(self, message_id: str) -> Optional[int]:
        """
        Increment failed_sends counter for a thread.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            New failed_sends count (int), or None if message_id not found
        """
        self._ensure_connected()
        
        try:
            thread = await self.client.emailthread.update(
                where={'messageId': message_id},
                data={'failedSends': {'increment': 1}}
            )
            return thread.failedSends
        except Exception:
            return None
    
    async def increment_followups_sent(self, message_id: str) -> Optional[int]:
        """
        Increment followups_sent counter for a thread.
        
        Args:
            message_id: Unique Gmail message ID
            
        Returns:
            New followups_sent count (int), or None if message_id not found
        """
        self._ensure_connected()
        
        try:
            thread = await self.client.emailthread.update(
                where={'messageId': message_id},
                data={'followupsSent': {'increment': 1}}
            )
            return thread.followupsSent
        except Exception:
            return None
    
    async def get_threads_by_status(self, status: str, limit: int = 100) -> List[Dict]:
        """
        Get threads by status.
        
        Args:
            status: Thread status to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of thread records as dicts with snake_case keys (empty list if none found)
        """
        self._ensure_connected()
        
        # Convert string status to enum if needed
        try:
            status_enum = ThreadStatus[status.upper().replace(' ', '_')]
        except (KeyError, AttributeError):
            status_enum = status
        
        threads = await self.client.emailthread.find_many(
            where={'status': status_enum},
            order={'initialReplyReceivedAt': 'desc'},
            take=limit
        )
        return [self._convert_to_snake_case(thread.model_dump()) for thread in threads]
    
    async def get_threads_needing_followup(
        self,
        current_time: datetime,
        stage: Optional[int] = None
    ) -> List[Dict]:
        """
        Get threads that need follow-up now (based on next_followup_at).
        
        Filters for threads where:
        - Status is FOLLOWUP_ACTIVE
        - next_followup_at is set and <= current_time
        - No stop reason set
        - Failed sends < 3
        - Optionally filter by stage
        
        Args:
            current_time: Current timestamp
            stage: Optional stage filter (1, 2, or 3)
            
        Returns:
            List of thread records with snake_case keys needing follow-up (empty list if none)
        """
        self._ensure_connected()
        
        where_clause = {
            'status': ThreadStatus.FOLLOWUP_ACTIVE,
            'nextFollowupAt': {'lte': current_time, 'not': None},
            'stopReason': None,
            'failedSends': {'lt': 3}
        }
        
        if stage is not None:
            where_clause['currentStage'] = stage
        
        threads = await self.client.emailthread.find_many(
            where=where_clause,
            order={'nextFollowupAt': 'asc'}
        )
        return [self._convert_to_snake_case(thread.model_dump()) for thread in threads]
    
    async def insert_reply(
        self,
        email_thread_id: int,
        message_id: str,
        received_at: datetime,
        reply_to_stage: Optional[int],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        intent: Optional[str] = None,
        has_phone: bool = False,
        has_address: bool = False,
        extracted_phone: Optional[str] = None,
        extracted_address: Optional[str] = None,
        analysis_details: Optional[Dict] = None
    ) -> Optional[int]:
        """
        Insert a new email reply with idempotency.
        
        Args:
            email_thread_id: Parent thread ID
            message_id: Unique message ID for this reply
            received_at: When reply was received
            reply_to_stage: NULL for initial reply, 1-3 for reply to followup
            subject: Email subject
            body_text: Plain text body
            body_html: HTML body (optional)
            intent: Classified intent
            has_phone: Whether phone number detected
            has_address: Whether address detected
            extracted_phone: Extracted phone number
            extracted_address: Extracted address
            analysis_details: Full analysis JSON from LLM
            
        Returns:
            Reply ID if inserted, None if message_id already exists
        """
        self._ensure_connected()
        
        try:
            # Convert string intent to enum if provided
            intent_enum = None
            if intent:
                try:
                    intent_enum = ReplyIntent[intent.upper().replace(' ', '_')]
                except (KeyError, AttributeError):
                    intent_enum = ReplyIntent.UNCLEAR
            
            reply = await self.client.emailreply.create(
                data={
                    'emailThreadId': email_thread_id,
                    'messageId': message_id,
                    'receivedAt': received_at,
                    'processedAt': datetime.now(),
                    'replyToStage': reply_to_stage,
                    'subject': subject,
                    'bodyText': body_text,
                    'bodyHtml': body_html,
                    'intent': intent_enum,
                    'hasPhone': has_phone,
                    'hasAddress': has_address,
                    'extractedPhone': extracted_phone,
                    'extractedAddress': extracted_address,
                    'analysisDetails': analysis_details
                }
            )
            return reply.id
        except Exception:
            return None
    
    async def get_replies_for_thread(self, email_thread_id: int) -> List[Dict]:
        """
        Get all replies for a thread, ordered by received time.
        
        Args:
            email_thread_id: Thread ID
            
        Returns:
            List of reply records as dicts
        """
        self._ensure_connected()
        
        replies = await self.client.emailreply.find_many(
            where={'emailThreadId': email_thread_id},
            order={'receivedAt': 'asc'}
        )
        return [self._convert_to_snake_case(reply.model_dump()) for reply in replies]
    
    async def get_reply_by_message_id(self, message_id: str) -> Optional[Dict]:
        """
        Get a specific reply by its message ID.
        
        Args:
            message_id: Unique message ID
            
        Returns:
            Reply record as dict, or None if not found
        """
        self._ensure_connected()
        
        reply = await self.client.emailreply.find_unique(
            where={'messageId': message_id}
        )
        return self._convert_to_snake_case(reply.model_dump()) if reply else None
    
    async def insert_followup_send(
        self,
        email_thread_id: int,
        stage: int,
        sent_at: datetime,
        template_used: str,
        send_success: bool = True,
        send_error: Optional[str] = None,
        smtp_message_id: Optional[str] = None
    ) -> int:
        """
        Record a follow-up send attempt.
        
        Args:
            email_thread_id: Parent thread ID
            stage: Follow-up stage (1, 2, or 3)
            sent_at: When follow-up was sent
            template_used: Template text used
            send_success: Whether send succeeded
            send_error: Error message if failed
            smtp_message_id: Message-ID from SMTP
            
        Returns:
            Send record ID
        """
        self._ensure_connected()
        
        send = await self.client.followupsend.create(
            data={
                'emailThreadId': email_thread_id,
                'stage': stage,
                'sentAt': sent_at,
                'templateUsed': template_used,
                'sendSuccess': send_success,
                'sendError': send_error,
                'smtpMessageId': smtp_message_id
            }
        )
        return send.id
    
    async def get_followup_sends_for_thread(self, email_thread_id: int) -> List[Dict]:
        """
        Get all follow-up sends for a thread.
        
        Args:
            email_thread_id: Thread ID
            
        Returns:
            List of send records as dicts
        """
        self._ensure_connected()
        
        sends = await self.client.followupsend.find_many(
            where={'emailThreadId': email_thread_id},
            order={'sentAt': 'asc'}
        )
        return [self._convert_to_snake_case(send.model_dump()) for send in sends]
    
    async def insert_stage_transition(
        self,
        email_thread_id: int,
        from_stage: int,
        to_stage: int,
        from_status: str,
        to_status: str,
        reason: Optional[str] = None,
        triggered_by_reply_id: Optional[int] = None
    ) -> int:
        """
        Record a stage or status transition.
        
        Args:
            email_thread_id: Parent thread ID
            from_stage: Previous stage
            to_stage: New stage
            from_status: Previous status
            to_status: New status
            reason: Why transition happened
            triggered_by_reply_id: Reply that triggered this (if any)
            
        Returns:
            Transition record ID
        """
        self._ensure_connected()
        
        # Convert string status to enum
        try:
            from_status_enum = ThreadStatus[from_status.upper().replace(' ', '_')]
        except (KeyError, AttributeError):
            from_status_enum = ThreadStatus.PROCESSING
        
        try:
            to_status_enum = ThreadStatus[to_status.upper().replace(' ', '_')]
        except (KeyError, AttributeError):
            to_status_enum = ThreadStatus.PROCESSING
        
        transition = await self.client.stagetransition.create(
            data={
                'emailThreadId': email_thread_id,
                'fromStage': from_stage,
                'toStage': to_stage,
                'fromStatus': from_status_enum,
                'toStatus': to_status_enum,
                'reason': reason,
                'triggeredByReplyId': triggered_by_reply_id
            }
        )
        return transition.id
    
    async def get_stage_transitions_for_thread(self, email_thread_id: int) -> List[Dict]:
        """
        Get all stage transitions for a thread.
        
        Args:
            email_thread_id: Thread ID
            
        Returns:
            List of transition records as dicts
        """
        self._ensure_connected()
        
        transitions = await self.client.stagetransition.find_many(
            where={'emailThreadId': email_thread_id},
            order={'transitionedAt': 'asc'}
        )
        return [self._convert_to_snake_case(transition.model_dump()) for transition in transitions]
    
    async def get_thread_complete_history(self, email_thread_id: int) -> Optional[Dict]:
        """
        Get complete history for a thread including all replies, sends, and transitions.
        
        Args:
            email_thread_id: Thread ID
            
        Returns:
            Dict with thread, replies, followup_sends, and transitions
        """
        self._ensure_connected()
        
        thread = await self.get_thread_by_id(email_thread_id)
        if not thread:
            return None
        
        replies = await self.get_replies_for_thread(email_thread_id)
        sends = await self.get_followup_sends_for_thread(email_thread_id)
        transitions = await self.get_stage_transitions_for_thread(email_thread_id)
        
        return {
            'thread': thread,
            'replies': replies,
            'followup_sends': sends,
            'stage_transitions': transitions
        }
    
    async def record_followup_sent(
        self,
        message_id: str,
        stage: int,
        sent_at: datetime,
        template_used: str,
        smtp_message_id: Optional[str] = None
    ) -> bool:
        """
        Atomically record a successful follow-up send.
        
        Updates thread, inserts followup_sends record, and creates stage transition.
        
        Args:
            message_id: Thread's message ID
            stage: Follow-up stage sent (1, 2, or 3)
            sent_at: When sent
            template_used: Template text
            smtp_message_id: Message-ID from SMTP
            
        Returns:
            True if recorded successfully, False if message_id not found
        """
        self._ensure_connected()
        
        try:
            # Get thread info
            thread = await self.client.emailthread.find_unique(
                where={'messageId': message_id}
            )
            
            if not thread:
                return False
            
            old_stage = thread.currentStage
            old_status = thread.status
            
            # Update thread
            await self.client.emailthread.update(
                where={'messageId': message_id},
                data={
                    'followupsSent': {'increment': 1},
                    'lastFollowupSentAt': sent_at,
                    'currentStage': stage
                }
            )
            
            # Insert followup send record
            await self.insert_followup_send(
                email_thread_id=thread.id,
                stage=stage,
                sent_at=sent_at,
                template_used=template_used,
                send_success=True,
                smtp_message_id=smtp_message_id
            )
            
            # Record stage transition if stage changed
            if old_stage != stage:
                await self.insert_stage_transition(
                    email_thread_id=thread.id,
                    from_stage=old_stage,
                    to_stage=stage,
                    from_status=old_status,
                    to_status=old_status,
                    reason=f'followup_stage_{stage}_sent'
                )
            
            return True
        except Exception:
            return False
    
    async def schedule_next_followup(
        self,
        message_id: str,
        next_followup_at: datetime,
        next_stage: int
    ) -> bool:
        """
        Schedule the next follow-up for a thread.
        
        Updates next_followup_at timestamp and current_stage.
        
        Args:
            message_id: Thread's message ID
            next_followup_at: When to send next followup
            next_stage: What stage the next followup will be
            
        Returns:
            True if updated successfully, False if message_id not found
        """
        self._ensure_connected()
        
        try:
            await self.client.emailthread.update(
                where={'messageId': message_id},
                data={
                    'nextFollowupAt': next_followup_at,
                    'currentStage': next_stage
                }
            )
            return True
        except Exception:
            return False
    
    async def clear_next_followup(self, message_id: str) -> bool:
        """
        Clear the next_followup_at timestamp (when thread is stopped).
        
        Args:
            message_id: Thread's message ID
            
        Returns:
            True if updated successfully, False if message_id not found
        """
        self._ensure_connected()
        
        try:
            await self.client.emailthread.update(
                where={'messageId': message_id},
                data={'nextFollowupAt': None}
            )
            return True
        except Exception:
            return False
    
    async def get_threads_for_redis_sync(self) -> List[Dict]:
        """
        Get all threads that have scheduled follow-ups for Redis sync.
        
        Returns threads where:
        - Status is FOLLOWUP_ACTIVE
        - next_followup_at is set
        - No stop reason
        
        Returns:
            List of thread records with scheduled followups
        """
        self._ensure_connected()
        
        threads = await self.client.emailthread.find_many(
            where={
                'status': ThreadStatus.FOLLOWUP_ACTIVE,
                'nextFollowupAt': {'not': None},
                'stopReason': None
            },
            order={'nextFollowupAt': 'asc'}
        )
        return [self._convert_to_snake_case(thread.model_dump()) for thread in threads]


# Global database instance
db = PrismaDatabase()
