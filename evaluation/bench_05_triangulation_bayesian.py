"""
Component Benchmark 5 — Bayesian Truth-Discovery Layer (TruthFinder triangulation)

Pure computational benchmark (no external API calls) exercising the REAL
CommunityReporter._check_triangulation_bayesian() and update_user_reliability()
code paths against a disposable SQLite DB seeded with synthetic corroborating
reports. Validates:
  - Correctness of the TruthFinder combination formula
    P(true) = prod(r_u) / [prod(r_u) + prod(1-r_u)]
    against an independently computed reference value
  - Computation latency vs. number of independent corroborating reporters
    (1, 2, 5, 10, 20, 50) — this is a DB-bound micro-benchmark, so it also
    characterises SQLite read latency under the reporter's query pattern
  - Convergence behaviour of the reliability update rule
    r <- r + alpha*(1-r) on verification, r <- r - alpha*r on rejection
"""
import os
import sys
import time
import uuid
import sqlite3
import hashlib
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["COMMUNITY_REPORTS_DB"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "results", "_bench_triangulation.db"
)

from evaluation.common import save_json, summarize
from agent.reporter import CommunityReporter


def seed_corroborators(reporter: CommunityReporter, n: int, reliability: float,
                        domain="hazard", hazard="landslide", loc="ratnapura"):
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(reporter.db_path) as conn:
        for _ in range(n):
            uh = hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()[:16]
            conn.execute("""
                INSERT INTO community_reports
                (report_id, timestamp, user_hash, language, report_domain, hazard_type,
                 category, location_text, description, confidence_score, severity_score,
                 action, status, people_at_risk, ongoing, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (f"RPT-{uh}", now, uh, "en", domain, hazard, hazard, loc,
                  "synthetic corroborating report", 0.5, 0.5, "monitor", "new", 0, 1, now))
            conn.execute("""
                INSERT INTO user_reliability (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at)
                VALUES (?, ?, 1, 0, 0, ?)
            """, (uh, reliability, now))
        conn.commit()


def reference_truthfinder(n: int, reliability: float) -> float:
    r = max(0.05, min(0.95, reliability))
    prod_r = r ** n
    prod_1_r = (1 - r) ** n
    denom = prod_r + prod_1_r
    return prod_r / denom if denom else 0.0


def main():
    scenarios = []
    latency_by_n = {}

    for n_corroborators in [1, 2, 5, 10, 20, 50]:
        for reliability in [0.3, 0.5, 0.7, 0.9]:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "results",
                f"_bench_tri_{n_corroborators}_{int(reliability*100)}.db"
            )
            if os.path.exists(db_path):
                os.remove(db_path)

            reporter = CommunityReporter()
            reporter.db_path = db_path
            reporter._init_db()
            seed_corroborators(reporter, n_corroborators, reliability)

            extracted = {"report_domain": "hazard", "hazard_type": "landslide", "location_text": "ratnapura"}
            latencies = []
            score = None
            for _ in range(20):
                t0 = time.perf_counter()
                score = reporter._check_triangulation_bayesian(extracted, "+94_query_user")
                latencies.append(time.perf_counter() - t0)

            p_true_ref = reference_truthfinder(n_corroborators, reliability)
            p_true_measured = score / 0.30 if score else 0.0

            scenarios.append({
                "n_corroborators": n_corroborators,
                "reliability": reliability,
                "triangulation_score": score,
                "p_true_reference": p_true_ref,
                "p_true_measured": p_true_measured,
                "abs_error": abs(p_true_ref - p_true_measured),
                "latency": summarize(latencies),
            })
            latency_by_n.setdefault(n_corroborators, []).extend(latencies)

    latency_scaling = {n: summarize(v) for n, v in latency_by_n.items()}

    # ── Reliability convergence trajectory ──────────────────────────────
    traj_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "_bench_tri_trajectory.db")
    if os.path.exists(traj_db):
        os.remove(traj_db)
    reporter = CommunityReporter()
    reporter.db_path = traj_db
    reporter._init_db()

    uh = "trajectory_test_user"
    with sqlite3.connect(reporter.db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO user_reliability (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at)
            VALUES (?, 0.5, 0, 0, 0, ?)
        """, (uh, datetime.now(timezone.utc).isoformat()))
        conn.commit()

    trajectory_verified = [0.5]
    for _ in range(15):
        reporter.update_user_reliability(uh, verified=True)
        trajectory_verified.append(reporter._get_user_reliability(uh))

    uh2 = "trajectory_test_user_rejected"
    with sqlite3.connect(reporter.db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO user_reliability (user_hash, reliability, n_reports, n_verified, n_rejected, updated_at)
            VALUES (?, 0.5, 0, 0, 0, ?)
        """, (uh2, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    trajectory_rejected = [0.5]
    for _ in range(15):
        reporter.update_user_reliability(uh2, verified=False)
        trajectory_rejected.append(reporter._get_user_reliability(uh2))

    max_abs_error = max(s["abs_error"] for s in scenarios)
    print(f"Max abs error vs reference TruthFinder formula: {max_abs_error:.6f}")

    save_json("05_triangulation_bayesian.json", {
        "scenarios": scenarios,
        "latency_scaling_by_n_corroborators": latency_scaling,
        "max_abs_error_vs_reference": max_abs_error,
        "reliability_trajectory_on_repeated_verification": trajectory_verified,
        "reliability_trajectory_on_repeated_rejection": trajectory_rejected,
    })


if __name__ == "__main__":
    main()
