# Mosaic Autoresponder - Automated Creator Follow-Up System

An intelligent email automation system that monitors multiple Gmail accounts, classifies creator responses using AI, and executes multi-stage follow-up sequences to collect contact information from interested TikTok affiliate creators.

## System Overview

The Mosaic Autoresponder automates the follow-up process for creator outreach campaigns by:

- **Monitoring** 3 Gmail accounts concurrently for creator replies
- **Classifying** email intent using Groq AI (interested, not interested, clarification, etc.)
- **Detecting** contact information (WhatsApp numbers, phone numbers, addresses)
- **Sending** automated follow-up emails at 24h and 48h intervals
- **Delegating** complex queries and replies to human agents
- **Tracking** all interactions in PostgreSQL for analytics

### Key Features

- Processes 600+ emails per day across multiple accounts
- Asynchronous processing with 10 concurrent workers
- Idempotent follow-up scheduling (no duplicates)
- Automatic human handoff when creators reply or provide contact details
- Comprehensive logging and audit trail
- Rate limiting to respect Gmail quotas

## Architecture

```
IMAP Watcher → Email Parser → Intent Classifier (Groq AI) → Decision Router
                                                                    ↓
                                                    ┌───────────────┴───────────────┐
                                                    ↓                               ↓
                                            SMTP Sender                      Mark Unread
                                                    ↓                        (Human Review)
                                            PostgreSQL Scheduler
                                            (Redis cache, 15min sync)
```

**Scheduling Architecture:**
- PostgreSQL stores `next_followup_at` timestamp (source of truth)
- Redis caches scheduled follow-ups for fast lookups
- Sync runs every 15 minutes to update Redis from PostgreSQL
- Automatic fallback to PostgreSQL if Redis is unavailable

See `app/docs/SCHEDULING_ARCHITECTURE.md` for complete details.

## Prerequisites

- Python 3.10 or higher
- PostgreSQL 14+ (local installation)
- Redis 6+ (local installation)
- Gmail accounts with app passwords enabled
- Groq API key

## Database Technology

This project uses **Prisma ORM** for PostgreSQL database access, providing:
- **Type-safe database queries** with auto-completion
- **Built-in SQL injection protection** through parameterized queries
- **Automatic connection pooling** and management
- **Schema migrations** and version control
- **Clean, maintainable code** with modern Python async/await patterns

## Setup Instructions

### 1. Install uv (Python Package Manager)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with Homebrew
brew install uv

# Verify installation
uv --version
```

### 2. Clone and Setup Project

```bash
# Clone repository
git clone <repository-url>
cd mosaic-autoresponder

# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows

# Install dependencies
uv sync
```

### 3. Install PostgreSQL Locally

**macOS:**
```bash
# Install via Homebrew
brew install postgresql@14
brew services start postgresql@14

# Create database
createdb mosaic_autoresponder
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql

# Create database
sudo -u postgres createdb mosaic_autoresponder
```

**Windows:**
- Download installer from https://www.postgresql.org/download/windows/
- Run installer and follow setup wizard
- Use pgAdmin or psql to create database `mosaic_autoresponder`

### 4. Install Redis Locally

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis-server
```

**Windows:**
- Download from https://github.com/microsoftarchive/redis/releases
- Or use WSL with Linux instructions above

### 5. Setup Gmail App Passwords

For each of your 3 Gmail accounts:

1. Enable 2-Step Verification:
   - Go to https://myaccount.google.com/security
   - Enable 2-Step Verification

2. Generate App Password:
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" and your device
   - Copy the 16-character password (format: `xxxx xxxx xxxx xxxx`)

3. Save credentials for `.env` file

### 6. Get Groq API Key

1. Sign up at https://console.groq.com/
2. Navigate to API Keys section
3. Create new API key
4. Copy key (format: `gsk_...`)

### 7. Configure Environment Variables

```bash
# Copy example file
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use your preferred editor
```

Update the following in `.env`:
- `GMAIL_ACCOUNT_1_EMAIL`, `GMAIL_ACCOUNT_2_EMAIL`, `GMAIL_ACCOUNT_3_EMAIL`
- `GMAIL_ACCOUNT_1_PASSWORD`, `GMAIL_ACCOUNT_2_PASSWORD`, `GMAIL_ACCOUNT_3_PASSWORD` (app passwords)
- `GROQ_API_KEY`
- `DATABASE_URL` (if different from default)
- `REDIS_URL` (if different from default)

### 8. Initialize Database Schema

```bash
# Create the database
createdb mosaic_autoresponder

# Apply schema using Prisma
prisma db push
```

