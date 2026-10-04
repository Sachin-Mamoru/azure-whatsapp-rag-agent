"""
Annotation tooling for the archived 29-report extraction benchmark.

  python evaluation/icitr_reporting/annotation_tools.py rescore [--labels original|proposed|adjudicated]
  python evaluation/icitr_reporting/annotation_tools.py discrepancy
  python evaluation/icitr_reporting/annotation_tools.py packet
  python evaluation/icitr_reporting/annotation_tools.py agreement

All commands read the archived dataset and archived predictions and never
modify them. Outputs go to evaluation/icitr_reporting/annotation/.
"""
import argparse
import csv
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from stats_utils import cohen_kappa, proportion, write_json  # noqa: E402

DATASET = os.path.join(ROOT, "evaluation", "datasets", "report_extraction_testset.json")
ARCHIVED = os.path.join(ROOT, "evaluation", "results", "04_reporting_pipeline.json")
OUT = os.path.join(HERE, "annotation")
FIELDS = ["report_domain", "hazard_type", "has_location", "people_at_risk", "ongoing"]
REVIEW_FIELDS = ["report_domain", "hazard_type", "has_location", "people_at_risk", "ongoing"]
PROMPT_DEFS = {
    "people_at_risk": "true if message mentions people, houses, schools, roads; false otherwise",
    "ongoing": "true if implies the situation is happening now; false otherwise",
    "report_domain": "one of [hazard, infrastructure, regulatory, safety, unknown] (no definitions given)",
    "hazard_type": "one of [landslide, flood, erosion, drainage, mixed, other, unknown] (no definitions given)",
    "has_location": "derived: location_text is non-null",
}


def load():
    dataset = {d["id"]: d for d in json.load(open(DATASET, encoding="utf-8"))}
    archived = {p["id"]: p["extracted"] for p in json.load(open(ARCHIVED, encoding="utf-8"))["extraction"]["per_item"]}
    proposals = json.load(open(os.path.join(OUT, "proposed_labels.json"), encoding="utf-8"))
    return dataset, archived, proposals


def predicted(extracted, field):
    if field == "has_location":
        return bool(extracted.get("location_text"))
    if field in ("people_at_risk", "ongoing"):
        return bool(extracted.get(field))
    return extracted.get(field)


def labels_for(kind, dataset, proposals):
    labels = {i: dict(d["gt"]) for i, d in dataset.items()}
    if kind == "proposed":
        for p in proposals["proposals"]:
            labels[p["id"]][p["field"]] = p["proposed"]
    elif kind == "adjudicated":
        path = os.path.join(OUT, "adjudicated_labels.csv")
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        missing = [r["id"] for r in rows if any(r[f] == "" for f in REVIEW_FIELDS)]
        if missing or len(rows) != len(labels):
            sys.exit(f"adjudicated_labels.csv incomplete: {len(rows)} rows, unfilled: {missing}")
        for r in rows:
            labels[r["id"]] = {f: _parse(r[f]) for f in REVIEW_FIELDS}
    return labels


def _parse(value):
    v = value.strip().lower()
    return {"true": True, "false": False}.get(v, v)


def cmd_rescore(args):
    dataset, archived, proposals = load()
    labels = labels_for(args.labels, dataset, proposals)
    correct = {f: 0 for f in FIELDS}
    all_five = 0
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for item_id in dataset:
        ok = {f: predicted(archived[item_id], f) == labels[item_id][f] for f in FIELDS}
        for f, v in ok.items():
            correct[f] += v
        all_five += all(ok.values())
        p, g = predicted(archived[item_id], "people_at_risk"), labels[item_id]["people_at_risk"]
        confusion["tp" if p and g else "tn" if not p and not g else "fp" if p else "fn"] += 1
    n = len(dataset)
    result = {
        "label_set": args.labels,
        "label_set_note": {
            "original": "archived hand labels (unchanged)",
            "proposed": "original labels with policy-derived PROPOSED changes; not human-reviewed; sensitivity only",
            "adjudicated": "blinded two-annotator labels after adjudication",
        }[args.labels],
        "predictions": "archived run evaluation/results/04_reporting_pipeline.json (model/prompt not recorded in that file)",
        "n": n,
        "per_field": {f: proportion(c, n) for f, c in correct.items()},
        "all_five_fields": proportion(all_five, n),
        "exposure_confusion": confusion,
        "caveat": "has_location is presence of any location text, not geolocation accuracy; the 29 items are not a held-out set for any re-labelled variant.",
    }
    path = os.path.join(OUT, f"rescore_{args.labels}.json")
    write_json(path, result)
    print(json.dumps({k: result[k] for k in ("label_set", "per_field", "all_five_fields", "exposure_confusion")}, indent=1))


