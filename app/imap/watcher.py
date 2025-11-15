"""
IMAP watcher for monitoring 3 Gmail accounts.

Polls Gmail IMAP servers for new unseen emails, filters replies to outreach,
and handles connection failures with exponential backoff.
"""

import asyncio
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime
import aioimaplib

from app.imap.parser import parse_email


logger = logging.getLogger(__name__)


class IMAPConnectionError(Exception):
    """Raised when IMAP connection fails."""
    pass


class IMAPAuthenticationError(Exception):
    """Raised when IMAP authentication fails."""
    pass


class IMAPWatcher:
    """
    Monitor multiple Gmail accounts for new email replies.
    
    Polls IMAP servers at regular intervals, fetches unseen emails,
    and filters for replies to outreach messages. Handles connection
    failures with exponential backoff and stops retrying on auth errors.
    """
    
    def __init__(self, polling_interval: int = 60):
        """
        Initialize IMAP watcher.
        
        Args:
            polling_interval: Seconds between polling cycles (default: 60)
        """
        self.polling_interval = polling_interval
        self.accounts = self._load_accounts()
        self.connections: Dict[str, Optional[aioimaplib.IMAP4_SSL]] = {}
        self.running = False
    
    def _load_accounts(self) -> List[Dict[str, str]]:
        """
        Load Gmail account configurations from environment variables.
        
        Returns:
            List of account configs with email, password, imap_server, imap_port
            
        Raises:
            ValueError: If required environment variables are missing
        """
        accounts = []
        
        for i in range(1, 4):
            email = os.getenv(f'GMAIL_ACCOUNT_{i}_EMAIL')
            password = os.getenv(f'GMAIL_ACCOUNT_{i}_PASSWORD')
            
            if not email or not password:
                raise ValueError(
                    f"Missing GMAIL_ACCOUNT_{i}_EMAIL or GMAIL_ACCOUNT_{i}_PASSWORD"
                )
            
            accounts.append({
                'email': email,
                'password': password,
                'imap_server': os.getenv('IMAP_SERVER', 'imap.gmail.com'),
                'imap_port': int(os.getenv('IMAP_PORT', '993'))
            })
        
        return accounts
    
    async def connect_with_backoff(
        self,
        account: Dict[str, str],
        max_retries: int = 5
    ) -> aioimaplib.IMAP4_SSL:
        """
        Connect to IMAP server with exponential backoff.
        
        Retries connection failures with exponential backoff.
        Stops retrying immediately on authentication errors to avoid lockouts.
        
        Args:
            account: Account config dict
            max_retries: Maximum connection attempts (default: 5)
            
        Returns:
            Connected IMAP client
            
        Raises:
            IMAPAuthenticationError: If authentication fails (no retry)
            IMAPConnectionError: If connection fails after all retries
        """
        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Connecting to IMAP for {account['email']} "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                
                client = aioimaplib.IMAP4_SSL(
                    host=account['imap_server'],
                    port=account['imap_port']
                )
                
                await client.wait_hello_from_server()
                
                response = await client.login(account['email'], account['password'])
                
                if response.result != 'OK':
                    raise IMAPAuthenticationError(
                        f"Authentication failed for {account['email']}: {response}"
                    )
                
                logger.info(f"Successfully connected to IMAP for {account['email']}")
                return client
                
            except IMAPAuthenticationError:
                logger.error(
                    f"Authentication failed for {account['email']} - stopping retries "
                    "to avoid account lockout"
                )
                raise
                
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to connect to IMAP for {account['email']} "
                        f"after {max_retries} attempts: {e}"
                    )
                    raise IMAPConnectionError(
                        f"Connection failed after {max_retries} attempts"
                    ) from e
                
                wait_time = 2 ** attempt
                logger.warning(
                    f"IMAP connection failed for {account['email']}: {e}. "
                    f"Retrying in {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
        
        raise IMAPConnectionError("Unexpected error in connection loop")
    
    async def ensure_connection(self, account: Dict[str, str]) -> aioimaplib.IMAP4_SSL:
        """
        Ensure active IMAP connection for account.
        
        Reuses existing connection if available, otherwise creates new one.
        
        Args:
            account: Account config dict
            
        Returns:
            Connected IMAP client
        """
        email = account['email']
        
        if email in self.connections and self.connections[email]:
            try:
                await self.connections[email].noop()
                return self.connections[email]
            except Exception as e:
                logger.warning(f"Existing connection dead for {email}: {e}")
                self.connections[email] = None
        
        client = await self.connect_with_backoff(account)
        self.connections[email] = client
        return client
    
    async def fetch_new_replies(self, account: Dict[str, str]) -> List[Dict]:
        """
        Fetch new unseen emails from account inbox.
        
        Selects INBOX, searches for unseen messages, and fetches their content.
        
        Args:
            account: Account config dict
            
        Returns:
            List of parsed email dicts
        """
        try:
            client = await self.ensure_connection(account)
            
            await client.select('INBOX')
            
            response = await client.search('UNSEEN')
            
            if response.result != 'OK':
                logger.warning(f"Search failed for {account['email']}: {response}")
                return []
            
            message_ids = response.lines[0].decode().strip().split()
            
            if not message_ids or message_ids == [b'']:
                return []
            
            logger.info(
                f"Found {len(message_ids)} unseen emails in {account['email']}"
            )
            
            emails = []
            
            for msg_id in message_ids:
                try:
                    fetch_response = await client.fetch(msg_id, '(RFC822)')
                    
                    if fetch_response.result != 'OK':
                        logger.warning(
                            f"Failed to fetch message {msg_id} from {account['email']}"
                        )
                        continue
                    
                    raw_email = None
                    for line in fetch_response.lines:
                        if isinstance(line, bytes) and line.startswith(b'From:'):
                            raw_email = line
                            break
                        elif isinstance(line, tuple) and len(line) > 1:
                            raw_email = line[1]
                            break
                    
                    if not raw_email:
                        logger.warning(
                            f"Could not extract raw email for message {msg_id}"
                        )
                        continue
                    
                    parsed = parse_email(raw_email)
                    parsed['account_email'] = account['email']
                    parsed['imap_uid'] = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    
                    emails.append(parsed)
                    
                except Exception as e:
                    logger.error(
                        f"Error parsing message {msg_id} from {account['email']}: {e}",
                        exc_info=True
                    )
                    continue
            
            return emails
            
        except Exception as e:
            logger.error(
                f"Error fetching emails from {account['email']}: {e}",
                exc_info=True
            )
            return []
    
    def is_reply_to_outreach(self, email_data: Dict) -> bool:
        """
        Check if email is a reply to an outreach message.
        
        Filters based on:
        - Has thread_id (is a reply, not new message)
        - Subject contains "Re:" or similar reply indicators
        
        Args:
            email_data: Parsed email dict
            
        Returns:
            True if email is a reply to outreach
        """
        thread_id = email_data.get('thread_id', '')
        message_id = email_data.get('message_id', '')
        subject = email_data.get('subject', '').lower()
        
        if thread_id and thread_id != message_id:
            return True
        
        if subject.startswith('re:') or subject.startswith('fwd:'):
            return True
        
        return False
    
    async def watch_account(self, account: Dict[str, str]) -> List[Dict]:
        """
        Watch single account for new replies.
        
        Fetches unseen emails and filters for replies to outreach.
        
        Args:
            account: Account config dict
            
        Returns:
            List of reply emails
        """
        try:
            emails = await self.fetch_new_replies(account)
            
            replies = [
                email for email in emails
                if self.is_reply_to_outreach(email)
            ]
            
            if replies:
                logger.info(
                    f"Found {len(replies)} replies to outreach in {account['email']}"
                )
            
            return replies
            
        except IMAPAuthenticationError:
            logger.error(
                f"Authentication error for {account['email']} - skipping this account"
            )
            return []
            
        except Exception as e:
            logger.error(
                f"Error watching account {account['email']}: {e}",
                exc_info=True
            )
            return []
    
    async def watch_all_accounts(self) -> List[Dict]:
        """
        Watch all configured accounts concurrently.
        
        Returns:
            Combined list of replies from all accounts
        """
        tasks = [self.watch_account(account) for account in self.accounts]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_replies = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Account watch failed: {result}")
            elif isinstance(result, list):
                all_replies.extend(result)
        
        return all_replies
    
    async def start(self, callback=None):
        """
        Start watching all accounts with polling loop.
        
        Polls accounts at regular intervals and calls callback with new replies.
        
        Args:
            callback: Async function to call with list of new replies
        """
        self.running = True
        logger.info(
            f"Starting IMAP watcher for {len(self.accounts)} accounts "
            f"(polling every {self.polling_interval}s)"
        )
        
        while self.running:
            try:
                replies = await self.watch_all_accounts()
                
                if replies and callback:
                    await callback(replies)
                
                await asyncio.sleep(self.polling_interval)
                
            except Exception as e:
                logger.error(f"Error in watcher loop: {e}", exc_info=True)
                await asyncio.sleep(self.polling_interval)
    
    async def stop(self):
        """Stop the watcher and close all connections."""
        self.running = False
        logger.info("Stopping IMAP watcher")
        
        for email, client in self.connections.items():
            if client:
                try:
                    await client.logout()
                    logger.info(f"Closed connection for {email}")
                except Exception as e:
                    logger.warning(f"Error closing connection for {email}: {e}")
        
        self.connections.clear()


async def start_watcher(callback=None, polling_interval: int = 60):
    """
    Convenience function to start IMAP watcher.
    
    Args:
        callback: Async function to call with new replies
        polling_interval: Seconds between polls (default: 60)
        
    Returns:
        IMAPWatcher instance
    """
    watcher = IMAPWatcher(polling_interval=polling_interval)
    await watcher.start(callback=callback)
    return watcher
