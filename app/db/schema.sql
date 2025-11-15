-- PostgreSQL Schema for Creator Outreach Follow-Up System
-- This schema tracks email threads, follow-up history, and system state

-- Main email threads table
-- Stores the primary state of each email conversation with creators
CREATE TABLE email_threads (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) UNIQUE NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    account_email VARCHAR(255) NOT NULL,
    creator_email VARCHAR(255) NOT NULL,
    subject TEXT,
    received_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NOT NULL,
    
    -- Intent classification and contact detection
    intent VARCHAR(50),
    has_contact BOOLEAN DEFAULT FALSE,
    extracted_details TEXT,
    
    -- Follow-up tracking
    current_stage INTEGER DEFAULT 0,
    last_followup_sent_at TIMESTAMP,
    failed_sends INTEGER DEFAULT 0,
    followups_sent INTEGER DEFAULT 0,
    
    -- Status and completion tracking
    status VARCHAR(50) NOT NULL,
    stop_reason VARCHAR(100),
    delegated_to_human BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Follow-up history table
-- Tracks each follow-up action for audit and analysis
CREATE TABLE followup_history (
    id SERIAL PRIMARY KEY,
    email_thread_id INTEGER NOT NULL,
    stage INTEGER NOT NULL,
    sent_at TIMESTAMP NOT NULL,
    template_used TEXT,
    
    FOREIGN KEY (email_thread_id) REFERENCES email_threads(id) ON DELETE CASCADE
);

-- Performance indexes
CREATE INDEX idx_email_threads_status ON email_threads(status);
CREATE INDEX idx_email_threads_account ON email_threads(account_email);
CREATE INDEX idx_email_threads_stage_time ON email_threads(current_stage, last_followup_sent_at);
CREATE INDEX idx_email_threads_thread_id ON email_threads(thread_id);
CREATE INDEX idx_followup_history_thread ON followup_history(email_thread_id);

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_email_threads_updated_at
    BEFORE UPDATE ON email_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
