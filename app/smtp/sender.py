"""
SMTP sender for follow-up emails with retry logic and failure tracking.

Sends follow-up emails via Gmail SMTP with proper threading headers,
exponential backoff retry, and database failure tracking to prevent
infinite retry loops.
"""

import asyncio
from typing import Optional, Dict
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib

from app.db.connect import db
from app.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)


# Follow-up message templates
STAGE_1_TEMPLATE = (
    "Could you share your WhatsApp contact and address with me? "
    "I will ask my team to connect with you immediately."
)

STAGE_2_TEMPLATE = (
    "Just checking in — can you please share your WhatsApp contact "
    "so we can connect quickly?"
)

STAGE_3_TEMPLATE = (
    "Wanted to follow up again — we'd love to take this forward but "
    "just need your WhatsApp number to coordinate better."
)


class SMTPSender:
    """
    SMTP sender for automated follow-up emails.
    
    Handles sending follow-up emails via Gmail SMTP with:
    - Proper email threading (In-Reply-To, References headers)
    - Exponential backoff retry (2 retries)
    - Database failure tracking
    - Automatic error state marking after 3 failed sends
    """
    
    def __init__(self):
        self.smtp_server = settings.smtp_server
        self.smtp_port = settings.smtp_port
        self.max_retries = 2
        self.max_failed_sends = 3
    
    def get_template(self, stage: int) -> str:
        """
        Get message template for follow-up stage.
        
        Args:
            stage: Follow-up stage (1, 2, or 3)
            
        Returns:
            Template string for the stage
            
        Raises:
            ValueError: If stage is not 1, 2, or 3
        """
        templates = {
            1: STAGE_1_TEMPLATE,
            2: STAGE_2_TEMPLATE,
            3: STAGE_3_TEMPLATE
        }
        
        if stage not in templates:
            raise ValueError(f"Invalid stage: {stage}. Must be 1, 2, or 3")
        
        return templates[stage]
    
    def _get_account_password(self, account_email: str) -> Optional[str]:
        """
        Get app password for Gmail account from settings.
        
        Args:
            account_email: Email address of the account
            
        Returns:
            App password string, or None if not found
        """
        password = settings.get_account_password(account_email)
        if not password:
            logger.error(f"No password found for account: {account_email}")
        return password
    
    def _compose_email(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None
    ) -> MIMEMultipart:
        """
        Compose email message with proper threading headers.
        
        Args:
            from_email: Sender email address
            to_email: Recipient email address
            subject: Email subject (should match original for threading)
            body: Email body text
            in_reply_to: Message-ID of email being replied to
            references: Space-separated list of Message-IDs in thread
            
        Returns:
            Composed MIME message ready to send
        """
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Add threading headers for proper conversation grouping
        if in_reply_to:
            msg['In-Reply-To'] = in_reply_to
        
        if references:
            msg['References'] = references
        elif in_reply_to:
            # If no references but have in_reply_to, use it as references
            msg['References'] = in_reply_to
        
        # Attach body as plain text
        msg.attach(MIMEText(body, 'plain'))
        
        return msg
    
    async def _send_with_retry(
        self,
        from_email: str,
        password: str,
        to_email: str,
        message: MIMEMultipart
    ) -> bool:
        """
        Send email with exponential backoff retry.
        
        Attempts to send email up to max_retries times with exponential backoff.
        Backoff delays: 1s, 2s (total max 3 seconds of retry delay).
        
        Args:
            from_email: Sender email address
            password: Gmail app password
            to_email: Recipient email address
            message: Composed MIME message
            
        Returns:
            True if sent successfully, False if all retries failed
        """
        for attempt in range(self.max_retries + 1):
            try:
                async with aiosmtplib.SMTP(
                    hostname=self.smtp_server,
                    port=self.smtp_port,
                    use_tls=False,
                    start_tls=True
                ) as smtp:
                    await smtp.login(from_email, password)
                    await smtp.send_message(message)
                    
                    if attempt > 0:
                        logger.info(
                            f"Email sent successfully on retry {attempt} "
                            f"to {to_email}"
                        )
                    else:
                        logger.info(f"Email sent successfully to {to_email}")
                    
                    return True
            
            except aiosmtplib.SMTPAuthenticationError as e:
                logger.error(
                    f"SMTP authentication failed for {from_email}: {e}. "
                    "Check app password configuration."
                )
                return False
            
            except (
                aiosmtplib.SMTPException,
                ConnectionError,
                TimeoutError,
                OSError
            ) as e:
                if attempt == self.max_retries:
                    logger.error(
                        f"Failed to send email after {self.max_retries + 1} attempts "
                        f"to {to_email}: {e}"
                    )
                    return False
                
                # Exponential backoff: 1s, 2s
                delay = 2 ** attempt
                logger.warning(
                    f"SMTP send failed (attempt {attempt + 1}/{self.max_retries + 1}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
        
        return False
    
    async def send_followup(
        self,
        thread_data: Dict,
        stage: int
    ) -> bool:
        """
        Send follow-up email for specified stage.
        
        Handles complete follow-up send flow:
        1. Check if thread has exceeded max failed sends
        2. Get template and compose email
        3. Send with retry logic
        4. Update database on success/failure
        5. Mark thread as ERROR if max failures exceeded
        
        Args:
            thread_data: Thread record from database containing:
                - message_id: Original message ID for threading
                - thread_id: Gmail thread ID
                - account_email: Account to send from
                - creator_email: Recipient email
                - subject: Original subject line
                - failed_sends: Current failure count
            stage: Follow-up stage to send (1, 2, or 3)
            
        Returns:
            True if sent successfully, False if failed
        """
        message_id = thread_data['message_id']
        account_email = thread_data['account_email']
        creator_email = thread_data['creator_email']
        subject = thread_data.get('subject', 'Re: Collaboration Opportunity')
        failed_sends = thread_data.get('failed_sends', 0)
        
        # Check if thread has exceeded max failed sends
        if failed_sends >= self.max_failed_sends:
            logger.error(
                f"Thread {message_id} has {failed_sends} failed sends, "
                f"marking as ERROR"
            )
            await db.update_thread(
                message_id,
                status='ERROR',
                stop_reason='MAX_SEND_FAILURES'
            )
            return False
        
        # Get account password
        password = self._get_account_password(account_email)
        if not password:
            logger.error(
                f"Cannot send follow-up: no password for {account_email}"
            )
            await db.increment_failed_sends(message_id)
            return False
        
        # Get template for stage
        try:
            template = self.get_template(stage)
        except ValueError as e:
            logger.error(f"Invalid stage {stage}: {e}")
            return False
        
        # Compose email with threading headers
        # Ensure subject starts with "Re:" for proper threading
        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"
        
        message = self._compose_email(
            from_email=account_email,
            to_email=creator_email,
            subject=subject,
            body=template,
            in_reply_to=message_id,
            references=message_id
        )
        
        logger.info(
            f"Sending Stage {stage} follow-up to {creator_email} "
            f"from {account_email}"
        )
        
        # Send with retry
        success = await self._send_with_retry(
            from_email=account_email,
            password=password,
            to_email=creator_email,
            message=message
        )
        
        if success:
            # Record successful send in database
            sent_at = datetime.now()
            await db.record_followup_sent(
                message_id=message_id,
                stage=stage,
                sent_at=sent_at,
                template_used=template
            )
            
            logger.info(
                f"Successfully sent and recorded Stage {stage} follow-up "
                f"for thread {message_id}"
            )
            return True
        else:
            # Increment failure counter
            new_count = await db.increment_failed_sends(message_id)
            logger.warning(
                f"Failed to send Stage {stage} follow-up for thread {message_id}. "
                f"Failed sends: {new_count}"
            )
            
            # Check if we've hit the limit
            if new_count and new_count >= self.max_failed_sends:
                logger.error(
                    f"Thread {message_id} reached max failed sends ({new_count}), "
                    f"marking as ERROR"
                )
                await db.update_thread(
                    message_id,
                    status='ERROR',
                    stop_reason='MAX_SEND_FAILURES'
                )
            
            return False


# Global sender instance
sender = SMTPSender()
