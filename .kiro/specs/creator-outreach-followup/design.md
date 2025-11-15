# Design Document

## Overview

The Automated Follow-Up System is a Python-based email automation service that monitors multiple Gmail accounts, classifies incoming creator responses using LLM-based intent recognition, and executes a multi-stage follow-up sequence to collect WhatsApp contact details and shipping addresses from interested creators. The system uses asynchronous processing to handle high volumes (600+ emails/day) and maintains a comprehensive database for tracking, analytics, and human delegation.

### Key Design Principles

- **Asynchronous Processing**: Handle multiple emails concurrently without blocking
- **Idempotency**: Ensure follow-ups are not duplicated even if the system restarts
- **Separation of Concerns**: Modular architecture with distinct responsibilities
- **Database-Driven State Management**: All decisions based on persistent state
- **Fail-Safe Human Handoff**: Default to human review when uncertain

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              IMAP Servers (3 Email Accounts)                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   IMAP Watcher (app/imap/watcher.py)         │
│  - Monitors 3 mailboxes via IMAP IDLE                        │
│  - Fetches new replies every 60 seconds                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Preprocessor/Parser (app/imap/parser.py)        │
│  - Cleans email content                                      │
│  - Extracts thread_id, sender, subject                       │
│  - Detects phone/address with regex                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  Worker Loop (app/core/worker.py)            │
│  - Async task queue (up to 10 concurrent workers)            │
│  - Processes jobs from Redis queue                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│            Intent Classifier (app/ml/classifier.py)          │
│  - Lightweight model + rules for fast classification         │
│  - Returns: INTERESTED, NOT_INTERESTED, CLARIFICATION, etc.  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│          Decision Router (app/core/decision_router.py)       │
│  - Business logic for follow-up/stop/human delegation        │
│  - Checks database state for idempotency                     │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Follow-Up  │  │  Database   │  │   IMAP      │
│  Scheduler  │  │ (Postgres)  │  │ Controller  │
│   (Redis)   │  │             │  │ (mark read) │
└──────┬──────┘  └─────────────┘  └─────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│              SMTP Sender (app/smtp/sender.py)                │
│  - Sends follow-up emails via SMTP                           │
│  - Uses templates for Stage 1, 2, 3                          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│          FastAPI Dashboard (app/main.py + app/web/)          │
│  - View unread threads requiring human attention             │
│  - Manual takeover interface                                 │
│  - Analytics and monitoring                                  │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

- **Language**: Python 3.10+
- **Email Integration**: Gmail IMAP/SMTP with app passwords
- **LLM Provider**: Groq API via LangChain (for all initial classification)
- **AI Framework**: LangChain for LLM orchestration and prompt management
- **Database**: PostgreSQL for persistent storage
- **Cache & Queue**: Redis for scheduling, locks, and rate limiting
- **Async Framework**: asyncio for concurrent processing
- **Web Framework**: FastAPI for dashboard, API endpoints, and AI service layer
- **Task Scheduling**: Redis-based scheduling with asyncio workers
- **Environment Management**: python-dotenv for configuration

### ML Evolution Strategy

**Phase 1 (Current)**: All classification via Groq API
- Use LangChain with Groq for intent classification
- Fast deployment, no model training required
- Collect training data in CSV for future use

**Phase 2 (Future)**: Custom model when sufficient data collected
- Train lightweight model on collected CSV data
- Deploy custom model alongside Groq API
- Gradual migration: custom model primary, Groq fallback
- Monitor accuracy and adjust threshold

## Project Structure

