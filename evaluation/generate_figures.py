"""
Generates publication-ready figures (300 DPI PNG) from the JSON results
produced by bench_00..bench_08. Run after run_all.py / individual benchmarks.
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.common import FIGURES_DIR, load_json_result

plt.rcParams.update({
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "figure.autolayout": True,
})


def fig_component_latency_overview():
    r01 = load_json_result("01_rag_retrieval.json")
    r02 = load_json_result("02_rag_generation.json")
    r03 = load_json_result("03_agent_routing.json")
    r04 = load_json_result("04_reporting_pipeline.json")
    r06 = load_json_result("06_database_throughput.json")
    r07 = load_json_result("07_language_detection.json")

    components = [
        ("Language detection\n(script-based)", r07["latency_seconds"]["mean"] * 1000),
        ("RAG retrieval\n(FAISS, k=4)", r01["by_k"]["4"]["latency"]["mean"] * 1000),
        ("Report intent\ndetection (keyword)", r04["intent_detection"]["latency"]["mean"] * 1000),
        ("SQLite write\n(sequential)", r06["sequential_write_community_reports"]["mean"] * 1000),
        ("SQLite read\n(sequential)", r06["sequential_read_community_reports"]["mean"] * 1000),
        ("RAG generation\n(retrieval+LLM)", r02["latency"]["mean"] * 1000),
        ("Report LLM\nextraction", r04["extraction"]["latency"]["mean"] * 1000),
        ("Agent routing\n(E2E, LLM+tool)", r03["latency"]["mean"] * 1000),
    ]
    labels = [c[0] for c in components]
    values = [c[1] for c in components]

    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    colors = plt.cm.viridis(np.linspace(0.15, 0.9, len(labels)))
    bars = ax.barh(labels, values, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("Mean latency (ms, log scale)")
    ax.set_title("Figure 1. Mean latency by system component")
    for bar, v in zip(bars, values):
        if v < 1000:
            label = f"{v*1000:,.1f} \u00b5s" if v < 0.05 else f"{v:,.2f} ms"
        else:
            label = f"{v/1000:,.2f} s"
        ax.text(v * 1.08, bar.get_y() + bar.get_height() / 2, label,
                va="center", fontsize=8)
    ax.invert_yaxis()
    fig.savefig(os.path.join(FIGURES_DIR, "fig1_component_latency_overview.png"))
    plt.close(fig)


def fig_retrieval_recall_vs_k():
    r01 = load_json_result("01_rag_retrieval.json")
    ks = sorted(int(k) for k in r01["by_k"].keys())
    recalls = [r01["by_k"][str(k)]["recall_at_k"] for k in ks]
    latencies = [r01["by_k"][str(k)]["latency"]["mean"] * 1000 for k in ks]

    fig, ax1 = plt.subplots(figsize=(5.5, 4))
    ax1.plot(ks, recalls, "o-", color="#2166ac", label="Keyword Recall@k")
    ax1.set_xlabel("k (nearest neighbours retrieved)")
    ax1.set_ylabel("Recall@k (keyword-coverage proxy)", color="#2166ac")
    ax1.set_ylim(0, 1.05)
    ax1.tick_params(axis="y", labelcolor="#2166ac")

    ax2 = ax1.twinx()
    ax2.plot(ks, latencies, "s--", color="#b2182b", label="Retrieval latency")
    ax2.set_ylabel("Mean retrieval latency (ms)", color="#b2182b")
    ax2.tick_params(axis="y", labelcolor="#b2182b")

    ax1.set_title("Figure 2. FAISS retrieval: recall and latency vs. k")
    fig.savefig(os.path.join(FIGURES_DIR, "fig2_retrieval_recall_vs_k.png"))
    plt.close(fig)


def fig_rag_generation_by_language():
    r02 = load_json_result("02_rag_generation.json")
    langs = list(r02["latency_by_language"].keys())
    means = [r02["latency_by_language"][l]["mean"] for l in langs]
    stds = [r02["latency_by_language"][l]["stdev"] for l in langs]

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(langs, means, yerr=stds, capsize=5, color=["#4393c3", "#f4a582", "#92c5de"])
    ax.set_ylabel("End-to-end RAG latency (s)")
    ax.set_xlabel("Detected language")
    ax.set_title("Figure 3. RAG generation latency by language")
    fig.savefig(os.path.join(FIGURES_DIR, "fig3_rag_latency_by_language.png"))
    plt.close(fig)


def fig_routing_confusion_matrix():
    r03 = load_json_result("03_agent_routing.json")
    tools = ["query_knowledge_base", "search_web", "submit_community_report", "get_community_observations"]
    short = ["KB\nquery", "Web\nsearch", "Submit\nreport", "Get\nobservations"]
    cm = np.array([[r03["confusion_matrix"][t].get(t2, 0) for t2 in tools] for t in tools])

    fig, ax = plt.subplots(figsize=(5.2, 4.6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(tools)), short)
    ax.set_yticks(range(len(tools)), short)
    ax.set_xlabel("Predicted tool")
    ax.set_ylabel("Expected tool (ground truth)")
    ax.set_title(f"Figure 4. Agent tool-routing confusion matrix\n(accuracy = {r03['accuracy']*100:.1f}%, n={r03['n_queries']})")
    for i in range(len(tools)):
        for j in range(len(tools)):
            ax.text(j, i, cm[i, j], ha="center", va="center",
                     color="white" if cm[i, j] > cm.max() / 2 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.savefig(os.path.join(FIGURES_DIR, "fig4_routing_confusion_matrix.png"))
    plt.close(fig)


def fig_reporting_pipeline():
    r04 = load_json_result("04_reporting_pipeline.json")
    intent = r04["intent_detection"]
    fields = r04["extraction"]["field_accuracy"]

    fig, axes = plt.subplots(1, 2, figsize=(9, 4))

    metrics = ["precision", "recall", "f1"]
    vals = [intent[m] for m in metrics]
    axes[0].bar(metrics, vals, color=["#66c2a5", "#fc8d62", "#8da0cb"])
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title("(a) Keyword-based intent detector")
    for i, v in enumerate(vals):
        axes[0].text(i, v + 0.02, f"{v:.2f}", ha="center")

    field_names = list(fields.keys())
    field_vals = [fields[f] for f in field_names]
    axes[1].bar(range(len(field_names)), field_vals, color="#8073ac")
    axes[1].set_xticks(range(len(field_names)), field_names, rotation=30, ha="right")
    axes[1].set_ylim(0, 1.05)
    axes[1].set_title(f"(b) LLM extraction field accuracy\n(exact-match rate = {r04['extraction']['exact_match_rate']*100:.1f}%)")
    for i, v in enumerate(field_vals):
        axes[1].text(i, v + 0.02, f"{v:.2f}", ha="center")

    fig.suptitle("Figure 5. Community reporting pipeline accuracy")
    fig.savefig(os.path.join(FIGURES_DIR, "fig5_reporting_pipeline_accuracy.png"))
    plt.close(fig)


def fig_triangulation():
    r05 = load_json_result("05_triangulation_bayesian.json")
    scenarios = r05["scenarios"]
    reliabilities = sorted(set(s["reliability"] for s in scenarios))
    ns = sorted(set(s["n_corroborators"] for s in scenarios))

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    for rel in reliabilities:
        pts = sorted([s for s in scenarios if s["reliability"] == rel], key=lambda s: s["n_corroborators"])
        axes[0].plot([p["n_corroborators"] for p in pts], [p["p_true_measured"] for p in pts],
                     "o-", label=f"r = {rel}")
    axes[0].set_xlabel("Independent corroborating reports (n)")
    axes[0].set_ylabel("P(true) — TruthFinder combination")
    axes[0].set_title("(a) Triangulation vs. corroborator count")
    axes[0].legend(fontsize=8)

    traj_v = r05["reliability_trajectory_on_repeated_verification"]
    traj_r = r05["reliability_trajectory_on_repeated_rejection"]
    axes[1].plot(range(len(traj_v)), traj_v, "o-", color="#1a9850", label="Repeated verification")
    axes[1].plot(range(len(traj_r)), traj_r, "s-", color="#d73027", label="Repeated rejection")
    axes[1].axhline(0.95, ls=":", color="gray", lw=1)
    axes[1].axhline(0.05, ls=":", color="gray", lw=1)
    axes[1].set_xlabel("Update event #")
    axes[1].set_ylabel("User reliability score r")
    axes[1].set_title("(b) Reliability-score convergence")
    axes[1].legend(fontsize=8)

    fig.suptitle("Figure 6. Bayesian truth-discovery (TruthFinder) behaviour")
    fig.savefig(os.path.join(FIGURES_DIR, "fig6_triangulation_bayesian.png"))
    plt.close(fig)


def fig_db_throughput():
    r06 = load_json_result("06_database_throughput.json")
    conc = r06["concurrent_write_scaling"]
    workers = [c["n_workers"] for c in conc]
    throughput = [c["throughput_ops_per_s"] for c in conc]
    p95 = [c["latency"]["p95"] * 1000 for c in conc]

    fig, ax1 = plt.subplots(figsize=(5.5, 4))
    ax1.plot(workers, throughput, "o-", color="#2166ac")
    ax1.set_xlabel("Concurrent writer threads")
    ax1.set_ylabel("Throughput (ops/s)", color="#2166ac")
    ax1.tick_params(axis="y", labelcolor="#2166ac")

    ax2 = ax1.twinx()
    ax2.plot(workers, p95, "s--", color="#b2182b")
    ax2.set_ylabel("p95 write latency (ms)", color="#b2182b")
    ax2.tick_params(axis="y", labelcolor="#b2182b")

    ax1.set_title("Figure 7. SQLite write throughput under concurrency")
    fig.savefig(os.path.join(FIGURES_DIR, "fig7_db_concurrency.png"))
    plt.close(fig)


def fig_e2e_concurrency():
    r08 = load_json_result("08_concurrency_load.json")
    levels = r08["levels"]
    conc = [l["concurrency"] for l in levels]
    throughput = [l["throughput_req_per_s"] for l in levels]
    p50 = [l["latency"]["p50"] for l in levels]
    p95 = [l["latency"]["p95"] for l in levels]

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 4))
    axes[0].plot(conc, throughput, "o-", color="#1a9850")
    axes[0].set_xlabel("Concurrent simulated WhatsApp users")
    axes[0].set_ylabel("Throughput (requests/s)")
    axes[0].set_title("(a) End-to-end throughput")

    axes[1].plot(conc, p50, "o-", label="p50")
    axes[1].plot(conc, p95, "s--", label="p95")
    axes[1].set_xlabel("Concurrent simulated WhatsApp users")
    axes[1].set_ylabel("End-to-end latency (s)")
    axes[1].set_title("(b) Latency percentiles")
    axes[1].legend()

    fig.suptitle("Figure 8. Orchestrator end-to-end throughput / latency vs. concurrency")
    fig.savefig(os.path.join(FIGURES_DIR, "fig8_e2e_concurrency.png"))
    plt.close(fig)


def fig_rag_vs_closedbook_ablation():
    r09 = load_json_result("09_rag_vs_closedbook_baseline.json")
    rag, cb = r09["rag"], r09["closed_book"]

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    metrics = ["faithfulness", "relevance"]
    x = np.arange(len(metrics))
    width = 0.35
    rag_vals = [rag[m]["mean"] for m in metrics]
    cb_vals = [cb[m]["mean"] for m in metrics]
    rag_err = [rag[m]["mean"] - rag[m]["ci95_mean_lo"] for m in metrics]
    cb_err = [cb[m]["mean"] - cb[m]["ci95_mean_lo"] for m in metrics]
    axes[0].bar(x - width / 2, rag_vals, width, yerr=rag_err, capsize=4, label="RAG (grounded)", color="#2166ac")
    axes[0].bar(x + width / 2, cb_vals, width, yerr=cb_err, capsize=4, label="Closed-book (no retrieval)", color="#b2182b")
    axes[0].set_xticks(x, [m.capitalize() for m in metrics])
    axes[0].set_ylim(0, 5.5)
    axes[0].set_ylabel("LLM-judge score (0-5)")
    axes[0].set_title("(a) Judge scores, 95% bootstrap CI")
    axes[0].legend(fontsize=8)

    hallu_rag = rag["hallucination_rate"] or 0
    hallu_cb = cb["hallucination_rate"] or 0
    axes[1].bar(["RAG", "Closed-book"], [hallu_rag, hallu_cb], color=["#2166ac", "#b2182b"])
    axes[1].set_ylim(0, 1.0)
    axes[1].set_ylabel("Hallucination-flag rate")
    axes[1].set_title("(b) LLM-judge-flagged fabricated facts")
    for i, v in enumerate([hallu_rag, hallu_cb]):
        axes[1].text(i, v + 0.02, f"{v:.2f}", ha="center")

    cov_rag = rag["keyword_coverage"]["mean"]
    cov_cb = cb["keyword_coverage"]["mean"]
    axes[2].bar(["RAG", "Closed-book"], [cov_rag, cov_cb], color=["#2166ac", "#b2182b"])
    axes[2].set_ylim(0, 1.05)
    axes[2].set_ylabel("Keyword coverage")
    axes[2].set_title("(c) Keyword-coverage proxy")
    for i, v in enumerate([cov_rag, cov_cb]):
        axes[2].text(i, v + 0.02, f"{v:.2f}", ha="center")

    fig.suptitle(f"Figure 9. RAG vs. closed-book ablation (n={r09['n']}, judge={r09['judge_model']})")
    fig.savefig(os.path.join(FIGURES_DIR, "fig9_rag_vs_closedbook_ablation.png"))
    plt.close(fig)


def main():
    fig_component_latency_overview()
    fig_retrieval_recall_vs_k()
    fig_rag_generation_by_language()
    fig_routing_confusion_matrix()
    fig_reporting_pipeline()
    fig_triangulation()
    fig_db_throughput()
    fig_e2e_concurrency()
    fig_rag_vs_closedbook_ablation()
    print(f"Figures written to {FIGURES_DIR}")


if __name__ == "__main__":
    main()
