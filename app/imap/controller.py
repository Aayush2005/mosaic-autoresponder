"""
IMAP controller for marking emails as read/unread.

Provides functions to set and remove the Seen flag on Gmail messages
via IMAP, with graceful error handling for connection issues.
"""

import asyncio
from typing import Dict, Optional
import aioimaplib

from app.config import settings
from app.utils.logger import get_logger


logger = get_logger(__name__)


class IMAPController:
    """
    Control IMAP flags for email messages.
    
    Manages connections to Gmail IMAP servers and provides methods
    to mark messages as read or unread. Handles connection errors
    gracefully with automatic reconnection.
    """
    
    def __init__(self):
        """Initialize IMAP controller."""
        self.connections: Dict[str, Optional[aioimaplib.IMAP4_SSL]] = {}
        self.accounts = self._load_accounts()
    
    def _load_accounts(self) -> Dict[str, Dict[str, str]]:
        """
        Load Gmail account configurations from settings.
        
        Returns:
            Dict mapping email addresses to account configs
        """
        accounts = {}
        
        for email in settings.all_account_emails:
            password = settings.get_account_password(email)
            if email and password:
                accounts[email] = {
                    'email': email,
                    'password': password,
                    'imap_server': settings.imap_server,
                    'imap_port': settings.imap_port
                }
        
        return accounts
    
    async def _connect(self, account_email: str) -> Optional[aioimaplib.IMAP4_SSL]:
        """
        Connect to IMAP server for account.
        
        Args:
            account_email: Email address of account
            
        Returns:
            Connected IMAP client, or None if connection fails
        """
        if account_email not in self.accounts:
            logger.error(f"Account {account_email} not configured")
            return None
        
        account = self.accounts[account_email]
        
        try:
            client = aioimaplib.IMAP4_SSL(
                host=account['imap_server'],
                port=account['imap_port']
            )
            
            await client.wait_hello_from_server()
            
            response = await client.login(account['email'], account['password'])
            
            if response.result != 'OK':
                logger.error(f"Authentication failed for {account_email}")
                return None
            
            logger.debug(f"Connected to IMAP for {account_email}")
            return client
            
        except Exception as e:
            logger.error(f"Failed to connect to IMAP for {account_email}: {e}")
            return None
    
    async def _ensure_connection(self, account_email: str) -> Optional[aioimaplib.IMAP4_SSL]:
        """
        Ensure active IMAP connection for account.
        
        Reuses existing connection if available, otherwise creates new one.
        
        Args:
            account_email: Email address of account
            
        Returns:
            Connected IMAP client, or None if connection fails
        """
        if account_email in self.connections and self.connections[account_email]:
            try:
                await self.connections[account_email].noop()
                return self.connections[account_email]
            except Exception:
                logger.debug(f"Existing connection dead for {account_email}, reconnecting")
                self.connections[account_email] = None
        
        client = await self._connect(account_email)
        if client:
            self.connections[account_email] = client
        
        return client
    
    async def _find_message_by_id(
        self,
        client: aioimaplib.IMAP4_SSL,
        message_id: str
    ) -> Optional[str]:
        """
        Find message UID by Message-ID header.
        
        Args:
            client: Connected IMAP client
            message_id: Gmail Message-ID header value
            
        Returns:
            Message UID as string, or None if not found
        """
        try:
            search_query = f'HEADER Message-ID "{message_id}"'
            response = await client.search(search_query)
            
            if response.result != 'OK':
                logger.warning(f"Search failed for message_id {message_id}")
                return None
            
            message_ids = response.lines[0].decode().strip().split()
            
            if not message_ids or message_ids == [b'']:
                logger.warning(f"Message not found: {message_id}")
                return None
            
            uid = message_ids[0]
            return uid.decode() if isinstance(uid, bytes) else uid
            
        except Exception as e:
            logger.error(f"Error searching for message {message_id}: {e}")
            return None
    
    async def mark_as_read(
        self,
        account_email: str,
        message_id: str
    ) -> bool:
        """
        Mark email as read by setting Seen flag.
        
        Args:
            account_email: Email address of account that received the message
            message_id: Gmail Message-ID header value
            
        Returns:
            True if successfully marked as read, False otherwise
        """
        try:
            client = await self._ensure_connection(account_email)
            if not client:
                logger.error(f"Could not connect to {account_email}")
                return False
            
            await client.select('INBOX')
            
            uid = await self._find_message_by_id(client, message_id)
            if not uid:
                logger.warning(
                    f"Could not find message {message_id} in {account_email}"
                )
                return False
            
            response = await client.store(uid, '+FLAGS', r'(\Seen)')
            
            if response.result != 'OK':
                logger.error(
                    f"Failed to mark message {message_id} as read: {response}"
                )
                return False
            
            logger.info(f"Marked message {message_id} as read in {account_email}")
            return True
            
        except Exception as e:
            logger.error(
                f"Error marking message {message_id} as read in {account_email}: {e}",
                exc_info=True
            )
            return False
    
    async def mark_as_unread(
        self,
        account_email: str,
        message_id: str
    ) -> bool:
        """
        Mark email as unread by removing Seen flag.
        
        Args:
            account_email: Email address of account that received the message
            message_id: Gmail Message-ID header value
            
        Returns:
            True if successfully marked as unread, False otherwise
        """
        try:
            client = await self._ensure_connection(account_email)
            if not client:
                logger.error(f"Could not connect to {account_email}")
                return False
            
            await client.select('INBOX')
            
            uid = await self._find_message_by_id(client, message_id)
            if not uid:
                logger.warning(
                    f"Could not find message {message_id} in {account_email}"
                )
                return False
            
            response = await client.store(uid, '-FLAGS', r'(\Seen)')
            
            if response.result != 'OK':
                logger.error(
                    f"Failed to mark message {message_id} as unread: {response}"
                )
                return False
            
            logger.info(f"Marked message {message_id} as unread in {account_email}")
            return True
            
        except Exception as e:
            logger.error(
                f"Error marking message {message_id} as unread in {account_email}: {e}",
                exc_info=True
            )
            return False
    
    async def close_all(self):
        """Close all IMAP connections."""
        for email, client in self.connections.items():
            if client:
                try:
                    await client.logout()
                    logger.debug(f"Closed connection for {email}")
                except Exception as e:
                    logger.warning(f"Error closing connection for {email}: {e}")
        
        self.connections.clear()


# Global controller instance
controller = IMAPController()


async def mark_as_read(account_email: str, message_id: str) -> bool:
    """
    Convenience function to mark email as read.
    
    Args:
        account_email: Email address of account
        message_id: Gmail Message-ID header value
        
    Returns:
        True if successful, False otherwise
    """
    return await controller.mark_as_read(account_email, message_id)


async def mark_as_unread(account_email: str, message_id: str) -> bool:
    """
    Convenience function to mark email as unread.
    
    Args:
        account_email: Email address of account
        message_id: Gmail Message-ID header value
        
    Returns:
        True if successful, False otherwise
    """
    return await controller.mark_as_unread(account_email, message_id)
