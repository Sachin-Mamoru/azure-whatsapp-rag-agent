# A Multilingual Agentic RAG System for WhatsApp-Based Disaster Early Warning and Community-Sourced Hazard Reporting: Architecture, Implementation, and Performance Evaluation

*Draft manuscript — technical evaluation section prepared for submission to a Q1 disaster-risk-management / applied-AI journal. Author to complete title-page metadata (authors, affiliations, ORCID, corresponding author, funding/ethics statements) and the Related Work bibliography before submission.*

---

## Abstract

Low- and middle-income disaster-prone regions increasingly rely on ubiquitous messaging platforms such as WhatsApp for public-safety communication, yet most deployed chatbots either answer static FAQs or forward messages to a human operator, with no mechanism for citizens to *contribute* observations back into the advisory pipeline. We present the architecture and an empirical technical evaluation of a deployed, multilingual (English/Sinhala/Tamil) WhatsApp disaster-advisory agent that combines (i) a LangChain tool-calling agent (GPT-4o-mini) that autonomously routes each message to a retrieval-augmented generation (RAG) knowledge-base tool, a live web-search tool, or a volunteered-geographic-information (VGI) hazard-reporting tool; (ii) a Bayesian truth-discovery mechanism (TruthFinder-style source-reliability weighting) that triangulates independent citizen reports before surfacing them as supplementary advisory context; and (iii) a serverless Azure Container Apps deployment with a background scheduler for periodic alert dissemination. We benchmark every architectural component in isolation against the real, unmodified production code — FAISS retrieval, GPT-4o-mini generation, agent tool-routing, LLM-based report extraction, Bayesian triangulation, SQLite persistence, deterministic language detection, and end-to-end concurrency — using hand-labelled evaluation sets. The agentic routing layer achieves 100% tool-selection accuracy (n=20) versus 38.9% recall for a pure keyword-based report filter, quantitatively justifying the agentic design over rule-based dispatch. All LLM-backed operations (1.8–6.2 s mean latency) dominate end-to-end latency, while deterministic components (language detection, SQLite I/O) operate in the microsecond-to-millisecond range. Systematic outlier analysis during concurrency testing surfaced a substring-matching routing defect in the deterministic pre-check layer; we document its discovery, root cause, fix, and post-fix re-verification as a case study in benchmarking-driven quality assurance. We report the Bayesian triangulation mechanism's correctness against a closed-form reference implementation (maximum absolute error 1.6×10⁻⁴) and identify the single-writer SQLite persistence layer as the primary scalability constraint for multi-replica horizontal scaling. All benchmark code, hand-labelled test sets, raw results, and figures are released for reproducibility.

**Keywords:** disaster early warning; conversational AI; retrieval-augmented generation; LLM agents; volunteered geographic information; Bayesian truth discovery; WhatsApp chatbot; multilingual NLP; serverless architecture; performance evaluation

---

## 1. Introduction

### 1.1 Motivation

Sri Lanka experiences recurring monsoon-driven flooding and landslides, and public disaster communication remains fragmented across radio, SMS, and manual community-liaison networks. WhatsApp is the dominant messaging platform in the region, making it an attractive channel for both *outbound* early-warning dissemination and *inbound* citizen-to-authority hazard reporting. However, existing WhatsApp-based safety bots are typically single-purpose: either a static FAQ retriever or a one-way broadcast tool. Two capabilities are largely absent from the deployed literature: (1) **autonomous, LLM-driven routing** between a curated authoritative knowledge base and live web information, and (2) a **governed pipeline for crowd-sourced hazard reports** that scores plausibility and reporter credibility before such reports influence the advice given to other citizens.

### 1.2 System summary

We designed and deployed a system (Figure 1) that: detects the user's language from Unicode script; runs deterministic pre-checks (registration, opt-out, greeting) before any LLM call; and, for substantive messages, invokes a LangChain tool-calling agent backed by GPT-4o-mini with four tools — `query_knowledge_base` (FAISS RAG over 916 chunks drawn from three official hazard-guidance PDFs), `search_web` (Serper/DuckDuckGo), `submit_community_report` (structured extraction + Bayesian scoring pipeline), and `get_community_observations`. Citizen reports are stored separately from the authoritative knowledge base and are only surfaced as explicitly labelled, unverified supplementary context. A background APScheduler process periodically synchronises registrations from Google Sheets, crawls a GitHub Pages–hosted early-warning feed to dispatch alerts, and retires stale reports while decaying reporter reliability.

### 1.3 Contributions

