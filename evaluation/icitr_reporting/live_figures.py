"""
Publication figure from a live run's AI-reference metrics (no API calls).

  python evaluation/icitr_reporting/live_figures.py --run-dir <run dir>

Reads analysis/ai_reference_metrics.json (written by analyze_ai_reference.py).
Reference labels are AI-reviewed (one annotator), not human; the figure says so.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stats_utils import wilson_ci  # noqa: E402

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3dd", "#fcfcfb"
V2, LEGACY = "#2a78d6", "#eb6834"  # validated categorical slots 1-2 (light surface)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    m = json.load(open(os.path.join(args.run_dir, "analysis", "ai_reference_metrics.json"), encoding="utf-8"))
    fs, deg = m["false_support_vs_ai"], m["degraded_images"]
    groups = [
        ("all non-supporting", fs["all_non_supporting"]["visual_v2_C"]["k"], fs["all_non_supporting"]["legacy_L"]["k"], fs["all_non_supporting"]["visual_v2_C"]["n"]),
        ("caption contradicts\nphoto", fs["contradiction"]["visual_v2_C"]["k"], fs["contradiction"]["legacy_L"]["k"], fs["contradiction"]["visual_v2_C"]["n"]),
        ("no hazard visible", fs["no_hazard_visible"]["visual_v2_C"]["k"], fs["no_hazard_visible"]["legacy_L"]["k"], fs["no_hazard_visible"]["visual_v2_C"]["n"]),
        ("degraded copies\n(blur, dark, downscale)", deg["degraded_adding_support_C"], deg["degraded_adding_support_L"], deg["n"]),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    width = 0.36
    for k, (code, label, color) in enumerate(((1, "visual-v2", V2), (2, "earlier handling", LEGACY))):
        xs, ps, errs, his = [], [], [[], []], []
        for i, (_, c, l, n) in enumerate(groups):
            kk = c if code == 1 else l
            p = kk / n
            lo, hi = wilson_ci(kk, n)
            xs.append(i + (k - 0.5) * width)
            ps.append(p)
            errs[0].append(max(0.0, p - lo))
            errs[1].append(max(0.0, hi - p))
            his.append(hi)
        ax.bar(xs, ps, width * 0.92, color=color, label=label, yerr=errs, capsize=3,
               error_kw={"ecolor": INK2, "lw": 1})
        for x, p, hi in zip(xs, ps, his):
            ax.text(x, hi + 0.02, f"{p:.0%}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{g[0]}\n(n={g[3]})" for g in groups], fontsize=8, color=INK2)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("share that still adds support", fontsize=8, color=INK2)
    ax.tick_params(axis="y", labelsize=8, colors=INK2)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    ax.set_title("Photos that should add no support but do (single run; AI-reviewed reference, not human)", fontsize=8.5, color=INK, loc="left")
    fig.tight_layout()
    out = os.path.join(args.run_dir, "analysis", "fig_support_vs_ai_reference.png")
    fig.savefig(out, dpi=220, facecolor=SURFACE)
    print(out)


if __name__ == "__main__":
    main()
