# Image evaluation tables

Run commit `d7f7fd69`, split `test`, model alias `gpt-4o-mini`, snapshots gpt-4o-mini-2024-07-18.

Extraction status: {'ok': 159}; vision status: {'ok': 155, 'error': 4}.

Reference labels: text = constructed caption claim; image = provisional Commons source category. No human annotations were used.

## Table A. Visual support on items whose image should not support the report

Rows other than *_vision_ok include items whose vision call failed; for those items the comparison reflects failure handling (legacy adds 0.05, visual-v2 adds 0), not model judgement.

| Subset | visual-v2 (C) | legacy (L) | discordant L-only / C-only | exact McNemar p |
|---|---|---|---|---|
| all_non_supporting | 22.5% (18/80; 95% CI 14.7%–32.8%) | 50.0% (40/80; 95% CI 39.3%–60.7%) | 22 / 0 | 4.77e-07 |
| contradiction_hazard_image | 35.0% (7/20; 95% CI 18.1%–56.7%) | 65.0% (13/20; 95% CI 43.3%–81.9%) | 6 / 0 | 0.0312 |
| no_hazard_image | 18.3% (11/60; 95% CI 10.6%–29.9%) | 45.0% (27/60; 95% CI 33.1%–57.5%) | 16 / 0 | 3.05e-05 |
| all_non_supporting_vision_ok | 23.1% (18/78; 95% CI 15.1%–33.6%) | 48.7% (38/78; 95% CI 37.9%–59.6%) | 20 / 0 | 1.91e-06 |

Items whose image should support the report but contributed nothing: visual-v2 20.8% (11/53; 95% CI 12.0%–33.5%); legacy 17.0% (9/53; 95% CI 9.2%–29.2%).

## Table B. Extraction and visual classification

| Measure | Value |
|---|---|
| Text hazard type vs constructed claim (model output) | 100.0% (133/133; 95% CI 97.2%–100.0%) |
| Text hazard type macro-F1, model output (flood/landslide/unknown) | 1.000 |
| Keyword fallback after API failure (not model performance) | n/a |
| Visual coarse class vs provisional class | 72.3% (94/130; 95% CI 64.1%–79.3%) |
| Visual macro-F1 (flood/landslide/none) | 0.718 |
| hazard_detected vs provisional hazard presence | 74.6% (97/130; 95% CI 66.5%–81.3%) |

## Table C. Hazard-type backfill (text left hazard type unknown)

| Policy | Coverage | Correct vs provisional | Backfilled on no-hazard image |
|---|---|---|---|
| visual-v2 | 50.9% (29/57; 95% CI 38.3%–63.4%) | 72.4% (21/29; 95% CI 54.3%–85.3%) | 24.1% (7/29; 95% CI 12.2%–42.1%) |
| legacy | 50.9% (29/57; 95% CI 38.3%–63.4%) | 72.4% (21/29; 95% CI 54.3%–85.3%) | 24.1% (7/29; 95% CI 12.2%–42.1%) |

## Table D. Latency (seconds)

| Stage | n | mean | p50 | p95 |
|---|---|---|---|---|
| extraction | 159 | 1.66 | 1.60 | 2.04 |
| vision | 159 | 2.54 | 2.48 | 3.30 |
| sequential_model_path_plus_scoring | 159 | 4.19 | 4.11 | 5.15 |
