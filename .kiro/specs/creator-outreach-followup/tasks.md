# Implementation Plan (Simplified - Assignment Scope Only)

## MUST-HAVES (Grading Items)

- [x] 1. Project setup and structure
  - Create clean directory structure: `app/imap/`, `app/smtp/`, `app/ml/`, `app/core/`, `app/db/`, `app/utils/`
  - Initialize with `uv init` and create virtual environment with `uv venv`
  - Add dependencies: `uv add aiosmtplib aioimaplib redis asyncpg langchain langchain-groq python-dotenv email-reply-parser phonenumbers`
  - Create `.env.example` and `.env` with Gmail credentials and Groq API key
  - Create `.gitignore` (exclude .env, .venv/, logs/, __pycache__)
  - _Requirements: 4.1, 4.2_
  - **Note**: Using `asyncpg` instead of `psycopg2` to avoid blocking DB calls in async code

- [x] 2. Database schema (PostgreSQL)
  - [x] 2.1 Create `app/db/schema.sql`
    - Table: `email_threads` (message_id UNIQUE, thread_id, account_email, creator_email, intent, has_contact, current_stage, status, stop_reason, **failed_sends INT DEFAULT 0**, **followups_sent INT DEFAULT 0**, timestamps)
    - Table: `followup_history` (email_thread_id, stage, sent_at, template_used)
    - Add indexes for performance
    - **Add UNIQUE constraint on message_id for idempotency**
    - **Add failed_sends counter for SMTP failure tracking**
    - **Add followups_sent counter for scheduler idempotency**
    - _Requirements: 5.1, 5.2, 5.3_
  
  - [x] 2.2 Create `app/db/connect.py`
    - Async PostgreSQL connection with `asyncpg` (non-blocking)
    - Connection pool: `await asyncpg.create_pool()`
    - Basic CRUD functions: `insert_thread()`, `update_thread()`, `get_thread()`
    - Use `ON CONFLICT (message_id) DO NOTHING` for idempotency
    - _Requirements: 5.1_

- [ ] 3. Email parsing and contact detection
  - [ ] 3.1 Create `app/utils/contact_detector.py`
    - Use `phonenumbers` library for phone number detection and normalization
    - **Validate with phonenumbers.is_valid_number() - if no valid numbers, treat as no contact**
    - Supports international formats, validates phone numbers
    - Address detection with keywords
    - **Don't rely on regex-only heuristics - use phonenumbers validation**
    - _Requirements: 1.2, 3.1_
  
  - [ ] 3.2 Create `app/imap/parser.py`
    - Parse raw IMAP email (headers, body, thread_id)
    - Use `email_reply_parser` to extract reply content (removes signatures, quoted text)
    - Clean email body (remove HTML)
    - Use contact_detector.py for phone/address detection
    - _Requirements: 1.2, 3.1_
    - **Note**: `email_reply_parser` strips quoted text, `phonenumbers` validates numbers

- [ ] 4. Intent classification with Groq
  - [ ] 4.1 Create `app/ml/classifier.py`
    - Set up LangChain with Groq API
    - Simple prompt: classify as INTERESTED, NOT_INTERESTED, CLARIFICATION, CONTACT_PROVIDED
    - **Add timeout: 8 seconds per LLM call**
    - **Add retry: 2 retries with exponential backoff (1s, 2s)**
    - If all retries fail, default to CLARIFICATION (human review)
    - Return intent label
    - _Requirements: 1.1, 1.2_
    - **Note**: Worst case 27s per batch (10 concurrent), fits in 60s polling window

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
    - **Handle IMAP disconnects: reconnect loop with exponential backoff**
    - **If auth errors occur, stop retrying hard (avoid account lockouts)**
    - **Log all connection issues clearly**
    - _Requirements: 4.1, 4.2, 4.3_
    - **Note**: Reconnect with backoff prevents hammering Gmail on transient failures
  
  - [ ] 6.2 Create `app/imap/controller.py`
    - Mark email as read (set \Seen flag)
    - Mark email as unread (remove \Seen flag)
    - Handle IMAP connection errors gracefully
    - _Requirements: 1.4, 3.1, 6.5_

