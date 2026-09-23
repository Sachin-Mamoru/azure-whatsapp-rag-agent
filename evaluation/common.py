"""Shared utilities for the performance-evaluation benchmark suite."""
import json
import os
import random
import statistics
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Tuple

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
FIGURES_DIR = os.path.join(os.path.dirname(__file__), "figures")
DATASETS_DIR = os.path.join(os.path.dirname(__file__), "datasets")
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(FIGURES_DIR, exist_ok=True)


@contextmanager
def timer():
    """Context manager yielding a dict populated with elapsed seconds on exit."""
    box: Dict[str, float] = {}
    t0 = time.perf_counter()
    try:
        yield box
    finally:
        box["elapsed_s"] = time.perf_counter() - t0


def percentiles(values: List[float], ps=(50, 90, 95, 99)) -> Dict[str, float]:
    if not values:
        return {f"p{p}": float("nan") for p in ps}
    values_sorted = sorted(values)
    out = {}
    n = len(values_sorted)
    for p in ps:
        k = max(0, min(n - 1, int(round(p / 100 * (n - 1)))))
        out[f"p{p}"] = values_sorted[k]
    return out


def bootstrap_ci(values: List[float], stat_fn: Callable[[List[float]], float] = statistics.mean,
                  n_boot: int = 2000, ci: float = 0.95, seed: int = 42) -> Tuple[float, float]:
    """Non-parametric percentile bootstrap CI for a summary statistic (default: mean).

    Standard technique for reporting uncertainty over a single-run sample of
    n items without needing to repeat the (expensive, LLM-backed) experiment
    itself n_boot times — only the resampling/statistic computation is repeated.
    """
    if len(values) < 2:
        v = values[0] if values else float("nan")
        return (v, v)
    rng = random.Random(seed)
    n = len(values)
    boot_stats = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        boot_stats.append(stat_fn(sample))
    boot_stats.sort()
    alpha = (1 - ci) / 2
    lo_idx = max(0, int(round(alpha * n_boot)) - 1)
    hi_idx = min(n_boot - 1, int(round((1 - alpha) * n_boot)) - 1)
    return (boot_stats[lo_idx], boot_stats[hi_idx])


def summarize(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0}
    out = {
        "n": len(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }
    out.update(percentiles(values))
    ci_lo, ci_hi = bootstrap_ci(values)
    out["ci95_mean_lo"] = ci_lo
    out["ci95_mean_hi"] = ci_hi
    return out


def wilson_ci(successes: int, n: int, ci: float = 0.95) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion (accuracy/precision/recall/F1
    counts) — standard practice for small-n classification metrics, avoids the
    normal-approximation interval's poor behaviour near 0/1."""
    if n == 0:
        return (float("nan"), float("nan"))
    z = 1.959963984540054 if abs(ci - 0.95) < 1e-9 else 1.6448536269514722  # 95% / 90%
    p = successes / n
    denom = 1 + z ** 2 / n
    center = p + z ** 2 / (2 * n)
    margin = z * ((p * (1 - p) / n + z ** 2 / (4 * n ** 2)) ** 0.5)
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))


def save_json(name: str, data: Any) -> str:
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"[saved] {path}")
    return path


def load_dataset(name: str) -> Any:
    path = os.path.join(DATASETS_DIR, name)
    with open(path) as f:
        return json.load(f)


def load_json_result(name: str) -> Any:
    path = os.path.join(RESULTS_DIR, name)
    with open(path) as f:
        return json.load(f)
