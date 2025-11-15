# Requirements Document

## Introduction

This document specifies the requirements for an Automated Follow-Up System designed to manage email responses from TikTok affiliate creators. The system automates follow-up communications with interested creators who have not provided their WhatsApp contact details or shipping address, reducing lead drop-offs and improving conversion rates while enabling seamless handoff to human agents when needed.

## Glossary

- **Follow-Up System**: The automated email management system that processes creator replies and sends follow-up messages
- **Creator**: A TikTok affiliate content creator who receives outreach emails for product collaboration
- **Lead**: A creator who has responded to an outreach email
- **Intent Classification**: The process of categorizing a creator's email reply into predefined categories (interested, not interested, clarification needed, etc.)
- **Follow-Up Stage**: A specific step in the automated follow-up sequence (Stage 1: Initial Reply, Stage 2: First Follow-Up, Stage 3: Second Follow-Up)
- **Contact Details**: WhatsApp number or phone contact information provided by the creator
- **Shipping Address**: Physical address provided by the creator for product delivery
- **Stop Condition**: A scenario that terminates the automated follow-up sequence
- **Email Thread**: A conversation chain consisting of the original outreach email and subsequent replies
- **Human Delegation**: The process of routing an email thread to a human agent for manual handling
- **Outreach Email Account**: One of three email accounts used to send initial outreach messages to creators

## Requirements

### Requirement 1

**User Story:** As a business operator, I want the system to automatically detect when a creator expresses interest without providing contact details, so that I can initiate appropriate follow-up sequences without manual intervention

#### Acceptance Criteria

1. WHEN the Follow-Up System receives an email reply to an outreach message, THE Follow-Up System SHALL classify the reply intent using the Intent Classification process
2. WHEN the Intent Classification process identifies a reply as "interested" or "clarification needed", THE Follow-Up System SHALL extract contact information from the email body
3. IF the email reply indicates interest AND does not contain Contact Details or Shipping Address, THEN THE Follow-Up System SHALL initiate a Stage 1 follow-up response
4. WHEN the Follow-Up System sends a Stage 1 follow-up response, THE Follow-Up System SHALL mark the email thread as read
5. WHEN the Follow-Up System sends a Stage 1 follow-up response, THE Follow-Up System SHALL record the follow-up stage and timestamp in the database

### Requirement 2

**User Story:** As a business operator, I want the system to send timed follow-up messages to creators who haven't responded, so that I can maximize the chance of obtaining their contact information

#### Acceptance Criteria

1. WHEN 24 hours have elapsed since a Stage 1 follow-up AND no creator response has been received, THE Follow-Up System SHALL send a Stage 2 follow-up message
2. WHEN 48 hours have elapsed since a Stage 2 follow-up AND no creator response has been received, THE Follow-Up System SHALL send a Stage 3 follow-up message
3. WHEN the Follow-Up System sends a Stage 2 or Stage 3 follow-up message, THE Follow-Up System SHALL mark the email thread as read
4. THE Follow-Up System SHALL NOT send more than 2 automated follow-up messages (Stage 2 and Stage 3) after the initial Stage 1 response
5. WHEN the Follow-Up System sends any follow-up message, THE Follow-Up System SHALL record the follow-up stage and timestamp in the database

### Requirement 3

**User Story:** As a business operator, I want the system to stop automated follow-ups when a creator responds or provides contact details, so that I don't send unnecessary messages and can enable human takeover

#### Acceptance Criteria

1. WHEN a creator replies to any follow-up message, THE Follow-Up System SHALL mark the email thread as unread
2. WHEN a creator replies to any follow-up message, THE Follow-Up System SHALL terminate the automated follow-up sequence
3. IF a creator provides Contact Details or Shipping Address in any reply, THEN THE Follow-Up System SHALL terminate the automated follow-up sequence
4. WHEN a creator explicitly requests to continue communication via email, THE Follow-Up System SHALL terminate the automated follow-up sequence
5. WHEN the Follow-Up System terminates a follow-up sequence, THE Follow-Up System SHALL record the stop reason in the database

### Requirement 4

**User Story:** As a business operator, I want the system to handle high volumes of email replies across multiple accounts efficiently, so that all creator responses are processed in a timely manner

#### Acceptance Criteria

1. THE Follow-Up System SHALL monitor email replies from 3 Outreach Email Accounts concurrently
2. THE Follow-Up System SHALL process a minimum of 600 email replies per day across all Outreach Email Accounts
3. THE Follow-Up System SHALL process up to 10 email replies concurrently with asynchronous execution
4. WHEN the Follow-Up System processes an email reply, THE Follow-Up System SHALL complete the processing and send a response within 2 minutes
5. THE Follow-Up System SHALL maintain processing performance when handling concurrent email replies

### Requirement 5

**User Story:** As a business analyst, I want the system to track all follow-up stages and outcomes in a database, so that I can analyze conversion rates and system effectiveness

#### Acceptance Criteria

1. WHEN the Follow-Up System receives a creator reply, THE Follow-Up System SHALL create a database record containing the lead identifier, email content, and intent classification
2. WHEN the Follow-Up System sends a follow-up message, THE Follow-Up System SHALL update the database record with the follow-up stage number and timestamp
3. WHEN the Follow-Up System terminates a follow-up sequence, THE Follow-Up System SHALL record the stop reason in the database
4. THE Follow-Up System SHALL maintain a complete audit trail of all email interactions for each Lead
5. THE Follow-Up System SHALL store database records with sufficient detail to enable future analysis of conversion rates and drop-off points

### Requirement 6

**User Story:** As a human agent, I want the system to route complex queries and specific scenarios to me, so that I can provide personalized responses when automation is insufficient

#### Acceptance Criteria

1. WHEN a creator reply contains clarifying questions that cannot be answered by automated responses, THE Follow-Up System SHALL mark the email thread as unread for Human Delegation
2. WHEN a creator replies after receiving a follow-up message, THE Follow-Up System SHALL mark the email thread as unread for Human Delegation
3. WHEN the Follow-Up System marks an email thread as unread, THE Follow-Up System SHALL record the delegation reason in the database
4. THE Follow-Up System SHALL NOT send additional automated follow-ups to email threads marked for Human Delegation
5. WHEN the Follow-Up System delegates an email thread, THE Follow-Up System SHALL ensure the thread remains visible in the inbox for human review

### Requirement 7

**User Story:** As a business operator, I want the system to use predefined message templates for each follow-up stage, so that communication remains consistent and professional

#### Acceptance Criteria

1. WHEN the Follow-Up System sends a Stage 1 follow-up, THE Follow-Up System SHALL use the message template: "Could you share your WhatsApp contact and address with me? I will ask my team to connect with you immediately."
2. WHEN the Follow-Up System sends a Stage 2 follow-up, THE Follow-Up System SHALL use the message template: "Just checking in — can you please share your WhatsApp contact so we can connect quickly?"
3. WHEN the Follow-Up System sends a Stage 3 follow-up, THE Follow-Up System SHALL use the message template: "Wanted to follow up again — we'd love to take this forward but just need your WhatsApp number to coordinate better."
4. THE Follow-Up System SHALL maintain the original email thread context when sending follow-up messages
5. THE Follow-Up System SHALL send follow-up messages from the same Outreach Email Account that received the creator's reply