- [ ] 7. SMTP sender (follow-ups)
  - [ ] 7.1 Create `app/smtp/sender.py`
    - Send email via Gmail SMTP with app password
    - Templates for Stage 1, 2, 3 (hardcoded strings)
    - Proper email threading (In-Reply-To, References headers)
    - Reply from same account that received email
    - **Retry SMTP with exponential backoff (2 retries)**
    - **Increment `failed_sends` counter in DB on failure**
    - **If failed_sends > 3, mark thread as ERROR and stop further sends**
    - _Requirements: 1.3, 1.4, 1.5, 7.1, 7.2, 7.3_
    - **Note**: Failed send tracking prevents infinite retry loops

- [ ] 8. Redis scheduler (delayed follow-ups)
  - [ ] 8.1 Create `app/core/scheduler.py`
    - Schedule Stage 2 (24 hours) and Stage 3 (48 hours) in Redis sorted set (score = epoch seconds)
    - Check every 15 minutes for due follow-ups using ZRANGEBYSCORE
    - **Use ZREM to atomically pop items from sorted set**
    - **Check DB status AND followups_sent count before sending**
    - **Verify thread not stopped, not in error state, and stage not already sent**
    - Store `followup:{thread_id}:{stage}` key to prevent double-send
    - Cancel scheduled follow-ups when creator replies (ZREM + delete keys)
    - _Requirements: 2.1, 2.2, 2.3, 3.2_
    - **Note**: ZREM + DB check + followups_sent prevents double sends completely

- [ ] 9. Main application loop with concurrency control
  - [ ] 9.1 Create `app/main.py`
    - Simple async loop: poll IMAP → process emails → schedule follow-ups
    - Use `asyncio.Semaphore(10)` to cap concurrency at 10 emails
    - Use `asyncio.gather()` with `return_exceptions=True` for error handling
    - Run scheduler check every 15 minutes
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
    
    **Example implementation**:
    ```python
    sem = asyncio.Semaphore(10)
    
    async def safe_process(email):
        async with sem:
            await process_email(email)
    
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
    - **Local setup instructions: PostgreSQL + Redis locally**
    - **Troubleshooting section for common issues**
    - _Requirements: All_
  
  - [ ] 11.2 Create `docs/architecture_diagram.md`
    - Simple Mermaid diagram showing flow
    - Components: IMAP → Parser → Classifier → Router → SMTP/Scheduler
    - _Requirements: All_
  
  - [ ] 11.3 Create `.env.example` with test data
    - **Point to disposable Gmail account (app password)**
    - **Local PostgreSQL and Redis URLs**
    - **Note: Instructors will run locally - don't expect external APIs**
    - Include Groq API key placeholder
    - _Requirements: All_
  
  - [ ] 11.4 Create `demo.py`
    - Simple script to demonstrate the system
    - Send test email, show follow-up flow
    - Works with local setup only
    - _Requirements: All_

## OPTIONAL (Nice-to-Have, Not Graded)

- [ ] 12. Essential reliability features
  - [ ] 12.1 Add retry wrapper (`app/utils/retry.py`)
    - Retry decorator for network calls (IMAP/SMTP/Groq)
    - 2-3 retries with exponential backoff
    - _Requirements: 3.2_
  
  - [ ] 12.2 Add simple debouncing (`app/core/debouncer.py`)
    - Filter trivial emails (< 10 chars, "hi", "hello")
    - 5-second Redis debounce to prevent duplicates
    - _Requirements: 1.1, 1.2_
  
  - [ ] 12.3 Add basic rate limiting
    - Simple counter in Redis (500/day per account)
    - Queue emails if limit reached
    - _Requirements: 1.4_

## Production Edge Cases & Failure Handling (CRITICAL)

### 1. Groq/LangChain Timeouts & Concurrent Handling
**Problem**: Slow LLM calls pile up emails in watcher
**Solution**:
```python
async def classify_with_timeout(email_body, timeout=8.0, max_retries=2):
    """
    Classify email intent with timeout and retry.
    
    Timeout: 8 seconds (reduced from 10 for faster failure)
    Retries: 2 with exponential backoff (1s, 2s)
    Fallback: CLARIFICATION (human review) if all fail
    
    Worst case per email: 8 + 1 + 8 + 2 + 8 = 27 seconds
    With 10 concurrent: Still 27 seconds total (parallel processing)
    """
    for attempt in range(max_retries + 1):
        try:
            return await asyncio.wait_for(
                classify_intent(email_body),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            if attempt == max_retries:
                logger.warning(f"LLM timeout after {max_retries} retries, defaulting to CLARIFICATION")
                return "CLARIFICATION"
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"LLM error: {e}, defaulting to CLARIFICATION")
            return "CLARIFICATION"