def cmd_discrepancy(_args):
    dataset, archived, proposals = load()
    by_key = {(p["id"], p["field"]): ("proposed", p) for p in proposals["proposals"]}
    by_key.update({(r["id"], r["field"]): ("retained", r) for r in proposals["retained"]})
    rows = []
    for item_id, d in dataset.items():
        for f in FIELDS:
            orig = d["gt"][f]
            pred = predicted(archived[item_id], f)
            kind, entry = by_key.get((item_id, f), (None, None))
            if pred == orig and kind != "proposed":
                continue
            prompt_conflict = ""
            if f == "people_at_risk" and pred and not orig and entry and entry["rule"] == "E2":
                prompt_conflict = "prompt counts roads as exposure; policy E2 does not"
            rows.append({
                "id": item_id, "language": d["language"], "field": f, "message": d["message"],
                "original_label": orig, "archived_prediction": pred,
                "prediction_matches_original": pred == orig,
                "prompt_definition": PROMPT_DEFS[f], "prompt_policy_conflict": prompt_conflict,
                "policy_rule": entry["rule"] if entry else "",
                "proposed_label": entry["proposed"] if kind == "proposed" else orig,
                "resolution": ("change proposed" if kind == "proposed" else
                               "retain original" if kind == "retained" else "unresolved"),
                "rationale": entry["rationale"] if entry else "",
                "review_status": "pending blinded human review",
            })
    with open(os.path.join(OUT, "discrepancy_report.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    lines = ["# Item-level discrepancy report", "",
             "Generated by `annotation_tools.py discrepancy`. Rows: every field where the archived prediction "
             "differs from the original label, plus every policy-derived proposal. Proposed labels are **not** "
             "adjudicated; all rows are pending blinded human review.", "",
             "| id | lang | field | original | archived pred. | rule | proposed | resolution | rationale |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['language']} | {r['field']} | {r['original_label']} | "
                     f"{r['archived_prediction']} | {r['policy_rule']} | {r['proposed_label']} | "
                     f"{r['resolution']} | {r['rationale']}{' (' + r['prompt_policy_conflict'] + ')' if r['prompt_policy_conflict'] else ''} |")
    unresolved = [r for r in rows if r["resolution"] == "unresolved"]
    lines += ["", f"Rows: {len(rows)}; change proposed: {sum(r['resolution'] == 'change proposed' for r in rows)}; "
                  f"retained: {sum(r['resolution'] == 'retain original' for r in rows)}; unresolved: {len(unresolved)}."]
    open(os.path.join(OUT, "discrepancy_report.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{len(rows)} rows, {len(unresolved)} unresolved")


def cmd_packet(_args):
    dataset, _, _ = load()
    rng = random.Random(20261004)
    codes = rng.sample(range(100, 1000), len(dataset))
    key = {f"T{c}": item_id for c, item_id in zip(codes, dataset)}
    os.makedirs(os.path.join(OUT, "blinded_review"), exist_ok=True)
    with open(os.path.join(OUT, "blinded_review", "KEY_DO_NOT_SHARE.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_code", "id"])
        w.writerows(sorted(key.items()))
    for reviewer, seed in (("A", 1), ("B", 2)):
        order = sorted(key)
        random.Random(seed).shuffle(order)
        with open(os.path.join(OUT, "blinded_review", f"reviewer_{reviewer}.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["item_code", "language", "message", *REVIEW_FIELDS, "notes"])
            for code in order:
                d = dataset[key[code]]
                w.writerow([code, d["language"], d["message"], *[""] * len(REVIEW_FIELDS), ""])
    with open(os.path.join(OUT, "adjudicated_labels.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", *REVIEW_FIELDS, "rule_ids", "adjudicator", "notes"])
        for item_id in dataset:
            w.writerow([item_id, *[""] * len(REVIEW_FIELDS), "", "", ""])
    print("wrote blinded_review/reviewer_A.csv, reviewer_B.csv, KEY_DO_NOT_SHARE.csv, adjudicated_labels.csv")


def cmd_agreement(_args):
    key = {r["item_code"]: r["id"] for r in csv.DictReader(
        open(os.path.join(OUT, "blinded_review", "KEY_DO_NOT_SHARE.csv"), encoding="utf-8"))}
    sheets = {}
    for reviewer in ("A", "B"):
        rows = list(csv.DictReader(open(os.path.join(OUT, "blinded_review", f"reviewer_{reviewer}.csv"),
                                        encoding="utf-8")))
        blank = [r["item_code"] for r in rows if any(r[f].strip() == "" for f in REVIEW_FIELDS)]
        if blank:
            sys.exit(f"reviewer_{reviewer}.csv has {len(blank)} unlabelled items; complete it first")
        sheets[reviewer] = {key[r["item_code"]]: {f: _parse(r[f]) for f in REVIEW_FIELDS} for r in rows}
    ids = sorted(key.values())
    result = {"n": len(ids), "per_field": {}, "disagreements": []}
    for f in REVIEW_FIELDS:
        a = [sheets["A"][i][f] for i in ids]
        b = [sheets["B"][i][f] for i in ids]
        result["per_field"][f] = {"raw_agreement": proportion(sum(x == y for x, y in zip(a, b)), len(ids)),
                                  "cohen_kappa": cohen_kappa(a, b)}
        result["disagreements"] += [{"id": i, "field": f, "A": sheets["A"][i][f], "B": sheets["B"][i][f]}
                                    for i in ids if sheets["A"][i][f] != sheets["B"][i][f]]
    write_json(os.path.join(OUT, "inter_annotator_agreement.json"), result)
    print(json.dumps(result["per_field"], indent=1))
    print(f"{len(result['disagreements'])} disagreements to adjudicate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rescore")
    r.add_argument("--labels", choices=["original", "proposed", "adjudicated"], default="original")
    sub.add_parser("discrepancy")
    sub.add_parser("packet")
    sub.add_parser("agreement")
    args = parser.parse_args()
    {"rescore": cmd_rescore, "discrepancy": cmd_discrepancy, "packet": cmd_packet,
     "agreement": cmd_agreement}[args.cmd](args)