1. An architecture combining agentic tool-routing, multilingual RAG, and Bayesian VGI truth discovery in a single production WhatsApp deployment (§3).
2. A component-level performance-evaluation methodology and open benchmark suite exercising the *real* production code paths of all eight architectural components, rather than isolated unit-level mocks (§4).
3. Empirical evidence that LLM-based agentic routing substantially outperforms a keyword-based intent filter for the report-detection task (100% vs. 38.9% recall), providing a quantitative justification often missing from agentic-system papers (§5.5).
4. A worked case study showing how systematic latency-outlier analysis (not just mean/median reporting) surfaced a genuine production routing defect, which we diagnose, fix, and re-verify (§5.9, §6.3) — offered as a methodological argument for reporting full latency distributions rather than averages alone.
5. A validated, closed-form-checked implementation of Bayesian source-reliability triangulation (TruthFinder-style) for crowd-sourced hazard reports, with measured computational scaling behaviour (§5.6).
6. A fully reproducible, openly released evaluation artifact (code, datasets, raw results, figures) enabling independent replication (§7).

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
`![Figure 1 — System architecture](figures/fig0_system_architecture.png)`

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

Apple M3 Pro, 18 GB RAM, macOS 15.5; Python 3.11.16; FastAPI 0.115.0; LangChain 0.2.14; FAISS-CPU 1.8.0; `gpt-4o-mini` at temperature 0.0–0.1; `text-embedding-3-large` embeddings; direct residential-broadband calls to `api.openai.com` (no proxy/cache). All test sets (18–20 items each) are hand-labelled and included with the release for peer review.

### 4.3 Metrics

- **Latency**: mean, standard deviation, and p50/p90/p95/p99, measured with `time.perf_counter()` around each call.
- **Retrieval quality**: Recall@k using a keyword-coverage proxy (a retrieved chunk is scored relevant if it contains ≥1 expected keyword) — a deliberately disclosed automatic-proxy limitation (§6.4).
- **Routing/classification accuracy**: exact-match accuracy and full confusion matrices against hand-labelled ground truth.
- **Extraction accuracy**: per-field accuracy (5 fields) and whole-record exact-match rate against ground truth.
- **Numerical correctness**: absolute error of the production Bayesian-triangulation output versus an independently coded closed-form reference implementation of the same formula.
- **Throughput/concurrency**: requests/second and latency percentiles across concurrency levels 1/2/4/8, and SQLite operations/second across 1/2/4/8/16 concurrent writer threads.

### 4.4 Reproducibility

```bash
python3 -m venv .venv-eval && source .venv-eval/bin/activate
pip install -r requirements.txt matplotlib numpy pandas scikit-learn
python evaluation/run_all.py     # executes bench_00 .. bench_08, then regenerates all figures
```
Raw results: `evaluation/results/*.json`. Figures: `evaluation/figures/*.png`. Test sets: `evaluation/datasets/*.json`.

---

## 5. Results

### 5.1 Offline indexing pipeline

Building the FAISS index from 3 PDFs (355 pages → 916 chunks, chunk size 1000/overlap 200) took 12.5 s (warm run) to 55.5 s (cold run including first-import overhead), an embedding throughput of ≈73 chunks/s — inexpensive enough to run on every container cold start, though caching the saved index remains the correct design choice given the observed run-to-run variance.

### 5.2 RAG retrieval (FAISS)

**Table 3.** Recall@k and retrieval-only latency (20-item grounded QA set).

| k | Recall@k (keyword proxy) | Mean latency | p95 latency |
|---|---|---|---|
| 1 | 0.80 | 422.3 ms | 1033.5 ms |
| 2 | 0.80 | 324.8 ms | 339.1 ms |
| 4 | 0.80 | 324.7 ms | 342.6 ms |
| 8 | 0.80 | 331.2 ms | 360.1 ms |

`![Figure 2 — Recall@k and latency vs. k](figures/fig2_retrieval_recall_vs_k.png)`

Latency is dominated by the embedding-API round trip rather than FAISS's exact nearest-neighbour search over 916 vectors (sub-millisecond); recall is flat across k, indicating retrieval quality is limited by query/embedding semantics rather than neighbourhood size.

### 5.3 RAG generation (retrieval + GPT-4o-mini synthesis)

**Table 4.** End-to-end RAG query latency and answer-quality proxies (n=20).

| Metric | Value |
|---|---|
| Mean latency | 4.09 s (σ = 1.32 s); p50 3.80 s, p95 6.29 s |
| Mean keyword coverage (groundedness proxy) | 0.82 (σ = 0.28) |
| Latency: English (n=16) / Sinhala (n=2) / Tamil (n=2) | 4.00 s / 4.88 s / 4.01 s |

