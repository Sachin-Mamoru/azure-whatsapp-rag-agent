# Phase 2 — Agentic Community Reporting System

> Extension of the WhatsApp disaster advisory chatbot with a **LangChain tool-calling agent**, **community hazard reporting**, **Bayesian truth discovery**, and an **admin governance panel**. Developed as part of an MPhil research contribution on participatory early-warning systems.

---

## Table of Contents

1. [Agent Architecture & Behaviour](#1-agent-architecture--behaviour)
   - 1.1 [Two-Layer Processing Model](#11-two-layer-processing-model)
   - 1.2 [LangChain Tool-Calling Agent](#12-langchain-tool-calling-agent)
   - 1.3 [Complete Message Workflow](#13-complete-message-workflow)
   - 1.4 [Background Cron Jobs (Scheduler)](#14-background-cron-jobs-scheduler)
2. [Community Reporting Module](#2-community-reporting-module)
   - 2.1 [What it Does](#21-what-it-does)
   - 2.2 [Research Contribution](#22-research-contribution)
   - 2.3 [Algorithms & Formulas](#23-algorithms--formulas)
   - 2.4 [Related Work & References](#24-related-work--references)
   - 2.5 [Novelty](#25-novelty)
3. [Admin Governance Panel](#3-admin-governance-panel)
4. [New Files & Changes Summary](#4-new-files--changes-summary)

---

## 1. Agent Architecture & Behaviour

### 1.1 Two-Layer Processing Model

Phase 2 introduces a deliberate **two-layer architecture** that separates deterministic safety logic from LLM-driven routing:

```
Incoming WhatsApp message
         │
         ▼
┌─────────────────────────────────────────────┐
│  Layer 1 — Deterministic Pre-checks          │
│  (orchestrator.py)                           │
│                                              │
│  • Unicode script detection (SI/TA/EN)       │
│  • Language selection menu (1/2/3)           │
│  • STOP / unsubscribe (must be instant)      │
│  • Registration command                      │
│  • Report clarification continuation         │
│  • First-time greeting → show menu           │
└──────────────┬──────────────────────────────┘
               │ passes through
               ▼
┌─────────────────────────────────────────────┐
│  Layer 2 — LangChain Tool-Calling Agent       │
│  (disaster_agent.py + agent_tools.py)        │
│                                              │
│  LLM decides which tool(s) to invoke:        │
│  • query_knowledge_base                      │
│  • search_web                                │
│  • submit_community_report                   │
│  • get_community_observations                │
└─────────────────────────────────────────────┘
```

**Why Layer 1 is kept outside the agent:**
STOP and consent commands are legally and ethically required to be deterministic — an LLM must never decide whether to ignore an unsubscribe request. Language switching and registration are also high-confidence keyword matches that do not benefit from LLM routing overhead.

---

### 1.2 LangChain Tool-Calling Agent

The agent is built with LangChain's `create_tool_calling_agent` + `AgentExecutor`. A new agent executor is instantiated on every request (so the system prompt always carries the correct language and phone context).

**System prompt (summarised):**
```
You are a multilingual disaster safety assistant for Sri Lanka.
Language: {language}. Respond ONLY in that language.

Available tools:
  • query_knowledge_base   — for safety/hazard questions (use first)
  • search_web             — if KB returns no result or question is time-sensitive
  • submit_community_report — if user describes a hazard they are observing
  • get_community_observations — if user asks what others are reporting nearby

Rules:
  - Always try query_knowledge_base before search_web
  - If the message contains a first-person hazard observation, call submit_community_report
  - Maximum 4 tool iterations per message
```

**Tool definitions (agent_tools.py):**

| Tool | When invoked | What it does |
|---|---|---|
| `query_knowledge_base` | Safety/hazard/preparedness questions | FAISS vector search over 916 chunks from 3 PDFs (landslide guide, NBRO housing manual, DMC Sinhala guidelines). Injects verified community reports as supplemental context. |
| `search_web` | Real-time events, news, current conditions | SerpAPI (Google) with DuckDuckGo fallback |
| `submit_community_report` | User describes something they are seeing | Full reporting pipeline: extract → score → store → acknowledge |
| `get_community_observations` | User asks what others report in an area | Returns recent high-confidence, non-closed reports from DB |

Every tool call is logged to the `agent_tool_calls` SQLite table for research evaluation (routing accuracy dataset).

---

### 1.3 Complete Message Workflow

```
User sends WhatsApp message
        │
        ▼
[orchestrator.py] process_message()
        │
        ├─ Script detection (Sinhala/Tamil Unicode range check) → update session language
        │
        ├─ Language command? → return menu
        ├─ STOP command?     → unsubscribe in DB, return confirmation
        ├─ Register command? → return registration URL
        ├─ 1/2/3 selection? → set session language
        ├─ First visit + greeting? → return language menu
        │
        ├─ report_state == "awaiting_clarification"?
        │     └─ route directly to reporter.process_report(pending_report=...) [stateful]
        │
        └─ else → DisasterAgent.ainvoke()
                        │
                        ▼
              LangChain tool-calling loop (max 4 iterations)
                        │
              ┌─────────┴──────────────────────────────────┐
              │                                            │
              ▼                                            ▼
      query_knowledge_base                  submit_community_report
              │                                            │
              ▼                                            ▼
        FAISS vector search             reporter.process_report()
        + community context injection          │
              │                         LLM extraction (JSON)
              ▼                                │
        OpenAI GPT-4o-mini              confidence scoring
        generates answer                       │
                                        store in SQLite
                                               │
                                        return acknowledgement
                                        (trilingual, keyed by action)
```

**Conversation memory:** Session state (language, report clarification state, pending report) is stored in Redis if available, falling back to in-memory dict. Conversation history (last N turns) is passed to the agent as LangChain `HumanMessage`/`AIMessage` objects.

---

### 1.4 Background Cron Jobs (Scheduler)

The scheduler (`agent/scheduler.py`) uses **APScheduler `AsyncIOScheduler`** started in the FastAPI lifespan hook. Three jobs run in the background:

```
App start (FastAPI lifespan)
        │
        └─ start_scheduler(reporter=orchestrator.reporter)
                │
                ├─ Job 1: _sync_sheets_job          every 30 min  (env: SHEETS_SYNC_INTERVAL_MINUTES)
                │         Pulls registrations from Google Sheets → SQLite
                │
                ├─ Job 2: _alert_cycle_job           every 60 min  (env: ALERT_CHECK_INTERVAL_MINUTES)
                │         Crawls early-warning-site/data.json
                │         → sends WhatsApp alerts to registered users in active-warning districts
                │
                └─ Job 3: _retention_job             every 6 hours (env: RETENTION_CHECK_INTERVAL_MINUTES)
                          Expires old community reports by domain:
                            hazard        > 7 days  → archived
                            infrastructure > 30 days → archived
                            regulatory    > 180 days → archived
                            safety        > 14 days  → archived
                            unknown (low-conf) > 14 days → deleted
                          For each archived/deleted report:
                            → update_user_reliability(verified=False, half-weight α×0.5)
                              (weak decay: expiry without validation is NOT strong falsity signal)
```

**Misfire behaviour:** If the container restarts and misses a scheduled window, APScheduler applies a grace period (`misfire_grace_time`) before skipping — 300 s for alert/sheets, 600 s for retention. This prevents alert storms after cold starts.

---

## 2. Community Reporting Module

### 2.1 What it Does

`agent/reporter.py` is a self-contained module that converts unstructured citizen observations sent via WhatsApp into structured, scored, governed mitigation intelligence.

**End-to-end pipeline for a single report:**

```
"There is flooding near Kelani River, water entering houses on the main road"
        │
        ▼
1. detect_report_intent()          ← fast keyword check (no LLM call)
   checks LANDSLIDE/FLOOD/INFRA indicators in EN/SI/TA
        │
        ▼
2. _extract_report()               ← LLM structured extraction
   Returns JSON:
   {
     "report_domain":   "hazard",
     "hazard_type":     "flood",
     "category":        "immediate_hazard",
     "location_text":   "Kelani River",
     "description":     "flooding near Kelani River, water entering houses",
     "people_at_risk":  true,
     "ongoing":         true,
     "immediacy":       "immediate"
   }
        │
        ▼
3. clarification check             ← if no location_text, ask user once
        │
        ▼
4. _fetch_rainfall_for_location()  ← async Open-Meteo API (no key required)
   Looks up today's precipitation for matching Sri Lanka district
   Caches to self._rainfall_cache
        │
        ▼
5. _score_confidence()             ← composite scoring
   Returns: (confidence_score 0–1, severity_score 0–1)
        │
        ▼
6. _decide_action()                ← decision engine
   Returns: store_only | monitor | flag_review | escalate
        │
        ▼
7. Store in SQLite community_reports table
   user_hash = SHA-256(phone_number)[:16]  ← privacy-preserving
        │
        ▼
8. _upsert_user_report_count()     ← update user's report count
        │
        ▼
9. _acknowledgement()              ← trilingual response (EN/SI/TA)
   keyed by action tier
```

**Report domain taxonomy:**

| Domain | Description | Examples |
|---|---|---|
| `hazard` | Active environmental hazard | Flooding, landslide, cyclone |
| `infrastructure` | Physical structure at risk | Road damage, bridge crack, wall collapse |
| `regulatory` | Governance / policy concern | Illegal dumping, blocked drain |
| `safety` | Public safety without clear hazard | Missing person, animal attack |
| `unknown` | Could not classify | — |

---

### 2.2 Research Contribution

This module addresses a fundamental gap in **Volunteered Geographic Information (VGI)** for disaster management: *how do you make citizen-reported hazard data trustworthy enough to incorporate into an advisory system's reasoning context without compromising users with false information?*

The contribution is a **three-layer credibility framework** designed for low-resource multilingual contexts:

1. **LLM-assisted structured extraction** — transforms free-text multilingual reports into a typed schema with zero manual annotation, enabling downstream algorithmic processing.

2. **Composite confidence scoring** — combines four independent signals (completeness, geospatial plausibility, Bayesian triangulation, rainfall correlation) into a single calibrated score, without any labelled training data.

3. **Source credibility tracking (Bayesian Truth Discovery)** — models each contributor's reliability as a Beta-distributed random variable updated by admin verification decisions, so that repeat contributors with a track record of accuracy contribute more to the triangulation signal than anonymous one-off reporters.

---

### 2.3 Algorithms & Formulas

#### Confidence Score (Composite)

$$\text{conf} = w_1 \cdot S_{\text{completeness}} + w_2 \cdot S_{\text{plausibility}} + w_3 \cdot S_{\text{triangulation}} + w_4 \cdot S_{\text{sev-boost}}$$

Where default weights are:

| Component | Weight | Description |
|---|---|---|
| $S_{\text{completeness}}$ | 0.30 | Fraction of schema fields populated (location, description, hazard type, etc.) |
| $S_{\text{plausibility}}$ | 0.20 | District/locality lookup + Open-Meteo rainfall correlation |
| $S_{\text{triangulation}}$ | 0.30 | Bayesian truth discovery across independent corroborators |
| $S_{\text{sev-boost}}$ | 0.20 | Presence of high-severity linguistic indicators |

#### Severity Score

$$S_{\text{severity}} = \frac{1}{|K|} \sum_{k \in K} \mathbb{1}[\text{indicator}_k \in \text{description}]$$

Where $K$ is the set of IMMEDIACY and SEVERITY indicator keywords across EN/SI/TA. Capped at 1.0.

#### Decision Engine

| Condition | Action |
|---|---|
| conf ≥ 0.80 AND sev ≥ 0.70 | `escalate` (urgent) |
| conf ≥ 0.60 OR sev ≥ 0.70 | `flag_review` (admin attention) |
| conf ≥ 0.40 | `monitor` (watch for corroboration) |
| conf < 0.40 | `store_only` (not surfaced in RAG context) |

#### Bayesian Truth Discovery (TruthFinder variant)

Given $n$ **spatially independent** corroborating reports of the same event from users $u_1 \ldots u_n$ with reliability scores $r_1 \ldots r_n \in [0,1]$:

$$P(\text{true}) = \frac{\prod_{i=1}^{n} r_i}{\prod_{i=1}^{n} r_i + \prod_{i=1}^{n}(1 - r_i)}$$

This is scaled to a $[0, 0.30]$ contribution to the overall confidence score.

**Sybil resistance:** The same `user_hash` cannot corroborate their own report — `_check_spatial_independence()` filters out the reporter from the corroboration pool. New users start at $r = 0.5$ (uninformative prior).

#### Source Reliability Update (Bayesian Log-Odds)

When an admin verifies or rejects a report, the reporter's reliability is updated via a Bayesian log-odds step:

$$\text{logit}(r_{\text{new}}) = \text{logit}(r_{\text{old}}) + \alpha \cdot \Delta$$

Where:
- $\alpha = 0.3$ (learning rate)
- $\Delta = +1$ for verified (correct report), $\Delta = -1$ for rejected (false report)
- $\Delta = -0.5$ for auto-expired unvalidated reports (weak rejection — half-weight)
- $r$ is clamped to $[0.05, 0.95]$ to prevent degeneracy

Equivalent to:

$$r_{\text{new}} = \sigma\!\left(\sigma^{-1}(r_{\text{old}}) + \alpha \cdot \Delta\right)$$

Where $\sigma$ is the sigmoid function.

#### Rainfall Plausibility Bonus (Open-Meteo)

For flood/landslide reports, the plausibility component receives a bonus based on same-day precipitation at the nearest district centroid (17 Sri Lanka districts mapped to lat/lon):

| Precipitation | Bonus |
|---|---|
| ≥ 50 mm/day (heavy rain) | +0.05 |
| ≥ 20 mm/day (moderate rain) | +0.02 |
| < 20 mm/day | 0 |

Total plausibility $S_{\text{plausibility}}$ is capped at 0.20.

#### Retention Policy (Table 8)

| Domain | Max age | Action on expiry |
|---|---|---|
| hazard | 7 days | Archive |
| infrastructure | 30 days | Archive |
| regulatory | 180 days | Archive |
| safety | 14 days | Archive |
| unknown (conf < 0.40) | 14 days | Delete |

Archived reports trigger a half-weight reliability decay ($\alpha \times 0.5$) on the submitter.

#### Privacy: Phone Number Hashing

All user identifiers are stored as irreversible 16-character hex digests:

$$\text{user-hash} = \text{SHA-256}(\text{phone-number})[{:}16]$$

The raw phone number is never written to the community reports database.

---

### 2.4 Related Work & References

| Reference | Relevance |
|---|---|
| Yin, J. et al. (2012). *Twitter catches the flu: Detecting influenza epidemics using Twitter.* EMNLP. | Early application of social media text mining for hazard detection — motivates NLP pipeline for citizen reports |
| Goodchild, M.F. (2007). *Citizens as sensors: The world of volunteered geography.* GeoJournal, 69(4), 211–221. | Foundational VGI paper — defines citizen sensing as a distinct knowledge production mode |
| Yin, Y. et al. (2008). *TruthFinder: Finding trustworthy information on the World Wide Web.* KDD. | Source of the TruthFinder algorithm used for $P(\text{true})$ triangulation formula |
| Zhao, B. & Han, J. (2012). *A probabilistic model for estimating real-valued truth from conflicting sources.* QDB workshop. | Probabilistic grounding for Bayesian truth discovery in the presence of conflicting VGI |
| Castillo, C. et al. (2011). *Information credibility on Twitter.* WWW. | Features for credibility scoring in social media — informs completeness and indicator-based severity scoring |
| Imran, M. et al. (2015). *Processing social media messages in mass emergency: A survey.* ACM Computing Surveys, 47(4). | Survey of disaster social media processing — benchmarks for extraction and classification pipelines |
| Mendoza, M. et al. (2010). *Twitter under crisis: Can we trust what we RT?* SOMA workshop. | Propagation-based credibility — motivates Sybil-resistance design |
| Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS. | Foundation for the RAG advisory layer that intersects with community observations |
| Edge, M. et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarisation.* Microsoft Research. | Modern RAG architectural patterns that inform dual-store (KB + community) retrieval design |

---

### 2.5 Novelty

This system makes four contributions not found in combination in prior work:

**1. Multilingual report extraction without labelled data**
Existing VGI hazard systems (e.g., AIDR, Ushahidi) require manually annotated training corpora for each language. This system uses GPT-4o-mini zero-shot structured extraction with multilingual indicator dictionaries (English, Sinhala, Tamil) — making it applicable to under-resourced South Asian languages without crowd-sourced annotation.

**2. Confidence scoring from independent signal fusion**
Rather than relying on a single classifier, the system fuses four independent signals (structural completeness, geospatial plausibility via district lookup, Bayesian triangulation across independent reporters, and near-real-time rainfall correlation from Open-Meteo). Each signal is theoretically grounded and interpretable — important for institutional trust in an early-warning context.

**3. Bayesian source credibility in a messaging-first interface**
Prior truth discovery systems (TruthFinder, Spaun, CRH) assume a structured web table input. This work applies the core TruthFinder formulation directly to unstructured WhatsApp messages, with a phone-number-hashed identity model that is both privacy-preserving and Sybil-resistant (same user cannot corroborate their own report).

**4. Dual-store RAG with explicit source provenance**
Community observations are kept in a separate SQLite store from the authoritative PDF knowledge base (FAISS vectorstore). They are injected into the RAG system prompt as explicitly labelled supplementary context (`✅ CONFIRMED` vs `⚠ unverified`), preserving epistemic transparency — the LLM is never allowed to treat a citizen report as equivalent to an official guideline.

---

## 3. Admin Governance Panel

Available at `https://sachin-mamoru.github.io/azure-whatsapp-rag-agent/admin.html`

| Tab | Filter | Shows |
|---|---|---|
| New | `status = new` | All unreviewed reports, any action tier |
| Escalated | `action = escalate AND status NOT IN (verified, closed, archived)` | Urgent auto-detected reports awaiting admin confirmation |
| Needs Review | `action = flag_review AND status NOT IN (verified, closed, archived)` | Moderate-high confidence reports awaiting admin check |
| Verified | `status = verified` | Admin-confirmed reports (fed into RAG context as CONFIRMED) |
| Stats | — | Total / new / needs_review / escalated counts + tracked user count |

**Verify** → sets `status = verified`, calls `update_user_reliability(verified=True, α=0.3)` → report surfaces as `✅ CONFIRMED` in subsequent bot responses for 48 hours.

**Reject** → sets `status = closed`, calls `update_user_reliability(verified=False, α=0.3)` → report suppressed from RAG context; user reliability decays.

---

## 4. New Files & Changes Summary

| File | Status | Description |
|---|---|---|
| `agent/reporter.py` | **New** | Full community reporting pipeline: LLM extraction, composite scoring, Bayesian truth discovery, Open-Meteo rainfall plausibility, SQLite persistence, trilingual acknowledgement |
| `agent/agent_tools.py` | **New** | 4 LangChain tools (`query_knowledge_base`, `search_web`, `submit_community_report`, `get_community_observations`) with per-request context closure and tool-call logging |
| `agent/disaster_agent.py` | **New** | `DisasterAgent` wrapping LangChain `create_tool_calling_agent` + `AgentExecutor`; builds fresh executor per call with correct language context |
| `agent/scheduler.py` | **Modified** | Added `_retention_job` (APScheduler, every 6 h); `start_scheduler` now accepts shared `CommunityReporter` instance |
| `agent/orchestrator.py` | **Modified** | Replaced manual if/elif routing with `agent.ainvoke()`; added report clarification bypass; pre-checks kept outside agent |
| `agent/rag.py` | **Modified** | `query()` accepts `community_context` injected into system prompt as labelled supplementary context |
| `app.py` | **Modified** | Added 4 admin REST endpoints: `GET /admin/reports`, `POST /admin/reports/{id}/verify`, `POST /admin/reports/{id}/reject`, `GET /admin/reports/stats` |
| `config.py` | **Modified** | Added `COMMUNITY_REPORTS_DB` env var |
| `deploy.sh` | **Modified** | Added `COMMUNITY_REPORTS_DB` env var to both create and update blocks |
| `early-warning-site/admin.html` | **Modified** | Community Reports panel with New/Escalated/Needs Review/Verified/Stats tabs, Verify/Reject buttons, inline status badges |
| `scripts/setup-persistent-storage.sh` | **New** | One-time Azure Files persistent volume setup (reference only — SQLite on SMB has locking constraints) |
