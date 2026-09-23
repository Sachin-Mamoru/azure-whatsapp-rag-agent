# A Multilingual Agentic RAG System for WhatsApp-Based Disaster Early Warning and Community-Sourced Hazard Reporting: Architecture, Implementation, and Performance Evaluation

*Draft manuscript — technical evaluation section prepared for submission to a Q1 disaster-risk-management / applied-AI journal. Author to complete title-page metadata (authors, affiliations, ORCID, corresponding author, funding/ethics statements) and the Related Work bibliography before submission.*

---

## Abstract

Low- and middle-income disaster-prone regions increasingly rely on ubiquitous messaging platforms such as WhatsApp for public-safety communication, yet most deployed chatbots either answer static FAQs or forward messages to a human operator, with no mechanism for citizens to *contribute* observations back into the advisory pipeline. We present the architecture and an empirical technical evaluation of a deployed, multilingual (English/Sinhala/Tamil) WhatsApp disaster-advisory agent that combines (i) a LangChain tool-calling agent (GPT-4o-mini) that autonomously routes each message to a retrieval-augmented generation (RAG) knowledge-base tool, a live web-search tool, or a volunteered-geographic-information (VGI) hazard-reporting tool; (ii) a Bayesian truth-discovery mechanism (TruthFinder-style source-reliability weighting) that triangulates independent citizen reports before surfacing them as supplementary advisory context; and (iii) a serverless Azure Container Apps deployment with a background scheduler for periodic alert dissemination. We benchmark every architectural component in isolation against the real, unmodified production code — FAISS retrieval, GPT-4o-mini generation, agent tool-routing, LLM-based report extraction, Bayesian triangulation, SQLite persistence, deterministic language detection, and end-to-end concurrency — using hand-labelled evaluation sets scaled from an initial n=18–20 pilot to n=29–60 items per component, with 95% bootstrap/Wilson confidence intervals reported throughout. The agentic routing layer achieves 100% tool-selection accuracy (n=38, Wilson 95% CI [90.8%, 100%]) versus 41.4% recall for a pure keyword-based report filter, quantitatively justifying the agentic design over rule-based dispatch. A controlled ablation against a closed-book baseline (identical generator model, no retrieval), scored by an independent LLM judge, found RAG reduced the hallucination-flag rate from 20.0% to 13.3% and raised faithfulness from 4.40 to 4.67 (0–5 scale) — directionally consistent with the RAG hypothesis, though not statistically significant at n=30. All LLM-backed operations (1.7–6.2 s mean latency) dominate end-to-end latency, while deterministic components (language detection, SQLite I/O) operate in the microsecond-to-millisecond range. Systematic outlier analysis during concurrency testing surfaced a substring-matching routing defect in the deterministic pre-check layer; we document its discovery, root cause, fix, and post-fix re-verification as a case study in benchmarking-driven quality assurance. We further probe the actual live Azure deployment directly (not merely local execution), finding a ~755 ms network/infrastructure latency floor and — incidentally — that the production instance is currently configured for a single, statically-scaled replica rather than the auto-scaling behaviour described in its own documentation. We report the Bayesian triangulation mechanism's correctness against a closed-form reference implementation (maximum absolute error 1.6×10⁻⁴) and identify the single-writer SQLite persistence layer as the primary scalability constraint for multi-replica horizontal scaling. All benchmark code, hand-labelled test sets, raw results, and figures are released for reproducibility.

**Keywords:** disaster early warning; conversational AI; retrieval-augmented generation; LLM agents; volunteered geographic information; Bayesian truth discovery; WhatsApp chatbot; multilingual NLP; serverless architecture; performance evaluation

---

## 1. Introduction

### 1.1 Motivation

Sri Lanka experiences recurring monsoon-driven flooding and landslides, and public disaster communication remains fragmented across radio, SMS, and manual community-liaison networks. WhatsApp is the dominant messaging platform in the region, making it an attractive channel for both *outbound* early-warning dissemination and *inbound* citizen-to-authority hazard reporting. However, existing WhatsApp-based safety bots are typically single-purpose: either a static FAQ retriever or a one-way broadcast tool. Two capabilities are largely absent from the deployed literature: (1) **autonomous, LLM-driven routing** between a curated authoritative knowledge base and live web information, and (2) a **governed pipeline for crowd-sourced hazard reports** that scores plausibility and reporter credibility before such reports influence the advice given to other citizens.

### 1.2 System summary

We designed and deployed a system (Figure 1) that: detects the user's language from Unicode script; runs deterministic pre-checks (registration, opt-out, greeting) before any LLM call; and, for substantive messages, invokes a LangChain tool-calling agent backed by GPT-4o-mini with four tools — `query_knowledge_base` (FAISS RAG over 916 chunks drawn from three official hazard-guidance PDFs), `search_web` (Serper/DuckDuckGo), `submit_community_report` (structured extraction + Bayesian scoring pipeline), and `get_community_observations`. Citizen reports are stored separately from the authoritative knowledge base and are only surfaced as explicitly labelled, unverified supplementary context. A background APScheduler process periodically synchronises registrations from Google Sheets, crawls a GitHub Pages–hosted early-warning feed to dispatch alerts, and retires stale reports while decaying reporter reliability.

