"""Small, dependency-free statistics for the benchmark.

  wilson(k, n)          95% Wilson score interval for a proportion (good at small n and near 0/1)
  mcnemar_exact(b, c)   exact two-sided McNemar test on the discordant pairs of a paired design
  bootstrap_ci(xs, f)   percentile bootstrap interval for any statistic (median latency, mean WER)
  holm(pvals)           Holm-Bonferroni adjustment when testing several languages at once
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """b = pairs where only condition A failed, c = only condition B failed. Returns p-value."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def bootstrap_ci(xs: Sequence[float], stat: Callable[[Sequence[float]], float],
                 n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    xs = list(xs)
    if not xs:
        return (float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    est = stat(xs)
    boots = sorted(stat([xs[rng.randrange(len(xs))] for _ in xs]) for _ in range(n_boot))
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return est, lo, hi


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return float("nan") if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def percentile(xs: Sequence[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def holm(pvals: Sequence[float]) -> list[float]:
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


def fmt_rate(k: int, n: int) -> str:
    p, lo, hi = wilson(k, n)
    if n == 0:
        return "n/a"
    return f"{100*p:.1f}% [{100*lo:.1f}, {100*hi:.1f}] ({k}/{n})"
