"""
Intent classification using Groq API via LangChain.

Classifies creator email replies into intent categories to determine
appropriate follow-up actions. Uses timeout and retry logic for reliability.
"""

import asyncio
import logging
import os

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate


logger = logging.getLogger(__name__)


INTENT_INTERESTED = "INTERESTED"
INTENT_NOT_INTERESTED = "NOT_INTERESTED"
INTENT_CLARIFICATION = "CLARIFICATION"
INTENT_CONTACT_PROVIDED = "CONTACT_PROVIDED"

CLASSIFICATION_TIMEOUT = 8.0
MAX_RETRIES = 2


class IntentClassifier:
    """
    Classifies email intent using Groq API.
    
    Handles timeouts and retries gracefully, defaulting to CLARIFICATION
    (human review) if classification fails after all retry attempts.
    """
    
    def __init__(self):
        """
        Initialize the intent classifier with Groq API.
        
        Reads GROQ_API_KEY from environment variables.
        """
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set in environment")
        
        self.llm = ChatGroq(
            model="mixtral-8x7b-32768",
            temperature=0,
            groq_api_key=api_key
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("user", "Classify this email reply:\n\n{email_text}")
        ])
        
        self.chain = self.prompt | self.llm
    
    def _get_system_prompt(self) -> str:
        """
        Build the classification prompt with examples.
        
        Returns clear instructions and few-shot examples for accurate classification.
        """
        return """You are an email intent classifier for creator outreach responses.

Classify the email into exactly ONE of these categories:

1. INTERESTED - Creator shows interest or engagement
   Examples: "Yes, I'm interested", "Tell me more", "Sounds good", "I'd like to collaborate"

2. NOT_INTERESTED - Creator declines or shows no interest
   Examples: "No thanks", "Not interested", "I'll pass", "Not for me"

3. CLARIFICATION - Creator asks questions or needs more information
   Examples: "What's the retainer?", "How does this work?", "Can you explain?", "What products?"

4. CONTACT_PROVIDED - Creator shares contact details (phone, WhatsApp, address)
   Examples: "My WhatsApp is +1234567890", "Here's my address: 123 Main St", "Call me at..."

Respond with ONLY the category name, nothing else.

If the email is ambiguous or unclear, respond with CLARIFICATION."""
    
    async def classify_intent(self, email_body: str) -> str:
        """
        Classify email intent with timeout and retry logic.
        
        Attempts classification with exponential backoff on failure.
        Defaults to CLARIFICATION if all attempts fail to ensure human review.
        
        Args:
            email_body: The email text to classify
            
        Returns:
            Intent category: INTERESTED, NOT_INTERESTED, CLARIFICATION, or CONTACT_PROVIDED
        """
        if not email_body or not email_body.strip():
            logger.warning("Empty email body provided for classification")
            return INTENT_CLARIFICATION
        
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = await asyncio.wait_for(
                    self._classify_with_llm(email_body),
                    timeout=CLASSIFICATION_TIMEOUT
                )
                return result
                
            except asyncio.TimeoutError:
                if attempt == MAX_RETRIES:
                    logger.warning(
                        f"LLM timeout after {MAX_RETRIES} retries, "
                        f"defaulting to CLARIFICATION for human review"
                    )
                    return INTENT_CLARIFICATION
                
                backoff_delay = 2 ** attempt
                logger.warning(
                    f"LLM timeout on attempt {attempt + 1}/{MAX_RETRIES + 1}, "
                    f"retrying in {backoff_delay}s"
                )
                await asyncio.sleep(backoff_delay)
                
            except Exception as e:
                logger.error(
                    f"LLM classification error on attempt {attempt + 1}: {e}, "
                    f"defaulting to CLARIFICATION"
                )
                return INTENT_CLARIFICATION
        
        return INTENT_CLARIFICATION
    
    async def _classify_with_llm(self, email_body: str) -> str:
        """
        Perform the actual LLM classification call.
        
        Args:
            email_body: The email text to classify
            
        Returns:
            Parsed intent category
        """
        response = await self.chain.ainvoke({"email_text": email_body})
        intent = self._parse_response(response.content)
        
        logger.info(f"Classified email intent as: {intent}")
        return intent
    
    def _parse_response(self, response_text: str) -> str:
        """
        Extract intent category from LLM response.
        
        Handles various response formats and defaults to CLARIFICATION
        if the response doesn't match expected categories.
        
        Args:
            response_text: Raw LLM response
            
        Returns:
            Normalized intent category
        """
        cleaned = response_text.strip().upper()
        
        valid_intents = {
            INTENT_INTERESTED,
            INTENT_NOT_INTERESTED,
            INTENT_CLARIFICATION,
            INTENT_CONTACT_PROVIDED
        }
        
        for intent in valid_intents:
            if intent in cleaned:
                return intent
        
        logger.warning(
            f"Could not parse intent from response: '{response_text}', "
            f"defaulting to CLARIFICATION"
        )
        return INTENT_CLARIFICATION


async def classify_email_intent(email_body: str) -> str:
    """
    Convenience function to classify a single email.
    
    Creates a classifier instance and performs classification with
    timeout and retry logic.
    
    Args:
        email_body: The email text to classify
        
    Returns:
        Intent category: INTERESTED, NOT_INTERESTED, CLARIFICATION, or CONTACT_PROVIDED
    """
    classifier = IntentClassifier()
    return await classifier.classify_intent(email_body)
