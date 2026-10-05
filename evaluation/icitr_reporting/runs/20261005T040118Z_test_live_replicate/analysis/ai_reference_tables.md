# Results against the AI-reviewed reference

Run commit `d7f7fd69`, split `test`. Reference: one AI annotator (Claude Sonnet 5.5), single pass; **not human annotation**; no inter-annotator agreement.

## Table A. Visual support on images that do not support the report (AI reference)

| Subset | visual-v2 | legacy | discordant legacy-only / v2-only | exact McNemar p |
|---|---|---|---|---|
| all_non_supporting | 24.0% (23/96; 95% CI 16.5%–33.4%) | 49.0% (47/96; 95% CI 39.2%–58.8%) | 24 / 0 | 1.19e-07 |
| non_supporting_vision_ok | 24.7% (23/93; 95% CI 17.1%–34.4%) | 47.3% (44/93; 95% CI 37.5%–57.4%) | 21 / 0 | 9.54e-07 |
| contradiction | 20.8% (11/53; 95% CI 12.0%–33.5%) | 64.2% (34/53; 95% CI 50.7%–75.7%) | 23 / 0 | 2.38e-07 |
| no_hazard_visible | 11.6% (8/69; 95% CI 6.0%–21.2%) | 37.7% (26/69; 95% CI 27.2%–49.5%) | 18 / 0 | 7.63e-06 |

Images the reference says support their report (37) that added nothing: visual-v2 0.0% (0/37; 95% CI 0.0%–9.4%); legacy 0.0% (0/37; 95% CI 0.0%–9.4%).

## Table B. Model vision output vs AI reference

| Measure | Value |
|---|---|
| Coarse category accuracy | 78.5% (102/130; 95% CI 70.6%–84.7%) |
| Macro-F1 (flood/landslide/other/none) | 0.629 |
| hazard_detected agreement | 82.3% (107/130; 95% CI 74.8%–87.9%) |
| Contradiction recall | 0.0% (0/50; 95% CI 0.0%–7.1%) |
| Contradiction precision | n/a |
| Evidence tier exact / within one tier | 26.2% (34/130; 95% CI 19.4%–34.3%) / 76.9% (100/130; 95% CI 69.0%–83.3%) |
| Mean absolute tier error | 1.00 tiers |

## Table C. Hazard-type backfill vs AI reference

| Policy | Backfilled | Correct | Backfilled where AI sees no hazard |
|---|---|---|---|
| visual-v2 | 29 | 62.1% (18/29; 95% CI 44.0%–77.3%) | 27.6% (8/29; 95% CI 14.7%–45.7%) |
| legacy | 29 | 62.1% (18/29; 95% CI 44.0%–77.3%) | 27.6% (8/29; 95% CI 14.7%–45.7%) |

## Label quality: Commons category vs AI reference

Agreement on flood/landslide/none: 75.9% (101/133; 95% CI 68.0%–82.4%). Confusion: {'flood->flood': 16, 'flood->none': 7, 'landslide->landslide': 28, 'landslide->none': 16, 'landslide->other': 6, 'none->none': 57, 'none->flood': 2, 'none->other': 1}.
