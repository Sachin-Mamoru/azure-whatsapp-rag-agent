"""
Build the shareable evidence archive.

  python evaluation/icitr_reporting/evidence/make_archive.py

Writes evidence/dist/icitr_reporting_evidence_<commit>.tar.gz (not committed).
Excludes .env, credentials, databases, user data and caches. Includes the
Commons images (all CC BY / CC BY-SA / CC0 / PD) with an ATTRIBUTION.md built
from the manifest. Fails if a secret-like string or a raw Sri Lankan mobile
number is found in any text file it packs.
"""
import io
import json
import os
import re
import subprocess
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
INCLUDE = ["agent", "config.py", "app.py", "requirements.txt", "tests",
           "evaluation/icitr_reporting", "evaluation/common.py", "evaluation/__init__.py",
           "evaluation/bench_04_reporting_pipeline.py", "evaluation/bench_05_triangulation_bayesian.py",
           "evaluation/datasets/report_extraction_testset.json", "evaluation/results/04_reporting_pipeline.json",
           "evaluation/results/05_triangulation_bayesian.json"]
EXCLUDE = re.compile(r"(^|/)(\.env|credentials\.json|__pycache__|dist|commons_cache\.json)(/|$)|\.db$|\.pyc$")
SECRET = re.compile(r"sk-[A-Za-z0-9_-]{20,}|EAA[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY")
PHONE = re.compile(r"(?<!\d)(?:\+?94|0)7\d{8}(?!\d)")
SYNTHETIC_NUMBERS = {"94770000000"}  # placeholder used by the audited-code probe


def files():
    for entry in INCLUDE:
        path = os.path.join(ROOT, entry)
        if os.path.isfile(path):
            yield entry
            continue
        for base, _, names in os.walk(path):
            for name in names:
                rel = os.path.relpath(os.path.join(base, name), ROOT)
                if not EXCLUDE.search(rel):
                    yield rel


def attribution():
    lines = ["# Image attribution", "", "Images are 1024-px renditions from Wikimedia Commons, redistributed under "
             "their original licences. Derived (degraded/re-encoded) copies are adaptations of the listed source and carry its licence.", "",
             "| item | file | title | author | licence | source |", "|---|---|---|---|---|---|"]
    for line in open(os.path.join(ROOT, "evaluation/icitr_reporting/image_data/manifest.jsonl"), encoding="utf-8"):
        i = json.loads(line)
        c = i["commons"]
        lines.append(f"| {i['item_id']} | {i['image_file']} | {c['title']} | {c['artist'] or c['uploader']} | "
                     f"{c['licence']} | {c['page_url']} |")
    return "\n".join(lines) + "\n"


def main():
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out_dir = os.path.join(HERE, "dist")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"icitr_reporting_evidence_{commit}.tar.gz")
    problems, count = [], 0
    with tarfile.open(out, "w:gz") as tar:
        for rel in sorted(set(files())):
            full = os.path.join(ROOT, rel)
            if not rel.endswith((".jpg", ".png")):
                text = open(full, encoding="utf-8", errors="ignore").read()
                if SECRET.search(text) or set(PHONE.findall(text)) - SYNTHETIC_NUMBERS:
                    problems.append(rel)
            tar.add(full, arcname=f"icitr_reporting_evidence/{rel}")
            count += 1
        data = attribution().encode("utf-8")
        info = tarfile.TarInfo("icitr_reporting_evidence/ATTRIBUTION.md")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    if problems:
        os.remove(out)
        sys.exit(f"refusing to build: secret- or phone-like strings in {problems}")
    print(f"{out} ({count + 1} files, {os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
