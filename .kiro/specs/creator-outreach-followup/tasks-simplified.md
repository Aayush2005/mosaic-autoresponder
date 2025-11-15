# Implementation Plan (Simplified - Assignment Scope Only)

## MUST-HAVES (Grading Items)

- [ ] 1. Project setup and structure
  - Create clean directory structure: `app/imap/`, `app/smtp/`, `app/ml/`, `app/core/`, `app/db/`, `app/utils/`
  - Initialize with `uv init` and create virtual environment with `uv venv`
  - Add dependencies: `uv add aiosmtplib aioimaplib redis asyncpg langchain langchain-groq python-dotenv email-reply-parser phonenumbers`
  - Create `.env.example` and `.env` with Gmail credentials and Groq API key
  - Create `.gitignore` (exclude .env, .venv/, logs/, __pycache__)
  - _Requirements: 4.1, 4.2_
  - **Note**: Using `asyncpg` instead of `psycopg2` to avoid blocking DB calls in async code

- [ ] 2. Database schema (PostgreSQL)
  - [ ] 2.1 Create `app/db/schema.sql`
    - Table: `email_threads` (message_id UNIQUE, thread_id, account_email, creator_email, intent, has_contact, current_stage, status, stop_reason, timestamps)
    - Table: `followup_history` (email_thread_id, stage, sent_at, template_used)
    - Add indexes for performance
    - **Add UNIQUE constraint on message_id for idempotency**
    - _Requirements: 5.1, 5.2, 5.3_
  
  - [ ] 2.2 Create `app/db/connect.py`
    - Async PostgreSQL connection with `asyncpg` (non-blocking)
    - Connection pool: `await asyncpg.create_pool()`
    - Basic CRUD functions: `insert_thread()`, `update_thread()`, `get_thread()`
    - Use `ON CONFLICT (message_id) DO NOTHING` for idempotency
    - _Requirements: 5.1_

- [ ] 3. Email parsing and contact detection
  - [ ] 3.1 Create `app/utils/contact_detector.py`
    - Use `phonenumbers` library for phone number detection and normalization
    - Supports international formats, validates phone numbers
    - Address detection with keywords
    - _Requirements: 1.2, 3.1_
  
  - [ ] 3.2 Create `app/imap/parser.py`
    - Parse raw IMAP email (headers, body, thread_id)
    - Use `email_reply_parser` to extract reply content (removes signatures, quoted text)
    - Clean email body (remove HTML)
    - Use contact_detector.py for phone/address detection
    - _Requirements: 1.2, 3.1_
    - **Note**: `email_reply_parser` saves hours fighting false positives

- [ ] 4. Intent classification with Groq
  - [ ] 4.1 Create `app/ml/classifier.py`
    - Set up LangChain with Groq API
    - Simple prompt: classify as INTERESTED, NOT_INTERESTED, CLARIFICATION, CONTACT_PROVIDED
    - Return intent label
    - _Requirements: 1.1, 1.2_

- [ ] 5. Decision router (business logic)
  - [ ] 5.1 Create `app/core/decision_router.py`
    - If interested + no contact → Send Stage 1
    - If contact provided → Stop, mark unread
    - If reply to follow-up → Stop, mark unread
    - If not interested → Stop, mark complete
    - _Requirements: 1.3, 3.2, 3.3, 6.1, 6.2_

- [ ] 6. IMAP watcher (3 Gmail accounts)
  - [ ] 6.1 Create `app/imap/watcher.py`
    - Connect to 3 Gmail accounts with app passwords
    - Fetch new unseen emails
    - Filter only replies to outreach
    - Simple polling (every 60 seconds)
    - _Requirements: 4.1, 4.2, 4.3_
  
  - [ ] 6.2 Create `app/imap/controller.py`
    - Mark email as read (set \Seen flag)
    - Mark email as unread (remove \Seen flag)
    - _Requirements: 1.4, 3.1, 6.5_

- [ ] 7. SMTP sender (follow-ups)
  - [ ] 7.1 Create `app/smtp/sender.py`
    - Send email via Gmail SMTP with app password
    - Templates for Stage 1, 2, 3 (hardcoded strings)
    - Proper email threading (In-Reply-To, References headers)
    - Reply from same account that received email
    - _Requirements: 1.3, 1.4, 1.5, 7.1, 7.2, 7.3_

