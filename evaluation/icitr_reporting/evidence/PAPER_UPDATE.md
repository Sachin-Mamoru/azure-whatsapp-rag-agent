# Manuscript update: community-reporting subsystem (ICITR)

Scope: structured extraction, location clarification, image understanding,
contributor reputation, corroboration, confidence/severity scoring, human
review, persistence and retention. RAG question answering, retrieval, outbound
alerts and whole-system architecture belong to the separate journal paper and
are not described here.

Every sentence below is supported by an entry in `CLAIMS_MATRIX.md`. Text in
§4 describes an evaluation that has not yet run; it is written as protocol and
must not be converted to results until the run and annotation are complete.

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

## 4. Image evaluation protocol (not yet run)

The photographic-evidence policy is to be evaluated on 155 openly licensed
Wikimedia Commons photographs (80 of the 133 test photos are from Sri Lankan
events) paired with templated English, Sinhala and Tamil captions. The
captions are matching, sparse or contradictory, and are supplemented by
degraded and duplicate copies.
- **Split:** by event; prompts, policies and the analysis are frozen
  (commit `5d6f7b8`) before any test-split call.
- **Primary outcome:** the share of photos that should not support their
  report (contradiction or no hazard; n = 80) that nevertheless add
  confidence, under the new policy versus the earlier handling. Compared
  pairwise on identical model outputs with an exact McNemar test.
- **Secondary outcomes:** missed support (n = 53), backfill coverage and
  correctness, visual category agreement, latency and token cost.
- **Labels:** provisional, from the Commons category, until two blinded
  annotators have labelled all items. Reference priorities from that
  annotation will then allow review recall and workload to be compared
  between the two decision policies.

## 5. Limitations paragraph

Confidence, corroboration and reputation are heuristic scores, not calibrated
probabilities. Corroboration counts distinct accounts, which may belong to one
person or repeat the same second-hand claim; only byte-identical photos are
detected as copies. Location matching uses a single place token and no
geocoding. The archived extraction set is small, constructed, and labelled by
one author without a written policy. The image set uses templated captions,
provisional labels, and photos limited by open licensing (flood test photos
come from two event groups). The candidate decision policy and the
photographic-evidence policy are implemented and unit-tested but have not
been validated against reference priorities or human labels. In the current
deployment the report database is held in container temporary storage, so
reputation histories do not survive restarts.

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