```
mosaic-autoresponder/
├── app/
│   ├── main.py                           # FastAPI entrypoint
│   ├── __init__.py
│
│   ├── config/
│   │   ├── settings.py                   # Pydantic settings (env loader)
│   │   ├── constants.py                  # Templates, enums, follow-up messages
│   │   ├── __init__.py
│
│   ├── core/
│   │   ├── decision_router.py            # Routing logic
│   │   ├── scheduler.py                  # Async delayed tasks (24h, 48h)
│   │   ├── worker.py                     # Processes queue jobs
│   │   ├── exceptions.py                 # Custom exception classes
│   │   ├── exception_handler.py          # FastAPI global handler
│   │   ├── rate_limit.py                 # Redis-based rate limiter
│   │   ├── __init__.py
│
│   ├── imap/
│   │   ├── watcher.py                    # Async watcher for 3 Gmail accounts
│   │   ├── controller.py                 # Mark read/unread
│   │   ├── parser.py                     # Extract body, thread-id, etc.
│   │   ├── client.py                     # IMAP client abstraction
│   │   ├── __init__.py
│
│   ├── smtp/
│   │   ├── sender.py                     # Async SMTP sender
│   │   ├── client.py                     # SMTP client abstraction
│   │   ├── __init__.py
│
│   ├── ml/
│   │   ├── classifier.py                 # Intent classifier (Groq via LangChain)
│   │   ├── prompts.py                    # LLM prompt templates
│   │   ├── training_data.py              # CSV data collection utilities
│   │   ├── __init__.py
│
│   ├── db/
│   │   ├── models.py                     # SQLAlchemy models
│   │   ├── schema.sql                    # PostgreSQL schema
│   │   ├── crud.py                       # Database CRUD functions
│   │   ├── connect.py                    # DB engine/session
│   │   ├── migrations/                   # Alembic migrations (optional)
│   │   │   ├── env.py
│   │   │   ├── versions/
│   │   ├── __init__.py
│
│   ├── utils/
│   │   ├── logger.py                     # Custom rotating logger
│   │   ├── regex.py                      # Phone/address detection patterns
│   │   ├── email_utils.py                # Extract quoted text, strip HTML
│   │   ├── time_utils.py                 # Timezone helpers
│   │   ├── decorators.py                 # Retry, backoff, timing decorators
│   │   ├── validator.py                  # Phone/address validators
│   │   ├── __init__.py
│
│   ├── web/
│   │   ├── routes.py                     # FastAPI routes
│   │   ├── ai_service.py                 # LangChain + Groq service layer
│   │   ├── dashboard.py                  # Human takeover screen
│   │   ├── templates/                    # Dashboard HTML
│   │   ├── static/                       # CSS, JS
│   │   ├── __init__.py
│
│   ├── tasks/
│   │   ├── followup_tasks.py             # Follow-up scheduling tasks
│   │   ├── inbound_tasks.py              # Processing inbound replies
│   │   ├── __init__.py
│
│   ├── queues/
│   │   ├── redis_queue.py                # Redis queue abstraction
│   │   ├── locks.py                      # Redis locks for idempotency
│   │   ├── __init__.py
│
│   ├── tests/
│   │   ├── test_parser.py
│   │   ├── test_classifier.py
│   │   ├── test_router.py
│   │   ├── test_scheduler.py
│   │   ├── test_imap.py
│   │   ├── test_smtp.py
│   │   ├── __init__.py
│
├── data/
│   ├── training_data.csv                 # ML training dataset
│
├── logs/                                  # Rotating logs (90-day retention)
│   ├── imap_watcher.log
│   ├── classifier.log
│   ├── decision_router.log
│   ├── smtp_sender.log
│   ├── scheduler.log
│   ├── worker.log
│   ├── application.log
│
├── docker/
│   ├── Dockerfile.api                    # FastAPI service
│   ├── Dockerfile.worker                 # Optional separate worker
│   ├── docker-compose.yml                # PostgreSQL + Redis + API
│
├── docs/
│   ├── system_design.md                  # Final report + diagrams
│   ├── sequence_diagram.md               # Mermaid sequence flow
│   ├── architecture_diagram.png
│   ├── db_schema.md
│   ├── README_FOR_INTERVIEWER.md
│
├── .env                                   # Actual secrets (gitignored, not committed)
├── .env.example                           # Template for .env (committed to repo)
├── .gitignore
├── .python-version                        # Python version for uv
├── pyproject.toml                         # Modern Python packaging with uv
├── uv.lock                                # Dependency lock file
├── README.md                              # Repo summary + how to run
```

### Dependency Management with uv

The project uses `uv` for fast, modern Python package management:

```bash
# Initialize project
uv init

# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Add dependencies
uv add fastapi uvicorn sqlalchemy psycopg2-binary redis
uv add aiosmtplib aioimaplib langchain langchain-groq
uv add pydantic pydantic-settings python-dotenv

# Add dev dependencies
uv add --dev pytest pytest-asyncio black ruff

# Install all dependencies
uv sync

# Run application
uv run python -m app.main
```

## Components and Interfaces

### 1. IMAP Watcher (`app/imap/watcher.py`)

**Responsibility**: Monitor 3 Gmail accounts via IMAP and fetch new replies

**Key Methods**:
- `watch_all_mailboxes()`: Start IMAP IDLE connections for 3 Gmail accounts
- `fetch_new_replies(account_config)`: Get unseen emails from inbox
- `is_reply_to_outreach(email_headers)`: Check if email is a reply to outreach
- `enqueue_for_processing(email_data)`: Add to Redis processing queue

**Gmail Configuration**:
```python
GMAIL_ACCOUNTS = [
    {
        "email": "account1@gmail.com",
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "username": "account1@gmail.com",
        "app_password": "xxxx xxxx xxxx xxxx"  # 16-char app password
    },
    {
        "email": "account2@gmail.com",
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "username": "account2@gmail.com",
        "app_password": "xxxx xxxx xxxx xxxx"
    },
    {
        "email": "account3@gmail.com",
        "imap_server": "imap.gmail.com",
        "imap_port": 993,
        "username": "account3@gmail.com",
        "app_password": "xxxx xxxx xxxx xxxx"
    }
]
POLLING_INTERVAL = 60  # seconds
```