- [ ] 8. Redis scheduler (delayed follow-ups)
  - [ ] 8.1 Create `app/core/scheduler.py`
    - Schedule Stage 2 (24 hours) and Stage 3 (48 hours) in Redis sorted set (score = epoch seconds)
    - Check every 15 minutes for due follow-ups using ZRANGEBYSCORE
    - Use ZREM to atomically pop items from sorted set
    - Check DB before sending (verify not stopped)
    - Store `followup:{thread_id}:{stage}` key to prevent double-send
    - Cancel scheduled follow-ups when creator replies (ZREM + delete keys)
    - _Requirements: 2.1, 2.2, 2.3, 3.2_
    - **Note**: Atomic ZREM prevents race conditions between scheduler instances

- [ ] 9. Main application loop with concurrency control
  - [ ] 9.1 Create `app/main.py`
    - Simple async loop: poll IMAP → process emails → schedule follow-ups
    - Use `asyncio.Semaphore(10)` to cap concurrency at 10 emails
    - Use `asyncio.gather()` with `return_exceptions=True` for error handling
    - Run scheduler check every 15 minutes
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
    
    **Example implementation**:
    ```python
    sem = asyncio.Semaphore(10)  # Cap at 10 concurrent
    
    async def safe_process(email):
        async with sem:
            await process_email(email)
    
    # Process with concurrency control
    await asyncio.gather(
        *[safe_process(e) for e in new_emails],
        return_exceptions=True
    )
    ```

- [ ] 10. Logging
  - [ ] 10.1 Create `app/utils/logger.py`
    - Single log file: `logs/application.log`
    - Log all key events: email received, intent classified, follow-up sent, stopped
    - Simple rotating file handler (daily rotation, 30-day retention)
    - _Requirements: 5.4_

- [ ] 11. Documentation and demo
  - [ ] 11.1 Write `README.md`
    - System overview
    - Setup instructions (uv, Gmail app passwords, Groq API)
    - How to run: `uv run python -m app.main`
    - Environment variables
    - _Requirements: All_
  
  - [ ] 11.2 Create `docs/architecture_diagram.md`
    - Simple Mermaid diagram showing flow
    - Components: IMAP → Parser → Classifier → Router → SMTP/Scheduler
    - _Requirements: All_
  
  - [ ] 11.3 Create `demo.py`
    - Simple script to demonstrate the system
    - Send test email, show follow-up flow
    - _Requirements: All_

## OPTIONAL (Nice-to-Have, Not Graded)

- [ ] 12. Essential reliability features
  - [ ] 12.1 Add retry wrapper (`app/utils/retry.py`)
    - Retry decorator for network calls (IMAP/SMTP/Groq)
    - 2-3 retries with exponential backoff
    - _Requirements: 3.2_
    
    **Example implementation**:
    ```python
    async def retry_with_backoff(func, max_retries=3):
        for attempt in range(max_retries):
            try:
                return await func()
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
    ```
  
  - [ ] 12.2 Add simple debouncing (`app/core/debouncer.py`)
    - Filter trivial emails (< 10 chars, "hi", "hello")
    - 5-second Redis debounce to prevent duplicates
    - _Requirements: 1.1, 1.2_
  
  - [ ] 12.3 Add basic rate limiting
    - Simple counter in Redis (500/day per account)
    - Queue emails if limit reached
    - _Requirements: 1.4_

## Coding Standards (CRITICAL)

### Code Quality Requirements

1. **No Inline Comments**
   - Use docstrings (triple quotes) to explain functions
   - Code should be self-explanatory with good variable names
   - Only add comments for complex business logic, not obvious code

2. **Human-Written Code Style**
   - Write clean, readable code that looks natural
   - Use meaningful variable names (not `x`, `y`, `temp`)
   - Proper spacing and formatting
   - No overly clever one-liners

