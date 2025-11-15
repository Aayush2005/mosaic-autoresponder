"""
Unified email analysis using single LLM call.

Combines intent classification and contact extraction into one API call
for efficiency and cost reduction.
"""

import asyncio
import json
import logging
import os
import phonenumbers
from typing import Dict, Optional

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

from app.utils.training_data_logger import log_training_data


logger = logging.getLogger(__name__)


INTENT_INTERESTED = "INTERESTED"
INTENT_NOT_INTERESTED = "NOT_INTERESTED"
INTENT_CLARIFICATION = "CLARIFICATION"
INTENT_CONTACT_PROVIDED = "CONTACT_PROVIDED"
INTENT_CONTINUE_OVER_EMAIL = "CONTINUE_OVER_EMAIL"

ANALYSIS_TIMEOUT = 10.0
MAX_RETRIES = 2


class EmailAnalyzer:
    """
    Unified email analyzer that extracts intent and contact info in single LLM call.
    
    More efficient than separate calls for classification and extraction.
    """
    
    def __init__(self):
        """Initialize the email analyzer with Groq API."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set in environment")
        
        self.llm = ChatGroq(
            model=os.getenv("GROQ_MODEL", "mixtral-8x7b-32768"),
            temperature=0,
            groq_api_key=api_key,
            max_tokens=400
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("user", "Analyze this email:\n\n{email_text}")
        ])
        
        self.chain = self.prompt | self.llm
    
    def _get_system_prompt(self) -> str:
        """Build unified analysis prompt."""
        return """You are an email analyzer for creator outreach responses. Analyze the email and extract:

1. INTENT - Classify into exactly ONE category:
   - INTERESTED: Shows interest or engagement ("Yes interested", "Tell me more", "Sounds good")
   - NOT_INTERESTED: Declines or no interest ("No thanks", "Not interested", "I'll pass")
   - CLARIFICATION: Asks questions ("What's the retainer?", "How does this work?")
   - CONTACT_PROVIDED: Shares contact details (phone, WhatsApp, address)
   - CONTINUE_OVER_EMAIL: Wants email discussion ("Let's continue over email", "Email me details")

2. CONTACT INFORMATION:
   - Phone numbers (including WhatsApp) - extract if sender is sharing their contact
   - Physical address - extract if sender is sharing their address
   - ONLY extract if sender is actually providing their own contact info
   - DON'T extract if just mentioned in conversation

Return JSON with this EXACT structure:
{
  "intent": "INTENT_CATEGORY",
  "phone_numbers": ["list of phone numbers if provided"],
  "has_address": true/false,
  "address_text": "full address if provided, otherwise null"
}

