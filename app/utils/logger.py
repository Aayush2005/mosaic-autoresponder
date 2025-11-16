"""
Centralized logging configuration for the automated follow-up system.

Provides a single rotating log file with daily rotation and 30-day retention.
Logs all key events: email received, intent classified, follow-up sent, stopped.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def setup_logger(
    name: str = None,
    log_level: str = 'INFO',
    log_file: str = 'logs/application.log'
) -> logging.Logger:
    """
    Configure and return a logger with rotating file handler.
    
    Creates a logger that writes to a single log file with daily rotation
    and 30-day retention. Also outputs to console for development.
    
    Args:
        name: Logger name (uses root logger if None)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        
    Returns:
        Configured logger instance
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get or create logger
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if logger.handlers:
        return logger
    
    # Set log level
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Create rotating file handler (daily rotation, 30-day retention)
    # Files will be named: application-YYYY-MM-DD.log
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    # Set suffix to include date in filename
    file_handler.suffix = "%Y-%m-%d"
    
    # Custom namer to create clean filenames like: application-2025-11-16.log
    def namer(default_name):
        # default_name will be like: logs/application.log.2025-11-16
        # We want: logs/application-2025-11-16.log
        base_filename = log_file.replace('.log', '')
        date_part = default_name.split('.')[-1]  # Get the date part
        return f"{base_filename}-{date_part}.log"
    
    file_handler.namer = namer
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    Get a logger instance.
    
    If the logger hasn't been configured yet, it will be set up with
    default settings from environment variables.
    
    Args:
        name: Logger name (uses root logger if None)
        
    Returns:
        Logger instance
    """
    logger = logging.getLogger(name)
    
    # If not configured, set up with defaults
    if not logger.handlers:
        log_level = os.getenv('LOG_LEVEL', 'INFO')
        log_file = os.getenv('LOG_FILE', 'logs/application.log')
        return setup_logger(name, log_level, log_file)
    
    return logger


# Create default application logger
app_logger = setup_logger('app', os.getenv('LOG_LEVEL', 'INFO'))


def log_email_received(message_id: str, creator_email: str, account_email: str):
    """
    Log when an email is received from a creator.
    
    Args:
        message_id: Gmail message ID
        creator_email: Creator's email address
        account_email: Account that received the email
    """
    app_logger.info(
        f"Email received | message_id={message_id} | "
        f"from={creator_email} | account={account_email}"
    )


def log_intent_classified(message_id: str, intent: str, has_contact: bool):
    """
    Log when an email's intent has been classified.
    
    Args:
        message_id: Gmail message ID
        intent: Classified intent (INTERESTED, NOT_INTERESTED, etc.)
        has_contact: Whether contact details were detected
    """
    app_logger.info(
        f"Intent classified | message_id={message_id} | "
        f"intent={intent} | has_contact={has_contact}"
    )


def log_followup_sent(message_id: str, stage: int, creator_email: str):
    """
    Log when a follow-up email is sent.
    
    Args:
        message_id: Gmail message ID
        stage: Follow-up stage (1, 2, or 3)
        creator_email: Creator's email address
    """
    app_logger.info(
        f"Follow-up sent | message_id={message_id} | "
        f"stage={stage} | to={creator_email}"
    )


def log_followup_scheduled(message_id: str, stage: int, delay_hours: int):
    """
    Log when a follow-up is scheduled.
    
    Args:
        message_id: Gmail message ID
        stage: Follow-up stage (2 or 3)
        delay_hours: Hours until follow-up should be sent
    """
    app_logger.info(
        f"Follow-up scheduled | message_id={message_id} | "
        f"stage={stage} | delay_hours={delay_hours}"
    )


def log_automation_stopped(message_id: str, reason: str):
    """
    Log when automation is stopped for a thread.
    
    Args:
        message_id: Gmail message ID
        reason: Reason for stopping (CONTACT_PROVIDED, REPLIED, etc.)
    """
    app_logger.info(
        f"Automation stopped | message_id={message_id} | reason={reason}"
    )


def log_delegated_to_human(message_id: str, reason: str):
    """
    Log when a thread is delegated to human review.
    
    Args:
        message_id: Gmail message ID
        reason: Reason for delegation
    """
    app_logger.info(
        f"Delegated to human | message_id={message_id} | reason={reason}"
    )


def log_error(message_id: str, error: str, context: str = None):
    """
    Log an error during email processing.
    
    Args:
        message_id: Gmail message ID
        error: Error message
        context: Additional context about the error
    """
    context_str = f" | context={context}" if context else ""
    app_logger.error(
        f"Processing error | message_id={message_id} | "
        f"error={error}{context_str}"
    )
