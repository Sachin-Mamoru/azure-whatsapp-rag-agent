# Manuscript update: community-reporting subsystem (ICITR)

Scope: structured extraction, location clarification, image understanding,
contributor reputation, corroboration, confidence/severity scoring, human
review, persistence and retention. RAG question answering, retrieval, outbound
alerts and whole-system architecture belong to the separate journal paper and
are not described here.

Every sentence below is supported by an entry in `CLAIMS_MATRIX.md`. §4
reports the single frozen live image run; its reference labels are
provisional (Commons category) or AI-reviewed, never human, and the text says
so wherever a figure appears.

---

## 1. Terminology to change throughout

| Draft wording | Replace with | Reason |
|---|---|---|
| "Bayesian truth discovery", "TruthFinder-style", "Bayesian triangulation" | "reputation-weighted corroboration (product-of-odds aggregation)" | The formula is a product-of-odds combination, not a posterior and not the TruthFinder iteration |
| "P(true)", "probability the report is true" | "corroboration agreement score" | No calibration study exists |
| "reporter reliability" (where it implies truthfulness probability) | "contributor reputation (a bounded moving average of review outcomes)" | Matches the update rule |
| "Sybil resistance" | "self-exclusion" | Multiple accounts are not detected |
| "independent corroborating reports" | "reports from other contributors" | Distinct accounts are not independent observations |
| "rainfall at the site", "recorded rainfall" | "same-day district precipitation forecast" | Open-Meteo daily forecast at a district centroid |
| "decaying reporter reliability" on expiry | remove | Never executed in the audited code; removed by design |

## 2. Methods text

**Structured extraction and validation.** Each report is extracted by
GPT-4o-mini (temperature 0) into a fixed schema: domain, hazard type,
category, location text, location specificity, description, human exposure,
ongoing status, hazard scale and infrastructure damage. The reply is
parsed and checked field by field against an explicit schema covering enumerated
values, booleans, numeric bounds and required fields. Invalid fields take
conservative defaults and are recorded. If the call times out (30 s), fails,
or returns malformed or non-object JSON, a deterministic keyword extractor
produces the record, and the reason is stored with it.

**Location clarification.** When no location, or only a non-specific one, is
extracted, the system asks one follow-up question and holds the partial
report in the user's session for up to 60 minutes. The user's next message
completes the report without repeating extraction or image analysis, and
"cancel" (in English, Sinhala or Tamil) discards it. Held reports are
isolated per user.

**Photographic evidence.** A photo is accepted only if its bytes are JPEG,
PNG, WebP or GIF and at most 10 MB. It is assessed by the same model in
multimodal mode against a five-tier evidence rubric (0.00–0.20), returning
hazard presence, hazard category, apparent severity and text–image
consistency. Each assessment is classified as unavailable (model error, timeout or
invalid core field), unusable (tier 0), no hazard, contradiction, or
supporting. Only a supporting photo contributes its tier to confidence. Hazard
type and scale are filled from the photo only when the text left them
unknown and the photo is supporting with high or moderate consistency; text
values are never overwritten, and each accept or reject decision is stored
with its reason.

**Confidence and severity.** Confidence is the sum of completeness (≤0.30),
plausibility (≤0.20; a district hazard-prone list plus a small bonus when a
same-day precipitation forecast fetched within three hours exceeds 20 or 50 mm),
corroboration (≤0.30) and photographic evidence (≤0.20). Severity sums
exposure (0.40), infrastructure damage (0.20), hazard scale (≤0.30) and
immediacy (0.10). Both are additive heuristic scores, not calibrated
probabilities. Sums are rounded to 10⁻⁶ before thresholds, so decimal
boundaries are not lost to binary floating-point residue.