`![Figure 3 — RAG generation latency by language](figures/fig3_rag_latency_by_language.png)`

Language does not materially change latency, indicating the multilingual prompt design introduces no asymmetric cost across the three supported languages.

### 5.4 Agent tool-routing

**Table 5.** Tool-selection accuracy and latency by expected tool (20-item labelled set, 3 languages).

| | |
|---|---|
| **Tool-selection accuracy** | **100% (20/20)** |
| Mean E2E latency | 6.21 s (σ = 2.90 s); p50 5.57 s, p95 10.79 s |
| By tool | KB query 8.68 s · web search 5.85 s · submit report 6.21 s · get observations 1.86 s |

`![Figure 4 — Tool-routing confusion matrix](figures/fig4_routing_confusion_matrix.png)`

`get_community_observations` is markedly faster because, uniquely among the four tools, it performs a synchronous database read rather than a nested LLM call; the other three tools each incur a second OpenAI completion inside the tool body.

### 5.5 Community reporting pipeline

**Table 6.** Keyword-based intent pre-filter as a binary classifier (18 positive / 20 negative).

| Precision | Recall | F1 | Mean latency |
|---|---|---|---|
| 1.00 | **0.39** | 0.56 | 6.0 µs |

**Table 7.** LLM-based structured-extraction field accuracy (n=18).

| Field | Accuracy |
|---|---|
| `has_location` | 1.00 |
| `ongoing` | 0.94 |
| `people_at_risk` | 0.83 |
| `report_domain` | 0.78 |
| `hazard_type` | 0.72 |
| **Exact match, all 5 fields** | **0.50** |
| Mean latency | 1.83 s (p95 2.15 s) |

`![Figure 5 — Reporting pipeline accuracy](figures/fig5_reporting_pipeline_accuracy.png)`

The 61-percentage-point gap between the keyword filter's recall (39%) and the agent's tool-routing accuracy (100%, §5.4, same class of report-style messages) is the central quantitative justification for escalating report detection to an LLM agent rather than a rule-based classifier.

### 5.6 Bayesian truth discovery

**Table 8.** Triangulation correctness and computational scaling.

| Metric | Value |
|---|---|
| Max absolute error vs. closed-form reference | 1.6×10⁻⁴ (rounding only — formula verified correct) |
| Latency @ 1 / 10 / 50 corroborators | 0.21 ms / 1.58 ms / 8.33 ms |
| Reliability convergence (repeated verification) | 0.50 → 0.95 (clamp) in 7 update events |
| Reliability convergence (repeated rejection) | 0.50 → 0.05 (clamp) in 7 update events |

`![Figure 6 — Bayesian triangulation behaviour](figures/fig6_triangulation_bayesian.png)`

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

`![Figure 7 — SQLite concurrency scaling](figures/fig7_db_concurrency.png)`