```

**Concurrent Processing Math**:
- 10 emails processed in parallel with `asyncio.gather()`
- Worst case: 8s + 1s + 8s + 2s + 8s = **27 seconds total**
- Polling interval: 60 seconds
- **33 seconds of buffer** before next batch
- If Groq is consistently down, emails marked as CLARIFICATION (human review)

### 2. IMAP Reconnect & Backoff
**Problem**: IMAP disconnects cause watcher to crash
**Solution**:
```python
async def connect_with_backoff(account, max_retries=5):
    """
    Connect to IMAP with exponential backoff.
    
    Stops retrying on auth errors to avoid account lockouts.
    Logs all connection issues clearly.
    """
    for attempt in range(max_retries):
        try:
            return await connect_imap(account)
        except AuthenticationError:
            logger.error(f"Auth failed for {account} - stopping retries")
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning(f"IMAP connection failed, retry in {wait}s")
            await asyncio.sleep(wait)
```

### 3. SMTP Send Failure Handling
**Problem**: Failed sends retry forever
**Solution**:
- Track `failed_sends` counter in DB
- Retry SMTP with backoff (2 retries)
- If `failed_sends > 3`, mark thread as ERROR and stop
```python
if thread.failed_sends > 3:
    await db.update_thread(thread_id, status="ERROR", stop_reason="MAX_SEND_FAILURES")
    return False
```

### 4. Scheduler Idempotency
**Problem**: Multiple scheduler instances double-send
**Solution**:
```python
items = await redis.zrangebyscore("followups", 0, now, start=0, num=10)
await redis.zrem("followups", *items)

for item in items:
    thread = await db.get_thread(thread_id)
    
    if thread.stop_reason:
        continue
    
    if thread.followups_sent >= stage:
        continue
    
    key = f"followup:{thread_id}:{stage}"
    if await redis.exists(key):
        continue
    
    await send_followup(thread, stage)
    await db.increment_followups_sent(thread_id)
    await redis.setex(key, 3600, "1")
```

### 5. Contact Detection Edge Cases
**Problem**: Regex false positives for phone numbers
**Solution**:
- Use `phonenumbers.parse()` and `phonenumbers.is_valid_number()`
- If no valid numbers found, treat as no contact
- Don't rely on regex-only heuristics
```python
import phonenumbers

def has_valid_phone(text):
    """
    Detect valid phone numbers using phonenumbers library.
    
    Returns True only if at least one valid, parseable number found.
    """
    for match in phonenumbers.PhoneNumberMatcher(text, None):
        if phonenumbers.is_valid_number(match.number):
            return True
    return False
```

### 6. Test Data & Local Setup
**Problem**: Instructors run locally, external APIs may not be reachable
**Solution**:
- `.env.example` points to disposable Gmail (app password)
- Local PostgreSQL and Redis URLs
- Clear setup instructions in README
- Demo script works with local setup only

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
   ```

### Example: Good vs Bad Code

**❌ Bad (AI-generated looking)**:
```python
async def proc(e):
    i = await classify(e['body'])
    c = detect_contact(e['body'])
    if c:
        return True
    return False
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
❌ Parallel worker pool
❌ Multi-service docker-compose
❌ Admin UI
❌ Alembic migrations
❌ Separate AI service layer
❌ Human takeover web interface

This is the **real scope** that matches the assignment grading criteria! 🎯
