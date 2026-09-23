"""
Runs the full component benchmark suite end-to-end, in dependency order,
then regenerates all figures. Equivalent to running bench_00..bench_08
individually. Real OpenAI API calls are made by benchmarks 2, 3 and 4 —
expect a few minutes of wall-clock time and a small (< $1) API cost at
gpt-4o-mini / text-embedding-3-large rates.
"""
import runpy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BENCHMARKS = [
    "bench_00_indexing",
    "bench_01_rag_retrieval",
    "bench_02_rag_generation",
    "bench_03_agent_routing",
    "bench_04_reporting_pipeline",
    "bench_05_triangulation_bayesian",
    "bench_06_database_throughput",
    "bench_07_language_detection",
    "bench_08_concurrency_load",
    "bench_09_rag_vs_closedbook_baseline",
    "bench_10_live_deployment_probe",
]

if __name__ == "__main__":
    for name in BENCHMARKS:
        print(f"\n{'='*70}\nRunning {name}\n{'='*70}")
        runpy.run_module(f"evaluation.{name}", run_name="__main__")

    print(f"\n{'='*70}\nGenerating figures\n{'='*70}")
    runpy.run_module("evaluation.generate_figures", run_name="__main__")