**Note:** The database uses **Prisma ORM** for type-safe, SQL-injection-proof database access. Prisma automatically manages connection pooling and provides a clean async API. The system also uses Redis as a performance cache for scheduling. See `app/docs/SCHEDULING_ARCHITECTURE.md` for details.

### 9. Verify Setup

```bash
# Test database connection
psql -d mosaic_autoresponder -c "SELECT 1;"

# Test Redis connection
redis-cli ping
# Should return: PONG

# Test Python environment and Prisma
uv run python -c "from app.db.prisma_client import db; import redis, langchain_groq; print('✓ All dependencies installed')"

# Generate Prisma client (if not already done)
prisma generate
```

## Running the Application

### Start the System

```bash
# Run main application
uv run python -m app.main

# Or with activated virtual environment
python -m app.main
```

The system will:
1. Connect to all 3 Gmail accounts via IMAP
2. Start polling for new emails every 60 seconds
3. Process emails asynchronously (up to 10 concurrent)
4. Check for scheduled follow-ups every 15 minutes
5. Log all activities to `logs/application.log`

### Monitor Logs

```bash
# Watch application logs in real-time
tail -f logs/application.log

# View recent errors
grep ERROR logs/application.log | tail -20
```

### Stop the System

Press `Ctrl+C` to gracefully shutdown the application.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GMAIL_ACCOUNT_1_EMAIL` | First Gmail account email | Required |
| `GMAIL_ACCOUNT_1_PASSWORD` | First account app password | Required |
| `GMAIL_ACCOUNT_2_EMAIL` | Second Gmail account email | Required |
| `GMAIL_ACCOUNT_2_PASSWORD` | Second account app password | Required |
| `GMAIL_ACCOUNT_3_EMAIL` | Third Gmail account email | Required |
| `GMAIL_ACCOUNT_3_PASSWORD` | Third account app password | Required |
| `GROQ_API_KEY` | Groq API key for AI classification | Required |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres:postgres@localhost:5432/mosaic_autoresponder` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `POLLING_INTERVAL` | IMAP polling interval (seconds) | `60` |
| `MAX_CONCURRENT_WORKERS` | Max concurrent email processing | `10` |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `GMAIL_ACCOUNT_X_RATE_LIMIT_PER_DAY` | Daily email limit per account | `500` |

## Project Structure

```
mosaic-autoresponder/
├── app/
│   ├── main.py                    # Application entry point
│   ├── config/
│   │   └── settings.py            # Environment configuration
│   ├── core/
│   │   ├── decision_router.py     # Business logic routing
│   │   ├── scheduler.py           # Follow-up scheduling
│   │   ├── debouncer.py           # Duplicate prevention
│   │   └── redis_sync.py          # Redis synchronization
│   ├── db/
│   │   └── prisma_client.py       # Prisma ORM database client
│   ├── imap/
│   │   ├── watcher.py             # Email monitoring
│   │   ├── parser.py              # Email parsing
│   │   └── controller.py          # IMAP operations
│   ├── smtp/
│   │   └── sender.py              # Email sending
│   ├── ml/
│   │   └── email_analyzer.py      # AI classification
│   └── utils/
│       └── logger.py              # Logging utilities
├── prisma/
│   └── schema.prisma              # Prisma schema definition
├── docs/
│   ├── SETUP_GUIDE.md             # Setup instructions
│   ├── CHANGES_SUMMARY.md         # Change log
│   └── PRISMA_MIGRATION.md        # Prisma migration guide

├── logs/                          # Application logs
├── data/                          # Data storage
├── .env                           # Environment variables (not committed)
├── .env.example                   # Environment template
└── README.md                      # This file
```

## How It Works

### 1. Email Monitoring

The system monitors 3 Gmail accounts every 60 seconds:
- Fetches unseen emails via IMAP
- Filters for replies to outreach emails
- Queues emails for processing

### 2. Intent Classification

Each email is analyzed using Groq AI:
- **INTERESTED**: Creator shows interest
- **NOT_INTERESTED**: Creator declines
- **CLARIFICATION**: Creator asks questions
- **CONTACT_PROVIDED**: Creator shares contact details

### 3. Contact Detection

Extracts contact information using phonenumbers library:
- WhatsApp numbers
- Phone numbers (validated, international formats)
- Shipping addresses

### 4. Decision Routing

Based on intent and contact detection:
- **Interested + No Contact** → Send Stage 1 follow-up, schedule Stage 2 (24h) and Stage 3 (48h)
- **Contact Provided** → Stop automation, mark unread for human review
- **Reply to Follow-up** → Stop automation, mark unread for human review
- **Not Interested** → Stop automation, mark complete

### 5. Follow-Up Sequence

