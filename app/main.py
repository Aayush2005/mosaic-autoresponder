"""
Main application loop for automated follow-up system.

Orchestrates the complete email processing pipeline:
1. Poll IMAP for new replies (every 60 seconds)
2. Process emails concurrently (max 10 at a time)
3. Run scheduler checks (every 15 minutes)

Uses asyncio for concurrent processing with proper error handling
and graceful shutdown.
"""

import asyncio
import signal
from typing import List, Dict
from datetime import datetime

from app.config import settings
from app.db.prisma_client import db
from app.core.scheduler import scheduler
from app.core.decision_router import route_email, Action
from app.imap.watcher import IMAPWatcher
from app.imap.controller import controller
from app.smtp.sender import sender
from app.utils.logger import (
    get_logger,
    log_email_received,
    log_intent_classified,
    log_followup_sent,
    log_followup_scheduled,
    log_automation_stopped,
    log_delegated_to_human
)


logger = get_logger(__name__)


class Application:
    """
    Main application orchestrator.
    
    Manages the complete lifecycle of the automated follow-up system:
    - IMAP watching for new replies
    - Concurrent email processing with semaphore
    - Scheduler for delayed follow-ups
    - Graceful shutdown on signals
    """
    
    def __init__(self):
        self.running = False
        self.watcher: IMAPWatcher = None
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_workers)
        self.scheduler_task = None
        self.watcher_task = None
    
    async def initialize(self):
        """
        Initialize all system components.
        
        Connects to database, Redis, and prepares IMAP watcher.
        """
        logger.info("Initializing application...")
        
        # Connect to database
        await db.connect()
        logger.info("Database connected")
        
        # Connect to Redis for scheduler
        await scheduler.connect()
        logger.info("Redis connected")
        
        # Initialize IMAP watcher
        self.watcher = IMAPWatcher(polling_interval=settings.polling_interval)
        logger.info("IMAP watcher initialized")
        
        logger.info("Application initialized successfully")
    
    async def shutdown(self):
        """
        Gracefully shutdown all system components.
        
        Stops watcher, scheduler, and closes all connections.
        """
        logger.info("Shutting down application...")
        
        self.running = False
        
        # Stop watcher
        if self.watcher:
            await self.watcher.stop()
        
        # Stop scheduler
        if scheduler.running:
            scheduler.stop()
        
        # Wait for tasks to complete
        if self.scheduler_task and not self.scheduler_task.done():
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass
        
        if self.watcher_task and not self.watcher_task.done():
            self.watcher_task.cancel()
            try:
                await self.watcher_task
            except asyncio.CancelledError:
                pass
        
        # Close connections
        await controller.close_all()
        await scheduler.close()
        await db.close()
        
        logger.info("Application shutdown complete")
    
    async def process_email(self, email_data: Dict) -> bool:
        """
        Process a single email through the complete pipeline.
        
        Steps:
        1. Extract email details
        2. Route email to determine action
        3. Execute action (send follow-up, delegate, or mark complete)
        4. Update database and mark email as read/unread
        
        Args:
            email_data: Parsed email dict from IMAP watcher
            
        Returns:
            True if processed successfully, False otherwise
        """
        message_id = email_data.get('message_id')
        account_email = email_data.get('account_email')
        creator_email = email_data.get('from_email')
        subject = email_data.get('subject', '')
        body = email_data.get('body', '')
        thread_id = email_data.get('thread_id')
        
        if not message_id or not body:
            logger.warning(f"Invalid email data: missing message_id or body")
            return False
        
        # Log email received
        log_email_received(message_id, creator_email, account_email)
        
        try:
            # Check if thread already processed and delegated/completed
            existing_thread = await db.get_thread(message_id)
            if existing_thread:
                status = existing_thread.get('status')
                if status in ['DELEGATED', 'COMPLETED']:
                    logger.info(
                        f"Thread {message_id} already processed with status {status}, skipping"
                    )
                    # Ensure delegated emails remain unread for human review
                    if status == 'DELEGATED':
                        await controller.mark_as_unread(account_email, message_id)
                        logger.info(f"Ensured {message_id} is marked as unread for human review")
                    return True
            
            # Route email to determine action
            decision = await route_email(message_id, body)
            
            action = decision['action']
            reason = decision['reason']
            update_fields = decision['update_fields']
            analysis = decision.get('analysis', {})
            
            # Log intent classification
            intent = analysis.get('intent')
            has_contact = analysis.get('has_phone', False) or analysis.get('has_address', False)
            if intent:
                log_intent_classified(message_id, intent, has_contact)
            
            logger.info(
                f"Decision for {message_id}: {action.value} (reason: {reason})"
            )
            
            # Check if thread already exists
            existing_thread = await db.get_thread(message_id)
            
            if not existing_thread:
                # Insert new thread
                received_at = datetime.now()
                thread_db_id = await db.insert_thread(
                    message_id=message_id,
                    thread_id=thread_id,
                    account_email=account_email,
                    creator_email=creator_email,
                    subject=subject,
                    received_at=received_at,
                    intent=analysis.get('intent'),
                    has_contact=analysis.get('has_phone', False) or analysis.get('has_address', False),
                    status=update_fields.get('status', 'PROCESSING')
                )
                
                if thread_db_id is None:
                    logger.warning(
                        f"Thread {message_id} already exists (race condition), "
                        f"skipping insert"
                    )
                else:
                    logger.info(f"Created new thread record for {message_id}")
            
            # Update thread with decision results
            await db.update_thread(message_id, **update_fields)
            
            # Execute action
            if action == Action.SEND_STAGE_1_FOLLOWUP:
                # Mark email as read
                await controller.mark_as_read(account_email, message_id)
                
                # Send Stage 1 follow-up
                thread_data = await db.get_thread(message_id)
                if thread_data:
                    success = await sender.send_followup(thread_data, stage=1)
                    
                    if success:
                        # Log follow-up sent
                        log_followup_sent(message_id, 1, creator_email)
                        
                        # Schedule Stage 2 for 24 hours later
                        await scheduler.schedule_followup(
                            message_id=message_id,
                            stage=2,
                            delay_hours=24
                        )
                        
                        # Log follow-up scheduled
                        log_followup_scheduled(message_id, 2, 24)
                        
                        logger.info(
                            f"Sent Stage 1 follow-up and scheduled Stage 2 "
                            f"for {message_id}"
                        )
                    else:
                        logger.error(
                            f"Failed to send Stage 1 follow-up for {message_id}"
                        )
                else:
                    logger.error(
                        f"Could not retrieve thread data for {message_id}"
                    )
            
            elif action == Action.DELEGATE_TO_HUMAN:
                # Mark email as unread for human attention
                await controller.mark_as_unread(account_email, message_id)
                
                # Log delegation
                log_delegated_to_human(message_id, reason)
                
                logger.info(
                    f"Marked {message_id} as unread for human review "
                    f"(reason: {reason})"
                )
                
                # Cancel any scheduled follow-ups
                await scheduler.cancel_followup(message_id)
                
                # Log automation stopped
                log_automation_stopped(message_id, reason)
            
            elif action == Action.MARK_COMPLETE:
                # Mark email as read
                await controller.mark_as_read(account_email, message_id)
                
                # Log automation stopped
                log_automation_stopped(message_id, reason)
                
                logger.info(
                    f"Marked {message_id} as complete (reason: {reason})"
                )
                
                # Cancel any scheduled follow-ups
                await scheduler.cancel_followup(message_id)
            
            elif action == Action.SKIP:
                logger.info(f"Skipping {message_id} (reason: {reason})")
            
            return True
        
        except Exception as e:
            logger.error(
                f"Error processing email {message_id}: {e}",
                exc_info=True
            )
            return False
    
    async def safe_process_email(self, email_data: Dict):
        """
        Process email with semaphore for concurrency control.
        
        Limits concurrent processing to max_concurrent_workers using semaphore.
        
        Args:
            email_data: Parsed email dict from IMAP watcher
        """
        async with self.semaphore:
            await self.process_email(email_data)
    
    async def process_batch(self, emails: List[Dict]):
        """
        Process a batch of emails concurrently.
        
        Uses asyncio.gather with return_exceptions=True to handle errors
        gracefully without stopping other email processing.
        
        Args:
            emails: List of parsed email dicts
        """
        if not emails:
            return
        
        logger.info(f"Processing batch of {len(emails)} emails")
        
        # Process all emails concurrently with semaphore limiting concurrency
        results = await asyncio.gather(
            *[self.safe_process_email(email) for email in emails],
            return_exceptions=True
        )
        
        # Log any exceptions
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    f"Exception processing email {i}: {result}",
                    exc_info=result
                )
        
        success_count = sum(1 for r in results if r is True)
        logger.info(
            f"Batch complete: {success_count}/{len(emails)} processed successfully"
        )
    
    async def run_watcher_loop(self):
        """
        Run IMAP watcher loop.
        
        Polls IMAP servers for new replies and processes them in batches.
        """
        logger.info("Starting IMAP watcher loop")
        
        while self.running:
            try:
                # Fetch new replies from all accounts
                replies = await self.watcher.watch_all_accounts()
                
                if replies:
                    # Process batch concurrently
                    await self.process_batch(replies)
                
                # Wait for next polling interval
                await asyncio.sleep(settings.polling_interval)
            
            except Exception as e:
                logger.error(
                    f"Error in watcher loop: {e}",
                    exc_info=True
                )
                await asyncio.sleep(settings.polling_interval)
    
    async def run_scheduler_loop(self):
        """
        Run scheduler loop.
        
        Checks for due follow-ups every 15 minutes and sends them.
        """
        logger.info("Starting scheduler loop")
        
        while self.running:
            try:
                await scheduler.check_and_send_due_followups()
                
                # Wait for next check interval (15 minutes)
                await asyncio.sleep(scheduler.CHECK_INTERVAL_SECONDS)
            
            except Exception as e:
                logger.error(
                    f"Error in scheduler loop: {e}",
                    exc_info=True
                )
                await asyncio.sleep(scheduler.CHECK_INTERVAL_SECONDS)
    
    async def run(self):
        """
        Run the main application.
        
        Starts both watcher and scheduler loops concurrently.
        Runs until shutdown signal received.
        """
        self.running = True
        
        logger.info("Starting automated follow-up system")
        logger.info(f"Polling interval: {settings.polling_interval}s")
        logger.info(f"Max concurrent workers: {settings.max_concurrent_workers}")
        logger.info(f"Scheduler check interval: {scheduler.CHECK_INTERVAL_SECONDS}s")
        
        # Start both loops concurrently
        self.watcher_task = asyncio.create_task(self.run_watcher_loop())
        self.scheduler_task = asyncio.create_task(self.run_scheduler_loop())
        
        # Wait for both tasks (they run until shutdown)
        await asyncio.gather(
            self.watcher_task,
            self.scheduler_task,
            return_exceptions=True
        )


async def main():
    """
    Main entry point for the application.
    
    Initializes the application, sets up signal handlers for graceful shutdown,
    and runs the main loop.
    """
    app = Application()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(app.shutdown())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Initialize all components
        await app.initialize()
        
        # Run main application loop
        await app.run()
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    
    finally:
        # Ensure cleanup happens
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
