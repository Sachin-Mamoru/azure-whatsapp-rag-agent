# System Architecture Brief — Azure WhatsApp RAG Agent (Phase 2)

Please draw a comprehensive system architecture diagram from the description below. Use boxes, arrows, and clear groupings/swimlanes. Label every component and every data flow. Use colour/shading to separate the major zones.

---

## Overview

A multilingual (English / Sinhala / Tamil) WhatsApp disaster advisory chatbot deployed on **Azure Container Apps**. It answers citizen queries via a RAG pipeline and also accepts crowd-sourced hazard reports (VGI), scores them with Bayesian truth discovery, and surfaces verified ones back into the advisory context. A background scheduler runs three cron jobs. An admin panel lets staff review and verify reports.

---

## Major Zones / Swimlanes

1. **User / External**
2. **WhatsApp Cloud API (Meta)**
3. **Azure Container Apps — FastAPI App (single container)**
   - 3a. Orchestrator (message router)
   - 3b. LangChain Tool-Calling Agent
   - 3c. Community Reporting Pipeline
   - 3d. Background Scheduler (APScheduler)
4. **Azure Storage**
5. **External APIs**
6. **GitHub**
7. **Admin Panel (Browser)**

---

## Component Inventory

### Zone 1 — User / External
- **WhatsApp User** (mobile phone) — sends text messages in EN / SI / TA

### Zone 2 — WhatsApp Cloud API (Meta)
- Receives messages from user
- Forwards webhook POST to `/webhook` on the FastAPI app
- The app calls `graph.facebook.com/v22.0/{phone_number_id}/messages` to send replies back

### Zone 3 — Azure Container Apps (FastAPI app, Python 3.11)

#### Entry point
- **FastAPI `/webhook` POST handler** — receives the WhatsApp webhook payload, extracts message text + phone number + language signal

#### 3a — Orchestrator (`agent/orchestrator.py`)
- **Deterministic Pre-checks (Layer 1)** — runs before any LLM call:
  - Unicode script detection → sets session language (Sinhala / Tamil / English)
  - Language selection command (user types 1 / 2 / 3)
  - STOP / unsubscribe → writes to `registrations.db`, returns confirmation
  - Registration command → returns Google Form URL
  - First-time greeting → returns language selection menu
  - Stateful check: if `report_state == awaiting_clarification` → route directly to Community Reporter (bypasses agent)
- **Session State Store (Redis / in-memory dict)** — stores per-phone: language, conversation history (last N turns), pending report object, report_state

#### 3b — LangChain Tool-Calling Agent (`agent/disaster_agent.py` + `agent/agent_tools.py`)
- **DisasterAgent** — builds a fresh `AgentExecutor` per request (LangChain `create_tool_calling_agent`), max_iterations=4
- Injects conversation history as `HumanMessage` / `AIMessage` objects
- LLM: **OpenAI GPT-4o-mini**
- Has 4 tools (each call is logged to `agent_tool_calls` table in `community_reports.db`):

  | Tool | Trigger | Action |
  |---|---|---|
  | `query_knowledge_base` | Safety / hazard / preparedness question | FAISS vector search → GPT-4o-mini synthesis, injects verified community context |
  | `search_web` | Real-time / current events question | SerpAPI (Google) → DuckDuckGo fallback |
  | `submit_community_report` | User describes a hazard they are observing | Calls Community Reporting Pipeline |
  | `get_community_observations` | User asks what others report nearby | SQL query on `community_reports.db` |

- **RAG System (`agent/rag.py`)** — FAISS vectorstore, 916 chunks from 3 PDFs, `text-embedding-3-large` embeddings; receives optional `community_context` string injected into system prompt

#### 3c — Community Reporting Pipeline (`agent/reporter.py`)
Sequential steps per report:
1. `detect_report_intent()` — keyword match in EN/SI/TA indicator dictionaries (LANDSLIDE_INDICATORS, FLOOD_INDICATORS, INFRASTRUCTURE_INDICATORS)
2. `_extract_report()` — GPT-4o-mini zero-shot JSON extraction → typed schema (domain, hazard_type, location_text, description, people_at_risk, ongoing, immediacy)
3. Clarification check — if no location → ask user once, set `report_state=awaiting_clarification`
4. `_fetch_rainfall_for_location()` — async call to **Open-Meteo API** (free, no key), 17 district coordinates, 5s timeout; caches result
5. `_score_confidence()` — composite score `0.30×completeness + 0.20×plausibility + 0.30×triangulation + 0.20×severity_boost`
6. `_check_triangulation_bayesian()` — TruthFinder formula across spatially independent corroborators; reads `user_reliability` table from `community_reports.db`
7. `_check_spatial_independence()` — Sybil resistance: same `user_hash` excluded from corroboration pool
8. `_decide_action()` → one of: `store_only` / `monitor` / `flag_review` / `escalate`
9. Write report to `community_reports` table in `community_reports.db`; write event to `report_status_log` table
10. Write `user_hash` = SHA-256(phone)[:16] to `user_reliability` table; increment report count
11. Return trilingual acknowledgement to orchestrator

#### 3d — Background Scheduler (`agent/scheduler.py`)
APScheduler `AsyncIOScheduler`, started in FastAPI lifespan hook. Three jobs:

**Job 1 — Google Sheets Sync** (every 30 min)
- Reads Google Sheets (linked to Google Form registration responses) via `google-auth` service account
- Upserts subscriber records into `registrations.db` (SQLite)

**Job 2 — Alert Cycle** (every 60 min)
- `alert_crawler.py` → HTTP GET `data.json` from **GitHub Pages early-warning site**
- Parses active district warnings (level: none/low/medium/high/extreme; hazard: flood/landslide/cyclone)
- `alert_sender.py` → queries `registrations.db` for subscribers in warned districts
- Sends trilingual WhatsApp alert messages via **WhatsApp Cloud API**