3. **Docstring Format**
   ```python
   async def process_email(email_data):
       """
       Process incoming email reply from creator.
       
       Extracts intent using Groq API, detects contact information,
       and routes to appropriate action (send follow-up or delegate).
       
       Args:
           email_data: Dict containing message_id, thread_id, body, sender
           
       Returns:
           bool: True if processed successfully, False otherwise
       """
       # Implementation here
   ```

4. **No Demo/Patch Code**
   - No `# TODO: Fix this later`
   - No `# Temporary workaround`
   - No placeholder functions
   - Every function must be production-ready
   - Permanent fixes only, no quick hacks

5. **Error Handling**
   - Proper try/except blocks with specific exceptions
   - Log errors with context
   - Graceful degradation, never crash

6. **Type Hints (Optional but Recommended)**
   ```python
   async def get_thread(message_id: str) -> Optional[dict]:
       """Fetch email thread from database by message ID."""
       pass
   ```

### Example: Good vs Bad Code

**❌ Bad (AI-generated looking)**:
```python
# Process the email
async def proc(e):
    # Get intent
    i = await classify(e['body'])  # classify intent
    # Check contact
    c = detect_contact(e['body'])  # detect contact info
    if c:  # if contact found
        return True  # return true
    return False  # return false
```

**✅ Good (Human-written)**:
```python
async def process_email(email_data):
    """
    Process incoming creator email and determine next action.
    
    Classifies intent using Groq API and checks for contact information.
    If contact details are found, stops automation and delegates to human.
    Otherwise, sends Stage 1 follow-up and schedules future stages.
    """
    intent = await classify_intent(email_data['body'])
    has_contact = detect_contact_info(email_data['body'])
    
    if has_contact:
        await stop_automation(email_data['thread_id'])
        await mark_for_human_review(email_data['message_id'])
        return True
    
    if intent == 'INTERESTED':
        await send_stage_one_followup(email_data)
        await schedule_future_followups(email_data['thread_id'])
    
    return True
```

## NOT NEEDED (Out of Scope)

❌ FastAPI dashboard
❌ Training data CSV collection
❌ Analytics and metrics database
❌ Complex API routes
❌ Parallel worker pool (10 workers)
❌ Multi-service docker-compose
❌ Admin UI
❌ Alembic migrations
❌ Separate AI service layer
❌ Human takeover web interface

## Simplified Architecture

```
Creator Email
    ↓
Gmail IMAP (3 accounts) ← Watcher polls every 60s
    ↓
Fetch new emails (up to 10)
    ↓
asyncio.gather() - Process 10 emails concurrently
    ├─→ Email 1: Parser → Classifier → Regex → Router → Action
    ├─→ Email 2: Parser → Classifier → Regex → Router → Action
    ├─→ Email 3: Parser → Classifier → Regex → Router → Action
    └─→ ... (up to 10 concurrent)
    ↓
Decision Router (for each email)
    ├─→ Contact found? → Stop, mark unread, log to DB
    ├─→ Interested + no contact? → Send Stage 1, schedule Stage 2 & 3, mark read
    └─→ Not interested? → Stop, mark complete
    ↓
Redis Scheduler (checks every 15 min)
    ↓
Send Stage 2 (24h) or Stage 3 (48h) via SMTP
    ↓
Mark read, log to DB
```

## File Structure (Simplified)

```
mosaic-autoresponder/
├── app/
│   ├── main.py                    # Main loop with asyncio.gather() + Semaphore
│   ├── imap/
│   │   ├── watcher.py             # Poll 3 Gmail accounts
│   │   ├── parser.py              # Parse emails (uses email_reply_parser)
│   │   ├── controller.py          # Mark read/unread
│   ├── smtp/
│   │   ├── sender.py              # Send follow-ups
│   ├── ml/
│   │   ├── classifier.py          # Groq intent classification
│   ├── core/
│   │   ├── decision_router.py     # Business logic
│   │   ├── scheduler.py           # Redis delayed tasks (atomic ZREM)
│   │   ├── debouncer.py           # (optional) Filter spam
│   ├── db/
│   │   ├── schema.sql             # PostgreSQL schema (message_id UNIQUE)
│   │   ├── connect.py             # asyncpg connection + CRUD
│   ├── utils/
│   │   ├── logger.py              # Single log file
│   │   ├── contact_detector.py    # Phone detection (uses phonenumbers)
│   │   ├── retry.py               # Retry with exponential backoff
├── logs/
│   ├── application.log            # Single log file
├── docs/
│   ├── architecture_diagram.md    # Simple Mermaid diagram
├── demo.py                         # Demo script
├── .env.example
├── .env
├── .gitignore
├── pyproject.toml
├── README.md
```

