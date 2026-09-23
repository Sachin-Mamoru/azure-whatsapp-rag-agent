"""
Component Benchmark 6 — SQLite Persistence Layer (registrations.db, community_reports.db)

Measures, against disposable copies of the real schemas:
  - Sequential write throughput (registration upserts, community report inserts)
  - Sequential read latency (district lookup, recent-reports query)
  - Concurrent write throughput/error-rate under N parallel threads
    (characterises the single-writer SQLite limitation relevant to the
    Container Apps auto-scaling / multi-replica discussion in the paper)
"""
import concurrent.futures
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.common import save_json, summarize

RESULTS_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def fresh_registrations_db(path):
    if os.path.exists(path):
        os.remove(path)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE NOT NULL,
                name TEXT, language TEXT NOT NULL, district TEXT NOT NULL,
                ds_division TEXT, gn_division TEXT, consent INTEGER NOT NULL DEFAULT 1,
                synced_at TEXT, created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    return path


def fresh_reports_db(path):
    if os.path.exists(path):
        os.remove(path)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE community_reports (
                report_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, user_hash TEXT NOT NULL,
                language TEXT NOT NULL, report_domain TEXT NOT NULL, hazard_type TEXT,
                category TEXT, location_text TEXT, description TEXT,
                confidence_score REAL NOT NULL, severity_score REAL NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                people_at_risk INTEGER DEFAULT 0, ongoing INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    return path


def bench_sequential_writes(db_path, table, n=500):
    latencies = []
    with sqlite3.connect(db_path) as conn:
        for i in range(n):
            t0 = time.perf_counter()
            if table == "registrations":
                conn.execute(
                    "INSERT INTO registrations (phone_number, name, language, district, consent, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (f"+9477{i:07d}", f"user{i}", "en", "colombo", 1, datetime.utcnow().isoformat()),
                )
            else:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO community_reports (report_id, timestamp, user_hash, language, "
                    "report_domain, hazard_type, category, location_text, description, "
                    "confidence_score, severity_score, action, status, people_at_risk, ongoing, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"RPT-{i}-{uuid.uuid4().hex[:6]}", now, f"hash{i}", "en", "hazard",
                     "flood", "flood", "colombo", "synthetic report", 0.5, 0.5,
                     "monitor", "new", 0, 1, now),
                )
            conn.commit()
            latencies.append(time.perf_counter() - t0)
    return latencies


def bench_sequential_reads(db_path, table, n=500):
    latencies = []
    with sqlite3.connect(db_path) as conn:
        for _ in range(n):
            t0 = time.perf_counter()
            if table == "registrations":
                conn.execute("SELECT * FROM registrations WHERE district = ?", ("colombo",)).fetchall()
            else:
                conn.execute(
                    "SELECT * FROM community_reports WHERE status = 'new' ORDER BY severity_score DESC LIMIT 20"
                ).fetchall()
            latencies.append(time.perf_counter() - t0)
    return latencies


def _concurrent_write_worker(db_path, table, worker_id, n_per_worker):
    ok, errors = 0, 0
    latencies = []
    conn = sqlite3.connect(db_path, timeout=5)
    for i in range(n_per_worker):
        t0 = time.perf_counter()
        try:
            if table == "registrations":
                conn.execute(
                    "INSERT INTO registrations (phone_number, name, language, district, consent, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (f"+9478{worker_id}{i:05d}", f"u{worker_id}_{i}", "en", "colombo", 1,
                     datetime.utcnow().isoformat()),
                )
            else:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT INTO community_reports (report_id, timestamp, user_hash, language, "
                    "report_domain, hazard_type, category, location_text, description, "
                    "confidence_score, severity_score, action, status, people_at_risk, ongoing, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"RPT-W{worker_id}-{i}-{uuid.uuid4().hex[:6]}", now, f"hash{worker_id}_{i}", "en",
                     "hazard", "flood", "flood", "colombo", "synthetic", 0.5, 0.5,
                     "monitor", "new", 0, 1, now),
                )
            conn.commit()
            ok += 1
        except Exception:
            errors += 1
        latencies.append(time.perf_counter() - t0)
    conn.close()
    return ok, errors, latencies


def bench_concurrent_writes(db_path, table, n_workers, n_per_worker=50):
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(_concurrent_write_worker, db_path, table, w, n_per_worker) for w in range(n_workers)]
        results = [f.result() for f in futures]
    wall_s = time.perf_counter() - t0

    total_ok = sum(r[0] for r in results)
    total_err = sum(r[1] for r in results)
    all_latencies = [lat for r in results for lat in r[2]]
    return {
        "n_workers": n_workers, "total_ops": n_workers * n_per_worker,
        "ok": total_ok, "errors": total_err, "wall_s": wall_s,
        "throughput_ops_per_s": total_ok / wall_s if wall_s > 0 else 0,
        "latency": summarize(all_latencies),
    }


def main():
    reg_db = fresh_registrations_db(os.path.join(RESULTS_DB_DIR, "_bench_registrations.db"))
    rep_db = fresh_reports_db(os.path.join(RESULTS_DB_DIR, "_bench_reports.db"))

    seq_write_reg = bench_sequential_writes(reg_db, "registrations", n=500)
    seq_write_rep = bench_sequential_writes(rep_db, "community_reports", n=500)
    seq_read_reg = bench_sequential_reads(reg_db, "registrations", n=500)
    seq_read_rep = bench_sequential_reads(rep_db, "community_reports", n=500)

    concurrency_results = []
    for n_workers in [1, 2, 4, 8, 16]:
        reg_db_c = fresh_registrations_db(os.path.join(RESULTS_DB_DIR, f"_bench_reg_conc_{n_workers}.db"))
        # Warm-up run (discarded) to remove first-write file-creation overhead from the timed sample
        bench_concurrent_writes(reg_db_c, "registrations", n_workers, n_per_worker=10)
        reg_db_c = fresh_registrations_db(os.path.join(RESULTS_DB_DIR, f"_bench_reg_conc_{n_workers}.db"))
        res = bench_concurrent_writes(reg_db_c, "registrations", n_workers, n_per_worker=200)
        concurrency_results.append(res)
        print(f"workers={n_workers}: throughput={res['throughput_ops_per_s']:.1f} ops/s "
              f"errors={res['errors']}/{res['total_ops']}")

    save_json("06_database_throughput.json", {
        "sequential_write_registrations": summarize(seq_write_reg),
        "sequential_write_community_reports": summarize(seq_write_rep),
        "sequential_read_registrations": summarize(seq_read_reg),
        "sequential_read_community_reports": summarize(seq_read_rep),
        "concurrent_write_scaling": concurrency_results,
    })


if __name__ == "__main__":
    main()