**Corroboration.** Reports from other contributors in the same domain,
hazard type and location token within 12 hours contribute. Each contributor
counts once, the submitter is excluded, and reports carrying a byte-identical
photo are excluded. With contributor reputations rᵢ clipped to [0.05, 0.95],
the agreement score is ∏rᵢ / (∏rᵢ + ∏(1 − rᵢ)), computed as
σ(Σ log(rᵢ/(1 − rᵢ))) with a numerically stable sigmoid, and scaled to 0.30.
Distinct accounts are not evidence of independent observation.

**Contributor reputation and human review.** Reputation starts at 0.5 and
is updated after each human review by r ← round₄(clip(0.7r + 0.3y, 0.05,
0.95)), with y = 1 for a verified report and y = 0 for a report verified as
false. A review decision, its event record, the report status and the
recomputed reputation are written in one transaction. Repeating a decision
has no effect. A mistaken review is corrected by recording the right decision
(or a retraction), after which reputation is recomputed by replaying each
report's latest decision in recording order. Because the moving average is
order-dependent, replay rather than inversion keeps the score equal to what
it would be had the mistaken decision never been made. Reports that expire
unreviewed are archived without any change to reputation, and remain
distinguishable from reports reviewed as false.

**Decision policy.** The deployed policy (baseline) maps confidence and
severity to store-only, monitor, flag-for-review or escalate. A candidate
policy is computed for every report and stored alongside it but does not
drive actions. Its actions are ordered escalate > expedited review > flag for
review > monitor > store only, and it sends every report with severity ≥ 0.70
and confidence < 0.70 to expedited human review.

**Provenance, retention and privacy.** Each stored report keeps a
provenance record sufficient to recompute its scores and action:
- full-precision score components and both policies' actions;
- prompt digests, the model alias and the per-call model snapshot;
- extraction status and the validated photo assessment;
- backfill decisions;
- the forecast context with fetch time;
- the pseudonyms, reputations and report identifiers of corroborating contributors.

Photos are deleted after 30 days, and unreferenced photos from abandoned
clarifications are removed. Contributors are identified by keyed HMAC-SHA-256
pseudonyms; earlier unkeyed identifiers are re-keyed on first contact so
histories carry over.

## 3. Results text (completed work)

**Correctness verification.** We reproduced four defects by running the
audited implementation on controlled inputs.
- Repeating the verification of one report raised its contributor's
  reputation each time (0.65, 0.755, 0.8285).
- A failed photo assessment added 0.05 evidence.
- A failed database write was acknowledged to the user as stored.
- The retention job's reputation update failed with a database lock (about
  5.4 s per report), so the documented decay never took effect.

Direct products also underflowed for large corroborating sets: with 1,100
contributors at reputation 0.5 the direct formula gives 0, whereas the
log-odds form gives the intended 0.5. On ordinary inputs the two agree to
1.1 × 10⁻¹⁶. The regression suite (55 tests, including one per defect
above that fails on the audited behaviour) passes on the evaluated revision.

**Decision policy analysis.** On a grid over confidence and severity
(including values one floating-point step either side of each threshold), the
baseline policy had 44 adjacent-step monotonicity violations, where a higher
score led to a lower-priority action. Examples:
- confidence 0.39 with severity 1.0 is stored without review;
- raising confidence from just below 0.70 to 0.70 at severity 0.50 moves a report from review to monitoring.

The candidate policy had none. Applied in shadow to the 29 archived
extractions (without corroboration, forecast or photo context), the candidate
moved 10 of 29 reports to expedited review. This shows a higher review load;
it is not evidence of better triage, since no reference priorities exist for
these reports.

**Extraction agreement on the archived set.** Re-scoring the archived
predictions for 29 constructed messages (21 English, 4 Sinhala, 4 Tamil)
against their original labels gave:

| Field | Agreement | Wilson 95% CI |
|---|---|---|
| Domain | 23/29 | 0.62–0.90 |
| Hazard type | 23/29 | 0.62–0.90 |
| Human exposure | 20/29 | 0.51–0.83 |
| Ongoing status | 27/29 | 0.78–0.98 |
| All five fields | 14/29 | 0.31–0.66 |