## Estimated Implementation Time

- Core functionality (tasks 1-9): **8-12 hours**
- Logging + docs (tasks 10-11): **2-3 hours**
- Optional enhancements (task 12): **1-2 hours**
- **Total: 11-17 hours**

## Key Simplifications & Best Practices

1. **No FastAPI** - Just a simple Python script with async loop
2. **No worker pool** - Use `asyncio.gather()` + `Semaphore` for concurrent processing
3. **No dashboard** - Logs are sufficient for debugging
4. **No training pipeline** - Just use Groq API directly
5. **No complex Docker setup** - Just PostgreSQL + Redis (can run locally)
6. **Single log file** - No need for separate logs per component
7. **Hardcoded templates** - No need for template management system
8. **Simple polling** - No need for IMAP IDLE or complex event handling

## Critical Fixes for Production Readiness

### 1. Async/Blocking Mismatch Fix
**Problem**: `psycopg2` is blocking, will stall async concurrency
**Solution**: Use `asyncpg` (async PostgreSQL driver)
```python
# asyncpg is non-blocking
pool = await asyncpg.create_pool(DATABASE_URL)
await pool.execute("INSERT INTO ...")
```

### 2. Idempotency Guard
**Problem**: Duplicate processing from IMAP events or scheduler races
**Solution**: UNIQUE constraint + ON CONFLICT
```sql
CREATE TABLE email_threads (
    message_id VARCHAR(255) UNIQUE NOT NULL,
    ...
);
```
```python
await pool.execute(
    "INSERT INTO email_threads (...) VALUES (...) ON CONFLICT (message_id) DO NOTHING"
)
```

### 3. Concurrency Control
**Problem**: Unlimited `asyncio.gather()` can spike threads/IO
**Solution**: Use `asyncio.Semaphore(10)` to cap concurrency
```python
sem = asyncio.Semaphore(10)

async def safe_process(email):
    async with sem:
        await process_email(email)

await asyncio.gather(*[safe_process(e) for e in emails], return_exceptions=True)
```

### 4. Scheduler Safety
**Problem**: Multiple scheduler instances can double-send
**Solution**: Atomic ZREM + check DB + Redis key
```python
# Atomic pop from sorted set
items = await redis.zrangebyscore("followups", 0, now, start=0, num=10)
await redis.zrem("followups", *items)

# Check DB before sending
thread = await db.get_thread(thread_id)
if thread.stop_reason:
    continue  # Already stopped

# Prevent double-send
key = f"followup:{thread_id}:{stage}"
if await redis.exists(key):
    continue  # Already sent
await redis.setex(key, 3600, "1")  # 1 hour TTL
```

### 5. Better Parsing Libraries
**Problem**: Regex for emails/phones has many false positives
**Solution**: Use battle-tested libraries
- `email_reply_parser` - Removes signatures, quoted text automatically
- `phonenumbers` - Validates and normalizes international phone numbers

### 6. Retry Logic
**Problem**: Network calls (IMAP/SMTP/Groq) can fail transiently
**Solution**: 2-3 retries with exponential backoff
```python
async def retry_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
```

## Concurrent Processing (Simple!)

```python
# Instead of sequential processing:
for email in new_emails:
    await process_email(email)  # Slow, one at a time

# Use asyncio.gather() for concurrency:
await asyncio.gather(*[
    process_email(email) 
    for email in new_emails[:10]  # Process up to 10 at once
])
```

**Benefits**:
- ✅ No worker pool complexity
- ✅ No Redis queue needed for processing
- ✅ Built-in Python asyncio
- ✅ Handles 600+ emails/day easily
- ✅ Simple error handling with `return_exceptions=True`

This is the **real scope** that matches the assignment grading criteria! 🎯