**Job 3 — Retention Job** (every 6 hours)
- Scans `community_reports.db` for expired reports:
  - hazard > 7 days → archived
  - infrastructure > 30 days → archived
  - regulatory > 180 days → archived
  - safety > 14 days → archived
  - unknown (conf < 0.40) > 14 days → deleted
- For each archived/deleted report: calls `update_user_reliability(verified=False, half-weight α×0.5)` → updates `user_reliability` table

### Zone 4 — Azure Storage

- **SQLite: `registrations.db`** (at `/tmp/registrations.db` in container)
  - Tables: `registrations` (phone, name, district, language, created_at)
  - Written by: Sheets Sync job, STOP command handler
  - Read by: Alert Cycle job, orchestrator (registration check)

- **SQLite: `community_reports.db`** (at `/tmp/community_reports.db` in container)
  - Tables:
    - `community_reports` — all citizen reports with confidence, action, status, user_hash, location, description, hazard_type, timestamps
    - `report_status_log` — audit log of every status change
    - `user_reliability` — per-user reliability score r ∈ [0.05, 0.95], report count, last_updated
    - `agent_tool_calls` — research dataset: every LangChain tool invocation with inputs, outputs, timestamp
  - Written by: Community Reporting Pipeline, Retention Job, admin verify/reject API
  - Read by: tool `get_community_observations`, `get_recent_reports_context()` (injected into RAG), Admin API

- **FAISS Vectorstore** (filesystem, `/vectorstore` in container)
  - 916 chunks from 3 PDFs (NBRO landslide guide, NBRO housing manual, DMC Sinhala disaster guidelines)
  - Embeddings: `text-embedding-3-large`

### Zone 5 — External APIs

- **OpenAI API**
  - `gpt-4o-mini` — chat completions (report extraction, RAG synthesis, agent reasoning)
  - `text-embedding-3-large` — document + query embeddings for FAISS

- **WhatsApp Cloud API (Meta Graph API v22.0)**
  - Inbound: webhook → FastAPI app
  - Outbound: app → `POST /messages` to send replies and alerts

- **SerpAPI** (primary web search) / **DuckDuckGo** (fallback)
  - Called by `search_web` tool when KB has no answer

- **Open-Meteo API** (free, no key required)
  - Called by Community Reporting Pipeline to fetch today's precipitation for flood/landslide plausibility
  - Endpoint: `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&daily=precipitation_sum`

- **Google Sheets API** (via service account `credentials.json`)
  - Source of user registrations (Google Form → Sheet → Sheets Sync job → `registrations.db`)

### Zone 6 — GitHub

- **GitHub Pages** (`sachin-mamoru.github.io/azure-whatsapp-rag-agent/`)
  - Hosts `early-warning-site/data.json` — district warning levels (manually updated by operator)
  - Hosts `early-warning-site/admin.html` — Admin Panel SPA

- **GitHub repository** — source code; `deploy.sh` builds Docker image, pushes to Azure Container Registry, triggers new Container App revision

### Zone 7 — Admin Panel (Browser)

- Static SPA at `https://sachin-mamoru.github.io/azure-whatsapp-rag-agent/admin.html`
- Calls FastAPI admin endpoints (CORS allowed for `sachin-mamoru.github.io`):
  - `GET /admin/reports?status=new|escalated|verified` → list reports
  - `GET /admin/reports?action=escalate|flag_review` → filter by action
  - `POST /admin/reports/{id}/verify` → sets status=verified, triggers `update_user_reliability(+)`
  - `POST /admin/reports/{id}/reject` → sets status=closed, triggers `update_user_reliability(-)`
  - `GET /admin/reports/stats` → counts by status
- Tabs: New / Escalated / Needs Review / Verified / Stats

---

## Key Data Flows (label these arrows)

1. User → WhatsApp Cloud API → `/webhook` POST → FastAPI
2. FastAPI → Orchestrator → (pre-checks pass) → DisasterAgent
3. DisasterAgent → Tool: `query_knowledge_base` → FAISS + community_context → OpenAI GPT-4o-mini → answer
4. DisasterAgent → Tool: `search_web` → SerpAPI / DuckDuckGo → answer
5. DisasterAgent → Tool: `submit_community_report` → Community Reporting Pipeline → `community_reports.db`
6. Community Reporting Pipeline → Open-Meteo API (rainfall)
7. Community Reporting Pipeline → OpenAI GPT-4o-mini (extraction)
8. Community Reporting Pipeline → read `user_reliability` table → TruthFinder score
9. FastAPI → WhatsApp Cloud API → reply to user
10. Scheduler Job 1 → Google Sheets API → `registrations.db`
11. Scheduler Job 2 → GitHub Pages `data.json` → `registrations.db` (read) → WhatsApp Cloud API (send alerts)
12. Scheduler Job 3 → `community_reports.db` (read+update) → `user_reliability` table (decay)
13. Admin Panel (browser) → Admin REST API → `community_reports.db` (read/write) → `user_reliability` table

---

## Deployment Stack

- **Runtime**: Python 3.11, FastAPI 0.115.0, Uvicorn
- **Container**: Docker, Azure Container Registry (`whatsappagentacr`)
- **Host**: Azure Container Apps, East US, environment `whatsapp-agent-env`
- **CI/CD**: `deploy.sh` (manual trigger) — builds image, pushes to ACR, updates container app revision
- **Secrets**: All credentials in Azure Container Apps environment variables (WHATSAPP_TOKEN, OPENAI_API_KEY, GOOGLE_SHEETS_SPREADSHEET_ID, etc.)
