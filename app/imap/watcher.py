"""
IMAP watcher for monitoring 3 Gmail accounts.

Polls Gmail IMAP servers for new unseen emails, filters replies to outreach,
and handles connection failures with exponential backoff.
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import aioimaplib

from app.config import settings
from app.imap.parser import parse_email
from app.utils.logger import get_logger


logger = get_logger(__name__)


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
        Load Gmail account configurations from settings.
        
        Returns:
            List of account configs with email, password, imap_server, imap_port
            
        Raises:
            ValueError: If required settings are missing
        """
        accounts = []
        
        for email in settings.all_account_emails:
            password = settings.get_account_password(email)
            
            if not email or not password:
                raise ValueError(
                    f"Missing email or password for account: {email}"
                )
            
            accounts.append({
                'email': email,
                'password': password,
                'imap_server': settings.imap_server,
                'imap_port': settings.imap_port
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
        Fetch new unseen emails from account inbox (last 7 days only).
        
        Selects INBOX, searches for unseen messages from the last 7 days,
        and fetches their content.
        
        Args:
            account: Account config dict
            
        Returns:
            List of parsed email dicts
        """
        try:
            client = await self.ensure_connection(account)
            
            await client.select('INBOX')
            
            # Calculate date 7 days ago in IMAP format (DD-Mon-YYYY)
            seven_days_ago = datetime.now() - timedelta(days=7)
            date_str = seven_days_ago.strftime('%d-%b-%Y')
            
            # Search for unseen emails from last 7 days
            search_criteria = f'UNSEEN SINCE {date_str}'
            response = await client.search(search_criteria)
            
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
            
            for idx, msg_id in enumerate(message_ids):
                logger.info(f"Processing message {idx+1}/{len(message_ids)}: {msg_id}")
                try:
                    fetch_response = await client.fetch(msg_id, '(RFC822)')
                    
                    if fetch_response.result != 'OK':
                        logger.warning(
                            f"Failed to fetch message {msg_id} from {account['email']}"
                        )
                        continue
                    
                    # Extract raw email from IMAP response
                    # Response format varies by server, try multiple approaches
                    raw_email = None
                    
                    # Debug: log response structure
                    logger.debug(f"FETCH response has {len(fetch_response.lines)} lines")
                    
                    for idx, line in enumerate(fetch_response.lines):
                        logger.debug(f"Line {idx}: type={type(line)}, len={len(line) if isinstance(line, (bytes, bytearray, tuple, list)) else 'N/A'}")
                        
                        # Approach 1: Tuple with email data
                        if isinstance(line, tuple):
                            for part in line:
                                if isinstance(part, (bytes, bytearray)) and len(part) > 100:
                                    raw_email = bytes(part) if isinstance(part, bytearray) else part
                                    logger.debug(f"Found email in tuple part, size={len(part)}")
                                    break
                        
                        # Approach 2: Direct bytes or bytearray with email headers
                        elif isinstance(line, (bytes, bytearray)):
                            if len(line) > 100 and (b'From:' in line or b'Return-Path:' in line or b'Received:' in line):
                                raw_email = bytes(line) if isinstance(line, bytearray) else line
                                logger.debug(f"Found email as direct bytes/bytearray, size={len(line)}")
                                break
                            # Sometimes the email is in a smaller chunk
                            elif b'RFC822' in line:
                                # Next line might have the email
                                if idx + 1 < len(fetch_response.lines):
                                    next_line = fetch_response.lines[idx + 1]
                                    if isinstance(next_line, (bytes, bytearray)) and len(next_line) > 100:
                                        raw_email = bytes(next_line) if isinstance(next_line, bytearray) else next_line
                                        logger.debug(f"Found email in next line after RFC822, size={len(next_line)}")
                                        break
                        
                        if raw_email:
                            break
                    
                    if not raw_email:
                        logger.warning(
                            f"Could not extract raw email for message {msg_id}, "
                            f"response lines: {len(fetch_response.lines)}, "
                            f"line types: {[type(l).__name__ for l in fetch_response.lines]}"
                        )
                        continue
                    
                    logger.info(f"Successfully extracted raw email for message {msg_id}")
                    
                    parsed = parse_email(raw_email)
                    parsed['account_email'] = account['email']
                    parsed['imap_uid'] = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
                    
                    logger.info(
                        f"Parsed email: subject='{parsed.get('subject', 'N/A')}', "
                        f"from={parsed.get('from_email', 'N/A')}"
                    )
                    
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
        
        # Debug logging
        logger.debug(
            f"Checking if reply: subject='{subject}', "
            f"thread_id='{thread_id[:50] if thread_id else 'None'}', "
            f"message_id='{message_id[:50] if message_id else 'None'}', "
            f"is_different={thread_id != message_id}"
        )
        
        if thread_id and thread_id != message_id:
            logger.info(f"Email identified as reply (different thread_id): {subject}")
            return True
        
        if subject.startswith('re:') or subject.startswith('fwd:'):
            logger.info(f"Email identified as reply (Re:/Fwd: in subject): {subject}")
            return True
        
        logger.debug(f"Email NOT identified as reply: {subject}")
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
            
            logger.info(f"Filtering {len(emails)} emails for replies to outreach...")
            
            replies = [
                email for email in emails
                if self.is_reply_to_outreach(email)
            ]
            
            logger.info(
                f"Found {len(replies)} replies to outreach out of {len(emails)} total emails "
                f"in {account['email']}"
            )
            
            if replies:
                logger.info(
                    f"Reply subjects: {[e.get('subject', 'N/A') for e in replies]}"
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
