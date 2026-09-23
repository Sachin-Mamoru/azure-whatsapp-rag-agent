"""Shared utilities for the performance-evaluation benchmark suite."""
import json
import os
import statistics
import time
from contextlib import contextmanager
from typing import Any, Dict, List

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
    return out


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