**Gmail App Password Setup**:
1. Enable 2-Step Verification on Gmail account
2. Go to Google Account → Security → App passwords
3. Generate app password for "Mail" application
4. Use 16-character password in configuration

### 2. Preprocessor/Parser (`app/imap/parser.py`)

**Responsibility**: Clean and extract structured data from raw emails

**Key Methods**:
- `parse_email(raw_email)`: Extract headers, body, metadata
- `clean_email_body(body)`: Remove signatures, quoted text, HTML
- `extract_thread_id(headers)`: Get email thread identifier
- `detect_contact_info(body)`: Regex-based phone/address detection

**Extraction Patterns**:
```python
PHONE_PATTERNS = [
    r'\+?\d{1,4}[\s-]?\(?\d{1,4}\)?[\s-]?\d{1,4}[\s-]?\d{1,9}',
    r'whatsapp[:\s]+\+?\d+',
    r'\d{10,15}'
]
ADDRESS_KEYWORDS = ['address', 'shipping', 'delivery', 'street', 'city', 'zip']
```

### 3. Intent Classifier (`app/ml/classifier.py`)

**Responsibility**: Classify creator intent using Groq API via LangChain

**Intent Categories**:
- `INTERESTED`: Creator shows interest (e.g., "Yes", "Tell me more", "Interested")
- `NOT_INTERESTED`: Creator declines (e.g., "No thanks", "Not interested")
- `CLARIFICATION`: Creator asks questions (e.g., "What's the retainer?", "How does it work?")
- `CONTACT_PROVIDED`: Creator shares contact details
- `CONTACT_PROVIDED`: Creator shares contact details
- `CONTINUE_EMAIL`: Creator explicitly wants to continue via email

**Classification Strategy (Phase 1)**:
- All classification via Groq API using LangChain
- Structured prompt with few-shot examples
- Response parsing to extract intent label
- Save all classifications to training CSV

**LangChain Implementation**:
```python
from langchain_groq import ChatGroq
from langchain.prompts import ChatPromptTemplate

llm = ChatGroq(
    model="mixtral-8x7b-32768",  # or llama2-70b-4096
    temperature=0,
    groq_api_key=os.getenv("GROQ_API_KEY")
)

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an email intent classifier..."),
    ("user", "Classify this email: {email_text}")
])

chain = prompt | llm
```

**Key Methods**:
- `classify_intent(email_body: str) -> dict`: Returns {intent, confidence}
- `_build_prompt(text: str) -> str`: Construct classification prompt
- `_parse_response(response: str) -> str`: Extract intent from LLM response
- `save_to_training_data(email_text: str, intent: str)`: Append to CSV

**Future Enhancement (Phase 2)**:
- Train custom model on collected CSV data
- Use custom model as primary, Groq as fallback
- Implement A/B testing between models

### 4. Decision Router (`app/core/decision_router.py`)

**Responsibility**: Business logic to determine follow-up, stop, or human delegation

**Decision Logic**:
```python
def determine_action(email_data, intent, has_contact_details):
    # Check if already in follow-up sequence
    existing_record = db.get_email_record(email_data['message_id'])
    
    if existing_record:
        # This is a reply to our follow-up
        return Action.DELEGATE_TO_HUMAN
    
    # New reply to outreach
    if intent == 'NOT_INTERESTED':
        return Action.MARK_COMPLETE
    
    if intent in ['INTERESTED', 'CLARIFICATION']:
        if has_contact_details:
            return Action.DELEGATE_TO_HUMAN
        else:
            return Action.START_FOLLOWUP_STAGE_1
    
    if intent == 'CONTACT_PROVIDED':
        return Action.DELEGATE_TO_HUMAN
    
    if intent == 'CONTINUE_EMAIL':
        return Action.DELEGATE_TO_HUMAN
    
    # Default to human review for uncertain cases
    return Action.DELEGATE_TO_HUMAN
```

**Key Methods**:
- `route_email(email_data, intent, contact_info) -> Action`
- `should_start_followup(email_data) -> bool`
- `should_delegate_to_human(email_data) -> bool`

### 5. Rate Limiter (`app/core/rate_limit.py`)

**Responsibility**: Enforce Gmail SMTP rate limits using token bucket algorithm

**Problem**: Gmail has sending limits that vary by account type (free, workspace, etc.)

**Solution**: Redis-based token bucket with configurable limits per account