Rules:
- If contact info is provided, intent should be CONTACT_PROVIDED
- If interested but no contact info, intent should be INTERESTED
- If ambiguous, use CLARIFICATION for human review
- Only extract contact info the sender is actually sharing"""
    
    async def analyze_email(self, email_body: str) -> Dict[str, any]:
        """
        Analyze email for intent and contact info in single LLM call.
        
        Args:
            email_body: The email text to analyze
            
        Returns:
            Dict containing:
                - intent: str (classification)
                - has_phone: bool
                - has_address: bool
                - phone_numbers: List[str] (validated E164 format)
                - address_text: Optional[str]
        """
        if not email_body or not email_body.strip():
            logger.warning("Empty email body provided for analysis")
            return self._default_result(INTENT_CLARIFICATION)
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    self._analyze_with_llm(email_body),
                    timeout=ANALYSIS_TIMEOUT
                )
                return result
                
            except asyncio.TimeoutError:
                if attempt == MAX_RETRIES:
                    logger.warning(
                        f"LLM timeout after {MAX_RETRIES} retries, "
                        f"defaulting to CLARIFICATION"
                    )
                    return self._default_result(INTENT_CLARIFICATION)
                
                backoff_delay = 2 ** attempt
                logger.warning(
                    f"LLM timeout on attempt {attempt + 1}/{MAX_RETRIES + 1}, "
                    f"retrying in {backoff_delay}s"
                )
                await asyncio.sleep(backoff_delay)
                
            except Exception as e:
                logger.error(
                    f"LLM analysis error on attempt {attempt + 1}: {e}, "
                    f"defaulting to CLARIFICATION"
                )
                return self._default_result(INTENT_CLARIFICATION)
        
        return self._default_result(INTENT_CLARIFICATION)
    
    async def _analyze_with_llm(self, email_body: str) -> Dict[str, any]:
        """
        Perform the actual LLM analysis call.
        
        Args:
            email_body: The email text to analyze
            
        Returns:
            Dict with intent and contact info
        """
        response = await self.chain.ainvoke({"email_text": email_body})
        result = self._parse_response(response.content)
        
        # Validate phone numbers
        result['phone_numbers'] = self._validate_phone_numbers(
            result.get('phone_numbers', [])
        )
        result['has_phone'] = len(result['phone_numbers']) > 0
        
        logger.info(
            f"Analyzed email - Intent: {result['intent']}, "
            f"Has phone: {result['has_phone']}, Has address: {result['has_address']}"
        )
        
        # Log for training data
        log_training_data(email_body, result['intent'])
        
        return result
    
    def _parse_response(self, response_text: str) -> Dict[str, any]:
        """
        Parse LLM JSON response.
        
        Args:
            response_text: Raw LLM response
            
        Returns:
            Dict with intent and contact info
        """
        try:
            # Extract JSON from response
            content = response_text.strip()
            
            if '```json' in content:
                content = content.split('```json')[1].split('```')[0].strip()
            elif '```' in content:
                content = content.split('```')[1].split('```')[0].strip()
            
            data = json.loads(content)
            
            # Validate intent
            intent = data.get('intent', '').upper()
            valid_intents = {
                INTENT_INTERESTED,
                INTENT_NOT_INTERESTED,
                INTENT_CLARIFICATION,
                INTENT_CONTACT_PROVIDED,
                INTENT_CONTINUE_OVER_EMAIL
            }
            
            if intent not in valid_intents:
                logger.warning(f"Invalid intent '{intent}', defaulting to CLARIFICATION")
                intent = INTENT_CLARIFICATION
            
            return {
                'intent': intent,
                'phone_numbers': data.get('phone_numbers', []),
                'has_address': data.get('has_address', False),
                'address_text': data.get('address_text')
            }
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return self._default_result(INTENT_CLARIFICATION)
    
    def _validate_phone_numbers(self, phone_list: list) -> list:
        """
        Validate and normalize phone numbers.
        
        Args:
            phone_list: List of phone number strings from LLM
            
        Returns:
            List of validated phone numbers in E164 format
        """
        valid_numbers = []
        
        for phone_str in phone_list:
            if not phone_str:
                continue
            
            try:
                # Try parsing with region hints
                for region in [None, 'US', 'GB', 'IN', 'CA', 'AU']:
                    try:
                        parsed = phonenumbers.parse(phone_str, region)
                        if phonenumbers.is_valid_number(parsed):
                            e164 = phonenumbers.format_number(
                                parsed,
                                phonenumbers.PhoneNumberFormat.E164
                            )
                            if e164 not in valid_numbers:
                                valid_numbers.append(e164)
                            break
                    except Exception:
                        continue
            except Exception:
                continue
        
        return valid_numbers
    
    def _default_result(self, intent: str) -> Dict[str, any]:
        """
        Return default result structure.
        
        Args:
            intent: Intent classification
            
        Returns:
            Dict with default values
        """
        return {
            'intent': intent,
            'has_phone': False,
            'has_address': False,
            'phone_numbers': [],
            'address_text': None
        }


async def analyze_email(email_body: str) -> Dict[str, any]:
    """
    Convenience function to analyze a single email.
    
    Args:
        email_body: The email text to analyze
        
    Returns:
        Dict with intent, has_phone, has_address, phone_numbers, address_text
    """
    analyzer = EmailAnalyzer()
    return await analyzer.analyze_email(email_body)