Automated follow-ups are sent at:
- **Stage 1**: Immediate (after initial interested reply)
- **Stage 2**: 24 hours after Stage 1
- **Stage 3**: 48 hours after Stage 2

Templates:
- **Stage 1**: "Could you share your WhatsApp contact and address with me? I will ask my team to connect with you immediately."
- **Stage 2**: "Just checking in — can you please share your WhatsApp contact so we can connect quickly?"
- **Stage 3**: "Wanted to follow up again — we'd love to take this forward but just need your WhatsApp number to coordinate better."

### 6. Human Handoff

Emails are marked unread for human review when:
- Creator replies to any follow-up
- Creator provides contact details
- Creator asks clarifying questions
- System is uncertain about intent

## Troubleshooting

### Common Issues

#### 1. IMAP Authentication Failed

**Error**: `Authentication failed for account@gmail.com`

**Solutions**:
- Verify 2-Step Verification is enabled on Gmail account
- Regenerate app password at https://myaccount.google.com/apppasswords
- Ensure app password is 16 characters without spaces in `.env`
- Check that IMAP is enabled in Gmail settings

#### 2. Database Connection Failed

**Error**: `could not connect to server: Connection refused`

**Solutions**:
```bash
# Check if PostgreSQL is running
brew services list | grep postgresql  # macOS
sudo systemctl status postgresql      # Linux

# Start PostgreSQL if stopped
brew services start postgresql@14     # macOS
sudo systemctl start postgresql       # Linux

# Verify connection
psql -d mosaic_autoresponder -c "SELECT 1;"

# Regenerate Prisma client if needed
prisma generate
```

#### 3. Redis Connection Failed

**Error**: `Error connecting to Redis`

**Solutions**:
```bash
# Check if Redis is running
brew services list | grep redis       # macOS
sudo systemctl status redis-server    # Linux

# Start Redis if stopped
brew services start redis             # macOS
sudo systemctl start redis-server     # Linux

# Test connection
redis-cli ping
```

#### 4. Groq API Timeout

**Error**: `LLM timeout after retries`

**Solutions**:
- Check Groq API status at https://status.groq.com/
- Verify API key is correct in `.env`
- Check internet connection
- System defaults to CLARIFICATION (human review) on timeout

#### 5. No Emails Being Processed

**Possible Causes**:
- No new unseen emails in monitored accounts
- Emails are not replies to outreach (check thread detection)
- IMAP connection dropped (check logs)

**Debug Steps**:
```bash
# Check logs for IMAP activity
grep "IMAP" logs/application.log | tail -20

# Check for processing errors
grep "ERROR" logs/application.log | tail -20

# Verify email accounts are accessible
# Send test email to one of the monitored accounts
```

#### 6. Follow-Ups Not Sending

**Possible Causes**:
- Rate limit reached (500 emails/day per account)
- SMTP authentication failed
- Redis scheduler not running

**Debug Steps**:
```bash
# Check SMTP logs
grep "SMTP" logs/application.log | tail -20

# Check scheduled follow-ups in Redis
redis-cli ZRANGE followups 0 -1 WITHSCORES

# Verify rate limit status
redis-cli GET "rate_limit:account1@gmail.com"
```

#### 7. Duplicate Follow-Ups Sent

**Should Not Happen** - System has multiple idempotency safeguards:
- Database `message_id` UNIQUE constraint
- Redis debouncing (10-second window)
- `followups_sent` counter check
- Redis lock keys

**If it happens**:
```bash
# Check database for duplicates
psql -d mosaic_autoresponder -c "SELECT message_id, COUNT(*) FROM email_threads GROUP BY message_id HAVING COUNT(*) > 1;"

# Check Redis locks
redis-cli KEYS "followup:*"
```

### Performance Issues

#### High Memory Usage

- Reduce `MAX_CONCURRENT_WORKERS` in `.env` (default: 10)
- Check for memory leaks in logs
- Restart application periodically

#### Slow Email Processing

- Check Groq API latency (timeout: 8 seconds)
- Verify database query performance
- Check Redis connection latency
- Review concurrent worker count

### Getting Help

If issues persist:
1. Check logs in `logs/application.log`
2. Enable DEBUG logging: `LOG_LEVEL=DEBUG` in `.env`
3. Review database state: `psql -d mosaic_autoresponder`
4. Check Redis state: `redis-cli MONITOR`

## Development

### Running Tests

```bash
# Install dev dependencies
uv add --dev pytest pytest-asyncio

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=app
```

### Code Quality

```bash
# Format code
uv run black app/

# Lint code
uv run ruff check app/
```

## License

[Your License Here]

## Contact

[Your Contact Information]