**Token Bucket Algorithm**:
```python
class RateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check_rate_limit(self, account_email: str) -> bool:
        """Check if account can send email (has tokens available)"""
        key = f"rate_limit:{account_email}"
        limit = self.get_account_limit(account_email)  # From env var
        
        # Get current token count
        tokens = await self.redis.get(key)
        if tokens is None:
            # Initialize bucket with full capacity
            await self.redis.setex(key, 86400, limit)  # 24 hours
            return True
        
        return int(tokens) > 0
    
    async def consume_token(self, account_email: str) -> bool:
        """Consume one token (send one email)"""
        key = f"rate_limit:{account_email}"
        
        # Decrement token count
        tokens = await self.redis.decr(key)
        
        if tokens < 0:
            # No tokens available, restore and return False
            await self.redis.incr(key)
            return False
        
        return True
    
    async def get_remaining_quota(self, account_email: str) -> int:
        """Get remaining emails that can be sent today"""
        key = f"rate_limit:{account_email}"
        tokens = await self.redis.get(key)
        return int(tokens) if tokens else 0
```

**Configuration (Per Account)**:
```python
# Load from environment variables
RATE_LIMITS = {
    "account1@gmail.com": int(os.getenv("GMAIL_ACCOUNT_1_RATE_LIMIT_PER_DAY", 500)),
    "account2@gmail.com": int(os.getenv("GMAIL_ACCOUNT_2_RATE_LIMIT_PER_DAY", 500)),
    "account3@gmail.com": int(os.getenv("GMAIL_ACCOUNT_3_RATE_LIMIT_PER_DAY", 500)),
}
```

**Graceful Degradation**:
```python
async def send_with_rate_limit(self, account_email: str, email_data: dict):
    """Send email with rate limit checking"""
    
    # Check rate limit
    if not await self.rate_limiter.check_rate_limit(account_email):
        # Limit reached, queue for later
        await self.queue_for_retry(email_data, delay_hours=1)
        logger.warning(f"Rate limit reached for {account_email}, queued for retry")
        return False
    
    # Consume token
    if not await self.rate_limiter.consume_token(account_email):
        # Race condition, queue for later
        await self.queue_for_retry(email_data, delay_hours=1)
        return False
    
    # Send email
    await self.smtp_sender.send_email(email_data)
    return True
```

**Important Notes**:
- Gmail rate limits vary by account type:
  - Free Gmail: ~500 emails/day (unverified, may be lower)
  - Google Workspace: ~2000 emails/day (varies by plan)
  - Must verify actual limits for your specific accounts
- Default 500/day is a conservative suggestion
- Token bucket resets every 24 hours
- Emails that hit rate limit are queued for retry (1 hour delay)

**Redis Keys**:
- `rate_limit:{account_email}` - Token count (24-hour TTL)

### 6. Follow-Up Scheduler (`app/core/scheduler.py`)

**Responsibility**: Schedule delayed follow-ups using Redis

**Scheduling Mechanism**:
- Use Redis sorted sets with timestamp scores
- Worker checks Redis every 15 minutes for due follow-ups
- TTL-based expiration for completed threads

**Key Methods**:
- `schedule_followup(email_id, stage, delay_hours)`: Add to Redis queue
- `get_due_followups() -> List[dict]`: Fetch emails needing follow-up
- `cancel_followup(email_id)`: Remove from schedule (when creator replies)

**Redis Keys**:
```python
followup:stage2  # Sorted set for 24h follow-ups
followup:stage3  # Sorted set for 48h follow-ups
lock:email:{email_id}  # Prevent duplicate processing
```

### 6. SMTP Sender (`app/smtp/sender.py`)

**Responsibility**: Send follow-up emails via SMTP

**Message Templates**:
```python
STAGE_1_TEMPLATE = "Could you share your WhatsApp contact and address with me? I will ask my team to connect with you immediately."

STAGE_2_TEMPLATE = "Just checking in — can you please share your WhatsApp contact so we can connect quickly?"

STAGE_3_TEMPLATE = "Wanted to follow up again — we'd love to take this forward but just need your WhatsApp number to coordinate better."
```

**Key Methods**:
- `send_email(to, subject, body, reply_to_message_id, from_account)`: Send via SMTP from same account
- `get_template(stage) -> str`: Get message template for stage
- `compose_reply(original_email, template) -> dict`: Build email with headers
- `get_account_for_thread(thread_id) -> str`: Retrieve which account received original email

**Thread Continuity**:
- Always reply from the same Gmail account that received the creator's email
- Use `account_email` field from database to determine sender
- Maintain proper email threading with `In-Reply-To` and `References` headers

**Gmail SMTP Configuration**:
```python
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USE_TLS = True
# Uses same app passwords as IMAP
```