Location text was present for 29/29; this measures presence, not geolocation
accuracy.

Exposure errors were all false positives (9 FP, 0 FN). Five of the nine
involved road-only mentions, which the extraction prompt defines as exposure
but the labels do not. We wrote an explicit annotation policy separating
human exposure, infrastructure impact and active versus completed hazards.
Applying it proposes six label changes. These are not yet human-reviewed, and
they leave every per-field count unchanged and lower all-five agreement to
13/29. The proposals and a blinded two-reviewer protocol are released; the
original-label figures above are the reported result.

## 4. Live image evaluation (single frozen run; reference labels are AI-reviewed, not human)

**Design.** Prompts, policies and the analysis plan were frozen in git
(`d7f7fd6`) before any test-split call; the runner refuses to start if a frozen
file differs. The test split holds 159 items: 133 real openly licensed
photographs from 11 event groups (80 from Sri Lankan events) paired with
templated English, Sinhala and Tamil captions, plus 26 derived controls (15
degraded copies, 8 exact duplicates, 3 re-encodings). GPT-4o-mini (snapshot
`gpt-4o-mini-2024-07-18`, temperature 0) ran once per item through the
production extraction and vision code. Two reference sets were used: the
Commons source category (provisional) and a single-pass AI review of every item
made before any model output existed (Claude Sonnet 5.5; one annotator, not
blind to dataset construction, no inter-annotator agreement). Human
annotation has not been done, so no figure below is a human-referenced result.

**Cost and speed.** All 159 items completed for $0.75 in total (about
$0.005 per report with a photo; 4.8 M vision input tokens). Measured from the
evaluation client, mean latency was 1.64 s for extraction (p95 2.04 s), 2.52 s
for the vision call (p95 3.13 s) and 4.16 s for the sequential model path
including scoring (p95 5.15 s). Transport, media download and database writes
are not included. Three vision replies (1.9%) violated the schema (an
out-of-range consistency value) and were handled as errors that add no support.

**Primary outcome: support given to images that do not support the report.**
Against the AI reference (96 real photos, 11 events), the earlier handling added
confidence for 48 (50.0%, Wilson 95% CI 40.2–59.8%) and visual-v2 for 24 (25.0%,
17.4–34.5%); all 24 discordant pairs favoured visual-v2 (exact McNemar
p = 1.2 × 10⁻⁷). Against the provisional labels (80 photos) the figures were
51.2% and 23.8% (p = 4.8 × 10⁻⁷). Because photos from one event are correlated,
we also resampled whole events (supplementary, not pre-registered): the
reduction was 25.0 percentage points (95% CI 16.1–32.8) with an improvement in
9 of 11 events and none worse. Among images the reference says do support their
report (37), none lost support under either policy.

**Why it improved, and what it does not fix.**
- The model never labelled a photo as contradicting its caption (consistency
  labels: high 90, low 38, moderate 3 of 131), so the contradiction rule never
  fired. The reduction came from not counting evidence on images the model
  itself judged to show no hazard or to be unusable (22 and 48 of 131).
- 24 of 96 non-supporting photos still added support because the model
  rated them as showing a hazard with high consistency: 12 of 53
  contradictory-caption photos (22.6%) and 8 of 69 photos where the reviewer sees
  no hazard (11.6%).
- Blurred, darkened or heavily downscaled copies were not recognised: 13 of 15
  still added support under visual-v2 (14 of 15 under the earlier handling), and
  in 12 of those 13 the model's visual outcome equalled that of the undegraded
  source. The reviewer judged 13 of the 15 unusable.
- Backfill of hazard type (29 of 57 eligible reports) was identical under both
  policies, so the stricter backfill gate changed no decision. Against the AI
  reference 17 of 29 backfills were correct (58.6%, 40.7–74.5%) and 8 of 29
  (27.6%) were made where the reviewer sees no hazard.