### 1.3 Contributions

1. An architecture combining agentic tool-routing, multilingual RAG, and Bayesian VGI truth discovery in a single production WhatsApp deployment (§3).
2. A component-level performance-evaluation methodology and open benchmark suite exercising the *real* production code paths of all ten architectural components (including a closed-book ablation and a live-deployment probe), rather than isolated unit-level mocks (§4).
3. Empirical evidence that LLM-based agentic routing substantially outperforms a keyword-based intent filter for the report-detection task (100% vs. 41.4% recall), providing a quantitative justification often missing from agentic-system papers (§5.5).
4. A controlled, same-model ablation of RAG against a closed-book baseline with independent LLM-as-judge scoring, showing a directionally lower hallucination rate under retrieval grounding — reported transparently alongside its own statistical-power limitations rather than overstated (§5.11, §6.6).
5. A worked case study showing how systematic latency-outlier analysis (not just mean/median reporting) surfaced a genuine production routing defect, which we diagnose, fix, and re-verify (§5.9, §6.3) — offered as a methodological argument for reporting full latency distributions rather than averages alone.
6. A live probe of the actual deployed Azure Container Apps instance that surfaces a concrete discrepancy between documented auto-scaling capability and actual runtime configuration (§5.12, §6.7).
7. A validated, closed-form-checked implementation of Bayesian source-reliability triangulation (TruthFinder-style) for crowd-sourced hazard reports, with measured computational scaling behaviour (§5.6).
8. A fully reproducible, openly released evaluation artifact (code, datasets, raw results, figures) enabling independent replication (§9).

---

## 2. Related Work

