# Sequence Flow Diagram

## Complete System Flow

```
Creator           Gmail IMAP        IMAP Watcher      Processing Layer    Intent+Contact       DB (SQL)       Redis (ZSET & Locks)       Follow-up Sender     Human Agent
|                  |                  |                    |                  |                  |                    |                     |                |
|--- Reply Email -->|                  |                    |                  |                  |                    |                     |                |
|                  |--- New UID ------>|                    |                  |                  |                    |                     |                |
|                  |                  |--- Fetch Email ---->|                  |                  |                    |                     |                |
|                  |                  |                    |-- Check inbound debounce (10s) ----->|                    |                     |                |
|                  |                  |                    |<-- If duplicate event, skip ---------|                    |                     |                |
|                  |                  |                    |-- Check if meaningful (contact/questions) -------------->|                     |                |
|                  |                  |                    |<-- If meaningful, bypass trivial debounce --------------|                     |                |
|                  |                  |                    |-- Check trivial debounce (30s) ------>|                    |                     |                |
|                  |                  |                    |<-- If recent trivial, skip ----------|                    |                     |                |
|                  |                  |                    |-- Acquire lock (idempotency) ------->|                    |                     |                |
|                  |                  |                    |<-- Lock acquired -------------------|                    |                     |                |
|                  |                  |------------------------------ Clean + Normalize Text ------------------------------>|                     |                |
|                  |                  |                                                              |                     |                     |                |
|                  |                  |                                            |-- LLM Intent Classifier (Groq) ---------|                     |                |
|                  |                  |                                            |-- Regex Contact Check ------------------|                     |                |
|                  |                  |                                            |<-- intent + contact --------------------|                     |                |
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |--- Update SQL (new thread/row) -------->|                     |                |
|                  |                  |                                            |<-- row created/updated -----------------|                     |                |
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |---- if contact_found: STOP FLOW --------|                     |                |
|                  |                  |                                            |          │                              |                     |                |
|                  |                  |                                            |          ▼                              |                     |                |
|                  |                  |                                            |--- Update SQL stop_reason ------------->|                     |                |
|                  |                  |                                            |--- Mark thread UNREAD (IMAP) -------------------------------->|                |
|                  |                  |                                            |--- Cancel scheduled follow-ups -------->|                     |                |
|                  |                  |                                            |--- Release lock ----------------------->|                     |                |
|                  |                  |                                            |---------------------------------------------------------------------> Human Agent notified
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |---- elseif intent = interested_no_contact -------------------|                |
|                  |                  |                                            |                       |                 |                     |                |
|                  |                  |                                            |                       ▼                 |                     |                |
|                  |                  |                                            |---- Send Stage-1 Follow-up (SMTP) ------------------------------>|                |
|                  |                  |                                            |---- Mark READ (IMAP) ------------------------------------------------>|                |
|                  |                  |                                            |---- Log stage-1 in SQL ---------------->|                     |                |
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |---- Schedule Stage-2 (24h) in Redis --->|                     |                |
|                  |                  |                                            |---- Schedule Stage-3 (48h) in Redis --->|                     |                |
|                  |                  |                                            |---- Release lock ----------------------->|                     |                |
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |                                         |                     |                |
|--- Reply Again --->|                 |                    |                  |                  |                    |                     |                |
| (e.g. sends contact)|               |--- New UID ------->|                    |                  |                    |                     |                |
|                  |                  |--- Fetch Email ---->|                    |                  |                    |                     |                |
|                  |                  |                    |-- Acquire lock ---------------------->|                    |                     |                |
|                  |                  |                    |<-- Lock acquired --------------------|                    |                     |                |
|                  |                  |                                            |-- Check if reply to follow-up -------->|                     |                |
|                  |                  |                                            |<-- Yes, it's a reply ------------------|                     |                |
|                  |                  |                                            |-- LLM / Regex -------------------------|                     |                |
|                  |                  |                                            |<-- contact detected -------------------|                     |                |
|                  |                  |                                            |---- STOP automation ------------------->|                     |                |
|                  |                  |                                            |---- Delete Stage-2 & 3 from Redis ----->|                     |                |
|                  |                  |                                            |---- Update SQL stop_reason ------------>|                     |                |
|                  |                  |                                            |---- Mark UNREAD (IMAP) ------------------------------------------------> Human Agent
|                  |                  |                                            |---- Release lock ----------------------->|                     |                |
|                  |                  |                                            |                                         |                     |                |
|                  |                  |                                            |                                         |                     |                |
|... (24 hours pass) ...              |                    |                  |                  |                    |                     |                |
|                  |                  |                    |                  |                  |                    |-- Scheduler pops Stage-2 ----|                |
|                  |                  |                    |                  |                  |                    |--- Acquire thread lock ----->|                |
|                  |                  |                    |                  |                  |                    |--- Check SQL stop_reason ---->|                |
|                  |                  |                    |                  |                  |                    |<-- STOP? If yes, abort -------|                |
|                  |                  |                    |                  |                  |                    |--- If not, send Stage-2 ----->|                |
|                  |                  |                    |                  |                  |                    |--- Mark READ via IMAP ------->|                |
|                  |                  |                    |                  |                  |                    |--- Update SQL stage ---------->|                |
|                  |                  |                    |                  |                  |                    |--- Release lock --------------|                |
|                  |                  |                    |                  |                  |                    |                     |                |
```

