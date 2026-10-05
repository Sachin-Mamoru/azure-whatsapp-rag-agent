# Image evaluation tables

Run commit `d7f7fd69`, split `test`, model alias `gpt-4o-mini`, snapshots gpt-4o-mini-2024-07-18.

Extraction status: {'ok': 159}; vision status: {'ok': 156, 'error': 3}.

Reference labels: text = constructed caption claim; image = provisional Commons source category. No human annotations were used.

## Table A. Visual support on items whose image should not support the report

Rows other than *_vision_ok include items whose vision call failed; for those items the comparison reflects failure handling (legacy adds 0.05, visual-v2 adds 0), not model judgement.

| Subset | visual-v2 (C) | legacy (L) | discordant L-only / C-only | exact McNemar p |
|---|---|---|---|---|
| all_non_supporting | 23.8% (19/80; 95% CI 15.8%–34.1%) | 51.2% (41/80; 95% CI 40.5%–61.9%) | 22 / 0 | 4.77e-07 |
| contradiction_hazard_image | 40.0% (8/20; 95% CI 21.9%–61.3%) | 60.0% (12/20; 95% CI 38.7%–78.1%) | 4 / 0 | 0.125 |
| no_hazard_image | 18.3% (11/60; 95% CI 10.6%–29.9%) | 48.3% (29/60; 95% CI 36.2%–60.7%) | 18 / 0 | 7.63e-06 |
| all_non_supporting_vision_ok | 24.1% (19/79; 95% CI 16.0%–34.5%) | 50.6% (40/79; 95% CI 39.8%–61.4%) | 21 / 0 | 9.54e-07 |

Items whose image should support the report but contributed nothing: visual-v2 20.8% (11/53; 95% CI 12.0%–33.5%); legacy 17.0% (9/53; 95% CI 9.2%–29.2%).

## Table B. Extraction and visual classification

| Measure | Value |
|---|---|
| Text hazard type vs constructed claim (model output) | 100.0% (133/133; 95% CI 97.2%–100.0%) |
| Text hazard type macro-F1, model output (flood/landslide/unknown) | 1.000 |
| Keyword fallback after API failure (not model performance) | n/a |
| Visual coarse class vs provisional class | 71.8% (94/131; 95% CI 63.5%–78.8%) |
| Visual macro-F1 (flood/landslide/none) | 0.719 |
| hazard_detected vs provisional hazard presence | 74.8% (98/131; 95% CI 66.7%–81.5%) |

## Table C. Hazard-type backfill (text left hazard type unknown)

| Policy | Coverage | Correct vs provisional | Backfilled on no-hazard image |
|---|---|---|---|
| visual-v2 | 50.9% (29/57; 95% CI 38.3%–63.4%) | 69.0% (20/29; 95% CI 50.8%–82.7%) | 24.1% (7/29; 95% CI 12.2%–42.1%) |
| legacy | 50.9% (29/57; 95% CI 38.3%–63.4%) | 69.0% (20/29; 95% CI 50.8%–82.7%) | 24.1% (7/29; 95% CI 12.2%–42.1%) |

## Table D. Latency (seconds)

| Stage | n | mean | p50 | p95 |
|---|---|---|---|---|
| extraction | 159 | 1.64 | 1.55 | 2.04 |
| vision | 159 | 2.52 | 2.45 | 3.13 |
| sequential_model_path_plus_scoring | 159 | 4.16 | 4.04 | 5.15 |