### 7. IMAP Controller (`app/imap/controller.py`)

**Responsibility**: Mark emails as read/unread via IMAP

**Key Methods**:
- `mark_as_read(account, message_id)`
- `mark_as_unread(account, message_id)`
- `get_connection(account) -> IMAPClient`: Connection pool management

### 8. Worker Loop (`app/core/worker.py`)

**Responsibility**: Async task processing from Redis queue

**Worker Flow**:
1. Fetch job from Redis queue
2. Acquire lock for email_id (prevent duplicate processing)
3. Parse email → Classify intent → Route decision
4. Execute action (send follow-up, delegate, mark complete)
5. Update database and release lock

**Key Methods**:
- `start_workers(num_workers=10)`: Start concurrent workers
- `process_job(job_data)`: Main processing logic
- `acquire_lock(email_id) -> bool`: Redis-based locking

### 9. Database Models (`app/db/models.py`)

**Responsibility**: PostgreSQL schema and ORM models

See "Data Models" section below for detailed schema.

### 11. Email Filter & Debouncer (`app/core/email_filter.py`)

**Responsibility**: Prevent duplicate processing and filter trivial emails using two-layer debouncing

**Problem**: 
1. IMAP duplicate events can trigger multiple processing of same email
2. Creators send back-to-back trivial replies ("hi", "ok", "?")
3. Need to prevent duplicate DB rows, duplicate follow-ups, and noisy behavior

**Solution**: Two-layer Redis-based debouncing strategy

**Layer 1: Inbound Debounce** (Prevents duplicate event processing)
```python
async def check_inbound_debounce(self, thread_id: str) -> bool:
    """Prevent duplicate processing of same inbound event"""
    key = f"debounce_inbound:{thread_id}"
    
    # Check if recently processed
    if await self.redis.exists(key):
        return False  # Skip, already processing
    
    # Mark as processing for 10 seconds
    await self.redis.setex(key, 10, "1")
    return True  # OK to process
```

**Layer 2: Trivial Debounce** (Suppresses repeated trivial messages)
```python
TRIVIAL_PATTERNS = ['hi', 'hello', 'thanks', 'thank you', 'ok', 'okay', '?', 'yes', 'no']
MIN_CONTENT_LENGTH = 10

async def check_trivial_debounce(self, thread_id: str, email_body: str) -> bool:
    """Suppress repeated trivial messages"""
    cleaned = email_body.strip().lower()
    
    # Check if trivial
    is_trivial = (
        len(cleaned) < self.MIN_CONTENT_LENGTH or
        cleaned in self.TRIVIAL_PATTERNS
    )
    
    if not is_trivial:
        return True  # Not trivial, process immediately
    
    # Check if trivial message recently sent
    key = f"debounce_trivial:{thread_id}"
    if await self.redis.exists(key):
        return False  # Skip, recent trivial message
    
    # Mark trivial message sent for 30 seconds
    await self.redis.setex(key, 30, "1")
    return True  # OK to process this trivial message
```

**Important: Meaningful Messages Always Processed**
```python
def is_meaningful(self, email_body: str) -> bool:
    """Check if email contains meaningful content that should bypass debounce"""
    # Contact details (phone, WhatsApp, address)
    if self.has_contact_details(email_body):
        return True
    
    # Clarifying questions (contains "?", "how", "what", "when")
    if self.has_questions(email_body):
        return True
    
    # Sufficient length and content
    if len(email_body.strip()) > 20:
        return True
    
    return False
```

**Complete Flow**:
```python
async def should_process(self, thread_id: str, email_body: str) -> bool:
    """Determine if email should be processed"""
    
    # 1. Check inbound debounce (prevent duplicate events)
    if not await self.check_inbound_debounce(thread_id):
        return False  # Duplicate event, skip
    
    # 2. Check if meaningful (bypass trivial debounce)
    if self.is_meaningful(email_body):
        return True  # Always process meaningful messages
    
    # 3. Check trivial debounce (suppress repeated trivial messages)
    if not await self.check_trivial_debounce(thread_id, email_body):
        return False  # Recent trivial message, skip
    
    return True  # OK to process
```

**Redis Keys**:
- `debounce_inbound:{thread_id}` - 10-second TTL, prevents duplicate event processing
- `debounce_trivial:{thread_id}` - 30-second TTL, suppresses repeated trivial messages

**Benefits**:
- ✅ Prevents duplicate DB rows from IMAP duplicate events
- ✅ Prevents duplicate Stage-1 follow-ups
- ✅ Suppresses noisy trivial replies ("hi", "ok", "?")
- ✅ Prevents repeated unread marking or human handoffs
- ✅ **Never blocks meaningful messages** (contact details, questions, real intent)
- ✅ Keeps system stable and responsive

**Example Scenarios**:

**Scenario 1: IMAP Duplicate Event**
```
00:00 - IMAP event: New email in thread123
       → debounce_inbound:thread123 set (10s)
       → Process email

00:01 - IMAP duplicate event: Same email
       → debounce_inbound:thread123 exists
       → Skip (duplicate)
```

**Scenario 2: Trivial Spam**
```
00:00 - Creator sends: "hi"
       → Trivial, but first one
       → debounce_trivial:thread123 set (30s)
       → Process (mark unread, delegate)

00:05 - Creator sends: "hello"
       → Trivial, debounce_trivial exists
       → Skip (recent trivial)

00:10 - Creator sends: "ok"
       → Trivial, debounce_trivial exists
       → Skip (recent trivial)

00:35 - Creator sends: "thanks"
       → Trivial, debounce_trivial expired
       → Process (mark unread again)
```

**Scenario 3: Meaningful Message (Bypasses Debounce)**
```
00:00 - Creator sends: "hi"
       → Trivial, debounce_trivial set (30s)
       → Process

00:05 - Creator sends: "My WhatsApp is +1234567890"
       → Meaningful (contact details)
       → **Bypass debounce, process immediately**
       → Stop automation, delegate to human
```

### 10. FastAPI Application (`app/main.py` + `app/web/`)

**Responsibility**: Web interface, API endpoints, and AI service layer

**API Endpoints**:
- `GET /api/threads/unread`: List threads needing human attention
- `GET /api/threads/{id}`: View thread details
- `POST /api/threads/{id}/takeover`: Mark as manually handled
- `GET /api/stats`: System statistics (emails processed, follow-up rates)
- `POST /api/classify`: Manual classification endpoint (for testing)
- `GET /api/training-data/stats`: Training data collection statistics

**AI Service Layer**:
- Centralized LangChain + Groq integration
- Prompt management and versioning
- Response caching for efficiency
- Error handling and fallback logic

**Dashboard Features**:
- View unread threads requiring human review
- Search and filter by account, date, intent
- Manual takeover button
- Analytics: conversion rates, drop-off analysis
- Training data collection progress
- LLM usage metrics (API calls, costs, latency)

## Data Models

### Database Schema

#### Table: `email_threads`

Stores the main email thread information and current state.

```sql
CREATE TABLE email_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id VARCHAR(255) UNIQUE NOT NULL,  -- Gmail message ID
    thread_id VARCHAR(255) NOT NULL,           -- Gmail thread ID
    account_email VARCHAR(255) NOT NULL,       -- Which of 3 accounts
    creator_email VARCHAR(255) NOT NULL,       -- Creator's email
    subject TEXT,
    received_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP,
    
    -- Intent and extraction results
    intent VARCHAR(50),                        -- INTERESTED, NOT_INTERESTED, etc.
    has_whatsapp BOOLEAN DEFAULT FALSE,
    has_address BOOLEAN DEFAULT FALSE,
    extracted_details TEXT,                    -- JSON string of extracted info
    
    -- Follow-up state
    current_stage INTEGER DEFAULT 0,           -- 0=initial, 1=stage1, 2=stage2, 3=stage3
    last_followup_sent_at TIMESTAMP,
    followup_count INTEGER DEFAULT 0,
    
    -- Status tracking
    status VARCHAR(50) NOT NULL,               -- PROCESSING, FOLLOWUP_ACTIVE, DELEGATED, COMPLETED
    stop_reason VARCHAR(100),                  -- CONTACT_PROVIDED, REPLIED, MAX_FOLLOWUPS, etc.
    delegated_to_human BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_status ON email_threads(status);
CREATE INDEX idx_followup_stage ON email_threads(current_stage, last_followup_sent_at);
CREATE INDEX idx_account ON email_threads(account_email);
```

#### Table: `followup_history`

Tracks each follow-up action for audit and analysis.

```sql
CREATE TABLE followup_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_thread_id INTEGER NOT NULL,
    stage INTEGER NOT NULL,                    -- 1, 2, or 3
    message_id VARCHAR(255),                   -- Gmail message ID of follow-up
    template_used TEXT,
    sent_at TIMESTAMP NOT NULL,
    marked_as_read BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (email_thread_id) REFERENCES email_threads(id)
);

CREATE INDEX idx_thread_history ON followup_history(email_thread_id);
```

#### Table: `email_replies`

Stores all replies received during follow-up sequences.

```sql
CREATE TABLE email_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_thread_id INTEGER NOT NULL,
    message_id VARCHAR(255) UNIQUE NOT NULL,
    reply_body TEXT,
    received_at TIMESTAMP NOT NULL,
    triggered_delegation BOOLEAN DEFAULT FALSE,
    
    FOREIGN KEY (email_thread_id) REFERENCES email_threads(id)
);
```

