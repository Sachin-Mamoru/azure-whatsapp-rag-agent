"""Small statistics helpers for the ICITR reporting evaluation (stdlib only)."""
import hashlib
import json
import math
import random
from typing import Callable, Dict, List, Optional, Sequence, Tuple


def wilson_ci(successes: int, n: int, z: float = 1.959964) -> Tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion(successes: int, n: int) -> Dict[str, float]:
    lo, hi = wilson_ci(successes, n)
    return {"k": successes, "n": n, "p": successes / n if n else float("nan"), "ci95_wilson": [lo, hi]}


def cluster_bootstrap(groups: Dict[str, List[float]], stat: Callable[[List[float]], float],
                      n_boot: int = 4000, seed: int = 7) -> Tuple[float, float]:
    """Percentile CI resampling whole clusters (e.g. events) with replacement."""
    keys = sorted(groups)
    if not keys:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    draws = []
    for _ in range(n_boot):
        sample: List[float] = []
        for _ in keys:
            sample.extend(groups[rng.choice(keys)])
        if sample:
            draws.append(stat(sample))
    draws.sort()
    return (draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1])


def cohen_kappa(a: Sequence, b: Sequence) -> Optional[float]:
    n = len(a)
    if n == 0 or n != len(b):
        return None
    labels = sorted(set(a) | set(b), key=str)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((list(a).count(l) / n) * (list(b).count(l) / n) for l in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def macro_f1(gold: Sequence[str], pred: Sequence[str], labels: Optional[Sequence[str]] = None) -> Dict:
    labels = list(labels) if labels else sorted(set(gold))
    per = {}
    for l in labels:
        tp = sum(g == l and p == l for g, p in zip(gold, pred))
        fp = sum(g != l and p == l for g, p in zip(gold, pred))
        fn = sum(g == l and p != l for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        per[l] = {"precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                  "support": tp + fn}
    return {"macro_f1": sum(v["f1"] for v in per.values()) / len(per) if per else float("nan"), "per_label": per}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
