# Results against the AI-reviewed reference

Run commit `d7f7fd69`, split `test`. Reference: one AI annotator (Claude Sonnet 5.5), single pass; **not human annotation**; no inter-annotator agreement.

## Table A. Visual support on images that do not support the report (AI reference)

| Subset | visual-v2 | legacy | discordant legacy-only / v2-only | exact McNemar p |
|---|---|---|---|---|
| all_non_supporting | 25.0% (24/96; 95% CI 17.4%–34.5%) | 50.0% (48/96; 95% CI 40.2%–59.8%) | 24 / 0 | 1.19e-07 |
| non_supporting_vision_ok | 25.5% (24/94; 95% CI 17.8%–35.2%) | 48.9% (46/94; 95% CI 39.1%–58.9%) | 22 / 0 | 4.77e-07 |
| contradiction | 22.6% (12/53; 95% CI 13.5%–35.5%) | 64.2% (34/53; 95% CI 50.7%–75.7%) | 22 / 0 | 4.77e-07 |
| no_hazard_visible | 11.6% (8/69; 95% CI 6.0%–21.2%) | 37.7% (26/69; 95% CI 27.2%–49.5%) | 18 / 0 | 7.63e-06 |

Images the reference says support their report (37) that added nothing: visual-v2 0.0% (0/37; 95% CI 0.0%–9.4%); legacy 0.0% (0/37; 95% CI 0.0%–9.4%).

## Table B. Model vision output vs AI reference

| Measure | Value |
|---|---|
| Coarse category accuracy | 78.6% (103/131; 95% CI 70.8%–84.8%) |
| Macro-F1 (flood/landslide/other/none) | 0.629 |
| hazard_detected agreement | 83.2% (109/131; 95% CI 75.9%–88.6%) |
| Contradiction recall | 0.0% (0/51; 95% CI 0.0%–7.0%) |
| Contradiction precision | n/a |
| Evidence tier exact / within one tier | 26.0% (34/131; 95% CI 19.2%–34.1%) / 76.3% (100/131; 95% CI 68.4%–82.8%) |
| Mean absolute tier error | 1.02 tiers |

## Table C. Hazard-type backfill vs AI reference

| Policy | Backfilled | Correct | Backfilled where AI sees no hazard |
|---|---|---|---|
| visual-v2 | 29 | 58.6% (17/29; 95% CI 40.7%–74.5%) | 27.6% (8/29; 95% CI 14.7%–45.7%) |
| legacy | 29 | 58.6% (17/29; 95% CI 40.7%–74.5%) | 27.6% (8/29; 95% CI 14.7%–45.7%) |

## Label quality: Commons category vs AI reference

Agreement on flood/landslide/none: 75.9% (101/133; 95% CI 68.0%–82.4%). Confusion: {'flood->flood': 16, 'flood->none': 7, 'landslide->landslide': 28, 'landslide->none': 16, 'landslide->other': 6, 'none->none': 57, 'none->flood': 2, 'none->other': 1}.