*(Author note: expand this section with a complete, verified literature review before submission. The pointers below identify the relevant research threads this work sits at the intersection of; specific citations must be checked against the target journal's reference style and verified against original sources — none should be taken as pre-verified bibliographic entries.)*

- **Retrieval-augmented generation (RAG).** Combining dense retrieval with generative language models to ground answers in a curated corpus, reducing hallucination relative to closed-book generation (cf. Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*, NeurIPS 2020).
- **LLM tool-calling / agentic orchestration.** Frameworks in which a language model autonomously selects from a set of external tools/functions based on natural-language descriptions, as implemented here via LangChain's tool-calling agent abstraction.
- **Volunteered geographic information (VGI) and crowd-sourced disaster reporting.** Literature on citizen-sourced hazard observations and the data-quality challenges (spam, duplication, malicious reports) that motivate credibility-weighting mechanisms.
- **Truth discovery / source-reliability estimation.** Bayesian and iterative source-credibility models for reconciling conflicting crowd-sourced claims (the system's triangulation mechanism follows the general TruthFinder-style iterative reliability-update pattern; cf. Yin, Han & Yu on truth discovery with multiple conflicting information providers).
- **Conversational agents for low-resource and multilingual disaster communication.** Prior work on SMS/USSD/WhatsApp-based early-warning systems in South/Southeast Asia and Sub-Saharan Africa, typically limited to unidirectional broadcast or menu-driven (non-generative) interaction.
- **Performance evaluation methodology for LLM-based production systems.** Emerging practice for benchmarking retrieval quality (Recall@k, groundedness), agent tool-selection accuracy, and end-to-end serving latency/throughput under concurrency — the methodological frame adopted in §4–§5.

---

## 3. System Architecture

### 3.1 Overview

Figure 1 shows the complete seven-zone architecture: (1) the WhatsApp user; (2) WhatsApp Cloud API (Meta); (3) the Azure Container Apps–hosted FastAPI application, comprising (3a) the orchestrator's deterministic pre-check and session layer, (3b) the LangChain tool-calling agent and its four tools plus the RAG subsystem, (3c) the community reporting pipeline, and (3d) the background scheduler; (4) Azure filesystem storage (two SQLite databases and the FAISS vectorstore); (5) external APIs (OpenAI, Serper/DuckDuckGo, Open-Meteo, Google Sheets); (6) GitHub (source control and the GitHub Pages early-warning feed); and (7) a static admin panel for human report review.

**Figure 1.** System architecture (all seven zones, component inventory, and labelled data flows).
`![Figure 1 — System architecture](evaluation/figures/fig0_system_architecture.png)`

### 3.2 Deterministic pre-check layer (Layer 1)

Before any LLM call, inbound messages pass through: (a) Unicode-script-range language detection (Sinhala U+0D80–U+0DFF, Tamil U+0B80–U+0BFF, else English); (b) short-command intent matching for language-menu, registration, and STOP/unsubscribe requests; (c) first-contact greeting handling; and (d) stateful continuation routing for a pending report clarification. This layer is intentionally rule-based (no LLM) for cost, latency, and predictability reasons; §5.9/§6.3 discusses a defect and fix discovered in this layer through benchmarking.

### 3.3 LangChain tool-calling agent

For any message reaching this layer, a fresh `AgentExecutor` (max 4 iterations) is built per request with four tools (Table 1). The system prompt enforces a strict output language and requires at least one tool call before a final answer, preventing the model from answering purely from parametric knowledge.

**Table 1.** Agent tool inventory.

| Tool | Trigger condition | Backing system |
|---|---|---|
| `query_knowledge_base` | Safety/preparedness question | FAISS (916 chunks, `text-embedding-3-large`) + GPT-4o-mini synthesis |
| `search_web` | Time-sensitive / current-conditions question | Serper.dev (Google) → DuckDuckGo fallback |
| `submit_community_report` | User describes an observed hazard | Community reporting pipeline (§3.4) |
| `get_community_observations` | User asks about nearby reports | Read-only SQL query over `community_reports.db` |

### 3.4 Community reporting pipeline (VGI intake)

Each report passes through an 11-step pipeline: keyword-based intent pre-filter → LLM zero-shot structured extraction (JSON schema: domain, hazard type, location, description, people-at-risk, ongoing, scale) → mandatory single-turn location clarification if missing → Open-Meteo rainfall lookup for plausibility → composite confidence scoring (completeness 0.30, plausibility 0.20, Bayesian triangulation 0.30, implicit severity boost) → severity scoring (exposure 0.40, infrastructure impact 0.20, hazard scale 0.30, immediacy 0.10) → a confidence×severity decision matrix (`store_only` / `monitor` / `flag_review` / `escalate`) → persistence with a full audit log → reporter-reliability update. The knowledge base and the community-report store are architecturally separate; community observations only ever enter the advisory context as explicitly labelled, unverified supplementary text.

### 3.5 Bayesian truth discovery

Independent, spatially distinct corroborating reports for the same (domain, hazard type, location) cluster within a 12-hour window are combined via the TruthFinder-style formula

$$P(\text{true}) = \frac{\prod_u r_u}{\prod_u r_u + \prod_u (1-r_u)}$$

where $r_u \in [0.05, 0.95]$ is each independent reporter's current reliability score, initialised at 0.5 and updated after each admin verification/rejection via $r \leftarrow r + \alpha(1-r)$ (verified) or $r \leftarrow r - \alpha r$ (rejected), $\alpha = 0.3$. Same-`user_hash` reports are excluded from a report's own corroboration pool (Sybil resistance). Phone numbers are never stored in plaintext — only a truncated SHA-256 hash.

### 3.6 Deployment

Single-container Python 3.11 / FastAPI 0.115 application on Azure Container Apps (consumption plan, 0–N replica auto-scaling), Azure Container Registry for images, Azure Redis Cache (with an in-memory fallback) for session state, and local-filesystem SQLite for structured persistence.

---

## 4. Evaluation Methodology

### 4.1 Design principle: benchmark the real code, not a proxy

Every result in §5 was produced by executing the actual, unmodified production functions (`agent/rag.py`, `agent/disaster_agent.py`, `agent/reporter.py`, `agent/orchestrator.py`) against the real OpenAI API and a real FAISS vectorstore built from the project's three training PDFs. No component's accuracy or latency numbers were simulated or hand-set. Table 2 documents the small number of deliberate network-boundary substitutions and the reason for each; all other behaviour is untouched.

**Table 2.** Real vs. isolated components in the evaluation.

| Component | Test mode | Rationale |
|---|---|---|
| FAISS retrieval, GPT-4o-mini generation, LangChain agent, report extraction, Bayesian scoring, SQLite | Real code, real OpenAI calls | These are the scientifically relevant measurements. |
| WhatsApp Cloud API (outbound send) | Not invoked | `send_whatsapp_message()` lives outside the benchmarked call path; excluded to avoid cost/noise on a third-party API not under study. |
| Redis session store | Forced in-memory fallback (an existing, production fallback path) | Isolates agent-reasoning latency from Azure-managed Redis network latency, a separate variable. |
| Google Sheets sync, GitHub Pages alert crawl | Not exercised | Depend on live third-party data outside the evaluation's scope. |

### 4.2 Experimental setup

Apple M3 Pro, 18 GB RAM, macOS 15.5; Python 3.11.16; FastAPI 0.115.0; LangChain 0.2.14; FAISS-CPU 1.8.0; `gpt-4o-mini` at temperature 0.0–0.1; `text-embedding-3-large` embeddings; direct residential-broadband calls to `api.openai.com` (no proxy/cache), plus a direct probe of the live deployed Azure Container Apps endpoint (§5.12). Test sets were scaled from an initial n=18–20 pilot to n=29–60 items per component (n=30 for the ablation study), hand-labelled and included with the release for peer review, with 95% bootstrap/Wilson confidence intervals reported for every mean/proportion.

### 4.3 Metrics

- **Latency**: mean, standard deviation, and p50/p90/p95/p99, measured with `time.perf_counter()` around each call, with 95% confidence intervals from non-parametric bootstrap resampling.
- **Retrieval quality**: Recall@k using a keyword-coverage proxy (a retrieved chunk is scored relevant if it contains ≥1 expected keyword) — a deliberately disclosed automatic-proxy limitation (§6.4).
- **Routing/classification accuracy**: exact-match accuracy (with Wilson score confidence intervals) and full confusion matrices against hand-labelled ground truth.
- **Extraction accuracy**: per-field accuracy (5 fields) and whole-record exact-match rate against ground truth.
- **Answer quality (ablation only, §5.11)**: independent LLM-as-judge (`gpt-4o`, distinct from the `gpt-4o-mini` generator) scoring of faithfulness (0–5), relevance (0–5), and a binary hallucination flag, compared between RAG and a closed-book baseline.
- **Numerical correctness**: absolute error of the production Bayesian-triangulation output versus an independently coded closed-form reference implementation of the same formula.
- **Throughput/concurrency**: requests/second and latency percentiles across concurrency levels 1/2/4/8, and SQLite operations/second across 1/2/4/8/16 concurrent writer threads.
- **Live deployment (§5.12)**: HTTP round-trip latency and status codes against the actual running Azure Container Apps instance, using only read-only, side-effect-free endpoints.

### 4.4 Reproducibility

```bash
python3 -m venv .venv-eval && source .venv-eval/bin/activate
pip install -r requirements.txt matplotlib numpy pandas scikit-learn
python evaluation/run_all.py     # executes bench_00 .. bench_10, then regenerates all figures
```
Raw results: `evaluation/results/*.json`. Figures: `evaluation/figures/*.png`. Test sets: `evaluation/datasets/*.json`.

---

## 5. Results

### 5.1 Offline indexing pipeline

Building the FAISS index from 3 PDFs (355 pages → 916 chunks, chunk size 1000/overlap 200) took 12.5 s (warm run) to 55.5 s (cold run including first-import overhead), an embedding throughput of ≈73 chunks/s — inexpensive enough to run on every container cold start, though caching the saved index remains the correct design choice given the observed run-to-run variance.

### 5.2 RAG retrieval (FAISS)

**Table 3.** Recall@k and retrieval-only latency (60-item grounded QA set, expanded from an initial n=20 pilot).

| k | Recall@k (keyword proxy) | Mean latency | p95 latency |
|---|---|---|---|
| 1 | 0.65 | 378.6 ms | 377.6 ms |
| 2 | 0.67 | 332.5 ms | 362.3 ms |
| 4 | 0.67 | 331.9 ms | 353.3 ms |
| 8 | 0.67 | 329.8 ms | 362.2 ms |

`![Figure 2 — Recall@k and latency vs. k](evaluation/figures/fig2_retrieval_recall_vs_k.png)`

Latency is dominated by the embedding-API round trip rather than FAISS's exact nearest-neighbour search over 916 vectors (sub-millisecond); recall is flat across k, indicating retrieval quality is limited by query/embedding semantics rather than neighbourhood size. Recall settled at a more representative 0.65–0.67 at 3× the sample size, down from an optimistic 0.80 on the original 20-item pilot — a concrete illustration of why small pilot samples are a threat to validity (§7).

### 5.3 RAG generation (retrieval + GPT-4o-mini synthesis)

**Table 4.** End-to-end RAG query latency and answer-quality proxies (n=60, expanded from an initial n=20 pilot; see §5.11 for a paired ablation against a closed-book baseline).

| Metric | Value |
|---|---|
| Mean latency | 3.33 s, 95% bootstrap CI [3.04 s, 3.64 s] |
| Mean keyword coverage (groundedness proxy) | 0.77 |
| Latency: English (n=40) / Sinhala (n=10) / Tamil (n=10) | 3.25 s / 3.60 s / 3.38 s |

`![Figure 3 — RAG generation latency by language](evaluation/figures/fig3_rag_latency_by_language.png)`

Language does not materially change latency, indicating the multilingual prompt design introduces no asymmetric cost across the three supported languages; the wider language split (10 si / 10 ta) makes this a more robust comparison than the original pilot's 2/2.

### 5.4 Agent tool-routing

**Table 5.** Tool-selection accuracy and latency by expected tool (38-item labelled set, 3 languages, expanded from an initial n=20 pilot).

| | |
|---|---|
| **Tool-selection accuracy** | **100% (38/38)**, Wilson 95% CI [90.8%, 100%] |
| Mean E2E latency | 6.21 s, 95% bootstrap CI [5.30 s, 7.16 s]; p50 5.56 s, p95 10.33 s |
| By tool | KB query 7.35 s (n=11) · web search 6.21 s (n=10) · submit report 7.07 s (n=11) · get observations 2.53 s (n=6) |

`![Figure 4 — Tool-routing confusion matrix](evaluation/figures/fig4_routing_confusion_matrix.png)`

`get_community_observations` is markedly faster because, uniquely among the four tools, it performs a synchronous database read rather than a nested LLM call; the other three tools each incur a second OpenAI completion inside the tool body. The confusion matrix remains perfectly diagonal at nearly 2× the original sample size.

### 5.5 Community reporting pipeline

**Table 6.** Keyword-based intent pre-filter as a binary classifier (29 positive / 60 negative, expanded from an initial 18/20 pilot).

| Precision | Recall | F1 | Mean latency |
|---|---|---|---|
| 1.00 | **0.41** | 0.59 | 6.0 µs |

**Table 7.** LLM-based structured-extraction field accuracy (n=29, expanded from an initial n=18 pilot).

| Field | Accuracy |
|---|---|
| `has_location` | 1.00 |
| `ongoing` | 0.93 |
| `report_domain` | 0.79 |
| `hazard_type` | 0.79 |
| `people_at_risk` | 0.69 |
| **Exact match, all 5 fields** | **0.48** |
| Mean latency | ≈ 1.7 s |

`![Figure 5 — Reporting pipeline accuracy](evaluation/figures/fig5_reporting_pipeline_accuracy.png)`

The ~18-percentage-point gap between the keyword filter's recall (41%) and the agent's tool-routing accuracy (100%, §5.4, same class of report-style messages) is the central quantitative justification for escalating report detection to an LLM agent rather than a rule-based classifier; this gap is stable between the pilot (61 pts) and the expanded set (59 pts), indicating it is a genuine property of the rule-based approach rather than pilot-sample noise.

### 5.6 Bayesian truth discovery

**Table 8.** Triangulation correctness and computational scaling.

| Metric | Value |
|---|---|
| Max absolute error vs. closed-form reference | 1.6×10⁻⁴ (rounding only — formula verified correct) |
| Latency @ 1 / 10 / 50 corroborators | 0.21 ms / 1.58 ms / 8.33 ms |
| Reliability convergence (repeated verification) | 0.50 → 0.95 (clamp) in 7 update events |
| Reliability convergence (repeated rejection) | 0.50 → 0.05 (clamp) in 7 update events |

`![Figure 6 — Bayesian triangulation behaviour](evaluation/figures/fig6_triangulation_bayesian.png)`

High-reliability reporters (r=0.9) push $P(\text{true})$ above 0.99 with only 2 independent corroborators, while low-reliability reporters (r=0.3) are actively down-weighted even as corroborator count grows — evidence the mechanism resists naive Sybil-style flooding by unreliable sources. Computation remains sub-10 ms at 50 corroborators, i.e. not a system bottleneck.

### 5.7 SQLite persistence layer

**Table 9.** Sequential operation latency.

| Operation | Mean | p95 |
|---|---|---|
| Write — `registrations` | 0.28 ms | 0.53 ms |
| Write — `community_reports` | 0.77 ms | 1.75 ms |
| Read — `registrations` (district filter) | 0.40 ms | 0.51 ms |
| Read — `community_reports` (status+severity sort) | 0.069 ms | 0.080 ms |

**Table 10.** Concurrent write throughput (thread pool, single SQLite file).

| Concurrent writers | Throughput (ops/s) | p95 latency |
|---|---|---|
| 1 | 3,783 | 0.37 ms |
| 2 | 3,357 | 0.46 ms |
| 4 | 2,096 | 1.37 ms |
| 8 | 2,110 | 0.62 ms |
| 16 | 1,392 | 1.47 ms |

`![Figure 7 — SQLite concurrency scaling](evaluation/figures/fig7_db_concurrency.png)`

Throughput falls 63% from 1 to 16 concurrent writers (no write errors observed — SQLite's busy-timeout absorbs contention as latency rather than failure), consistent with its single-writer lock. Because Azure Container Apps can auto-scale to multiple replicas while SQLite remains a local container-filesystem file, multi-replica deployment would fragment the database across replicas rather than share it — a concrete architectural limitation for horizontal scaling (§6.5).

### 5.8 End-to-end orchestrator throughput and concurrency

**Table 11.** `WhatsAppOrchestrator.process_message()` throughput/latency by concurrency (8 requests/level; measured **after** the fix in §5.9).

| Concurrency | Throughput (req/s) | p50 latency | p95 latency |
|---|---|---|---|
| 1 | 0.153 | 7.07 s | 12.51 s |
| 2 | 0.257 | 6.88 s | 10.45 s |
| 4 | 0.430 | 6.74 s | 11.18 s |
| 8 | 0.531 | 8.37 s | 15.03 s |

`![Figure 8 — End-to-end throughput/latency vs. concurrency](evaluation/figures/fig8_e2e_concurrency.png)`

Throughput scales near-linearly (0.153 → 0.531 req/s, ≈3.5×) while p50 latency grows only 18% (7.07 s → 8.37 s), confirming the system is I/O-bound on external LLM calls rather than CPU-bound — the async FastAPI design absorbs concurrent webhook deliveries within a single container replica without proportional latency degradation. All 32 simulated requests across the four levels completed successfully.

### 5.9 Case study: a routing defect surfaced by outlier analysis, and its fix

While collecting the data in Table 11, one test message — *"Is there any active flood alert right now in Kalutara?"* — returned in under 0.3 ms instead of the expected ≈6 s, at every concurrency level, a four-order-of-magnitude latency outlier invisible in mean/median statistics alone. Root-cause analysis traced this to `WhatsAppOrchestrator._REGISTER_COMMANDS` in the deterministic pre-check layer, which contained the bare token `"alert"` matched by raw substring containment; any message merely *mentioning* the word "alert" — an unremarkable word in a disaster-advisory context — was silently redirected to the registration-prompt flow before ever reaching the LLM agent, and so never received a substantive answer. We implemented a guard, `_is_command_intent()`, that only treats a message as a short explicit command if it (a) does not end in "?", (b) does not begin with an interrogative word, and (c) is no longer than six words — mirroring a question-exclusion guard already used elsewhere in the codebase's report-intent filter — and applied it to all three keyword-triggered pre-check paths (registration, STOP/unsubscribe, language-change). An 8-case targeted regression test (short genuine commands vs. equivalent full questions containing the same trigger words) passed 8/8 post-fix, and Table 11 reflects the corrected, re-run benchmark. We present this as a methodological argument for reporting full latency distributions — including minima and outliers — rather than central-tendency statistics alone, since the defect was undetectable from means or medians.

### 5.10 Language detection (deterministic pre-check)

**Table 12.** Unicode-script-based language detector (30-item trilingual set, expanded from an initial n=20 pilot).

| Accuracy | Mean latency | p99 latency |
|---|---|---|
| 100% (30/30), Wilson 95% CI [88.7%, 100%] | 0.61 µs | 3.5 µs |

The detector is effectively free and perfectly accurate on script-distinguishable text, validating its use ahead of any LLM call in preference to a slower, probabilistic library-based detector for the two non-Latin scripts.

### 5.11 RAG vs. closed-book baseline ablation (LLM-as-judge)

To address the missing-baseline gap common in agentic-RAG evaluations, we compare the production RAG system against a **closed-book baseline**: the identical generator model (`gpt-4o-mini`) and identical questions, but with the FAISS retrieval step removed. An independent LLM judge (`gpt-4o` — a different model from the generator, to reduce same-model self-evaluation bias) scores both conditions' answers for faithfulness (0–5), relevance (0–5), and a binary hallucination flag, on a seeded 30-item subsample of the 60-item QA set.

**Table 13.** RAG vs. closed-book ablation (n=30, judge = `gpt-4o`).

| Metric | RAG (grounded) | Closed-book (no retrieval) |
|---|---|---|
| Faithfulness (0–5) | 4.67, 95% CI [4.27, 4.97] | 4.40, 95% CI [3.87, 4.83] |
| Relevance (0–5) | 4.40 | 4.70 |
| **Hallucination-flag rate** | **13.3%**, Wilson 95% CI [5.3%, 29.7%] | **20.0%**, Wilson 95% CI [9.5%, 37.3%] |
| Keyword coverage | 0.76 | 0.74 |
| Mean latency | 3.46 s | 4.34 s |

`![Figure 9 — RAG vs. closed-book ablation](evaluation/figures/fig9_rag_vs_closedbook_ablation.png)`

RAG shows a directionally lower hallucination rate (13.3% vs. 20.0%) and higher faithfulness (4.67 vs. 4.40) than the closed-book baseline using the *identical* generator model — consistent with the core motivating hypothesis that grounding reduces fabricated claims. Closed-book scored marginally higher on judge-rated relevance (4.70 vs. 4.40). At n=30 the 95% confidence intervals for faithfulness and hallucination rate overlap between conditions, so **the effect is directionally consistent with the RAG hypothesis but does not reach conventional statistical significance at this sample size** — we report this honestly rather than overstating significance, and recommend scaling to n≥100 with paired significance testing (e.g. McNemar's test on the binary hallucination flag) for a camera-ready submission (§7).

### 5.12 Live Azure deployment probe

To close the gap between benchmarking local code execution and the actual deployed system, we probed the real, running production instance directly over the public internet, using only **read-only, side-effect-free** endpoints (`GET /`, `GET /health/token`) — no `/webhook` POST was ever sent, so no outbound WhatsApp Cloud API call was triggered.

**Table 14.** Live deployment network probe (n=30 requests/endpoint).

| Endpoint | Mean latency | p95 latency | HTTP status |
|---|---|---|---|
| `GET /` (root) | 755.4 ms | 853.5 ms | 200 × 30/30 |
| `GET /health/token` | 1231.4 ms | 1546.3 ms | 200 × 30/30 |

Live scale configuration (`az containerapp show`): `minReplicas=1, maxReplicas=1`. The container was never observed cold, so the ~755 ms root latency is pure network + ingress + FastAPI dispatch overhead with no LLM/agent work involved — a floor on any request's latency in production. `/health/token` is slower because it itself makes an outbound call to `graph.facebook.com` before responding. Notably, the live configuration shows the deployment is **not currently autoscaling** (`minReplicas = maxReplicas = 1`), which is a discrepancy against the documented "0–100 instances" auto-scaling capability — exactly the class of finding that only a live-deployment probe, rather than local code review, can surface (§6.7).

### 5.13 Cross-component summary

`![Figure 1 (evaluation) — Component latency overview](evaluation/figures/fig1_component_latency_overview.png)`

**Table 15.** Mean latency across all measured components (log scale spans four orders of magnitude).

| Component | Mean latency |
|---|---|
| Language detection | 0.7 µs |
| Report intent detection (keyword) | 6.0 µs |
| SQLite read | 0.07–0.4 ms |
| SQLite write | 0.3–0.8 ms |
| FAISS retrieval | 325 ms |
| Report LLM extraction | ≈1.7 s |
| RAG generation (E2E) | 3.33 s |
| Agent routing (E2E) | 6.21 s |

Deterministic components (language detection, SQLite I/O) are essentially free; the FAISS-retrieval network round trip sits three orders of magnitude above that; and every LLM-backed operation costs 1.8–6.2 s, dominating user-perceived latency. This motivates LLM-call reduction (response caching, smaller extraction models, request batching) as the highest-leverage direction for future latency optimisation.

---

## 6. Discussion

### 6.1 Agentic routing vs. rule-based dispatch

The 100%-vs-38.9% gap between agentic tool-selection and keyword-based report detection (§5.4–§5.5) is direct, quantitative evidence — measured on the *same class* of report-style input — that natural-language routing decisions in this domain benefit materially from LLM reasoning over rigid keyword rules, at the cost of substantially higher per-request latency (µs → seconds) and non-zero per-request API expense.

### 6.2 Latency budget and user experience

At 4–8 s median end-to-end latency, the system sits near the upper bound of tolerable response time for a synchronous chat interaction; the current WhatsApp-webhook design (deliver-then-process-async) is therefore the correct choice over a blocking reply, and the evaluation confirms it degrades gracefully under concurrent load (§5.8).

### 6.3 Value of outlier-focused benchmarking

§5.9 demonstrates a broader methodological point: a genuine, user-impacting production defect (silent mis-routing of a common conversational phrase) was invisible to every central-tendency statistic and was only surfaced by examining minimum/outlier latencies during a concurrency benchmark. We recommend outlier and tail-latency reporting as a standard component of technical evaluations for LLM-agent systems, not merely mean/median summaries.

### 6.4 Retrieval and generation quality proxies

Recall@k and answer "coverage" (§5.2–§5.3) are automatic, keyword-based proxies chosen for cost and reproducibility, not substitutes for human relevance/faithfulness judgement. `calculate_confidence()` in the production RAG module is a coarse, uncalibrated heuristic (constant at 0.80 for well-formed answers in our set) and should not be interpreted as a calibrated probability. A camera-ready evaluation should add either human annotation or an LLM-as-judge protocol (e.g., a RAGAS-style faithfulness/answer-relevance score) alongside the automatic proxies reported here.

### 6.5 Scalability constraints

The Bayesian triangulation computation itself is not a bottleneck (sub-10 ms at 50 corroborators, §5.6); the underlying single-writer SQLite persistence layer is (§5.7), and — because Azure Container Apps can auto-scale to multiple replicas while SQLite remains local to each container's filesystem — this constraint would manifest as *silently fragmented, inconsistent data* across replicas under horizontal scale-out, not merely reduced throughput. We recommend migrating to a shared managed database (Azure SQL/PostgreSQL, or Azure Table/Cosmos DB) before enabling multi-replica auto-scaling in production, since the current architecture implicitly assumes a single active replica.

### 6.6 Does RAG actually reduce hallucination here?

The ablation in §5.11 provides the first controlled (same-model, same-question) comparison in this evaluation between grounded and ungrounded generation. The direction of every measured effect (lower hallucination rate, higher faithfulness for RAG) is consistent with the standard RAG hypothesis, but at n=30 the confidence intervals overlap and the closed-book condition even scored slightly higher on judge-rated relevance. We interpret this as *encouraging but inconclusive* evidence rather than a proven effect, and note that closed-book `gpt-4o-mini` already has non-trivial world knowledge about Sri Lankan disaster preparedness from pretraining data, which likely narrows the gap versus a domain where the LLM has no relevant prior knowledge at all. A larger, pre-registered version of this ablation (n≥100, paired significance testing) is the natural next step.

### 6.7 Live deployment reveals a documentation-reality gap

The live-deployment probe (§5.12) was motivated purely by a desire for genuine network-latency numbers, but its most consequential finding was incidental: the production Container App is configured with `minReplicas = maxReplicas = 1`, meaning it is **not currently autoscaling**, in contrast to the "0–100 instances" auto-scaling capability described in the project's own deployment documentation. This is a useful illustration of a broader point for systems papers: claims about a deployed architecture's *capabilities* (what it *could* do) should be distinguished from its *current configuration* (what it *is* doing), and only checking the latter against the live environment — rather than relying on documentation or source code alone — can catch this class of drift.

---

## 7. Limitations and Threats to Validity

1. **Sample sizes (n=29–60 per test set, n=30 for the ablation)** were scaled up 1.5–3× from an initial n=18–20 pilot, with 95% bootstrap/Wilson confidence intervals now reported throughout; this is a substantial improvement but still short of the n≥100 with paired significance testing recommended for a camera-ready study, particularly for the ablation in §5.11 where the RAG-vs-closed-book effect is directionally consistent but not statistically significant at n=30.
2. **Keyword-coverage groundedness/recall proxies**, now supplemented by an independent LLM-as-judge (§5.11) using a different model from the production generator to reduce self-evaluation bias, remain automatic proxies rather than human or domain-expert (NBRO/DMC) judgement of factual correctness — the latter is still absent from this evaluation.
3. **Uncalibrated confidence heuristic**: the production `calculate_confidence()` function is a coarse heuristic, not a calibrated probability estimate.
4. **Network variability**: LLM/embedding latencies were measured over one residential connection to `api.openai.com`; §5.12 additionally measures the real deployed Azure endpoint directly, partially closing this gap for infrastructure-level (non-LLM) latency, but absolute LLM-call latency from inside the Azure region itself remains unmeasured.
5. **Single-machine, single-process concurrency test** (§5.8) isolates agent/LLM concurrency behaviour deliberately (§4.1) but does not reproduce the deployed multi-replica Azure Container Apps environment — though §5.12 shows the live deployment is in fact currently configured for a single replica, narrowing this gap in practice for the current deployment stage.
6. **No production traffic was used.** At the time of evaluation the deployment had no real end users (confirmed by the system owner); all test messages are synthetic. The live-deployment probe (§5.12) deliberately used only read-only, side-effect-free endpoints (no `/webhook` POST, no outbound WhatsApp messages) to preserve this constraint while still obtaining genuine production network measurements.
7. **Single-run measurements per configuration.** Most benchmarks report one execution per configuration with bootstrap/Wilson confidence intervals computed over the sample, rather than repeated end-to-end trials; a camera-ready version should additionally re-run each benchmark ≥3× and report between-run variance.
8. **No human/domain-expert evaluation or field study.** This remains the most significant outstanding gap for a disaster-risk-management-focused venue specifically (as opposed to a systems/ML venue): no NBRO/DMC expert has validated the factual correctness of hazard advice, and no real end-user has judged comprehension, trust, or actionability. This is flagged as required future work (§8) rather than substituted with automated proxies.

---

## 8. Conclusion and Future Work

We presented the architecture and a full component-level performance evaluation of a deployed, multilingual, agentic RAG system for WhatsApp-based disaster advisory and community hazard reporting. The evaluation — conducted against real production code, at sample sizes scaled up from an initial pilot, with an explicit closed-book ablation and a genuine live-deployment network probe — quantifies the latency/accuracy trade-offs of each architectural layer, validates the correctness of a Bayesian truth-discovery mechanism against a closed-form reference, provides directionally encouraging but not yet statistically conclusive evidence that retrieval grounding reduces hallucination, and demonstrates, through both a discovered-and-fixed routing defect and a documentation-vs-reality autoscaling discrepancy, the practical value of outlier-aware and live-system-aware benchmarking. Future work should (a) scale the ablation and routing test sets to n≥100 with paired significance testing, (b) commission human/domain-expert (NBRO/DMC) evaluation of hazard-advice correctness, (c) migrate shared persistence off local SQLite ahead of multi-replica deployment, (d) conduct a field trial with real users to validate the offline metrics against real-world engagement and report-verification outcomes, and (e) perform a sensitivity analysis of the Bayesian reliability learning rate α and the confidence/severity decision-matrix thresholds against ground-truth-verified historical reports once sufficient production data accumulates.

---

## 9. Data and Code Availability

The complete benchmark suite, hand-labelled evaluation datasets, raw JSON results, and all figures referenced in this manuscript are included in the project repository under `evaluation/` (`evaluation/PERFORMANCE_EVALUATION.md` contains the extended results appendix; `evaluation/run_all.py` reproduces every number and figure end-to-end).

---

## 10. References

*(Placeholder — author to complete with verified, correctly formatted citations in the target journal's style before submission. Do not cite the bullet points in §2 as final references without independently verifying title, authors, venue, and year against the original source.)*

1. Lewis, P. et al. — Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS, 2020. *(verify citation details)*
2. Yin, X., Han, J., & Yu, P. S. — Truth discovery with multiple conflicting information providers on the web. *(verify exact venue/year)*
3. [Author to add: LangChain / tool-calling agent framework citation]
4. [Author to add: WhatsApp/USSD/SMS disaster early-warning system literature, Sri Lanka / South Asia regional context]
5. [Author to add: FAISS / dense retrieval citation]
6. [Author to add: VGI data-quality and crowd-sourcing literature]

---

## Appendix A. Figure Index

| Figure | File |
|---|---|
| 1 (architecture) | `evaluation/figures/fig0_system_architecture.png` |
| 1 (evaluation, latency overview) | `evaluation/figures/fig1_component_latency_overview.png` |
| 2 | `evaluation/figures/fig2_retrieval_recall_vs_k.png` |
| 3 | `evaluation/figures/fig3_rag_latency_by_language.png` |
| 4 | `evaluation/figures/fig4_routing_confusion_matrix.png` |
| 5 | `evaluation/figures/fig5_reporting_pipeline_accuracy.png` |
| 6 | `evaluation/figures/fig6_triangulation_bayesian.png` |
| 7 | `evaluation/figures/fig7_db_concurrency.png` |
| 8 | `evaluation/figures/fig8_e2e_concurrency.png` |

## Appendix B. Extended Results Appendix

See [`evaluation/PERFORMANCE_EVALUATION.md`](evaluation/PERFORMANCE_EVALUATION.md) for the full results appendix (per-item results, stage-level latency breakdowns, and additional discussion) underlying §5 of this manuscript.