**Model agreement with the AI reference.** Coarse category 103/131 (78.6%,
70.8–84.8%), hazard presence 109/131 (83.2%, 75.9–88.6%), macro-F1 0.63 over
flood, landslide, other and none. The evidence tier matched exactly for 26.0%
and within one tier for 76.3% (mean absolute error 1.02 tiers); exact agreement
is sensitive to the reviewer's convention for non-supporting photos (0.05)
versus the model's (often 0.00). Contradiction recall was 0 of 51.

**Controls and reference quality.** Eight exact duplicates produced identical
category, outcome and tier, and three re-encodings the same category and
outcome. Against the AI reference, Commons category labels agreed on 75.9% of
the 133 real test photos (101/133), which is why they were not used as ground
truth for the headline result. Text hazard-type extraction matched the
templated caption claim on 133 of 133 items; with templated captions this is a
sanity check, not an accuracy estimate for real messages.

**Repeatability.** Because the model is not deterministic at temperature 0, the
test split was run a second time with identical frozen code, prompts and
inputs (run 1 above is the primary run; the repeat was decided after seeing run
1 and is reported as a replication). Between the two runs the visual-v2
support decision was identical for 158 of 159 items (99.4%), the coarse
category for 152 of 155 (98.1%, kappa 0.97), the visual outcome for 145 of 159
(91.2%), the consistency label for 147 of 155 (94.8%) and the evidence tier
for 138 of 155 (89.0%). The replication gave the same picture: support given
to non-supporting photos 24.0% (23/96) under visual-v2 versus 49.0% (47/96)
under the earlier handling (all 24 discordant pairs favouring visual-v2); no
contradiction was ever reported (0 of 50 contradictory-caption photos flagged);
13 of 15 degraded copies still added support (14 of 15 earlier); 18 of 29
backfills were correct and 8 were made where the reviewer sees no hazard; no
supporting photo lost support; 4 of 159 vision replies violated the schema. The
run-to-run variation is small relative to the effects reported, but
single-run percentages should be quoted to the nearest percentage point at most.

**Not measured.** Severe-report review recall, false escalation and review
workload (no independent reference priorities), contributor-weight ablation
(no histories; none simulated), and any human-referenced metric.

## 5. Limitations paragraph

Confidence, corroboration and reputation are heuristic scores, not calibrated
probabilities. Corroboration counts distinct accounts, which may belong to one
person or repeat the same second-hand claim; only byte-identical photos are
detected as copies. Location matching uses a single place token and no
geocoding. The archived extraction set is small, constructed, and labelled by
one author without a written policy. The image evaluation used templated
captions, a single AI-reviewed reference without human agreement, and photos
limited by open licensing (flood test photos come from two event groups); it
ran once at temperature 0 on a model whose repeated calls are not identical.
The photo policy removes support only when the model itself reports no hazard
or an unusable image: the model never reported a contradiction, rated blurred
and darkened copies as supporting, and rated a quarter of non-supporting
photos as supporting with high consistency. The candidate decision policy is
implemented and unit-tested but has not been validated against reference
priorities. In the current deployment the report database is held in container
temporary storage and sessions are held in process memory, so reputation
histories and pending reports do not survive restarts.

## 6. Draft passages to remove or revise

- **Abstract and §1:** "Bayesian truth-discovery mechanism", "decaying reporter
  reliability" and "maximum absolute error 1.6×10⁻⁴". The error came from
  four-decimal rounding; after the change, the re-run shows 0.
- **§3.5:** the heading "Bayesian truth discovery" and "Sybil resistance".
- **§5.5.1 and Table 6a (six-photo pilot):** remove. No images, reference
  scores or outputs exist in the repository, so the result cannot be
  reproduced.
- **§5.6:** "evidence the mechanism resists naive Sybil-style flooding". Not
  shown; repeated accounts are not detected.
- **§8(e):** keep as future work, but reference the replay-based reputation
  and the shadow policy now in place.