## Key Decision Points

### 1. Initial Reply Processing
- **Contact Found**: Stop automation, mark unread, delegate to human
- **Interested + No Contact**: Send Stage 1, schedule Stage 2 & 3
- **Not Interested**: Mark complete, no follow-up
- **Clarification**: Delegate to human immediately

### 2. Reply to Follow-Up
- **Any Reply**: Stop automation immediately, mark unread, delegate to human
- **Reason**: Human needs to handle the conversation

### 3. Scheduled Follow-Up
- **Check Stop Reason**: If thread already stopped, abort
- **Check Reply**: If creator replied, abort
- **Otherwise**: Send follow-up, mark read, update stage

## Stop Conditions (Automation Ends)

1. ✅ Creator shares contact details (WhatsApp/phone/address)
2. ✅ Creator replies to any follow-up (even without contact)
3. ✅ Creator explicitly asks to continue via email
4. ✅ Maximum 2 follow-ups sent (Stage 2 and Stage 3)
5. ✅ Creator shows no interest

## Thread Continuity

- All replies sent from **same Gmail account** that received original email
- Proper email threading with `In-Reply-To` and `References` headers
- Database tracks `account_email` for each thread

## Two-Layer Debouncing Strategy

### Layer 1: Inbound Debounce (10-second window)
- **Purpose**: Prevent duplicate processing from IMAP duplicate events
- **Redis Key**: `debounce_inbound:{thread_id}` (10s TTL)
- **Prevents**: Duplicate DB rows, duplicate Stage-1 follow-ups, multiple processing of same event

### Layer 2: Trivial Debounce (30-second window)
- **Purpose**: Suppress repeated trivial messages ("hi", "ok", "?")
- **Redis Key**: `debounce_trivial:{thread_id}` (30s TTL)
- **Filters**: Emails < 10 chars, trivial patterns ("Hi", "Hello", "Thanks", "OK", "?", "Yes", "No")
- **Prevents**: Repeated unread marking, multiple human handoffs, noisy behavior

### Meaningful Message Bypass
- **Contact details** (phone, WhatsApp, address) → Always processed immediately
- **Clarifying questions** (contains "?", "how", "what", "when") → Always processed immediately
- **Sufficient content** (> 20 characters) → Always processed immediately
- **Never blocks real user intent** → System stays responsive

### Benefits
- ✅ Prevents duplicate DB rows from IMAP events
- ✅ Suppresses trivial spam without blocking real messages
- ✅ Reduces LLM API calls and costs
- ✅ Keeps system stable and responsive
- ✅ Never delays meaningful messages

## Idempotency & Concurrency

- **Redis locks** prevent duplicate processing
- **Thread-level locking** ensures only one worker processes a thread
- **Lock timeout**: 2 minutes (processing should complete within this)
- **Lock renewal**: For long-running tasks

## Rate Limiting

- **Configurable limits**: Set via environment variables (Gmail quotas vary by account type)
- **Token bucket algorithm**: Redis-based implementation for smooth rate limiting
- **Per-account tracking**: Each Gmail account has independent rate limit
- **Graceful degradation**: Queue emails when limit reached, retry later
- **Default suggestion**: 500 emails/day per account (verify with your Gmail account type)
- **Assignment requirement**: 600+ emails/day (distribute across 3 accounts)
