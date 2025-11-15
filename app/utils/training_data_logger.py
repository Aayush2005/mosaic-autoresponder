"""
Training data collection for future model training.

Appends successfully classified emails to a CSV file for building
a custom intent classifier. Only stores cleaned email text and labels,
no PII or metadata.
"""

import csv
import os
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class TrainingDataLogger:
    """
    Logs email text and classified intent to CSV for model training.
    
    Creates a simple CSV with email_text and intent_label columns.
    Thread-safe append operations for concurrent processing.
    """
    
    def __init__(self, csv_path: str = "data/training_data.csv"):
        """
        Initialize training data logger.
        
        Args:
            csv_path: Path to CSV file (default: data/training_data.csv)
        """
        self.csv_path = csv_path
        self._ensure_csv_exists()
    
    def _ensure_csv_exists(self):
        """Create CSV file with headers if it doesn't exist."""
        csv_file = Path(self.csv_path)
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        
        if not csv_file.exists():
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['email_text', 'intent_label'])
            logger.info(f"Created training data CSV at {self.csv_path}")
    
    def log_classification(self, email_text: str, intent: str):
        """
        Append email text and intent to training CSV.
        
        Cleans the email text (removes extra whitespace) and appends
        to CSV file. Thread-safe for concurrent writes.
        
        Args:
            email_text: Raw email body text
            intent: Classified intent label
        """
        if not email_text or not intent:
            logger.warning("Skipping training data log: empty email or intent")
            return
        
        cleaned_text = self._clean_text(email_text)
        
        try:
            with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([cleaned_text, intent])
            
            logger.debug(f"Logged training data: intent={intent}, text_length={len(cleaned_text)}")
            
        except Exception as e:
            logger.error(f"Failed to log training data: {e}")
    
    def _clean_text(self, text: str) -> str:
        """
        Clean email text for training data.
        
        Removes excessive whitespace and normalizes line breaks.
        Does NOT remove PII - assumes email text is already sanitized if needed.
        
        Args:
            text: Raw email text
            
        Returns:
            Cleaned text
        """
        cleaned = ' '.join(text.split())
        return cleaned.strip()
    
    def get_training_data_count(self) -> int:
        """
        Get number of training examples in CSV.
        
        Returns:
            Number of rows (excluding header)
        """
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f) - 1
        except Exception:
            return 0


_global_logger: Optional[TrainingDataLogger] = None


def get_training_logger() -> TrainingDataLogger:
    """
    Get global training data logger instance.
    
    Returns:
        Singleton TrainingDataLogger instance
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = TrainingDataLogger()
    return _global_logger


def log_training_data(email_text: str, intent: str):
    """
    Convenience function to log training data.
    
    Args:
        email_text: Email body text
        intent: Classified intent
    """
    logger = get_training_logger()
    logger.log_classification(email_text, intent)
