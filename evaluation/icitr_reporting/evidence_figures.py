"""
Publication figures from deterministic evidence (no API calls).

  python evaluation/icitr_reporting/evidence_figures.py --run-dir <offline run dir>

fig_policy_action_maps.png  baseline vs candidate decision regions
fig_aggregation_stability.png  direct product vs log-odds corroboration points
"""
import argparse
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
os.environ.setdefault("OPENAI_API_KEY", "sk-not-used")

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3dd", "#fcfcfb"
# Sequential blue, light = lowest priority; validated for monotone lightness.
RAMP = ["#cde2fb", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"]
SERIES = ["#2a78d6", "#eb6834"]  # categorical slots 1-2, validated (light)


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)


def policy_maps(out):
    from agent import reporter as rep
    order = list(reversed(rep.ACTION_PRIORITY))  # store_only ... escalate
    n = 401
    axis = [i / (n - 1) for i in range(n)]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    cmap = ListedColormap(RAMP)
    norm = BoundaryNorm([i - 0.5 for i in range(len(order) + 1)], len(order))
    for ax, (name, fn) in zip(axes, rep.DECISION_POLICIES.items()):
        z = [[order.index(fn(c, s)) for c in axis] for s in axis]
        ax.imshow(z, origin="lower", extent=(0, 1, 0, 1), cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")
        ax.contour(axis, axis, z, levels=[i + 0.5 for i in range(len(order) - 1)], colors="white", linewidths=1.5)
        seen = {}
        for si, s in enumerate(axis[::20]):
            for ci, c in enumerate(axis[::20]):
                seen.setdefault(fn(c, s), []).append((c, s))
        for action, pts in seen.items():
            mx = sum(p[0] for p in pts) / len(pts)
            my = sum(p[1] for p in pts) / len(pts)
            # nearest in-region point to the centroid keeps labels inside L-shaped regions
            cx, cy = min(pts, key=lambda p: (p[0] - mx) ** 2 + (p[1] - my) ** 2)
            cx, cy = min(cx + 0.075, 0.9), cy
            light = order.index(action) <= 1
            ax.text(cx, cy, action.replace("_", " "), ha="center", va="center", fontsize=7.5,
                    color=INK if light else "white")
        ax.set_title(name, fontsize=9, color=INK)
        ax.set_xlabel("confidence score", fontsize=8, color=INK2)
        style(ax)
    axes[0].set_ylabel("severity score", fontsize=8, color=INK2)
    fig.suptitle("Decision regions; darker = higher review priority", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_policy_action_maps.png"), dpi=220, facecolor=SURFACE)
    plt.close(fig)


def aggregation(run_dir, out):
    data = json.load(open(os.path.join(run_dir, "offline_evidence.json"), encoding="utf-8"))["aggregation"]
    ns = sorted({int(k.split(",")[0][2:]) for k in data if k.startswith("n=") and k.endswith("r=0.5")})
    old = [data[f"n={n}, r=0.5"]["corroboration_points_old"] for n in ns]
    new = [data[f"n={n}, r=0.5"]["corroboration_points_new"] for n in ns]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    fig.patch.set_facecolor(SURFACE)
    ax.plot(ns, new, color=SERIES[0], lw=2, marker="o", ms=5, label="log-odds (current)")
    ax.plot(ns, old, color=SERIES[1], lw=2, marker="s", ms=5, ls="--", label="direct product (audited)")
    ax.set_xscale("log")
    ax.set_ylim(-0.01, 0.33)
    ax.set_xlabel("corroborating contributors, each reliability 0.5", fontsize=8, color=INK2)
    ax.set_ylabel("corroboration points (max 0.30)", fontsize=8, color=INK2)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.annotate("underflow: 0.5^n = 0 for n ≥ 1075", xy=(1100, 0.0), xytext=(12, 0.07), fontsize=7.5, color=INK2,
                arrowprops={"arrowstyle": "->", "color": INK2, "lw": 0.8})
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fig_aggregation_stability.png"), dpi=220, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    policy_maps(args.run_dir)
    aggregation(args.run_dir, args.run_dir)
    print("figures written to", args.run_dir)