#### Table: `processing_log`

Audit trail for debugging and monitoring.

```sql
CREATE TABLE processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_thread_id INTEGER,
    action VARCHAR(100) NOT NULL,
    details TEXT,                              -- JSON string with additional info
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Data Collection and Logging Strategy

### Training Data Collection

**Purpose**: Build a minimal, clean dataset for future model training and improvement

**Implementation**:
- Separate CSV file: `data/training_data.csv`
- Columns: `email_text` (cleaned), `intent_label` (final classification)
- Only stores successfully classified emails
- No PII, no metadata, no operational details
- Permanent storage for ML pipeline iteration

**CSV Format**:
```csv
email_text,intent_label
"Yes I'm interested in collaborating",INTERESTED
"No thanks not for me",NOT_INTERESTED
"What's the retainer structure?",CLARIFICATION
```

**Benefits**:
- Lightweight and easy to version control
- Simple to load for model training
- Clean separation from operational data
- Easy to audit and validate labels

### Operational Logging

**Purpose**: Detailed system event tracking for debugging, monitoring, and analytics

**Implementation**:
- Custom rotating file logger under `logs/` directory
- Structured log format (JSON or key-value pairs)
- Daily rotation with 90-day retention policy
- Separate log files by component for easier debugging

**Log Files**:
```
logs/
├── imap_watcher.log       # Email fetching events
├── classifier.log         # Intent classification decisions
├── decision_router.log    # Routing logic and actions
├── smtp_sender.log        # Follow-up sending events
├── scheduler.log          # Follow-up scheduling events
├── worker.log             # Worker processing events
└── application.log        # General application events
```

**Log Rotation Configuration**:
```python
from logging.handlers import TimedRotatingFileHandler

handler = TimedRotatingFileHandler(
    filename='logs/application.log',
    when='midnight',
    interval=1,
    backupCount=90,  # Keep 90 days
    encoding='utf-8'
)
```

**Logged Events**:
- Email received (message_id, account, timestamp)
- Intent classification (email_id, intent, confidence, method: rule/llm)
- LLM fallback usage (when rules fail)
- Contact detection results (has_phone, has_address)
- Decision routing (action taken, reason)
- Follow-up scheduling (stage, scheduled_time)
- IMAP flag updates (mark read/unread)
- SMTP sending (success/failure, retry attempts)
- Errors and exceptions (full stack trace)

**Benefits**:
- Detailed operational visibility
- Automatic cleanup prevents storage bloat
- Component-level logs for targeted debugging
- Sufficient history for analytics (90 days)
- Production-friendly and compliant

### Separation of Concerns

| Aspect | Training Data CSV | Operational Logs |
|--------|------------------|------------------|
| **Purpose** | ML model training | System debugging & monitoring |
| **Content** | Cleaned email text + label | Full event details + metadata |
| **Retention** | Permanent | 90 days (rotating) |
| **Size** | Minimal (2 columns) | Detailed (all fields) |
| **PII** | None | Sanitized/hashed |
| **Use Case** | Model improvement | Troubleshooting & analytics |

## Error Handling

### Error Categories and Strategies

1. **IMAP Errors**
   - Rate limiting: Implement exponential backoff
   - Authentication failures: Log error and alert admin
   - Network timeouts: Retry up to 3 times with 5-second delays
   - Connection drops: Automatic reconnection with backoff

2. **LLM API Errors**
   - Rate limiting: Queue requests and retry
   - Invalid responses: Default to human delegation
   - Timeout: Retry once, then delegate to human
   - Log all LLM fallback usage for monitoring

3. **Database Errors**
   - Connection failures: Retry with connection pool
   - Constraint violations: Log and skip (idempotency)
   - Transaction failures: Rollback and retry
   - Deadlocks: Retry with exponential backoff

4. **SMTP Errors**
   - Send failures: Retry up to 3 times
   - Authentication errors: Log and alert
   - Rate limiting: Implement backoff and queue

5. **Processing Errors**
   - Malformed emails: Log and delegate to human
   - Unexpected intent: Default to human delegation
   - Missing data: Log error and mark for manual review
   - Parser failures: Log raw email and delegate

### Retry Strategy

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError))
)
async def process_email(email_data):
    # Processing logic
    pass
```

### Logging Levels

- **DEBUG**: Detailed processing info (intent classification details, extraction results)
- **INFO**: Normal operations (email received, follow-up sent, scheduled)
- **WARNING**: Recoverable errors (API rate limit, retry triggered, LLM fallback)
- **ERROR**: Failures requiring attention (auth failure, database error, send failure)
- **CRITICAL**: System-level failures (service crash, all accounts unreachable)

## Testing Strategy

### Unit Tests