Throughput falls 63% from 1 to 16 concurrent writers (no write errors observed — SQLite's busy-timeout absorbs contention as latency rather than failure), consistent with its single-writer lock. Because Azure Container Apps can auto-scale to multiple replicas while SQLite remains a local container-filesystem file, multi-replica deployment would fragment the database across replicas rather than share it — a concrete architectural limitation for horizontal scaling (§6.5).

### 5.8 End-to-end orchestrator throughput and concurrency

**Table 11.** `WhatsAppOrchestrator.process_message()` throughput/latency by concurrency (8 requests/level; measured **after** the fix in §5.9).

| Concurrency | Throughput (req/s) | p50 latency | p95 latency |
|---|---|---|---|
| 1 | 0.153 | 7.07 s | 12.51 s |
| 2 | 0.257 | 6.88 s | 10.45 s |
| 4 | 0.430 | 6.74 s | 11.18 s |
| 8 | 0.531 | 8.37 s | 15.03 s |

`![Figure 8 — End-to-end throughput/latency vs. concurrency](figures/fig8_e2e_concurrency.png)`

Throughput scales near-linearly (0.153 → 0.531 req/s, ≈3.5×) while p50 latency grows only 18% (7.07 s → 8.37 s), confirming the system is I/O-bound on external LLM calls rather than CPU-bound — the async FastAPI design absorbs concurrent webhook deliveries within a single container replica without proportional latency degradation. All 32 simulated requests across the four levels completed successfully.

### 5.9 Case study: a routing defect surfaced by outlier analysis, and its fix

While collecting the data in Table 11, one test message — *"Is there any active flood alert right now in Kalutara?"* — returned in under 0.3 ms instead of the expected ≈6 s, at every concurrency level, a four-order-of-magnitude latency outlier invisible in mean/median statistics alone. Root-cause analysis traced this to `WhatsAppOrchestrator._REGISTER_COMMANDS` in the deterministic pre-check layer, which contained the bare token `"alert"` matched by raw substring containment; any message merely *mentioning* the word "alert" — an unremarkable word in a disaster-advisory context — was silently redirected to the registration-prompt flow before ever reaching the LLM agent, and so never received a substantive answer. We implemented a guard, `_is_command_intent()`, that only treats a message as a short explicit command if it (a) does not end in "?", (b) does not begin with an interrogative word, and (c) is no longer than six words — mirroring a question-exclusion guard already used elsewhere in the codebase's report-intent filter — and applied it to all three keyword-triggered pre-check paths (registration, STOP/unsubscribe, language-change). An 8-case targeted regression test (short genuine commands vs. equivalent full questions containing the same trigger words) passed 8/8 post-fix, and Table 11 reflects the corrected, re-run benchmark. We present this as a methodological argument for reporting full latency distributions — including minima and outliers — rather than central-tendency statistics alone, since the defect was undetectable from means or medians.

### 5.10 Language detection (deterministic pre-check)

**Table 12.** Unicode-script-based language detector (20-item trilingual set).

| Accuracy | Mean latency | p99 latency |
|---|---|---|
| 100% (20/20) | 0.71 µs | 4.0 µs |

The detector is effectively free and perfectly accurate on script-distinguishable text, validating its use ahead of any LLM call in preference to a slower, probabilistic library-based detector for the two non-Latin scripts.

### 5.11 Cross-component summary

`![Figure 1 (evaluation) — Component latency overview](figures/fig1_component_latency_overview.png)`

**Table 13.** Mean latency across all measured components (log scale spans four orders of magnitude).

| Component | Mean latency |
|---|---|
| Language detection | 0.7 µs |
| Report intent detection (keyword) | 6.0 µs |
| SQLite read | 0.07–0.4 ms |
| SQLite write | 0.3–0.8 ms |
| FAISS retrieval | 325 ms |
| Report LLM extraction | 1.83 s |
| RAG generation (E2E) | 4.09 s |
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

---

## 7. Limitations and Threats to Validity

1. **Sample sizes (n=18–20 per test set)** are adequate for demonstrating methodology and obtaining point estimates with visible variance but too small for tight confidence intervals; a camera-ready study should scale each test set to n≥100 with bootstrap confidence intervals.
2. **Keyword-coverage groundedness/recall proxies** (§6.4) are not human relevance judgements; results on answer *quality* should be corroborated with human or LLM-as-judge evaluation before strong claims are made.
3. **Uncalibrated confidence heuristic**: the production `calculate_confidence()` function is a coarse heuristic, not a calibrated probability estimate.
4. **Network variability**: all LLM/embedding latencies were measured over one residential connection to `api.openai.com` on one measurement occasion; absolute latencies will differ from the deployed Azure-region network path, though relative comparisons between components are robust to this.
5. **Single-machine, single-process concurrency test** (§5.8) isolates agent/LLM concurrency behaviour deliberately (§4.1) but does not reproduce the deployed multi-replica Azure Container Apps environment, nor real network latency to WhatsApp/Meta or Azure Redis.
6. **No production traffic was used.** At the time of evaluation the deployment had no real end users (confirmed by the system owner); all test messages are synthetic, and no benchmark traffic was sent through the live WhatsApp webhook or to real phone numbers.
7. **Single-run measurements.** Most benchmarks report one execution per configuration rather than repeated trials with aggregated confidence intervals; this is disclosed as a methodological limitation to be addressed before peer review by re-running each benchmark ≥3× and reporting the aggregate.

---

## 8. Conclusion and Future Work

We presented the architecture and a full component-level performance evaluation of a deployed, multilingual, agentic RAG system for WhatsApp-based disaster advisory and community hazard reporting. The evaluation — conducted against real production code rather than mocks — quantifies the latency/accuracy trade-offs of each architectural layer, validates the correctness of a Bayesian truth-discovery mechanism against a closed-form reference, and demonstrates, through a discovered-and-fixed routing defect, the practical value of outlier-aware benchmarking. Future work should (a) scale the evaluation datasets and add human/LLM-judge answer-quality scoring, (b) migrate shared persistence off local SQLite ahead of multi-replica deployment, (c) conduct a field trial with real users to validate the offline metrics against real-world engagement and report-verification outcomes, and (d) perform a sensitivity analysis of the Bayesian reliability learning rate α and the confidence/severity decision-matrix thresholds against ground-truth-verified historical reports once sufficient production data accumulates.

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
