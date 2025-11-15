"""
Contact information detection from email text.

Uses phonenumbers library for robust phone number validation and normalization.
Detects addresses using keyword-based pattern matching.
"""

import re
import phonenumbers
from phonenumbers import PhoneNumberMatcher
from typing import Dict, List, Optional


class ContactDetector:
    """
    Detect and validate contact information in email text.
    
    Uses phonenumbers library for international phone number validation
    and keyword-based detection for addresses.
    """
    
    ADDRESS_KEYWORDS = [
        'address', 'shipping', 'delivery', 'street', 'avenue', 'road',
        'city', 'state', 'zip', 'postal', 'country', 'apt', 'suite',
        'building', 'floor', 'house', 'lane', 'boulevard', 'drive'
    ]
    
    def __init__(self):
        pass
    
    def detect_contact_info(self, text: str) -> Dict[str, any]:
        """
        Detect all contact information in text.
        
        Returns dict with has_phone, has_address, phone_numbers, and address_text.
        Only returns has_phone=True if valid phone numbers are found.
        
        Args:
            text: Email body text to analyze
            
        Returns:
            Dict containing:
                - has_phone: bool (True only if valid numbers found)
                - has_address: bool
                - phone_numbers: List[str] (normalized E164 format)
                - address_text: Optional[str]
        """
        phone_numbers = self.extract_phone_numbers(text)
        address_text = self.extract_address(text)
        
        return {
            'has_phone': len(phone_numbers) > 0,
            'has_address': address_text is not None,
            'phone_numbers': phone_numbers,
            'address_text': address_text
        }
    
    def extract_phone_numbers(self, text: str) -> List[str]:
        """
        Extract and validate phone numbers using phonenumbers library.
        
        Only returns numbers that pass phonenumbers.is_valid_number() validation.
        Returns numbers in normalized E164 format (e.g., +12345678900).
        
        Args:
            text: Text to search for phone numbers
            
        Returns:
            List of validated phone numbers in E164 format
        """
        valid_numbers = []
        
        # Try to find phone numbers without region hint first
        for match in PhoneNumberMatcher(text, None):
            if phonenumbers.is_valid_number(match.number):
                # Format as E164 for consistency
                e164 = phonenumbers.format_number(
                    match.number,
                    phonenumbers.PhoneNumberFormat.E164
                )
                if e164 not in valid_numbers:
                    valid_numbers.append(e164)
        
        # If no numbers found, try common regions as hints
        if not valid_numbers:
            common_regions = ['US', 'GB', 'IN', 'CA', 'AU']
            for region in common_regions:
                try:
                    for match in PhoneNumberMatcher(text, region):
                        if phonenumbers.is_valid_number(match.number):
                            e164 = phonenumbers.format_number(
                                match.number,
                                phonenumbers.PhoneNumberFormat.E164
                            )
                            if e164 not in valid_numbers:
                                valid_numbers.append(e164)
                except Exception:
                    continue
        
        return valid_numbers
    
    def extract_address(self, text: str) -> Optional[str]:
        """
        Detect address information using keyword-based matching.
        
        Looks for address-related keywords and extracts surrounding context.
        Returns the text segment that likely contains an address.
        
        Args:
            text: Text to search for addresses
            
        Returns:
            Address text if found, None otherwise
        """
        text_lower = text.lower()
        
        # Check if any address keywords are present
        has_address_keyword = any(
            keyword in text_lower for keyword in self.ADDRESS_KEYWORDS
        )
        
        if not has_address_keyword:
            return None
        
        # Try to extract address block
        # Look for patterns like "Address: ..." or "Shipping address: ..."
        address_patterns = [
            r'(?:shipping\s+)?address[:\s]+([^\n]+(?:\n[^\n]+){0,3})',
            r'(?:delivery\s+)?address[:\s]+([^\n]+(?:\n[^\n]+){0,3})',
            r'ship\s+to[:\s]+([^\n]+(?:\n[^\n]+){0,3})',
        ]
        
        for pattern in address_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # If no explicit pattern, look for multi-line text with address keywords
        lines = text.split('\n')
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(keyword in line_lower for keyword in self.ADDRESS_KEYWORDS):
                # Extract this line and next 2-3 lines as potential address
                address_lines = lines[i:min(i+4, len(lines))]
                address_text = '\n'.join(address_lines).strip()
                if len(address_text) > 10:  # Minimum length check
                    return address_text
        
        return None
    
    def has_valid_phone(self, text: str) -> bool:
        """
        Quick check if text contains at least one valid phone number.
        
        Args:
            text: Text to check
            
        Returns:
            True if at least one valid phone number found
        """
        return len(self.extract_phone_numbers(text)) > 0
    
    def has_address_info(self, text: str) -> bool:
        """
        Quick check if text contains address information.
        
        Args:
            text: Text to check
            
        Returns:
            True if address keywords found
        """
        return self.extract_address(text) is not None


def detect_contact_info(text: str) -> Dict[str, any]:
    """
    Convenience function to detect contact information.
    
    Args:
        text: Email body text
        
    Returns:
        Dict with has_phone, has_address, phone_numbers, address_text
    """
    detector = ContactDetector()
    return detector.detect_contact_info(text)