- **Intent Classifier**: Test with sample emails for each intent category
- **Contact Extractor**: Test regex patterns and LLM extraction with various formats
- **Decision Engine**: Test all decision paths with different email states
- **Database Operations**: Test CRUD operations and query logic

### Integration Tests

- **Gmail API Integration**: Test with mock Gmail API responses
- **LLM Integration**: Test with mock LLM responses and real API calls
- **End-to-End Flow**: Test complete flow from email receipt to follow-up

### Test Data

Create sample emails covering:
- Interested replies without contact details
- Interested replies with WhatsApp numbers
- Interested replies with addresses
- Not interested replies
- Clarification questions
- Replies to follow-ups
- Edge cases (empty emails, non-English, special characters)

### Performance Testing

- **Load Test**: Simulate 600 emails/day across 3 accounts
- **Concurrency Test**: Verify 10 concurrent email processing
- **Timing Test**: Ensure processing completes within 2 minutes per email

### Manual Testing Checklist

- [ ] Verify emails are marked as read after follow-ups
- [ ] Verify emails are marked as unread when creator replies
- [ ] Verify follow-up timing (24h and 48h delays)
- [ ] Verify maximum 2 follow-ups per thread
- [ ] Verify human delegation scenarios
- [ ] Test with all 3 Gmail accounts
- [ ] Verify database records are created correctly

## Configuration Management

### Environment Variables

**File Structure**:
- `.env.example` - Template with placeholder values (committed to repo)
- `.env` - Actual secrets (gitignored, user creates from .env.example)

**`.env.example` Template**:
```bash
# Gmail IMAP Configuration (3 accounts with app passwords)
GMAIL_ACCOUNT_1_EMAIL=your_email_1@gmail.com
GMAIL_ACCOUNT_1_APP_PASSWORD=your_16_char_app_password_here
GMAIL_ACCOUNT_1_IMAP_SERVER=imap.gmail.com
GMAIL_ACCOUNT_1_IMAP_PORT=993

GMAIL_ACCOUNT_2_EMAIL=your_email_2@gmail.com
GMAIL_ACCOUNT_2_APP_PASSWORD=your_16_char_app_password_here
GMAIL_ACCOUNT_2_IMAP_SERVER=imap.gmail.com
GMAIL_ACCOUNT_2_IMAP_PORT=993

GMAIL_ACCOUNT_3_EMAIL=your_email_3@gmail.com
GMAIL_ACCOUNT_3_APP_PASSWORD=your_16_char_app_password_here
GMAIL_ACCOUNT_3_IMAP_SERVER=imap.gmail.com
GMAIL_ACCOUNT_3_IMAP_PORT=993

# Gmail SMTP Configuration (uses same app passwords)
GMAIL_SMTP_SERVER=smtp.gmail.com
GMAIL_SMTP_PORT=587
GMAIL_SMTP_USE_TLS=true

# Groq API Configuration (via LangChain)
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=mixtral-8x7b-32768
# Alternative models: llama2-70b-4096, gemma-7b-it
GROQ_TEMPERATURE=0
GROQ_MAX_TOKENS=150

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/followup_db

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Processing Configuration
MAX_CONCURRENT_WORKERS=10
POLLING_INTERVAL_SECONDS=60
FOLLOWUP_CHECK_INTERVAL_MINUTES=15

# Follow-up Timing
STAGE_2_DELAY_HOURS=24
STAGE_3_DELAY_HOURS=48

# Rate Limiting (Gmail quotas vary - verify for your account type)
# Free Gmail: ~500/day, Google Workspace: ~2000/day, varies by account
GMAIL_ACCOUNT_1_RATE_LIMIT_PER_DAY=500
GMAIL_ACCOUNT_2_RATE_LIMIT_PER_DAY=500
GMAIL_ACCOUNT_3_RATE_LIMIT_PER_DAY=500
RATE_LIMIT_ALGORITHM=token_bucket

# Logging
LOG_LEVEL=INFO
LOG_FILE=./logs/followup_system.log
```

**Setup Instructions**:
1. Copy `.env.example` to `.env`: `cp .env.example .env`
2. Edit `.env` with your actual credentials
3. Never commit `.env` to version control (it's in `.gitignore`)

## Deployment Considerations

### Local Development

- Use SQLite for database
- Single process with asyncio
- Manual Gmail API credential setup

### Production Deployment

- Use PostgreSQL for better concurrency
- Deploy as a long-running service (systemd, Docker, or cloud service)
- Implement health checks and monitoring
- Set up alerting for errors and failures
- Use secrets management for API keys and credentials

### Monitoring Metrics

- Emails processed per hour
- Follow-up success rate (contact details obtained)
- Human delegation rate
- Processing time per email
- API error rates
- Database query performance
