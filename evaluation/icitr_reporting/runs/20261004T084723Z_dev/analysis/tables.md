# Image evaluation tables

Run commit `cddd3cd1`, split `dev`, model alias `gpt-4o-mini`, snapshots none (no successful model call).

Extraction status: {'fallback': 22}; vision status: {'error': 22}.

Reference labels: text = constructed caption claim; image = provisional Commons source category. No human annotations were used.

## Table A. Visual support on items whose image should not support the report

| Subset | visual-v2 (C) | legacy (L) | discordant L-only / C-only | exact McNemar p |
|---|---|---|---|---|
| all_non_supporting | 0.0% (0/10; 95% CI 0.0%–27.8%) | 100.0% (10/10; 95% CI 72.2%–100.0%) | 10 / 0 | 0.00195 |
| contradiction_hazard_image | 0.0% (0/10; 95% CI 0.0%–27.8%) | 100.0% (10/10; 95% CI 72.2%–100.0%) | 10 / 0 | 0.00195 |
| no_hazard_image | n/a | n/a | 0 / 0 | 1 |

Items whose image should support the report but contributed nothing: visual-v2 100.0% (12/12; 95% CI 75.8%–100.0%); legacy 0.0% (0/12; 95% CI 0.0%–24.2%).

## Table B. Extraction and visual classification

| Measure | Value |
|---|---|
| Text hazard type vs constructed claim (model output) | n/a |
| Text hazard type macro-F1, model output (flood/landslide/unknown) | n/a |
| Keyword fallback after API failure (not model performance) | 81.8% (18/22; 95% CI 61.5%–92.7%) |
| Visual coarse class vs provisional class | n/a |
| Visual macro-F1 (flood/landslide/none) | n/a |
| hazard_detected vs provisional hazard presence | n/a |

## Table C. Hazard-type backfill (text left hazard type unknown)

| Policy | Coverage | Correct vs provisional | Backfilled on no-hazard image |
|---|---|---|---|
| visual-v2 | 0.0% (0/7; 95% CI 0.0%–35.4%) | n/a | n/a |
| legacy | 0.0% (0/7; 95% CI 0.0%–35.4%) | n/a | n/a |

## Table D. Latency (seconds)

| Stage | n | mean | p50 | p95 |
|---|---|---|---|---|
