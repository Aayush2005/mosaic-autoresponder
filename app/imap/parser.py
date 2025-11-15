"""
Email parsing and extraction for IMAP messages.

Parses raw IMAP email data, extracts headers and body content,
removes HTML and quoted text, and detects contact information.
"""

import email
import re
from email.message import Message
from email.header import decode_header
from typing import Dict, Optional
from html.parser import HTMLParser
from io import StringIO

try:
    from email_reply_parser import EmailReplyParser
except ImportError:
    EmailReplyParser = None

from app.utils.contact_detector import ContactDetector


class HTMLStripper(HTMLParser):
    """
    Simple HTML tag stripper.
    
    Converts HTML to plain text by removing all tags.
    """
    
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()
    
    def handle_data(self, data):
        self.text.write(data)
    
    def get_text(self):
        return self.text.getvalue()


class EmailParser:
    """
    Parse and extract structured data from raw IMAP emails.
    
    Handles header decoding, body extraction, HTML stripping,
    quoted text removal, and contact information detection.
    """
    
    def __init__(self):
        self.contact_detector = ContactDetector()
    
    def parse_email(self, raw_email: bytes) -> Dict[str, any]:
        """
        Parse raw IMAP email into structured data.
        
        Extracts headers, cleans body content, removes quoted text,
        and detects contact information.
        
        Args:
            raw_email: Raw email bytes from IMAP fetch
            
        Returns:
            Dict containing:
                - message_id: str
                - thread_id: str (from In-Reply-To or References)
                - subject: str
                - from_email: str
                - from_name: str
                - to_email: str
                - date: str
                - body: str (cleaned, no HTML, no quoted text)
                - has_contact: bool
                - contact_info: Dict (phone numbers, address)
        """
        msg = email.message_from_bytes(raw_email)
        
        # Extract headers
        message_id = self._extract_message_id(msg)
        thread_id = self._extract_thread_id(msg)
        subject = self._decode_header(msg.get('Subject', ''))
        from_email, from_name = self._parse_from_header(msg.get('From', ''))
        to_email = self._extract_email_address(msg.get('To', ''))
        date = msg.get('Date', '')
        
        # Extract and clean body
        body = self._extract_body(msg)
        body = self.clean_email_body(body)
        
        # Detect contact information
        contact_info = self.contact_detector.detect_contact_info(body)
        
        return {
            'message_id': message_id,
            'thread_id': thread_id,
            'subject': subject,
            'from_email': from_email,
            'from_name': from_name,
            'to_email': to_email,
            'date': date,
            'body': body,
            'has_contact': contact_info['has_phone'] or contact_info['has_address'],
            'contact_info': contact_info
        }
    
    def clean_email_body(self, body: str) -> str:
        """
        Clean email body by removing HTML, quoted text, and signatures.
        
        Uses email_reply_parser to strip quoted text and signatures.
        Falls back to basic cleaning if library not available.
        
        Args:
            body: Raw email body text
            
        Returns:
            Cleaned body text
        """
        # Remove HTML tags
        body = self._strip_html(body)
        
        # Remove quoted text and signatures using email_reply_parser
        if EmailReplyParser:
            try:
                body = EmailReplyParser.parse_reply(body)
            except Exception:
                # Fallback to basic cleaning if parser fails
                body = self._basic_quote_removal(body)
        else:
            body = self._basic_quote_removal(body)
        
        # Clean up whitespace
        body = self._normalize_whitespace(body)
        
        return body.strip()
    
    def _extract_message_id(self, msg: Message) -> str:
        """Extract Message-ID header."""
        message_id = msg.get('Message-ID', '')
        # Remove angle brackets
        return message_id.strip('<>')
    
    def _extract_thread_id(self, msg: Message) -> str:
        """
        Extract thread ID from email headers.
        
        Tries In-Reply-To first, then References, falls back to Message-ID.
        """
        # Try In-Reply-To header (direct reply)
        in_reply_to = msg.get('In-Reply-To', '')
        if in_reply_to:
            return in_reply_to.strip('<>').split()[0]
        
        # Try References header (thread chain)
        references = msg.get('References', '')
        if references:
            # Get first reference (original message)
            refs = references.strip().split()
            if refs:
                return refs[0].strip('<>')
        
        # Fallback to Message-ID (new thread)
        return self._extract_message_id(msg)
    
    def _decode_header(self, header: str) -> str:
        """
        Decode email header that may contain encoded words.
        
        Handles RFC 2047 encoded-word syntax.
        """
        if not header:
            return ''
        
        decoded_parts = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                decoded_parts.append(
                    part.decode(encoding or 'utf-8', errors='ignore')
                )
            else:
                decoded_parts.append(part)
        
        return ''.join(decoded_parts)
    
    def _parse_from_header(self, from_header: str) -> tuple:
        """
        Parse From header into email and name.
        
        Returns:
            Tuple of (email, name)
        """
        from_header = self._decode_header(from_header)
        
        # Pattern: "Name" <email@example.com> or email@example.com
        match = re.search(r'<([^>]+)>', from_header)
        if match:
            email_addr = match.group(1)
            name = from_header[:match.start()].strip().strip('"')
            return email_addr, name
        
        # Just email address
        return from_header.strip(), ''
    
    def _extract_email_address(self, header: str) -> str:
        """Extract email address from header."""
        header = self._decode_header(header)
        match = re.search(r'<([^>]+)>', header)
        if match:
            return match.group(1)
        return header.strip()
    
    def _extract_body(self, msg: Message) -> str:
        """
        Extract email body from message.
        
        Handles multipart messages and prefers plain text over HTML.
        """
        body = ''
        
        if msg.is_multipart():
            # Get all parts
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                # Skip attachments
                if 'attachment' in content_disposition:
                    continue
                
                # Prefer text/plain
                if content_type == 'text/plain':
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                        break
                    except Exception:
                        continue
                
                # Fallback to text/html
                elif content_type == 'text/html' and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                    except Exception:
                        continue
        else:
            # Single part message
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
            except Exception:
                body = str(msg.get_payload())
        
        return body
    
    def _strip_html(self, text: str) -> str:
        """
        Remove HTML tags from text.
        
        Converts HTML to plain text.
        """
        if not text or '<' not in text:
            return text
        
        try:
            stripper = HTMLStripper()
            stripper.feed(text)
            return stripper.get_text()
        except Exception:
            # Fallback to regex-based stripping
            text = re.sub(r'<[^>]+>', '', text)
            return text
    
    def _basic_quote_removal(self, text: str) -> str:
        """
        Basic quoted text removal fallback.
        
        Removes common quote patterns when email_reply_parser unavailable.
        """
        lines = text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Skip lines starting with > (quoted text)
            if line.strip().startswith('>'):
                continue
            
            # Stop at common signature markers
            if line.strip() in ['--', '___', '---']:
                break
            
            # Stop at "On ... wrote:" patterns
            if re.match(r'^On .+ wrote:$', line.strip()):
                break
            
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace in text.
        
        Removes excessive blank lines and trailing spaces.
        """
        # Remove trailing whitespace from each line
        lines = [line.rstrip() for line in text.split('\n')]
        
        # Remove excessive blank lines (max 2 consecutive)
        normalized = []
        blank_count = 0
        
        for line in lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 2:
                    normalized.append(line)
            else:
                blank_count = 0
                normalized.append(line)
        
        return '\n'.join(normalized)


def parse_email(raw_email: bytes) -> Dict[str, any]:
    """
    Convenience function to parse email.
    
    Args:
        raw_email: Raw email bytes from IMAP
        
    Returns:
        Parsed email dict
    """
    parser = EmailParser()
    return parser.parse_email(raw_email)
