"""
Business logic for routing email responses to appropriate actions.

Determines whether to send follow-ups, delegate to humans, or mark threads
as complete based on intent classification and contact information detection.
"""

import logging
from typing import Dict, Optional
from datetime import datetime
from enum import Enum

from app.db.connect import db
from app.ml.email_analyzer import (
    INTENT_INTERESTED,
    INTENT_NOT_INTERESTED,
    INTENT_CLARIFICATION,
    INTENT_CONTACT_PROVIDED,
    INTENT_CONTINUE_OVER_EMAIL,
    analyze_email
)


logger = logging.getLogger(__name__)


class Action(Enum):
    """Possible actions the decision router can take."""
    SEND_STAGE_1_FOLLOWUP = "send_stage_1_followup"
    DELEGATE_TO_HUMAN = "delegate_to_human"
    MARK_COMPLETE = "mark_complete"
    SKIP = "skip"


class DecisionRouter:
    """
    Routes email threads to appropriate actions based on business logic.
    
    Implements the core decision tree:
    - Interested + no contact → Send Stage 1 follow-up
    - Contact provided → Stop, mark unread (delegate to human)
    - Reply to follow-up → Stop, mark unread (delegate to human)
    - Not interested → Stop, mark complete
    - Continue over email → Stop, mark complete (time waster)
    - Clarification needed → Delegate to human
    """
    
    def __init__(self):
        pass
    
    async def determine_action(
        self,
        message_id: str,
        email_body: str
    ) -> Dict[str, any]:
        """
        Determine what action to take for an email thread.
        
        Uses unified LLM analysis to extract intent and contact info in single call.
        Checks database state to see if this is a new outreach reply or
        a reply to our follow-up. Routes based on intent and contact detection.
        
        Args:
            message_id: Unique Gmail message ID
            email_body: Email text to analyze
            
        Returns:
            Dict containing:
                - action: Action enum value
                - reason: String explanation of decision
                - update_fields: Dict of database fields to update
                - analysis: Dict with intent and contact info
        """
        # Single LLM call for both intent and contact extraction
        analysis = await analyze_email(email_body)
        
        intent = analysis['intent']
        has_contact = analysis['has_phone'] or analysis['has_address']
        
        existing_thread = await db.get_thread(message_id)
        
        if existing_thread:
            logger.info(
                f"Thread {message_id} already exists in database, "
                f"this is a reply to our follow-up"
            )
            decision = self._handle_reply_to_followup(existing_thread, intent)
        else:
            logger.info(
                f"New reply to outreach: intent={intent}, has_contact={has_contact}"
            )
            decision = self._handle_new_reply(intent, has_contact)
        
        # Include analysis in decision for database storage
        decision['analysis'] = analysis
        
        return decision
    
    def _handle_reply_to_followup(self, thread: Dict, intent: str) -> Dict[str, any]:
        """
        Handle creator reply to our follow-up message.
        
        If they want to continue over email, mark complete (time waster).
        Otherwise, stop automation and delegate to human for personalized response.
        
        Args:
            thread: Existing thread record from database
            intent: Classified intent of the reply
            
        Returns:
            Decision dict with appropriate action
        """
        if intent == INTENT_CONTINUE_OVER_EMAIL:
            logger.info(
                f"Creator replied to follow-up wanting to continue over email (time waster), "
                f"marking complete"
            )
            return {
                'action': Action.MARK_COMPLETE,
                'reason': 'continue_over_email_after_followup',
                'update_fields': {
                    'status': 'COMPLETED',
                    'stop_reason': 'CONTINUE_OVER_EMAIL'
                }
            }
        
        logger.info(
            f"Creator replied to follow-up stage {thread.get('current_stage', 0)}, "
            f"delegating to human"
        )
        
        return {
            'action': Action.DELEGATE_TO_HUMAN,
            'reason': 'creator_replied_to_followup',
            'update_fields': {
                'status': 'DELEGATED',
                'stop_reason': 'CREATOR_REPLIED',
                'delegated_to_human': True
            }
        }
    
    def _handle_new_reply(self, intent: str, has_contact: bool) -> Dict[str, any]:
        """
        Handle new reply to initial outreach email.
        
        Routes based on intent and whether contact details were provided.
        
        Args:
            intent: Classified intent category
            has_contact: Whether contact details were detected
            
        Returns:
            Decision dict with appropriate action
        """
        if intent == INTENT_NOT_INTERESTED:
            logger.info("Creator not interested, marking complete")
            return {
                'action': Action.MARK_COMPLETE,
                'reason': 'not_interested',
                'update_fields': {
                    'status': 'COMPLETED',
                    'stop_reason': 'NOT_INTERESTED'
                }
            }
        
        if intent == INTENT_CONTINUE_OVER_EMAIL:
            logger.info("Creator wants to continue over email (time waster), marking complete")
            return {
                'action': Action.MARK_COMPLETE,
                'reason': 'continue_over_email',
                'update_fields': {
                    'status': 'COMPLETED',
                    'stop_reason': 'CONTINUE_OVER_EMAIL'
                }
            }
        
        if intent == INTENT_CONTACT_PROVIDED or has_contact:
            logger.info("Contact details provided, delegating to human")
            return {
                'action': Action.DELEGATE_TO_HUMAN,
                'reason': 'contact_provided',
                'update_fields': {
                    'status': 'DELEGATED',
                    'stop_reason': 'CONTACT_PROVIDED',
                    'delegated_to_human': True
                }
            }
        
        if intent == INTENT_INTERESTED:
            if has_contact:
                logger.info("Interested with contact, delegating to human")
                return {
                    'action': Action.DELEGATE_TO_HUMAN,
                    'reason': 'interested_with_contact',
                    'update_fields': {
                        'status': 'DELEGATED',
                        'stop_reason': 'CONTACT_PROVIDED',
                        'delegated_to_human': True
                    }
                }
            else:
                logger.info("Interested without contact, starting Stage 1 follow-up")
                return {
                    'action': Action.SEND_STAGE_1_FOLLOWUP,
                    'reason': 'interested_no_contact',
                    'update_fields': {
                        'status': 'FOLLOWUP_ACTIVE',
                        'current_stage': 1
                    }
                }
        
        if intent == INTENT_CLARIFICATION:
            logger.info("Clarification needed, delegating to human")
            return {
                'action': Action.DELEGATE_TO_HUMAN,
                'reason': 'clarification_needed',
                'update_fields': {
                    'status': 'DELEGATED',
                    'stop_reason': 'CLARIFICATION_NEEDED',
                    'delegated_to_human': True
                }
            }
        
        logger.warning(f"Unknown intent '{intent}', delegating to human for safety")
        return {
            'action': Action.DELEGATE_TO_HUMAN,
            'reason': 'unknown_intent',
            'update_fields': {
                'status': 'DELEGATED',
                'stop_reason': 'UNKNOWN_INTENT',
                'delegated_to_human': True
            }
        }
    
    async def should_send_followup(self, message_id: str, stage: int) -> bool:
        """
        Check if a follow-up should be sent for a thread at given stage.
        
        Verifies thread is in correct state and hasn't exceeded limits.
        
        Args:
            message_id: Unique Gmail message ID
            stage: Follow-up stage to check (1, 2, or 3)
            
        Returns:
            True if follow-up should be sent, False otherwise
        """
        thread = await db.get_thread(message_id)
        
        if not thread:
            logger.warning(f"Thread {message_id} not found, cannot send follow-up")
            return False
        
        if thread.get('status') != 'FOLLOWUP_ACTIVE':
            logger.info(
                f"Thread {message_id} status is {thread.get('status')}, "
                f"not sending follow-up"
            )
            return False
        
        if thread.get('stop_reason'):
            logger.info(
                f"Thread {message_id} has stop reason {thread.get('stop_reason')}, "
                f"not sending follow-up"
            )
            return False
        
        if thread.get('failed_sends', 0) >= 3:
            logger.warning(
                f"Thread {message_id} has {thread.get('failed_sends')} failed sends, "
                f"not sending follow-up"
            )
            return False
        
        if thread.get('followups_sent', 0) >= stage:
            logger.info(
                f"Thread {message_id} already sent {thread.get('followups_sent')} follow-ups, "
                f"not sending stage {stage} again"
            )
            return False
        
        if thread.get('current_stage', 0) != stage:
            logger.info(
                f"Thread {message_id} is at stage {thread.get('current_stage')}, "
                f"not stage {stage}"
            )
            return False
        
        return True
    
    async def mark_thread_stopped(
        self,
        message_id: str,
        stop_reason: str,
        delegate_to_human: bool = False
    ) -> bool:
        """
        Mark a thread as stopped with reason.
        
        Updates thread status and optionally marks for human delegation.
        
        Args:
            message_id: Unique Gmail message ID
            stop_reason: Reason for stopping (CREATOR_REPLIED, MAX_FOLLOWUPS, etc.)
            delegate_to_human: Whether to mark for human review
            
        Returns:
            True if updated successfully, False otherwise
        """
        update_fields = {
            'stop_reason': stop_reason,
            'delegated_to_human': delegate_to_human
        }
        
        if delegate_to_human:
            update_fields['status'] = 'DELEGATED'
        else:
            update_fields['status'] = 'COMPLETED'
        
        success = await db.update_thread(message_id, **update_fields)
        
        if success:
            logger.info(
                f"Marked thread {message_id} as stopped: {stop_reason}, "
                f"delegate={delegate_to_human}"
            )
        else:
            logger.error(f"Failed to mark thread {message_id} as stopped")
        
        return success


async def route_email(
    message_id: str,
    email_body: str
) -> Dict[str, any]:
    """
    Convenience function to route a single email.
    
    Creates a router instance and determines the appropriate action.
    Uses unified LLM analysis for efficiency (single API call).
    
    Args:
        message_id: Unique Gmail message ID
        email_body: Email text to analyze
        
    Returns:
        Decision dict with action, reason, update_fields, and analysis
    """
    router = DecisionRouter()
    return await router.determine_action(message_id, email_body)
